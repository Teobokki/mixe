"""MIXE mail engine — IMAP/SMTP, accounts, message parsing.
©2026 EX Inc./HYPERION DIGITAL ©2026
"""
from __future__ import annotations

import base64
import imaplib
import json
import os
import re
import smtplib
import socket
import ssl
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, formatdate, make_msgid, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Callable, Iterable, Optional

APP = "MIXE"
SECRETS_FLAG = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
IMAP_TIMEOUT = 30
SMTP_TIMEOUT = 30
MAX_LIST = 300

# Quiet host fill from the address domain only — no provider labels in the UI.
_PRESETS = {
    "gmail.com": ("imap.gmail.com", 993, True, "smtp.gmail.com", 587, "starttls"),
    "googlemail.com": ("imap.gmail.com", 993, True, "smtp.gmail.com", 587, "starttls"),
    "outlook.com": ("outlook.office365.com", 993, True, "smtp.office365.com", 587, "starttls"),
    "hotmail.com": ("outlook.office365.com", 993, True, "smtp.office365.com", 587, "starttls"),
    "live.com": ("outlook.office365.com", 993, True, "smtp.office365.com", 587, "starttls"),
    "msn.com": ("outlook.office365.com", 993, True, "smtp.office365.com", 587, "starttls"),
    "yahoo.com": ("imap.mail.yahoo.com", 993, True, "smtp.mail.yahoo.com", 587, "starttls"),
    "icloud.com": ("imap.mail.icloud.com", 993, True, "smtp.mail.icloud.com", 587, "starttls"),
    "me.com": ("imap.mail.icloud.com", 993, True, "smtp.mail.icloud.com", 587, "starttls"),
    "mac.com": ("imap.mail.icloud.com", 993, True, "smtp.mail.icloud.com", 587, "starttls"),
}


def ssl_context() -> ssl.SSLContext:
    """Default verified TLS context. Never disable certificate checks."""
    return ssl.create_default_context()


def app_data_dir() -> str:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(root, APP)
    os.makedirs(path, exist_ok=True)
    return path


def accounts_path() -> str:
    return os.path.join(app_data_dir(), "accounts.json")


def secrets_path() -> str:
    return os.path.join(app_data_dir(), "accounts.bin")


def preset_for_email(address: str):
    domain = (address or "").rsplit("@", 1)[-1].strip().lower()
    return _PRESETS.get(domain)


# ---------------------------------------------------------------------------
# Password vault — Windows DPAPI, with a local obfuscation fallback
# ---------------------------------------------------------------------------

def _dpapi_protect(data: bytes) -> Optional[bytes]:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, SECRETS_FLAG, ctypes.byref(blob_out)
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _dpapi_unprotect(data: bytes) -> Optional[bytes]:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, SECRETS_FLAG, ctypes.byref(blob_out)
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _obfuscation_key() -> bytes:
    seed = "%s|%s|%s" % (APP, os.environ.get("USERNAME") or os.environ.get("USER") or "user",
                         os.environ.get("COMPUTERNAME") or socket.gethostname())
    # Expand a short, non-secret pad. This is obfuscation, not encryption.
    pad = (seed * 8).encode("utf-8", "replace")
    return pad[:64]


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def protect_secret(text: str) -> str:
    raw = (text or "").encode("utf-8")
    blob = _dpapi_protect(raw)
    if blob is not None:
        return "dpapi:" + base64.b64encode(blob).decode("ascii")
    return "obf:" + base64.b64encode(_xor(raw, _obfuscation_key())).decode("ascii")


def unprotect_secret(token: str) -> str:
    if not token:
        return ""
    try:
        if token.startswith("dpapi:"):
            blob = base64.b64decode(token[6:])
            raw = _dpapi_unprotect(blob)
            if raw is None:
                return ""
            return raw.decode("utf-8", "replace")
        if token.startswith("obf:"):
            raw = _xor(base64.b64decode(token[4:]), _obfuscation_key())
            return raw.decode("utf-8", "replace")
    except Exception:
        return ""
    return ""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Account:
    id: str
    display_name: str
    email: str
    username: str
    imap_host: str
    imap_port: int = 993
    imap_ssl: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"  # "ssl" or "starttls"
    password: str = field(default="", repr=False)

    def public_dict(self) -> dict:
        d = asdict(self)
        d.pop("password", None)
        return d

    def label(self) -> str:
        name = (self.display_name or "").strip()
        if name and name.lower() != self.email.lower():
            return "%s  <%s>" % (name, self.email)
        return self.email


