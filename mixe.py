"""MIXE — desktop email client (IMAP / SMTP).
©2026 EX Inc./HYPERION DIGITAL ©2026
"""
import os
import re
import sys
import threading
import traceback
import uuid

APP = "MIXE"
APP_VERSION = "2.0.0"
COPYRIGHT = "\u00a92026 EX Inc./HYPERION DIGITAL \u00a92026"
REPO = "Teobokki/mixe"
UPDATE_URL = "https://raw.githubusercontent.com/%s/main/latest.json" % REPO
HELP_ACCOUNTS = (
    "MIXE connects with standard IMAP and SMTP. Enter the incoming and outgoing "
    "server details from your mail provider. Some providers (for example Gmail or "
    "Outlook) require an app password instead of your regular password."
)

from PySide6.QtCore import Qt, QThread, QObject, Signal, QSize, QTimer, QUrl
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QAction, QFont, QKeySequence, QColor, QDesktopServices, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QMessageBox, QFileDialog, QListWidget, QListWidgetItem, QSpinBox, QFormLayout, QFrame,
    QStatusBar, QDialog, QLineEdit, QComboBox, QCheckBox, QPlainTextEdit, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMenu, QSizePolicy, QToolButton,
)

from mixe_style import QSS, res_path, ACC, MUT, TXT, DIM, UNREAD, DANGER, WARN
from mixe_mail import (
    Account, AccountStore, Attachment, Folder, ImapSession, MailError, Message, MessageHeader,
    app_data_dir, friendly_error, parse_address_list, preset_for_email, quote_for_reply,
    recipients_csv, send_mail, subject_for_forward, subject_for_reply, test_account,
)


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def is_wine():
    if os.name != "nt":
        return False
    try:
        import ctypes
        return hasattr(ctypes.windll.ntdll, "wine_get_version")
    except Exception:
        return False


class Emblem(QLabel):
    clicked = Signal()

    def __init__(self, h=40):
        super().__init__()
        self._h = h
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("About " + APP)
        self.setFixedSize(h, h)
        self._pm = {}
        for k in (1, 2, 3):
            p = res_path("assets", "emblem@%dx.png" % k)
            if os.path.isfile(p):
                self._pm[k] = QPixmap(p)

    def paintEvent(self, e):
        dpr = self.devicePixelRatioF()
        key = 3 if dpr * self._h > 96 else (2 if dpr * self._h > 48 else 1)
        pm = self._pm.get(key) or self._pm.get(1)
        if not pm:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(self.rect(), pm)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.finished.emit(self.fn())
        except Exception as exc:
            self.failed.emit(friendly_error(exc))


class JobHost:
    """Runs one background job at a time; later jobs replace the tracked worker."""

    def __init__(self, parent):
        self.parent = parent
        self._jobs = []

    def start(self, fn, on_ok, on_fail=None, busy=None):
        thread = QThread(self.parent)
        worker = Worker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def cleanup():
            thread.quit()
            thread.wait(2000)
            worker.deleteLater()
            thread.deleteLater()
            if (thread, worker) in self._jobs:
                self._jobs.remove((thread, worker))

        def ok(result):
            cleanup()
            if on_ok:
                on_ok(result)

        def fail(msg):
            cleanup()
            if on_fail:
                on_fail(msg)

        worker.finished.connect(ok)
        worker.failed.connect(fail)
        self._jobs.append((thread, worker))
        thread.start()
        return thread


# ---------------------------------------------------------------------------
# Account dialog
# ---------------------------------------------------------------------------

