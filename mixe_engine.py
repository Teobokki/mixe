"""MIXE guest engine — QEMU + Android-x86 + adb.
©2026 EX Inc./HYPERION DIGITAL ©2026

Approach: launch a bundled QEMU (qemu-system-x86_64) with an Android-x86 ISO
downloaded on first run. APK sideload goes through adb over user-mode networking
(hostfwd tcp 5555). No Google Play Services are bundled.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Callable, Optional

from mixe_style import engine_root

# Android-x86 9.0-r2 (64-bit ISO) — open-source, no Play Services
ISO_NAME = "android-x86_64-9.0-r2.iso"
ISO_URLS = [
    # SourceForge redirect endpoint (HTTPS)
    "https://sourceforge.net/projects/android-x86/files/Release%209.0/android-x86_64-9.0-r2.iso/download",
    "https://downloads.sourceforge.net/project/android-x86/Release%209.0/android-x86_64-9.0-r2.iso",
]
ISO_SHA1 = "1cc85b5ed7c830ff71aecf8405c7281a9c995aa0"
ISO_SIZE_HINT = 965_700_000  # ~966 MB

DISK_NAME = "mixe_data.qcow2"
DISK_SIZE = "16G"
SHARED_NAME = "Shared"
CONFIG_NAME = "engine.json"
ADB_PORT = 5555

ProgressCb = Callable[[str, float], None]  # message, 0..1 or -1 indeterminate


def is_wine() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        return hasattr(ctypes.windll.ntdll, "wine_get_version")
    except Exception:
        return False


def data_dir(app_name: str = "MIXE") -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, app_name)
    os.makedirs(d, exist_ok=True)
    return d


def shared_dir() -> str:
    docs = os.path.join(os.path.expanduser("~"), "Documents", "MIXE", SHARED_NAME)
    os.makedirs(docs, exist_ok=True)
    return docs


class EngineConfig:
    def __init__(self, path: str):
        self.path = path
        self.data = {
            "ram_mb": 4096,
            "cpus": 4,
            "disk_installed": False,
            "iso_ready": False,
            "iso_sha1": "",
            "accel": "auto",
            "adb_port": ADB_PORT,
        }
        self.load()

    def load(self):
        if os.path.isfile(self.path):
            try:
                self.data.update(json.load(open(self.path, encoding="utf-8")))
            except Exception:
                pass

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        json.dump(self.data, open(self.path, "w", encoding="utf-8"), indent=2)


class VirtStatus:
    def __init__(self, ok: bool, accel: str, detail: str, wine: bool = False):
        self.ok = ok
        self.accel = accel  # whpx | tcg | none
        self.detail = detail
        self.wine = wine


def detect_virtualization(qemu_exe: str) -> VirtStatus:
    """Detect usable acceleration. Under Wine we always report missing HW virt."""
    wine = is_wine()
    if wine:
        return VirtStatus(
            False, "none",
            "Running under Wine/compatibility layer — hardware virtualization "
            "(VT-x / AMD-V / WHPX) is not available here. On a real Windows PC "
            "enable Virtualization in BIOS/UEFI and turn on Windows Hypervisor Platform.",
            wine=True,
        )
    # Probe qemu -accel help
    try:
        out = subprocess.check_output(
            [qemu_exe, "-accel", "help"],
            stderr=subprocess.STDOUT, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except Exception as e:
        out = str(e)
    low = out.lower()
    if "whpx" in low:
        # WHPX listed — try a tiny dry probe with -machine none if possible; else trust listing
        return VirtStatus(True, "whpx", "Windows Hypervisor Platform (WHPX) available.", wine=False)
    if "hax" in low:
        return VirtStatus(True, "hax", "Intel HAXM available.", wine=False)
    # TCG always exists but is too slow for a usable guest — treat as not OK for "real" run
    return VirtStatus(
        False, "tcg",
        "No hardware virtualization accelerator found. Enable VT-x/AMD-V in BIOS/UEFI, "
        "then enable 'Windows Hypervisor Platform' under Windows Features, and restart. "
        "TCG software emulation is available as a last resort but is very slow.",
        wine=False,
    )


class MixeEngine:
    def __init__(self, app_name: str = "MIXE"):
        self.app_name = app_name
        self.root = data_dir(app_name)
        self.cfg = EngineConfig(os.path.join(self.root, CONFIG_NAME))
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    # ---- paths ----
    def qemu_dir(self) -> str:
        return os.path.join(engine_root(), "qemu")

    def qemu_exe(self) -> str:
        d = self.qemu_dir()
        for name in ("qemu-system-x86_64w.exe", "qemu-system-x86_64.exe"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
        return os.path.join(d, "qemu-system-x86_64w.exe")

    def qemu_img(self) -> str:
        return os.path.join(self.qemu_dir(), "qemu-img.exe")

    def adb_exe(self) -> str:
        return os.path.join(engine_root(), "platform-tools", "adb.exe")

    def iso_path(self) -> str:
        return os.path.join(self.root, ISO_NAME)

    def disk_path(self) -> str:
        return os.path.join(self.root, DISK_NAME)

    def engine_bundled(self) -> bool:
        return os.path.isfile(self.qemu_exe()) and os.path.isfile(self.qemu_img()) and os.path.isfile(self.adb_exe())

    # ---- ISO download ----
    def iso_ready(self) -> bool:
        p = self.iso_path()
        if not os.path.isfile(p):
            return False
        if self.cfg.data.get("iso_sha1") == ISO_SHA1 and self.cfg.data.get("iso_ready"):
            return True
        # verify
        if self._sha1_file(p) == ISO_SHA1:
            self.cfg.data["iso_sha1"] = ISO_SHA1
            self.cfg.data["iso_ready"] = True
            self.cfg.save()
            return True
        return False

    def _sha1_file(self, path: str, cb: Optional[ProgressCb] = None) -> str:
        h = hashlib.sha1()
        total = os.path.getsize(path) or 1
        n = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                n += len(chunk)
                if cb:
                    cb("Verifying image…", n / total)
        return h.hexdigest()

    def download_iso(self, cb: Optional[ProgressCb] = None, cancel: Optional[threading.Event] = None) -> None:
        dest = self.iso_path()
        part = dest + ".part"
        last_err = None
        for url in ISO_URLS:
            try:
                if cb:
                    cb("Downloading Android-x86 image…", 0.0)
                req = urllib.request.Request(url, headers={"User-Agent": "MIXE/1.0 (EX-Inc)"})
                with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
                    total = int(r.headers.get("Content-Length") or ISO_SIZE_HINT)
                    n = 0
                    while True:
                        if cancel and cancel.is_set():
                            raise RuntimeError("Download cancelled")
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        n += len(chunk)
                        if cb:
                            cb("Downloading Android-x86 image… %.0f MB" % (n / 1e6), min(0.99, n / max(total, 1)))
                if cb:
                    cb("Verifying SHA-1…", 0.99)
                digest = self._sha1_file(part, cb)
                if digest.lower() != ISO_SHA1.lower():
                    raise RuntimeError("SHA-1 mismatch: got %s expected %s" % (digest, ISO_SHA1))
                os.replace(part, dest)
                self.cfg.data["iso_sha1"] = ISO_SHA1
                self.cfg.data["iso_ready"] = True
                self.cfg.save()
                if cb:
                    cb("Image ready", 1.0)
                return
            except Exception as e:
                last_err = e
                try:
                    if os.path.isfile(part):
                        os.remove(part)
                except Exception:
                    pass
                continue
        raise RuntimeError("Failed to download system image: %s" % last_err)

    # ---- disk ----
    def ensure_disk(self, cb: Optional[ProgressCb] = None) -> None:
        if os.path.isfile(self.disk_path()):
            return
        if cb:
            cb("Creating virtual disk…", 0.1)
        img = self.qemu_img()
        cmd = [img, "create", "-f", "qcow2", self.disk_path(), DISK_SIZE]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        subprocess.check_call(cmd, creationflags=flags)
        if cb:
            cb("Virtual disk ready", 1.0)

    # ---- launch ----
    def build_qemu_cmd(self, virt: VirtStatus, live: bool = True) -> list:
        exe = self.qemu_exe()
        share = os.path.join(self.qemu_dir(), "share")
        ram = int(self.cfg.data.get("ram_mb") or 4096)
        cpus = int(self.cfg.data.get("cpus") or 4)
        port = int(self.cfg.data.get("adb_port") or ADB_PORT)
        cmd = [
            exe,
            "-L", share,
            "-name", "MIXE Guest",
            "-m", str(ram),
            "-smp", str(cpus),
            "-machine", "q35",
            "-cpu", "qemu64",
            "-drive", "file=%s,if=virtio,format=qcow2" % self.disk_path(),
            "-netdev", "user,id=n0,hostfwd=tcp::%d-:5555" % port,
            "-device", "e1000,netdev=n0",
            "-usb",
            "-device", "usb-tablet",
            "-display", "sdl,gl=off",
            "-monitor", "none",
            "-serial", "null",
        ]
        # acceleration
        if virt.accel == "whpx":
            cmd += ["-accel", "whpx,kernel-irqchip=off"]
        elif virt.accel == "hax":
            cmd += ["-accel", "hax"]
        else:
            cmd += ["-accel", "tcg,thread=multi"]

        iso = self.iso_path()
        if live or not self.cfg.data.get("disk_installed"):
            if os.path.isfile(iso):
                cmd += ["-cdrom", iso, "-boot", "order=dc"]
        else:
            cmd += ["-boot", "order=c"]

        # shared folder via 9p (Android-x86 may need manual mount; also used as host path hint)
        # Shared folder: Documents/MIXE/Shared on the host; sync via adb (9p virtfs is unreliable on Windows QEMU).
        return cmd

    def start(self, virt: VirtStatus, cb: Optional[ProgressCb] = None) -> subprocess.Popen:
        with self._lock:
            if self.proc and self.proc.poll() is None:
                return self.proc
            if not self.engine_bundled():
                raise RuntimeError("MIXE engine binaries are missing (QEMU / adb). Reinstall MIXE.")
            if not self.iso_ready():
                raise RuntimeError("System image not ready. Download it first.")
            self.ensure_disk(cb)
            cmd = self.build_qemu_cmd(virt)
            if cb:
                cb("Starting guest…", 0.5)
            # SDL window — separate process
            flags = 0
            if os.name == "nt":
                flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            env = os.environ.copy()
            # Ensure QEMU finds its DLLs
            qdir = self.qemu_dir()
            env["PATH"] = qdir + os.pathsep + env.get("PATH", "")
            self.proc = subprocess.Popen(cmd, cwd=qdir, env=env, creationflags=flags)
            if cb:
                cb("Guest process started (PID %s)" % self.proc.pid, 1.0)
            return self.proc

    def stop(self):
        with self._lock:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=5)
                    except Exception:
                        self.proc.kill()
                except Exception:
                    pass
            self.proc = None

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    # ---- adb ----
    def _adb(self, *args, timeout: int = 60) -> subprocess.CompletedProcess:
        exe = self.adb_exe()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        return subprocess.run(
            [exe, *args],
            capture_output=True, text=True, timeout=timeout, creationflags=flags,
        )

    def adb_connect(self) -> str:
        port = int(self.cfg.data.get("adb_port") or ADB_PORT)
        # start server
        self._adb("start-server")
        r = self._adb("connect", "127.0.0.1:%d" % port)
        return (r.stdout or "") + (r.stderr or "")

    def adb_devices(self) -> str:
        r = self._adb("devices")
        return r.stdout or ""

    def install_apk(self, apk_path: str, cb: Optional[ProgressCb] = None) -> str:
        if not os.path.isfile(apk_path):
            raise FileNotFoundError(apk_path)
        if not apk_path.lower().endswith(".apk"):
            raise ValueError("File must be a .apk")
        if cb:
            cb("Connecting adb…", 0.1)
        self.adb_connect()
        # wait briefly for device
        for i in range(10):
            devs = self.adb_devices()
            if "127.0.0.1:%d" % int(self.cfg.data.get("adb_port") or ADB_PORT) in devs and "offline" not in devs.split("127.0.0.1")[-1][:40]:
                break
            time.sleep(1)
        if cb:
            cb("Installing %s…" % os.path.basename(apk_path), 0.4)
        # push to sdcard then pm install (more reliable than adb install on some builds)
        remote = "/data/local/tmp/mixe_install.apk"
        r1 = self._adb("push", apk_path, remote, timeout=300)
        if r1.returncode != 0:
            # fallback to adb install
            r = self._adb("install", "-r", apk_path, timeout=300)
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0:
                raise RuntimeError("adb install failed:\n" + out)
            if cb:
                cb("Installed", 1.0)
            return out
        r2 = self._adb("shell", "pm", "install", "-r", remote, timeout=300)
        self._adb("shell", "rm", remote)
        out = (r2.stdout or "") + (r2.stderr or "")
        if r2.returncode != 0 and "Success" not in out:
            raise RuntimeError("pm install failed:\n" + out)
        if cb:
            cb("Installed", 1.0)
        return out

    def adb_shell(self, *shell_args: str) -> str:
        r = self._adb("shell", *shell_args)
        return (r.stdout or "") + (r.stderr or "")

    def keyevent(self, code: int):
        """Send Android keyevent (BACK=4 HOME=3 APP_SWITCH=187)."""
        try:
            self.adb_connect()
            self.adb_shell("input", "keyevent", str(code))
        except Exception:
            pass

    def set_volume(self, up: bool = True):
        self.keyevent(24 if up else 25)

    def shake(self):
        # UI affordance: send a broadcast some titles may listen for; also nudge via input
        try:
            self.adb_connect()
            self.adb_shell("am", "broadcast", "-a", "com.mixe.SHAKE")
            self.adb_shell("input", "keyevent", "82")  # MENU as mild poke
        except Exception:
            pass

    def list_packages(self) -> list:
        try:
            self.adb_connect()
            out = self.adb_shell("pm", "list", "packages", "-3")
            pkgs = []
            for line in out.splitlines():
                m = re.match(r"package:(.+)", line.strip())
                if m:
                    pkgs.append(m.group(1))
            return pkgs
        except Exception:
            return []

    def sync_shared_to_guest(self, cb=None) -> str:
        """Push host Shared folder into /sdcard/MIXE on the guest via adb."""
        shared = shared_dir()
        self.adb_connect()
        self.adb_shell("mkdir", "-p", "/sdcard/MIXE")
        logs = []
        for name in sorted(os.listdir(shared)):
            src = os.path.join(shared, name)
            if not os.path.isfile(src):
                continue
            if cb:
                cb("Pushing %s…" % name, 0.5)
            r = self._adb("push", src, "/sdcard/MIXE/" + name, timeout=300)
            logs.append((r.stdout or "") + (r.stderr or ""))
        return "\n".join(logs) or "(nothing to push)"

    def launch_cmdline_preview(self, virt: VirtStatus) -> str:
        try:
            return " ".join(self.build_qemu_cmd(virt))
        except Exception as e:
            return "(unavailable: %s)" % e