@dataclass
class Folder:
    name: str
    delim: str = "/"
    flags: tuple = ()
    unseen: int = 0
    total: int = 0

    @property
    def is_inbox(self) -> bool:
        return self.name.upper() == "INBOX" or self.name.split(self.delim or "/")[-1].upper() == "INBOX"

    @property
    def is_trash(self) -> bool:
        flags = {f.lower() for f in self.flags}
        if "\\trash" in flags:
            return True
        tail = self.name.split(self.delim or "/")[-1].lower()
        return tail in ("trash", "bin", "deleted", "deleted items", "papierkorb")


@dataclass
class Attachment:
    filename: str
    content_type: str
    payload: bytes
    size: int = 0

    def __post_init__(self):
        if not self.size:
            self.size = len(self.payload or b"")


@dataclass
class MessageHeader:
    uid: str
    folder: str
    from_name: str
    from_addr: str
    to_addrs: list
    cc_addrs: list
    subject: str
    date: Optional[datetime]
    date_text: str
    unseen: bool
    size: int = 0


@dataclass
class Message(MessageHeader):
    body_text: str = ""
    attachments: list = field(default_factory=list)
    message_id: str = ""
    reply_to: str = ""
    references: str = ""
    raw_headers: str = ""


@dataclass
class StoreData:
    accounts: list
    last_account_id: str = ""


# ---------------------------------------------------------------------------
# Header / body helpers
# ---------------------------------------------------------------------------