class AccountDialog(QDialog):
    def __init__(self, parent=None, account: Account = None):
        super().__init__(parent)
        self.setWindowTitle("Account — " + APP)
        self.setWindowIcon(QIcon(res_path("assets", "logo.ico")))
        self.setModal(True)
        self.resize(560, 640)
        self.setStyleSheet(QSS)
        self._account = account
        self._jobs = JobHost(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QLabel("Add account" if account is None else "Edit account")
        title.setObjectName("h2")
        root.addWidget(title)

        hint = QLabel(HELP_ACCOUNTS)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("Your name")
        self.ed_email = QLineEdit()
        self.ed_email.setPlaceholderText("you@example.com")
        self.ed_email.editingFinished.connect(self._maybe_fill_hosts)
        self.ed_user = QLineEdit()
        self.ed_user.setPlaceholderText("Usually the same as the email address")
        self.ed_pass = QLineEdit()
        self.ed_pass.setEchoMode(QLineEdit.Password)
        self.ed_pass.setPlaceholderText("Password or app password")

        self.ed_imap = QLineEdit()
        self.ed_imap.setPlaceholderText("imap.example.com")
        self.sp_imap = QSpinBox()
        self.sp_imap.setRange(1, 65535)
        self.sp_imap.setValue(993)
        self.ck_imap_ssl = QCheckBox("Use SSL/TLS")
        self.ck_imap_ssl.setChecked(True)
        self.ck_imap_ssl.toggled.connect(self._imap_ssl_toggled)
        imap_row = QHBoxLayout()
        imap_row.addWidget(self.ed_imap, 1)
        imap_row.addWidget(QLabel("Port"))
        imap_row.addWidget(self.sp_imap)
        imap_row.addWidget(self.ck_imap_ssl)

        self.ed_smtp = QLineEdit()
        self.ed_smtp.setPlaceholderText("smtp.example.com")
        self.sp_smtp = QSpinBox()
        self.sp_smtp.setRange(1, 65535)
        self.sp_smtp.setValue(587)
        self.cb_smtp = QComboBox()
        self.cb_smtp.addItem("STARTTLS", "starttls")
        self.cb_smtp.addItem("SSL/TLS", "ssl")
        self.cb_smtp.currentIndexChanged.connect(self._smtp_sec_changed)
        smtp_row = QHBoxLayout()
        smtp_row.addWidget(self.ed_smtp, 1)
        smtp_row.addWidget(QLabel("Port"))
        smtp_row.addWidget(self.sp_smtp)
        smtp_row.addWidget(self.cb_smtp)

        form.addRow("Display name", self.ed_name)
        form.addRow("Email", self.ed_email)
        form.addRow("Username", self.ed_user)
        form.addRow("Password", self.ed_pass)
        form.addRow("IMAP host", imap_row)
        form.addRow("SMTP host", smtp_row)
        root.addLayout(form)

        self.lab_status = QLabel("")
        self.lab_status.setObjectName("hint")
        self.lab_status.setWordWrap(True)
        root.addWidget(self.lab_status)
        root.addStretch(1)

        row = QHBoxLayout()
        self.btn_test = QPushButton("Test connection")
        self.btn_test.setObjectName("secondary")
        self.btn_test.clicked.connect(self._test)
        row.addWidget(self.btn_test)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(save)
        root.addLayout(row)

        if account:
            self.ed_name.setText(account.display_name)
            self.ed_email.setText(account.email)
            self.ed_user.setText(account.username or account.email)
            self.ed_pass.setPlaceholderText("Leave blank to keep the saved password")
            self.ed_imap.setText(account.imap_host)
            self.sp_imap.setValue(int(account.imap_port or 993))
            self.ck_imap_ssl.setChecked(bool(account.imap_ssl))
            self.ed_smtp.setText(account.smtp_host)
            self.sp_smtp.setValue(int(account.smtp_port or 587))
            idx = self.cb_smtp.findData(account.smtp_security or "starttls")
            if idx >= 0:
                self.cb_smtp.setCurrentIndex(idx)

    def _imap_ssl_toggled(self, on):
        if on and self.sp_imap.value() in (143, 993):
            self.sp_imap.setValue(993)
        elif not on and self.sp_imap.value() in (143, 993):
            self.sp_imap.setValue(143)

    def _smtp_sec_changed(self):
        sec = self.cb_smtp.currentData()
        if sec == "ssl" and self.sp_smtp.value() in (587, 465):
            self.sp_smtp.setValue(465)
        elif sec == "starttls" and self.sp_smtp.value() in (587, 465):
            self.sp_smtp.setValue(587)

    def _maybe_fill_hosts(self):
        email = self.ed_email.text().strip()
        if not self.ed_user.text().strip():
            self.ed_user.setText(email)
        preset = preset_for_email(email)
        if not preset:
            return
        imap_host, imap_port, imap_ssl, smtp_host, smtp_port, smtp_sec = preset
        if not self.ed_imap.text().strip():
            self.ed_imap.setText(imap_host)
            self.sp_imap.setValue(imap_port)
            self.ck_imap_ssl.setChecked(imap_ssl)
        if not self.ed_smtp.text().strip():
            self.ed_smtp.setText(smtp_host)
            self.sp_smtp.setValue(smtp_port)
            idx = self.cb_smtp.findData(smtp_sec)
            if idx >= 0:
                self.cb_smtp.setCurrentIndex(idx)

    def built_account(self) -> Account:
        email = self.ed_email.text().strip()
        user = self.ed_user.text().strip() or email
        password = self.ed_pass.text()
        if self._account and not password:
            password = self._account.password
        return Account(
            id=(self._account.id if self._account else str(uuid.uuid4())),
            display_name=self.ed_name.text().strip() or email,
            email=email,
            username=user,
            imap_host=self.ed_imap.text().strip(),
            imap_port=int(self.sp_imap.value()),
            imap_ssl=self.ck_imap_ssl.isChecked(),
            smtp_host=self.ed_smtp.text().strip(),
            smtp_port=int(self.sp_smtp.value()),
            smtp_security=self.cb_smtp.currentData() or "starttls",
            password=password,
        )

    def _validate(self) -> str:
        acc = self.built_account()
        if not acc.email or "@" not in acc.email:
            return "Enter a valid email address."
        if not acc.password:
            return "Enter a password or app password."
        if not acc.imap_host:
            return "Enter an IMAP host."
        if not acc.smtp_host:
            return "Enter an SMTP host."
        return ""

    def _test(self):
        err = self._validate()
        if err:
            self.lab_status.setText(err)
            self.lab_status.setObjectName("error")
            self.lab_status.setStyleSheet(QSS)
            return
        self.btn_test.setEnabled(False)
        self.lab_status.setObjectName("hint")
        self.lab_status.setStyleSheet(QSS)
        self.lab_status.setText("Testing connection…")
        acc = self.built_account()

        def done(msg):
            self.btn_test.setEnabled(True)
            self.lab_status.setText(msg)

        def fail(msg):
            self.btn_test.setEnabled(True)
            self.lab_status.setObjectName("error")
            self.lab_status.setStyleSheet(QSS)
            self.lab_status.setText(msg)

        self._jobs.start(lambda: test_account(acc), done, fail)

    def _save(self):
        err = self._validate()
        if err:
            self.lab_status.setText(err)
            return
        self.accept()


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------

class ComposeDialog(QDialog):
    def __init__(self, parent, account: Account, on_send, to_text="", cc_text="", bcc_text="",
                 subject="", body="", attach_paths=None, title="Compose"):
        super().__init__(parent)
        self.account = account
        self._on_send = on_send
        self.setWindowTitle("%s — %s" % (title, APP))
        self.setWindowIcon(QIcon(res_path("assets", "logo.ico")))
        self.resize(760, 620)
        self.setStyleSheet(QSS)
        self.attachments = list(attach_paths or [])

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(6)
        self.ed_from = QLineEdit(account.label())
        self.ed_from.setReadOnly(True)
        self.ed_to = QLineEdit(to_text)
        self.ed_to.setPlaceholderText("name@example.com, …")
        self.ed_cc = QLineEdit(cc_text)
        self.ed_cc.setPlaceholderText("Optional")
        self.ed_bcc = QLineEdit(bcc_text)
        self.ed_bcc.setPlaceholderText("Optional")
        self.ed_subject = QLineEdit(subject)
        form.addRow("From", self.ed_from)
        form.addRow("To", self.ed_to)
        form.addRow("Cc", self.ed_cc)
        form.addRow("Bcc", self.ed_bcc)
        form.addRow("Subject", self.ed_subject)
        root.addLayout(form)

        self.body = QPlainTextEdit()
        self.body.setPlainText(body or "")
        root.addWidget(self.body, 1)

        att_row = QHBoxLayout()
        self.lab_att = QLabel("No attachments")
        self.lab_att.setObjectName("muted")
        att_row.addWidget(self.lab_att, 1)
        b_add = QPushButton("Attach")
        b_add.setObjectName("secondary")
        b_add.clicked.connect(self._add_att)
        b_clear = QPushButton("Clear attachments")
        b_clear.setObjectName("flat")
        b_clear.clicked.connect(self._clear_att)
        att_row.addWidget(b_add)
        att_row.addWidget(b_clear)
        root.addLayout(att_row)
        self._refresh_att()

        self.lab_status = QLabel("")
        self.lab_status.setObjectName("hint")
        self.lab_status.setWordWrap(True)
        root.addWidget(self.lab_status)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        self.btn_send = QPushButton("Send")
        self.btn_send.setObjectName("primary")
        self.btn_send.clicked.connect(self._send)
        row.addWidget(cancel)
        row.addWidget(self.btn_send)
        root.addLayout(row)

    def _refresh_att(self):
        if not self.attachments:
            self.lab_att.setText("No attachments")
        else:
            names = [os.path.basename(p) for p in self.attachments]
            self.lab_att.setText("%d attachment%s: %s" % (
                len(names), "" if len(names) == 1 else "s", ", ".join(names)
            ))

    def _add_att(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Attach files", "", "All files (*.*)")
        for p in paths:
            if p and p not in self.attachments:
                self.attachments.append(p)
        self._refresh_att()

    def _clear_att(self):
        self.attachments = []
        self._refresh_att()

    def _split_addrs(self, text: str) -> list:
        out = []
        for part in re.split(r"[;,]+", text or ""):
            part = part.strip()
            if not part:
                continue
            # Keep "Name <addr@host>" or bare addresses.
            if "<" in part and ">" in part:
                out.append(part)
            elif "@" in part:
                out.append(part)
            else:
                out.append(part)
        return out

    def _send(self):
        to_addrs = self._split_addrs(self.ed_to.text())
        cc_addrs = self._split_addrs(self.ed_cc.text())
        bcc_addrs = self._split_addrs(self.ed_bcc.text())
        if not to_addrs and not cc_addrs and not bcc_addrs:
            self.lab_status.setText("Add at least one recipient.")
            return
        self.btn_send.setEnabled(False)
        self.lab_status.setText("Sending…")
        subject = self.ed_subject.text()
        body = self.body.toPlainText()
        atts = list(self.attachments)
        acc = self.account

        def work():
            send_mail(acc, to_addrs, subject, body, cc_addrs, bcc_addrs, atts)
            return True

        def ok(_):
            self.accept()
            if self._on_send:
                self._on_send("Message sent.")

        def fail(msg):
            self.btn_send.setEnabled(True)
            self.lab_status.setText(msg)

        # Keep a reference so the thread is not collected mid-send.
        if not hasattr(self, "_jobs"):
            self._jobs = JobHost(self)
        self._jobs.start(work, ok, fail)


# ---------------------------------------------------------------------------
# Accounts manager
# ---------------------------------------------------------------------------

class AccountsDialog(QDialog):
    def __init__(self, parent, store: AccountStore, on_change):
        super().__init__(parent)
        self.store = store
        self.on_change = on_change
        self.setWindowTitle("Accounts — " + APP)
        self.setWindowIcon(QIcon(res_path("assets", "logo.ico")))
        self.resize(520, 380)
        self.setStyleSheet(QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        title = QLabel("Accounts")
        title.setObjectName("h2")
        root.addWidget(title)
        self.list = QListWidget()
        root.addWidget(self.list, 1)
        row = QHBoxLayout()
        b_add = QPushButton("Add")
        b_add.setObjectName("primary")
        b_add.clicked.connect(self._add)
        b_edit = QPushButton("Edit")
        b_edit.setObjectName("secondary")
        b_edit.clicked.connect(self._edit)
        b_del = QPushButton("Remove")
        b_del.setObjectName("danger")
        b_del.clicked.connect(self._remove)
        row.addWidget(b_add)
        row.addWidget(b_edit)
        row.addWidget(b_del)
        row.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("secondary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)
        self.list.itemDoubleClicked.connect(lambda *_: self._edit())
        self.refresh()

    def refresh(self):
        self.list.clear()
        for acc in self.store.accounts:
            item = QListWidgetItem(acc.label())
            item.setData(Qt.UserRole, acc.id)
            self.list.addItem(item)
        if self.list.count() and not self.list.currentItem():
            self.list.setCurrentRow(0)

    def _selected_id(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _add(self):
        dlg = AccountDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.store.upsert(dlg.built_account())
            self.refresh()
            if self.on_change:
                self.on_change()

    def _edit(self):
        acc_id = self._selected_id()
        acc = self.store.get(acc_id) if acc_id else None
        if not acc:
            return
        dlg = AccountDialog(self, acc)
        if dlg.exec() == QDialog.Accepted:
            self.store.upsert(dlg.built_account())
            self.refresh()
            if self.on_change:
                self.on_change()

    def _remove(self):
        acc_id = self._selected_id()
        acc = self.store.get(acc_id) if acc_id else None
        if not acc:
            return
        if QMessageBox.question(self, APP, "Remove %s from MIXE? Mail on the server is not deleted." % acc.email) != QMessageBox.Yes:
            return
        self.store.remove(acc.id)
        self.refresh()
        if self.on_change:
            self.on_change()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class Main(QMainWindow):
    def __init__(self, demo=False):
        super().__init__()
        self.setWindowTitle(APP)
        self.setWindowIcon(QIcon(res_path("assets", "logo.ico")))
        self.resize(1280, 800)
        self.store = AccountStore()
        self.session = None
        self.folders = []
        self.headers = []
        self.current_folder = "INBOX"
        self.current_message = None
        self._busy = False
        self._jobs = JobHost(self)
        self._demo = demo
        self._gen = 0

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        top = QWidget()
        top.setObjectName("topbar")
        th = QHBoxLayout(top)
        th.setContentsMargins(12, 8, 12, 8)
        th.setSpacing(10)
        self.emblem = Emblem(40)
        self.emblem.clicked.connect(self.about)
        th.addWidget(self.emblem)
        t = QLabel(APP)
        t.setObjectName("apptitle")
        th.addWidget(t)
        vl = QLabel("v" + APP_VERSION)
        vl.setObjectName("muted")
        th.addWidget(vl)

        self.cb_account = QComboBox()
        self.cb_account.setMinimumWidth(240)
        self.cb_account.currentIndexChanged.connect(self._account_changed)
        th.addWidget(self.cb_account)

        th.addStretch(1)
        self.b_refresh = QPushButton("Refresh")
        self.b_refresh.setObjectName("secondary")
        self.b_refresh.clicked.connect(self.refresh_current)
        th.addWidget(self.b_refresh)
        self.b_compose = QPushButton("Compose")
        self.b_compose.setObjectName("primary")
        self.b_compose.clicked.connect(self.compose_new)
        th.addWidget(self.b_compose)
        b_acc = QPushButton("Accounts")
        b_acc.setObjectName("secondary")
        b_acc.clicked.connect(self.manage_accounts)
        th.addWidget(b_acc)
        b_upd = QPushButton("Check for updates")
        b_upd.setObjectName("flat")
        b_upd.clicked.connect(self.check_updates)
        th.addWidget(b_upd)
        b_ab = QPushButton("About")
        b_ab.setObjectName("flat")
        b_ab.clicked.connect(self.about)
        th.addWidget(b_ab)
        v.addWidget(top)
        line = QWidget()
        line.setFixedHeight(1)
        line.setObjectName("hline")
        v.addWidget(line)

        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(40, 40, 40, 40)
        ev.addStretch(1)
        h = QLabel("MIXE")
        h.setObjectName("h1")
        h.setAlignment(Qt.AlignCenter)
        ev.addWidget(h)
        p = QLabel("Add an email account to start sending and receiving mail.")
        p.setObjectName("body")
        p.setAlignment(Qt.AlignCenter)
        ev.addWidget(p)
        ev.addSpacing(12)
        row = QHBoxLayout()
        row.addStretch(1)
        add = QPushButton("Add account")
        add.setObjectName("primary")
        add.clicked.connect(self.add_account)
        row.addWidget(add)
        row.addStretch(1)
        ev.addLayout(row)
        ev.addStretch(1)

        self.mail = QWidget()
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        mv = QHBoxLayout(self.mail)
        mv.setContentsMargins(10, 10, 10, 10)
        mv.addWidget(split)

        self.folder_list = QTreeWidget()
        self.folder_list.setHeaderHidden(True)
        self.folder_list.setMinimumWidth(180)
        self.folder_list.setAnimated(False)
        self.folder_list.itemSelectionChanged.connect(self._folder_selected)
        split.addWidget(self.folder_list)

        mid = QSplitter(Qt.Vertical)
        mid.setChildrenCollapsible(False)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["From", "Subject", "Date"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setHighlightSections(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.itemSelectionChanged.connect(self._message_selected)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._message_menu)
        mid.addWidget(self.table)

        reader = QWidget()
        rv = QVBoxLayout(reader)
        rv.setContentsMargins(0, 6, 0, 0)
        rv.setSpacing(6)
        self.lab_r_subject = QLabel("Select a message")
        self.lab_r_subject.setObjectName("h2")
        self.lab_r_subject.setWordWrap(True)
        rv.addWidget(self.lab_r_subject)
        self.lab_r_meta = QLabel("")
        self.lab_r_meta.setObjectName("muted")
        self.lab_r_meta.setWordWrap(True)
        rv.addWidget(self.lab_r_meta)
        act = QHBoxLayout()
        self.b_reply = QPushButton("Reply")
        self.b_reply.setObjectName("secondary")
        self.b_reply.clicked.connect(self.reply)
        self.b_replyall = QPushButton("Reply all")
        self.b_replyall.setObjectName("secondary")
        self.b_replyall.clicked.connect(self.reply_all)
        self.b_fwd = QPushButton("Forward")
        self.b_fwd.setObjectName("secondary")
        self.b_fwd.clicked.connect(self.forward)
        self.b_read = QPushButton("Mark unread")
        self.b_read.setObjectName("secondary")
        self.b_read.clicked.connect(self.toggle_read)
        self.b_del = QPushButton("Delete")
        self.b_del.setObjectName("danger")
        self.b_del.clicked.connect(self.delete_message)
        for b in (self.b_reply, self.b_replyall, self.b_fwd, self.b_read, self.b_del):
            b.setEnabled(False)
            act.addWidget(b)
        act.addStretch(1)
        rv.addLayout(act)
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setPlaceholderText("Message body")
        rv.addWidget(self.body, 1)
        self.att_row = QHBoxLayout()
        self.lab_att = QLabel("")
        self.lab_att.setObjectName("muted")
        self.att_row.addWidget(self.lab_att, 1)
        self.b_save_att = QPushButton("Save attachments")
        self.b_save_att.setObjectName("secondary")
        self.b_save_att.clicked.connect(self.save_attachments)
        self.b_save_att.setEnabled(False)
        self.att_row.addWidget(self.b_save_att)
        rv.addLayout(self.att_row)
        mid.addWidget(reader)
        mid.setSizes([320, 420])
        split.addWidget(mid)
        split.setSizes([220, 1000])

        self.stack_host = QVBoxLayout()
        self.stack_host.setContentsMargins(0, 0, 0, 0)
        self.stack_host.addWidget(self.empty)
        self.stack_host.addWidget(self.mail)
        v.addLayout(self.stack_host, 1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage(COPYRIGHT)

        QShortcut(QKeySequence("Ctrl+N"), self, self.compose_new)
        QShortcut(QKeySequence("Ctrl+R"), self, self.reply)
        QShortcut(QKeySequence("F5"), self, self.refresh_current)
        QShortcut(QKeySequence("Delete"), self, self.delete_message)

        self._reload_accounts_combo(select=self.store.last_account_id)
        if self._demo:
            self._load_demo()
        elif not self.store.accounts:
            self._show_empty(True)
        else:
            self._show_empty(False)
            self.refresh_folders()

    def _show_empty(self, empty: bool):
        self.empty.setVisible(empty)
        self.mail.setVisible(not empty)
        self.b_refresh.setEnabled(not empty)
        self.b_compose.setEnabled(not empty and bool(self.current_account()))

    def current_account(self) -> Account:
        acc_id = self.cb_account.currentData()
        return self.store.get(acc_id) if acc_id else None

    def _reload_accounts_combo(self, select=None):
        self.cb_account.blockSignals(True)
        self.cb_account.clear()
        for acc in self.store.accounts:
            self.cb_account.addItem(acc.label(), acc.id)
        if select:
            idx = self.cb_account.findData(select)
            if idx >= 0:
                self.cb_account.setCurrentIndex(idx)
        self.cb_account.blockSignals(False)

    def _close_session(self):
        sess = self.session
        self.session = None
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass

    def _account_changed(self):
        acc = self.current_account()
        if acc:
            self.store.last_account_id = acc.id
            self.store.save()
        self._close_session()
        self.folders = []
        self.headers = []
        self.current_message = None
        self.folder_list.clear()
        self.table.setRowCount(0)
        self._clear_reader()
        if acc:
            self._show_empty(False)
            self.refresh_folders()
        else:
            self._show_empty(True)

    def manage_accounts(self):
        dlg = AccountsDialog(self, self.store, self._after_accounts_changed)
        dlg.exec()

    def add_account(self):
        dlg = AccountDialog(self)
        if dlg.exec() == QDialog.Accepted:
            acc = self.store.upsert(dlg.built_account())
            self._after_accounts_changed(select=acc.id)

    def _after_accounts_changed(self, select=None):
        current = select or (self.current_account().id if self.current_account() else self.store.last_account_id)
        self._reload_accounts_combo(select=current)
        if self.store.accounts:
            self._show_empty(False)
            self._close_session()
            self.refresh_folders()
        else:
            self._close_session()
            self._show_empty(True)

    def _session_for(self, acc: Account) -> ImapSession:
        if self.session is not None and self.session.account.id == acc.id:
            # Keep password in sync if it was edited.
            self.session.account = acc
            return self.session
        self._close_session()
        self.session = ImapSession(acc)
        return self.session

    def set_busy(self, msg=None):
        self._busy = True
        self.b_refresh.setEnabled(False)
        if msg:
            self.status.showMessage(msg)

    def clear_busy(self, msg=None):
        self._busy = False
        self.b_refresh.setEnabled(bool(self.current_account()))
        self.status.showMessage(msg if msg is not None else COPYRIGHT)

    def _run(self, fn, on_ok, busy_msg, on_fail=None):
        self._gen += 1
        gen = self._gen
        self.set_busy(busy_msg)

        def ok(result):
            if gen != self._gen:
                return
            self.clear_busy(COPYRIGHT)
            on_ok(result)

        def fail(msg):
            if gen != self._gen:
                return
            self.clear_busy(msg)
            if on_fail:
                on_fail(msg)
            else:
                self.status.showMessage(msg)

        self._jobs.start(fn, ok, fail)

    def refresh_folders(self):
        acc = self.current_account()
        if not acc:
            return
        if self._demo:
            return

        def work():
            return self._session_for(acc).list_folders()

        def ok(folders):
            self.folders = folders or []
            self._fill_folders()
            target = self.current_folder or "INBOX"
            names = [f.name for f in self.folders]
            if target not in names:
                target = "INBOX" if "INBOX" in names else (names[0] if names else "INBOX")
            self.current_folder = target
            self._select_folder_item(target)
            self.refresh_messages(target)

        self._run(work, ok, "Loading folders…")

    def _fill_folders(self):
        self.folder_list.blockSignals(True)
        self.folder_list.clear()
        for folder in self.folders:
            label = folder.name
            if folder.unseen:
                label = "%s  (%d)" % (folder.name, folder.unseen)
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.UserRole, folder.name)
            if folder.is_inbox:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            self.folder_list.addTopLevelItem(item)
        self.folder_list.blockSignals(False)

    def _select_folder_item(self, name):
        self.folder_list.blockSignals(True)
        for i in range(self.folder_list.topLevelItemCount()):
            item = self.folder_list.topLevelItem(i)
            if item.data(0, Qt.UserRole) == name:
                self.folder_list.setCurrentItem(item)
                break
        self.folder_list.blockSignals(False)

    def _folder_selected(self):
        items = self.folder_list.selectedItems()
        if not items:
            return
        name = items[0].data(0, Qt.UserRole)
        if not name or name == self.current_folder and self.headers:
            # still allow re-click via Refresh
            if name == self.current_folder:
                return
        self.current_folder = name
        self.refresh_messages(name)

    def refresh_current(self):
        if self.current_account():
            self.refresh_folders()

    def refresh_messages(self, folder: str):
        acc = self.current_account()
        if not acc or self._demo:
            return

        def work():
            return self._session_for(acc).list_messages(folder)

        def ok(headers):
            self.headers = headers or []
            self._fill_table()
            n = len(self.headers)
            unseen = sum(1 for h in self.headers if h.unseen)
            self.status.showMessage("%s — %d message%s%s" % (
                folder, n, "" if n == 1 else "s",
                ("  ·  %d unread" % unseen) if unseen else "",
            ))

        self._run(work, ok, "Loading %s…" % folder)

    def _fill_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.headers))
        bold = QFont()
        bold.setBold(True)
        for row, h in enumerate(self.headers):
            who = h.from_name or h.from_addr or "(unknown)"
            items = [
                QTableWidgetItem(who),
                QTableWidgetItem(h.subject or "(no subject)"),
                QTableWidgetItem(h.date_text or ""),
            ]
            items[0].setData(Qt.UserRole, h.uid)
            items[0].setToolTip(h.from_addr or who)
            items[1].setToolTip(h.subject or "")
            for col, item in enumerate(items):
                if h.unseen:
                    item.setFont(bold)
                    item.setForeground(QColor(UNREAD))
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)

    def _selected_header(self) -> MessageHeader:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self.headers):
            return self.headers[row]
        return None

    def _message_selected(self):
        header = self._selected_header()
        if not header:
            return
        acc = self.current_account()
        if not acc:
            return
        if self._demo:
            # Already populated in demo mode.
            return

        def work():
            sess = self._session_for(acc)
            msg = sess.fetch_message(header.folder, header.uid)
            if msg.unseen:
                try:
                    sess.set_seen(header.folder, header.uid, True)
                    msg.unseen = False
                except Exception:
                    pass
            return msg

        def ok(msg):
            self.current_message = msg
            for h in self.headers:
                if h.uid == msg.uid:
                    h.unseen = False
                    break
            # Update the row style without rebuilding the whole table (keeps selection).
            row = self.table.currentRow()
            if 0 <= row < self.table.rowCount():
                font = QFont()
                font.setBold(False)
                for col in range(3):
                    item = self.table.item(row, col)
                    if item:
                        item.setFont(font)
                        item.setForeground(QColor(TXT))
            self._show_message(msg)

        def fail(err):
            self._clear_reader()
            self.lab_r_subject.setText("Could not open message")
            self.body.setPlainText(err)

        self._run(work, ok, "Opening message…", on_fail=fail)

    def _clear_reader(self):
        self.current_message = None
        self.lab_r_subject.setText("Select a message")
        self.lab_r_meta.setText("")
        self.body.setPlainText("")
        self.lab_att.setText("")
        for b in (self.b_reply, self.b_replyall, self.b_fwd, self.b_read, self.b_del, self.b_save_att):
            b.setEnabled(False)

    def _show_message(self, msg: Message):
        self.lab_r_subject.setText(msg.subject or "(no subject)")
        who = msg.from_name or msg.from_addr or "(unknown)"
        if msg.from_name and msg.from_addr:
            who = "%s <%s>" % (msg.from_name, msg.from_addr)
        to_line = recipients_csv(msg.to_addrs) or ""
        meta = "From  %s" % who
        if msg.date_text:
            meta += "    ·    %s" % (msg.date.astimezone().strftime("%Y-%m-%d %H:%M") if msg.date else msg.date_text)
        if to_line:
            meta += "\nTo    %s" % to_line
        if msg.cc_addrs:
            meta += "\nCc    %s" % recipients_csv(msg.cc_addrs)
        self.lab_r_meta.setText(meta)
        self.body.setPlainText(msg.body_text or "")
        if msg.attachments:
            names = ["%s (%s)" % (a.filename, _size_label(a.size)) for a in msg.attachments]
            self.lab_att.setText("Attachments: " + ", ".join(names))
            self.b_save_att.setEnabled(True)
        else:
            self.lab_att.setText("No attachments")
            self.b_save_att.setEnabled(False)
        for b in (self.b_reply, self.b_replyall, self.b_fwd, self.b_del):
            b.setEnabled(True)
        self.b_read.setEnabled(True)
        self.b_read.setText("Mark unread" if not msg.unseen else "Mark read")

    def _message_menu(self, pos):
        if not self._selected_header():
            return
        menu = QMenu(self)
        menu.addAction("Reply", self.reply)
        menu.addAction("Reply all", self.reply_all)
        menu.addAction("Forward", self.forward)
        menu.addSeparator()
        menu.addAction("Mark read", lambda: self._set_read(True))
        menu.addAction("Mark unread", lambda: self._set_read(False))
        menu.addSeparator()
        menu.addAction("Delete", self.delete_message)
        if self.current_message and self.current_message.attachments:
            menu.addSeparator()
            menu.addAction("Save attachments", self.save_attachments)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def compose_new(self):
        acc = self.current_account()
        if not acc:
            self.add_account()
            return
        self._open_compose(acc, title="Compose")

    def reply(self):
        self._reply(all_recipients=False)

    def reply_all(self):
        self._reply(all_recipients=True)

    def _reply(self, all_recipients=False):
        acc = self.current_account()
        msg = self.current_message
        if not acc or not msg:
            return
        to_addr = msg.reply_to or (format_addr_pair(msg.from_name, msg.from_addr))
        cc = ""
        if all_recipients:
            others = []
            for name, addr in (msg.to_addrs or []) + (msg.cc_addrs or []):
                if not addr:
                    continue
                if addr.lower() == (acc.email or "").lower():
                    continue
                if addr.lower() == (msg.from_addr or "").lower():
                    continue
                others.append(format_addr_pair(name, addr))
            cc = ", ".join(others)
        self._open_compose(
            acc,
            to_text=to_addr,
            cc_text=cc,
            subject=subject_for_reply(msg.subject),
            body=quote_for_reply(msg),
            title="Reply",
            in_reply_to=msg.message_id,
            references=" ".join(x for x in (msg.references, msg.message_id) if x),
        )

    def forward(self):
        acc = self.current_account()
        msg = self.current_message
        if not acc or not msg:
            return
        intro = "---------- Forwarded message ----------\n"
        if msg.from_addr:
            intro += "From: %s\n" % format_addr_pair(msg.from_name, msg.from_addr)
        if msg.date:
            try:
                intro += "Date: %s\n" % msg.date.astimezone().strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
        intro += "Subject: %s\n\n" % (msg.subject or "")
        paths = []
        if msg.attachments:
            # Write attachments to a temp dir so the compose dialog can re-attach them.
            tmp = os.path.join(app_data_dir(), "forward_tmp", msg.uid or "msg")
            os.makedirs(tmp, exist_ok=True)
            for att in msg.attachments:
                safe = re.sub(r"[\\/:*?\"<>|]", "_", att.filename or "attachment")
                path = os.path.join(tmp, safe)
                try:
                    with open(path, "wb") as fh:
                        fh.write(att.payload or b"")
                    paths.append(path)
                except Exception:
                    pass
        self._open_compose(
            acc,
            subject=subject_for_forward(msg.subject),
            body=intro + (msg.body_text or ""),
            attach_paths=paths,
            title="Forward",
        )

    def _open_compose(self, acc, to_text="", cc_text="", bcc_text="", subject="", body="",
                      attach_paths=None, title="Compose", in_reply_to="", references=""):
        def after(msg):
            self.status.showMessage(msg)

        dlg = ComposeDialog(
            self, acc, after, to_text=to_text, cc_text=cc_text, bcc_text=bcc_text,
            subject=subject, body=body, attach_paths=attach_paths, title=title,
        )
        # Stash threading headers onto a custom send by wrapping send_mail inside dialog?
        # ComposeDialog calls send_mail directly. For reply headers, subclass the send:
        if in_reply_to or references:
            orig_send = send_mail

            def hooked(account, to_addrs, subject_, body_, cc_addrs=None, bcc_addrs=None, attachments=None,
                       in_reply_to_=in_reply_to, references_=references):
                return orig_send(account, to_addrs, subject_, body_, cc_addrs, bcc_addrs, attachments,
                                 in_reply_to=in_reply_to_, references=references_)

            import mixe_mail as mm
            # Patch only for this dialog send via a bound wrapper on the dialog's _send path is messy.
            # Instead, temporarily wrap mixe_mail.send_mail — no, too global.
            # We'll set attributes the dialog can read if present.
            dlg._in_reply_to = in_reply_to
            dlg._references = references
            _patch_compose_send(dlg)
        dlg.exec()

    def toggle_read(self):
        msg = self.current_message or self._selected_header()
        if not msg:
            return
        self._set_read(bool(getattr(msg, "unseen", False)))

    def _set_read(self, seen: bool):
        acc = self.current_account()
        header = self._selected_header()
        if not acc or not header:
            return
        if self._demo:
            header.unseen = not seen
            if self.current_message and self.current_message.uid == header.uid:
                self.current_message.unseen = not seen
                self.b_read.setText("Mark unread" if seen else "Mark read")
            self._fill_table()
            return

        def work():
            self._session_for(acc).set_seen(header.folder, header.uid, seen)
            return seen

        def ok(seen_val):
            for h in self.headers:
                if h.uid == header.uid:
                    h.unseen = not seen_val
            if self.current_message and self.current_message.uid == header.uid:
                self.current_message.unseen = not seen_val
                self.b_read.setText("Mark unread" if seen_val else "Mark read")
            row = self.table.currentRow()
            self._fill_table()
            if 0 <= row < self.table.rowCount():
                self.table.selectRow(row)

        self._run(work, ok, "Updating…")

    def delete_message(self):
        acc = self.current_account()
        header = self._selected_header()
        if not acc or not header:
            return
        if self._demo:
            self.headers = [h for h in self.headers if h.uid != header.uid]
            self._fill_table()
            self._clear_reader()
            return

        def work():
            self._session_for(acc).delete_message(header.folder, header.uid, self.folders)
            return header.uid

        def ok(uid):
            self.headers = [h for h in self.headers if h.uid != uid]
            self._fill_table()
            self._clear_reader()
            self.status.showMessage("Message deleted.")

        self._run(work, ok, "Deleting…")

    def save_attachments(self):
        msg = self.current_message
        if not msg or not msg.attachments:
            return
        dest = QFileDialog.getExistingDirectory(self, "Save attachments")
        if not dest:
            return
        saved = 0
        errors = []
        for att in msg.attachments:
            safe = re.sub(r"[\\/:*?\"<>|]", "_", att.filename or "attachment")
            path = os.path.join(dest, safe)
            base, ext = os.path.splitext(path)
            n = 1
            while os.path.exists(path):
                path = "%s (%d)%s" % (base, n, ext)
                n += 1
            try:
                with open(path, "wb") as fh:
                    fh.write(att.payload or b"")
                saved += 1
            except Exception as exc:
                errors.append("%s: %s" % (safe, exc))
        if errors:
            QMessageBox.warning(self, APP, "Saved %d file(s), but some failed:\n%s" % (saved, "\n".join(errors)))
        else:
            self.status.showMessage("Saved %d attachment%s." % (saved, "" if saved == 1 else "s"))

    def about(self):
        QMessageBox.information(
            self, "About " + APP,
            "%s  %s\n\n"
            "A desktop email client for any IMAP and SMTP account.\n"
            "Send and receive real mail, read folders, and save attachments.\n\n"
            "Accounts are stored only on this PC. Passwords are protected with "
            "the signed-in Windows user account.\n\n"
            "%s" % (APP, APP_VERSION, COPYRIGHT),
        )

    def check_updates(self):
        import json
        from urllib.request import urlopen, Request

        def work():
            req = Request(UPDATE_URL, headers={"User-Agent": APP + "/" + APP_VERSION})
            with urlopen(req, timeout=15, context=__import__("ssl").create_default_context()) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data

        def ok(data):
            remote = str((data or {}).get("version") or "")
            notes = str((data or {}).get("notes") or "")
            url = str((data or {}).get("release_url") or (data or {}).get("url") or "")
            if remote and vtuple(remote) > vtuple(APP_VERSION):
                msg = "Version %s is available (you have %s)." % (remote, APP_VERSION)
                if notes:
                    msg += "\n\n" + notes
                if url and QMessageBox.question(self, APP, msg + "\n\nOpen the release page?") == QMessageBox.Yes:
                    QDesktopServices.openUrl(QUrl(url))
                elif not url:
                    QMessageBox.information(self, APP, msg)
            else:
                QMessageBox.information(self, APP, "You have the latest version (%s)." % APP_VERSION)

        def fail(err):
            QMessageBox.warning(self, APP, "Could not check for updates.\n%s" % err)

        self._jobs.start(work, ok, fail)

    def closeEvent(self, e):
        self._close_session()
        e.accept()

    def _load_demo(self):
        """Offline preview used only for --shots. Not used in normal runs."""
        from datetime import datetime, timedelta, timezone
        acc = Account(
            id="demo",
            display_name="Alex Rivera",
            email="alex@example.com",
            username="alex@example.com",
            imap_host="imap.example.com",
            smtp_host="smtp.example.com",
            password="",
        )
        self.store.accounts = [acc]
        self.store.last_account_id = acc.id
        self._reload_accounts_combo(select=acc.id)
        self._show_empty(False)
        self.folders = [
            Folder(name="INBOX", unseen=2, total=5, flags=("\\Inbox",)),
            Folder(name="Sent", flags=("\\Sent",)),
            Folder(name="Drafts", flags=("\\Drafts",)),
            Folder(name="Archive"),
            Folder(name="Trash", flags=("\\Trash",)),
        ]
        self._fill_folders()
        self._select_folder_item("INBOX")
        now = datetime.now().astimezone()
        def H(uid, name, addr, subject, minutes, unseen=False):
            dt = now - timedelta(minutes=minutes)
            return MessageHeader(
                uid=uid, folder="INBOX", from_name=name, from_addr=addr,
                to_addrs=[("Alex Rivera", "alex@example.com")], cc_addrs=[],
                subject=subject, date=dt, date_text="", unseen=unseen,
            )
        # fill date_text via format
        from mixe_mail import format_when
        self.headers = [
            H("1", "Sam Ortega", "sam@example.com", "Project update for Friday", 25, True),
            H("2", "Jordan Lee", "jordan@example.com", "Invoice and notes attached", 90, True),
            H("3", "Riley Chen", "riley@example.com", "Re: lunch next week", 60 * 26, False),
            H("4", "Morgan Patel", "morgan@example.com", "Welcome to the team", 60 * 80, False),
        ]
        for h in self.headers:
            h.date_text = format_when(h.date)
        self._fill_table()
        msg = Message(
            uid="1", folder="INBOX", from_name="Sam Ortega", from_addr="sam@example.com",
            to_addrs=[("Alex Rivera", "alex@example.com")], cc_addrs=[],
            subject="Project update for Friday", date=self.headers[0].date,
            date_text=self.headers[0].date_text, unseen=True,
            body_text=(
                "Hi Alex,\n\n"
                "Here is the Friday update:\n\n"
                "• The draft is on track\n"
                "• I will send the revised figures tomorrow morning\n"
                "• Let me know if you want a shorter summary\n\n"
                "Thanks,\nSam\n"
            ),
            attachments=[],
        )
        self.current_message = msg
        self.table.selectRow(0)
        self._show_message(msg)
        self.status.showMessage("INBOX — 4 messages  ·  2 unread")


def format_addr_pair(name, addr):
    from email.utils import formataddr
    if name and addr:
        return formataddr((name, addr))
    return addr or name or ""


def _size_label(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return ""
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%.1f MB" % (n / (1024.0 * 1024.0))


def _patch_compose_send(dlg: ComposeDialog):
    """Make ComposeDialog include In-Reply-To / References when present."""
    in_reply_to = getattr(dlg, "_in_reply_to", "")
    references = getattr(dlg, "_references", "")
    orig = dlg._send

    def _send():
        # Reimplement send with extra headers by wrapping the work function.
        to_addrs = dlg._split_addrs(dlg.ed_to.text())
        cc_addrs = dlg._split_addrs(dlg.ed_cc.text())
        bcc_addrs = dlg._split_addrs(dlg.ed_bcc.text())
        if not to_addrs and not cc_addrs and not bcc_addrs:
            dlg.lab_status.setText("Add at least one recipient.")
            return
        dlg.btn_send.setEnabled(False)
        dlg.lab_status.setText("Sending…")
        subject = dlg.ed_subject.text()
        body = dlg.body.toPlainText()
        atts = list(dlg.attachments)
        acc = dlg.account

        def work():
            send_mail(acc, to_addrs, subject, body, cc_addrs, bcc_addrs, atts,
                      in_reply_to=in_reply_to, references=references)
            return True

        def ok(_):
            dlg.accept()
            if dlg._on_send:
                dlg._on_send("Message sent.")

        def fail(msg):
            dlg.btn_send.setEnabled(True)
            dlg.lab_status.setText(msg)

        if not hasattr(dlg, "_jobs"):
            dlg._jobs = JobHost(dlg)
        dlg._jobs.start(work, ok, fail)

    dlg._send = _send


def take_shots(app, window: Main, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)

    def save(widget, name):
        path = os.path.join(out_dir, name)
        pix = widget.grab()
        pix.save(path, "PNG")
        return path

    window.show()
    window.raise_()
    app.processEvents()
    QTimer.singleShot(0, lambda: None)
    app.processEvents()
    save(window, "screenshot_home.png")

    acc_dlg = AccountDialog(window)
    acc_dlg.ed_name.setText("Alex Rivera")
    acc_dlg.ed_email.setText("alex@example.com")
    acc_dlg.ed_user.setText("alex@example.com")
    acc_dlg.ed_imap.setText("imap.example.com")
    acc_dlg.ed_smtp.setText("smtp.example.com")
    acc_dlg.show()
    app.processEvents()
    save(acc_dlg, "screenshot_account.png")
    acc_dlg.close()

    acc = window.current_account()
    if acc:
        comp = ComposeDialog(
            window, acc, None,
            to_text="sam@example.com",
            subject="Re: Project update for Friday",
            body="Thanks Sam — I'll look at the figures tomorrow.\n",
            title="Compose",
        )
        comp.show()
        app.processEvents()
        save(comp, "screenshot_compose.png")
        comp.close()

    accounts = AccountsDialog(window, window.store, None)
    accounts.show()
    app.processEvents()
    save(accounts, "screenshot_accounts.png")
    accounts.close()


def main():
    shots = "--shots" in sys.argv
    QApplication.setApplicationName(APP)
    QApplication.setOrganizationName("EX Inc.")
    QApplication.setApplicationVersion(APP_VERSION)
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(res_path("assets", "logo.ico")))
    app.setStyleSheet(QSS)
    win = Main(demo=shots)
    if shots:
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
        # Delay so the first paint happens.
        def go():
            take_shots(app, win, out)
            app.quit()
        QTimer.singleShot(400, go)
        win.show()
        return app.exec()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main() or 0)