def decode_hdr(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return ""
    value = value.strip()
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def parse_address(value: str) -> tuple:
    name, addr = parseaddr(decode_hdr(value) or "")
    return (name or "").strip(), (addr or "").strip()


def parse_address_list(value: str) -> list:
    text = decode_hdr(value) or ""
    out = []
    for part in text.split(","):
        name, addr = parseaddr(part)
        if addr:
            out.append(((name or "").strip(), addr.strip()))
    return out


def format_when(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        now = datetime.now(local.tzinfo)
        if local.date() == now.date():
            return local.strftime("%H:%M")
        if local.year == now.year:
            return local.strftime("%d %b")
        return local.strftime("%Y-%m-%d")
    except Exception:
        return ""


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        t = (tag or "").lower()
        if t in ("script", "style", "noscript", "iframe", "object", "embed"):
            self._skip += 1
        elif t in ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "hr",
                   "blockquote", "pre", "table"):
            if not self._skip:
                self.parts.append("\n")
        elif t == "td" and not self._skip:
            self.parts.append("\t")

    def handle_endtag(self, tag):
        t = (tag or "").lower()
        if t in ("script", "style", "noscript", "iframe", "object", "embed") and self._skip:
            self._skip -= 1
        elif t in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr", "table", "blockquote") and not self._skip:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip and data:
            self.parts.append(data)


def html_to_text(source: str) -> str:
    parser = _HTMLText()
    try:
        parser.feed(source or "")
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", "", source or "")
        text = re.sub(r"(?s)<[^>]+>", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", "  ", text)
    return text.strip()


def _part_bytes(part) -> bytes:
    try:
        data = part.get_payload(decode=True)
        return data if data is not None else b""
    except Exception:
        return b""


def _decode_part_text(part) -> str:
    data = _part_bytes(part)
    charset = part.get_content_charset() or part.get_charset() or "utf-8"
    if isinstance(charset, bytes):
        charset = charset.decode("ascii", "replace")
    for enc in (charset, "utf-8", "latin-1"):
        try:
            return data.decode(enc, "replace")
        except Exception:
            continue
    return data.decode("utf-8", "replace")


def extract_body_and_attachments(msg) -> tuple:
    text_plain = []
    text_html = []
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get_content_disposition() or "").lower()
            filename = decode_hdr(part.get_filename() or "")
            if ctype.startswith("multipart/"):
                continue
            if disp == "attachment" or (filename and disp != "inline"):
                payload = _part_bytes(part)
                attachments.append(Attachment(
                    filename=filename or "attachment",
                    content_type=ctype or "application/octet-stream",
                    payload=payload,
                ))
                continue
            if ctype == "text/plain":
                text_plain.append(_decode_part_text(part))
            elif ctype == "text/html":
                text_html.append(_decode_part_text(part))
            elif filename:
                attachments.append(Attachment(
                    filename=filename,
                    content_type=ctype or "application/octet-stream",
                    payload=_part_bytes(part),
                ))
    else:
        ctype = (msg.get_content_type() or "text/plain").lower()
        if ctype == "text/html":
            text_html.append(_decode_part_text(msg))
        else:
            text_plain.append(_decode_part_text(msg))

    if text_plain:
        body = "\n\n".join(p.strip() for p in text_plain if p.strip())
    elif text_html:
        body = html_to_text("\n".join(text_html))
    else:
        body = ""
    return body, attachments


def parse_message_bytes(raw: bytes, uid: str, folder: str) -> Message:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    from_name, from_addr = parse_address(msg.get("From", ""))
    to_addrs = parse_address_list(msg.get("To", ""))
    cc_addrs = parse_address_list(msg.get("Cc", ""))
    subject = decode_hdr(msg.get("Subject", "")) or "(no subject)"
    date_raw = msg.get("Date", "")
    dt = None
    try:
        dt = parsedate_to_datetime(date_raw) if date_raw else None
    except Exception:
        dt = None
    body, atts = extract_body_and_attachments(msg)
    return Message(
        uid=str(uid),
        folder=folder,
        from_name=from_name,
        from_addr=from_addr,
        to_addrs=to_addrs,
        cc_addrs=cc_addrs,
        subject=subject,
        date=dt,
        date_text=format_when(dt) or (decode_hdr(date_raw)[:24] if date_raw else ""),
        unseen=False,
        size=len(raw or b""),
        body_text=body,
        attachments=atts,
        message_id=decode_hdr(msg.get("Message-ID", "")),
        reply_to=decode_hdr(msg.get("Reply-To", "")),
        references=decode_hdr(msg.get("References", "")),
        raw_headers="",
    )


# ---------------------------------------------------------------------------
# Errors (never include passwords)
# ---------------------------------------------------------------------------

def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, MailError):
        return str(exc)
    if isinstance(exc, socket.timeout) or isinstance(exc, TimeoutError):
        return "The server did not respond in time. Check the host, port, and your network."
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "The server's security certificate could not be verified. The connection was not opened."
    if isinstance(exc, ssl.SSLError):
        return "A secure connection could not be established."
    if isinstance(exc, ConnectionRefusedError):
        return "The server refused the connection. Check the host and port."
    if isinstance(exc, socket.gaierror):
        return "The server address could not be found. Check the host name."
    if isinstance(exc, ConnectionResetError):
        return "The connection was reset by the server."
    text = str(exc) or exc.__class__.__name__
    text = re.sub(r"password[=:].*", "password=***", text, flags=re.I)
    low = text.lower()
    if "authentication" in low or "login" in low or "invalid credentials" in low or "auth" in low:
        return "Sign-in failed. Check the username and password. Some providers need an app password."
    return "Something went wrong: %s" % text


class MailError(Exception):
    pass


# ---------------------------------------------------------------------------
# Modified UTF-7 for IMAP mailbox names
# ---------------------------------------------------------------------------

def encode_folder(name: str) -> str:
    if not name:
        return name
    if all(0x20 <= ord(c) <= 0x7e and c != "&" for c in name):
        return name.replace("&", "&-") if "&" in name else name
    out = []
    buf = []

    def flush():
        if not buf:
            return
        raw = "".join(buf).encode("utf-16-be")
        b64 = base64.b64encode(raw).decode("ascii").rstrip("=").replace("/", ",")
        out.append("&" + b64 + "-")
        buf.clear()

    for ch in name:
        o = ord(ch)
        if ch == "&":
            flush()
            out.append("&-")
        elif 0x20 <= o <= 0x7e:
            flush()
            out.append(ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def decode_folder(name: str) -> str:
    if not name or "&" not in name:
        return name
    out = []
    i = 0
    while i < len(name):
        if name[i] == "&":
            j = name.find("-", i + 1)
            if j < 0:
                out.append(name[i:])
                break
            token = name[i + 1:j]
            if token == "":
                out.append("&")
            else:
                pad = "=" * ((4 - len(token) % 4) % 4)
                try:
                    raw = base64.b64decode(token.replace(",", "/") + pad)
                    out.append(raw.decode("utf-16-be"))
                except Exception:
                    out.append(name[i:j + 1])
            i = j + 1
        else:
            out.append(name[i])
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Account store
# ---------------------------------------------------------------------------

class AccountStore:
    def __init__(self):
        self.accounts: list[Account] = []
        self.last_account_id: str = ""
        self.load()

    def load(self) -> None:
        self.accounts = []
        self.last_account_id = ""
        secrets = self._load_secrets()
        path = accounts_path()
        if not os.path.isfile(path):
            return
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            return
        self.last_account_id = str(data.get("last_account_id") or "")
        for item in data.get("accounts") or []:
            try:
                acc_id = str(item.get("id") or uuid.uuid4())
                acc = Account(
                    id=acc_id,
                    display_name=str(item.get("display_name") or ""),
                    email=str(item.get("email") or ""),
                    username=str(item.get("username") or item.get("email") or ""),
                    imap_host=str(item.get("imap_host") or ""),
                    imap_port=int(item.get("imap_port") or 993),
                    imap_ssl=bool(item.get("imap_ssl", True)),
                    smtp_host=str(item.get("smtp_host") or ""),
                    smtp_port=int(item.get("smtp_port") or 587),
                    smtp_security=str(item.get("smtp_security") or "starttls"),
                    password=secrets.get(acc_id, ""),
                )
                if acc.smtp_security not in ("ssl", "starttls"):
                    acc.smtp_security = "starttls"
                self.accounts.append(acc)
            except Exception:
                continue

    def save(self) -> None:
        payload = {
            "accounts": [a.public_dict() for a in self.accounts],
            "last_account_id": self.last_account_id or (self.accounts[0].id if self.accounts else ""),
        }
        path = accounts_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
        self._save_secrets()

    def _load_secrets(self) -> dict:
        path = secrets_path()
        if not os.path.isfile(path):
            return {}
        try:
            raw = open(path, "rb").read()
            data = json.loads(raw.decode("utf-8"))
            out = {}
            for k, v in (data or {}).items():
                pw = unprotect_secret(str(v))
                if pw:
                    out[str(k)] = pw
            return out
        except Exception:
            return {}

    def _save_secrets(self) -> None:
        blob = {a.id: protect_secret(a.password) for a in self.accounts if a.password}
        path = secrets_path()
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(json.dumps(blob).encode("utf-8"))
        os.replace(tmp, path)

    def upsert(self, account: Account) -> Account:
        if not account.id:
            account.id = str(uuid.uuid4())
        for i, existing in enumerate(self.accounts):
            if existing.id == account.id:
                if not account.password:
                    account.password = existing.password
                self.accounts[i] = account
                self.last_account_id = account.id
                self.save()
                return account
        self.accounts.append(account)
        self.last_account_id = account.id
        self.save()
        return account

    def remove(self, acc_id: str) -> None:
        self.accounts = [a for a in self.accounts if a.id != acc_id]
        if self.last_account_id == acc_id:
            self.last_account_id = self.accounts[0].id if self.accounts else ""
        self.save()

    def get(self, acc_id: str) -> Optional[Account]:
        for a in self.accounts:
            if a.id == acc_id:
                return a
        return None


# ---------------------------------------------------------------------------
# IMAP session
# ---------------------------------------------------------------------------

_LIST_RE = re.compile(
    r'\((?P<flags>.*?)\)\s+(?P<delim>"[^"]*"|NIL)\s+(?P<name>.+)$',
    re.DOTALL | re.IGNORECASE,
)


def _strip_imap_quotes(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        return name[1:-1].replace('\\"', '"')
    return name


def parse_list_line(raw) -> Optional[Folder]:
    if raw is None:
        return None
    if isinstance(raw, tuple):
        # Some servers split literal mailbox names
        raw = b" ".join(x for x in raw if isinstance(x, (bytes, bytearray)))
    if isinstance(raw, (bytes, bytearray)):
        text = raw.decode("utf-8", "replace")
    else:
        text = str(raw)
    m = _LIST_RE.search(text)
    if not m:
        return None
    flags = tuple(f for f in m.group("flags").split() if f)
    delim_raw = m.group("delim")
    delim = "" if delim_raw.upper() == "NIL" else _strip_imap_quotes(delim_raw)
    name = decode_folder(_strip_imap_quotes(m.group("name")))
    if not name or name == "":
        return None
    return Folder(name=name, delim=delim or "/", flags=flags)


class ImapSession:
    def __init__(self, account: Account):
        self.account = account
        self._lock = threading.RLock()
        self._imap = None
        self._selected = None

    def close(self) -> None:
        with self._lock:
            self._drop()

    def _drop(self) -> None:
        imap = self._imap
        self._imap = None
        self._selected = None
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                try:
                    imap.shutdown()
                except Exception:
                    pass

    def _connect(self):
        acc = self.account
        if not acc.imap_host:
            raise MailError("Enter an IMAP host.")
        ctx = ssl_context()
        if acc.imap_ssl:
            imap = imaplib.IMAP4_SSL(acc.imap_host, int(acc.imap_port or 993), ssl_context=ctx, timeout=IMAP_TIMEOUT)
        else:
            imap = imaplib.IMAP4(acc.imap_host, int(acc.imap_port or 143), timeout=IMAP_TIMEOUT)
            # Never send credentials in the clear.
            try:
                imap.starttls(ssl_context=ctx)
            except Exception as exc:
                try:
                    imap.shutdown()
                except Exception:
                    pass
                raise MailError(
                    "This IMAP port did not offer STARTTLS, and unencrypted sign-in is not allowed. "
                    "Turn on SSL/TLS (port 993) or use a port that supports STARTTLS."
                ) from exc
        user = (acc.username or acc.email or "").strip()
        typ, data = imap.login(user, acc.password or "")
        if typ != "OK":
            raise MailError("Sign-in failed. Check the username and password. Some providers need an app password.")
        try:
            imap.enable("UTF8=ACCEPT")
        except Exception:
            pass
        return imap

    def _ensure(self):
        if self._imap is not None:
            try:
                typ, _ = self._imap.noop()
                if typ == "OK":
                    return self._imap
            except Exception:
                self._drop()
        self._imap = self._connect()
        return self._imap

    def _run(self, fn, retries=1):
        last = None
        for attempt in range(retries + 1):
            with self._lock:
                try:
                    imap = self._ensure()
                    return fn(imap)
                except MailError:
                    raise
                except Exception as exc:
                    last = exc
                    self._drop()
                    if attempt >= retries:
                        raise MailError(friendly_error(exc)) from exc
        raise MailError(friendly_error(last) if last else "Connection failed.")

    def list_folders(self) -> list[Folder]:
        def op(imap):
            typ, data = imap.list()
            if typ != "OK":
                raise MailError("Could not list folders.")
            folders = []
            seen = set()
            for line in data or []:
                folder = parse_list_line(line)
                if not folder or folder.name in seen:
                    continue
                flags = {f.lower() for f in folder.flags}
                if "\\noselect" in flags:
                    continue
                seen.add(folder.name)
                folders.append(folder)
            if not any(f.is_inbox for f in folders):
                folders.insert(0, Folder(name="INBOX", delim="/", flags=("\\Inbox",)))
            def sort_key(f: Folder):
                if f.is_inbox:
                    return (0, f.name.lower())
                flags = {x.lower() for x in f.flags}
                if "\\sent" in flags or f.name.split(f.delim)[-1].lower() in ("sent", "sent items"):
                    return (1, f.name.lower())
                if "\\drafts" in flags or f.name.split(f.delim)[-1].lower() == "drafts":
                    return (2, f.name.lower())
                if "\\junk" in flags or f.name.split(f.delim)[-1].lower() in ("junk", "spam"):
                    return (3, f.name.lower())
                if f.is_trash:
                    return (4, f.name.lower())
                return (5, f.name.lower())
            folders.sort(key=sort_key)
            for folder in folders:
                try:
                    typ, data = imap.status(encode_folder(folder.name), "(UNSEEN MESSAGES)")
                    if typ == "OK" and data and data[0]:
                        blob = data[0].decode("utf-8", "replace") if isinstance(data[0], (bytes, bytearray)) else str(data[0])
                        m_un = re.search(r"UNSEEN\s+(\d+)", blob, re.I)
                        m_tot = re.search(r"MESSAGES\s+(\d+)", blob, re.I)
                        if m_un:
                            folder.unseen = int(m_un.group(1))
                        if m_tot:
                            folder.total = int(m_tot.group(1))
                except Exception:
                    pass
            return folders
        return self._run(op)

    def _select(self, imap, folder: str, readonly: bool = False):
        box = encode_folder(folder or "INBOX")
        if readonly:
            typ, data = imap.select(box, readonly=True)
        else:
            typ, data = imap.select(box)
        if typ != "OK":
            raise MailError("Could not open folder %s." % folder)
        self._selected = folder
        return data

    def list_messages(self, folder: str, limit: int = MAX_LIST) -> list[MessageHeader]:
        def op(imap):
            self._select(imap, folder, readonly=True)
            typ, data = imap.uid("SEARCH", None, "ALL")
            if typ != "OK":
                raise MailError("Could not search the folder.")
            raw = data[0] if data else b""
            if not raw:
                return []
            if isinstance(raw, str):
                parts = raw.split()
            else:
                parts = raw.split()
            uids = [p.decode("ascii", "replace") if isinstance(p, (bytes, bytearray)) else str(p) for p in parts]
            uids = uids[-int(limit):]
            if not uids:
                return []
            typ, data = imap.uid(
                "FETCH",
                ",".join(uids),
                "(FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)])",
            )
            if typ != "OK":
                raise MailError("Could not load messages.")
            messages = _parse_fetch_headers(data or [], folder)
            messages.sort(key=lambda m: m.date or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return messages
        return self._run(op)

    def fetch_message(self, folder: str, uid: str) -> Message:
        def op(imap):
            self._select(imap, folder, readonly=True)
            typ, data = imap.uid("FETCH", str(uid), "(FLAGS BODY.PEEK[])")
            if typ != "OK" or not data:
                raise MailError("Could not open that message.")
            raw, flags = _extract_rfc822(data)
            if not raw:
                raise MailError("Could not open that message.")
            msg = parse_message_bytes(raw, uid, folder)
            msg.unseen = "\\Seen" not in flags
            return msg
        return self._run(op)

    def set_seen(self, folder: str, uid: str, seen: bool) -> None:
        def op(imap):
            self._select(imap, folder, readonly=False)
            if seen:
                typ, _ = imap.uid("STORE", str(uid), "+FLAGS", "(\\Seen)")
            else:
                typ, _ = imap.uid("STORE", str(uid), "-FLAGS", "(\\Seen)")
            if typ != "OK":
                raise MailError("Could not update the read state.")
        self._run(op)

    def delete_message(self, folder: str, uid: str, folders: Optional[list[Folder]] = None) -> None:
        def op(imap):
            self._select(imap, folder, readonly=False)
            current = Folder(name=folder)
            if folders:
                for f in folders:
                    if f.name == folder:
                        current = f
                        break
            if not current.is_trash:
                trash = _find_trash(folders or [])
                if trash and trash.name != folder:
                    moved = False
                    encoded = encode_folder(trash.name)
                    try:
                        typ, _ = imap.uid("MOVE", str(uid), encoded)
                        if typ == "OK":
                            return
                    except Exception:
                        pass
                    typ, _ = imap.uid("COPY", str(uid), encoded)
                    if typ != "OK":
                        # Fall through to a plain delete if no trash copy is possible.
                        typ, _ = imap.uid("STORE", str(uid), "+FLAGS", "(\\Deleted)")
                        imap.expunge()
                        if typ != "OK":
                            raise MailError("Could not delete the message.")
                        return
            typ, _ = imap.uid("STORE", str(uid), "+FLAGS", "(\\Deleted)")
            if typ != "OK":
                raise MailError("Could not delete the message.")
            try:
                imap.uid("EXPUNGE", str(uid))
            except Exception:
                imap.expunge()
        self._run(op)


def _find_trash(folders: list[Folder]) -> Optional[Folder]:
    for f in folders:
        if f.is_trash:
            return f
    return None


def _as_bytes(value) -> bytes:
    if value is None:
        return b""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return str(value).encode("utf-8", "replace")


def _parse_flags(blob: str) -> set:
    m = re.search(r"FLAGS\s*\((.*?)\)", blob, re.I | re.S)
    if not m:
        return set()
    return set(m.group(1).split())


def _extract_rfc822(data) -> tuple:
    raw = b""
    flags = set()
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2:
            meta = _as_bytes(item[0]).decode("utf-8", "replace")
            flags |= _parse_flags(meta)
            raw = _as_bytes(item[1])
            if raw:
                break
        elif isinstance(item, (bytes, bytearray)):
            flags |= _parse_flags(item.decode("utf-8", "replace"))
    return raw, flags


def _parse_fetch_headers(data, folder: str) -> list[MessageHeader]:
    # imaplib returns a list of (meta, header_bytes) tuples plus closing b')' items.
    out = []
    i = 0
    items = list(data or [])
    while i < len(items):
        item = items[i]
        meta = b""
        header = b""
        if isinstance(item, tuple) and len(item) >= 2:
            meta = _as_bytes(item[0])
            header = _as_bytes(item[1])
        elif isinstance(item, (bytes, bytearray)):
            meta = bytes(item)
        i += 1
        text = meta.decode("utf-8", "replace")
        um = re.search(r"UID\s+(\d+)", text, re.I)
        if not um:
            continue
        uid = um.group(1)
        flags = _parse_flags(text)
        size = 0
        sm = re.search(r"RFC822\.SIZE\s+(\d+)", text, re.I)
        if sm:
            size = int(sm.group(1))
        parsed = BytesParser(policy=policy.default).parsebytes(header or b"")
        from_name, from_addr = parse_address(parsed.get("From", ""))
        dt = None
        date_raw = parsed.get("Date", "")
        try:
            dt = parsedate_to_datetime(date_raw) if date_raw else None
        except Exception:
            dt = None
        out.append(MessageHeader(
            uid=uid,
            folder=folder,
            from_name=from_name,
            from_addr=from_addr,
            to_addrs=parse_address_list(parsed.get("To", "")),
            cc_addrs=parse_address_list(parsed.get("Cc", "")),
            subject=decode_hdr(parsed.get("Subject", "")) or "(no subject)",
            date=dt,
            date_text=format_when(dt) or (decode_hdr(date_raw)[:24] if date_raw else ""),
            unseen="\\Seen" not in flags,
            size=size,
        ))
    return out


# ---------------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------------

def send_mail(account: Account, to_addrs: list[str], subject: str, body: str,
              cc_addrs: Optional[list[str]] = None, bcc_addrs: Optional[list[str]] = None,
              attachments: Optional[list[str]] = None,
              in_reply_to: str = "", references: str = "") -> None:
    to_addrs = [a.strip() for a in (to_addrs or []) if a and a.strip()]
    cc_addrs = [a.strip() for a in (cc_addrs or []) if a and a.strip()]
    bcc_addrs = [a.strip() for a in (bcc_addrs or []) if a and a.strip()]
    if not to_addrs and not cc_addrs and not bcc_addrs:
        raise MailError("Add at least one recipient.")
    if not account.smtp_host:
        raise MailError("Enter an SMTP host.")

    msg = EmailMessage()
    from_label = formataddr((account.display_name or "", account.email))
    msg["From"] = from_label
    if to_addrs:
        msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg["Subject"] = subject or ""
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=(account.email.rsplit("@", 1)[-1] if "@" in account.email else None))
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body or "")

    for path in attachments or []:
        if not path or not os.path.isfile(path):
            continue
        name = os.path.basename(path)
        try:
            data = open(path, "rb").read()
        except Exception as exc:
            raise MailError("Could not read attachment %s." % name) from exc
        ctype, _, _ = _guess_type(name)
        maintype, _, subtype = ctype.partition("/")
        msg.add_attachment(data, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=name)

    recipients = to_addrs + cc_addrs + bcc_addrs
    ctx = ssl_context()
    smtp = None
    try:
        if account.smtp_security == "ssl":
            smtp = smtplib.SMTP_SSL(account.smtp_host, int(account.smtp_port or 465),
                                    context=ctx, timeout=SMTP_TIMEOUT)
        else:
            smtp = smtplib.SMTP(account.smtp_host, int(account.smtp_port or 587), timeout=SMTP_TIMEOUT)
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
        user = (account.username or account.email or "").strip()
        smtp.login(user, account.password or "")
        smtp.send_message(msg, from_addr=account.email, to_addrs=recipients)
    except MailError:
        raise
    except Exception as exc:
        raise MailError(friendly_error(exc)) from exc
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:
                try:
                    smtp.close()
                except Exception:
                    pass


def _guess_type(name: str) -> tuple:
    import mimetypes
    ctype, encoding = mimetypes.guess_type(name)
    return (ctype or "application/octet-stream", encoding, None)


def test_account(account: Account) -> str:
    """Connect to IMAP and SMTP to verify settings. Returns a short success message."""
    session = ImapSession(account)
    try:
        folders = session.list_folders()
        n = len(folders)
    finally:
        session.close()
    # SMTP: connect + login, do not send.
    ctx = ssl_context()
    smtp = None
    try:
        if account.smtp_security == "ssl":
            smtp = smtplib.SMTP_SSL(account.smtp_host, int(account.smtp_port or 465),
                                    context=ctx, timeout=SMTP_TIMEOUT)
        else:
            smtp = smtplib.SMTP(account.smtp_host, int(account.smtp_port or 587), timeout=SMTP_TIMEOUT)
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
        user = (account.username or account.email or "").strip()
        smtp.login(user, account.password or "")
    except Exception as exc:
        raise MailError("IMAP worked, but SMTP failed: %s" % friendly_error(exc)) from exc
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:
                try:
                    smtp.close()
                except Exception:
                    pass
    return "Connected. %d folder%s found, SMTP sign-in succeeded." % (n, "" if n == 1 else "s")


def quote_for_reply(msg: Message) -> str:
    who = msg.from_name or msg.from_addr or "Original sender"
    when = ""
    if msg.date:
        try:
            when = msg.date.astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            when = msg.date_text
    header = "On %s, %s wrote:" % (when, who) if when else "%s wrote:" % who
    body = msg.body_text or ""
    quoted = "\n".join(("> " + line) if line else ">" for line in body.splitlines())
    return "\n\n%s\n%s" % (header, quoted)


def subject_for_reply(subject: str) -> str:
    s = (subject or "").strip()
    if re.match(r"(?i)^re\s*:", s):
        return s
    return "Re: " + (s or "(no subject)")


def subject_for_forward(subject: str) -> str:
    s = (subject or "").strip()
    if re.match(r"(?i)^fwd\s*:", s):
        return s
    return "Fwd: " + (s or "(no subject)")


def recipients_csv(pairs: Iterable[tuple]) -> str:
    out = []
    for name, addr in pairs or []:
        if not addr:
            continue
        out.append(formataddr((name or "", addr)))
    return ", ".join(out)
