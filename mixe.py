"""MIXE — Android-style app runner for Windows (QEMU + Android-x86).
©2026 EX Inc./HYPERION DIGITAL ©2026
"""
import json, os, sys, threading, time, re, traceback

APP = "MIXE"
APP_VERSION = "1.0.0"
COPYRIGHT = "\u00a92026 EX Inc./HYPERION DIGITAL \u00a92026"
REPO = "Teobokki/mixe"
UPDATE_URL = "https://raw.githubusercontent.com/%s/main/latest.json" % REPO
VIRT_HELP_URL = "https://support.microsoft.com/windows/enable-virtualization-on-windows-c5578302-6e43-4b4b-a449-8fcf4d3f3f6e"

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QSize, QUrl, QMimeData
from PySide6.QtGui import QIcon, QPixmap, QDesktopServices, QPainter, QDragEnterEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QStackedWidget, QMessageBox, QProgressBar, QFileDialog, QListWidget, QListWidgetItem,
    QSpinBox, QFormLayout, QFrame, QStatusBar, QSizePolicy, QScrollArea, QGridLayout,
)

from mixe_style import QSS, res_path, ACC, MUT
from mixe_engine import MixeEngine, detect_virtualization, VirtStatus, shared_dir, ISO_NAME, ISO_SHA1


def is_wine():
    if os.name != "nt":
        return False
    try:
        import ctypes
        return hasattr(ctypes.windll.ntdll, "wine_get_version")
    except Exception:
        return False


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


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
    progress = Signal(str, float)
    done = Signal(object)
    fail = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            def cb(msg, frac):
                self.progress.emit(msg, frac)
            result = self.fn(cb)
            self.done.emit(result)
        except Exception as e:
            self.fail.emit(str(e) or traceback.format_exc())


class DropInstall(QFrame):
    """Drag-and-drop / click target for APK files."""
    apkDropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        lay = QVBoxLayout(self)
        self.lab = QLabel("Drop an .apk here\nor click to browse")
        self.lab.setAlignment(Qt.AlignCenter)
        self.lab.setObjectName("body")
        lay.addWidget(self.lab)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            path, _ = QFileDialog.getOpenFileName(self, "Install APK", "", "Android packages (*.apk)")
            if path:
                self.apkDropped.emit(path)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.toLocalFile().lower().endswith(".apk"):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dropEvent(self, e: QDropEvent):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(".apk"):
                self.apkDropped.emit(p)
                break


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.setWindowIcon(QIcon(res_path("assets", "logo.ico")))
        self.resize(1280, 800)
        self.engine = MixeEngine(APP)
        self.virt: VirtStatus = detect_virtualization(self.engine.qemu_exe()) if self.engine.engine_bundled() else VirtStatus(
            False, "none", "Engine binaries not found.", wine=is_wine()
        )
        self._busy = False

        root = QWidget(); root.setObjectName("root"); self.setCentralWidget(root)
        v = QVBoxLayout(root); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)

        # top bar
        top = QWidget(); top.setObjectName("topbar")
        th = QHBoxLayout(top); th.setContentsMargins(12, 8, 12, 8); th.setSpacing(10)
        self.emblem = Emblem(40); self.emblem.clicked.connect(self.about); th.addWidget(self.emblem)
        t = QLabel(APP); t.setObjectName("apptitle"); th.addWidget(t)
        vl = QLabel("v" + APP_VERSION); vl.setObjectName("muted"); th.addWidget(vl)
        th.addStretch(1)
        self.b_upd = QPushButton("Check for updates"); self.b_upd.setObjectName("flat"); self.b_upd.clicked.connect(self.check_updates)
        th.addWidget(self.b_upd)
        b_ab = QPushButton("About"); b_ab.setObjectName("flat"); b_ab.clicked.connect(self.about); th.addWidget(b_ab)
        v.addWidget(top)
        line = QWidget(); line.setFixedHeight(1); line.setObjectName("hline"); v.addWidget(line)

        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0); v.addLayout(body, 1)

        # sidebar
        side = QWidget(); side.setObjectName("sidebar"); side.setFixedWidth(88)
        sv = QVBoxLayout(side); sv.setContentsMargins(8, 12, 8, 12); sv.setSpacing(6)
        self.nav = {}
        for key, label in (
            ("home", "Home"),
            ("apps", "My Apps"),
            ("install", "Install"),
            ("keys", "Keys"),
            ("settings", "Settings"),
        ):
            b = QPushButton(label); b.setObjectName("nav"); b.setCheckable(True)
            b.setFixedHeight(56)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            sv.addWidget(b); self.nav[key] = b
        sv.addSpacing(12)
        # guest controls
        for key, label, slot in (
            ("back", "Back", lambda: self.engine.keyevent(4)),
            ("ghome", "Guest\nHome", lambda: self.engine.keyevent(3)),
            ("recents", "Recents", lambda: self.engine.keyevent(187)),
            ("rotate", "Rotate", self.rotate_guest),
            ("volup", "Vol +", lambda: self.engine.set_volume(True)),
            ("voldn", "Vol −", lambda: self.engine.set_volume(False)),
            ("shake", "Shake", self.engine.shake),
        ):
            b = QPushButton(label); b.setObjectName("nav"); b.setFixedHeight(48)
            b.clicked.connect(slot); sv.addWidget(b)
        sv.addStretch(1)
        body.addWidget(side)

        self.stack = QStackedWidget(); body.addWidget(self.stack, 1)
        self.pages = {}
        self.pages["home"] = self._page_home()
        self.pages["apps"] = self._page_apps()
        self.pages["install"] = self._page_install()
        self.pages["keys"] = self._page_keys()
        self.pages["settings"] = self._page_settings()
        for p in self.pages.values():
            self.stack.addWidget(p)

        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.prog = QProgressBar(); self.prog.setFixedWidth(220); self.prog.setVisible(False)
        self.status.addPermanentWidget(self.prog)
        self.status.showMessage(COPYRIGHT + "  ·  Engine: QEMU + Android-x86")

        self.show_page("home")
        QTimer.singleShot(400, self.refresh_status)

    # ---------- pages ----------
    def _wrap(self, title, subtitle=None):
        w = QWidget()
        lay = QVBoxLayout(w); lay.setContentsMargins(28, 22, 28, 22); lay.setSpacing(12)
        h = QLabel(title); h.setObjectName("h1"); lay.addWidget(h)
        if subtitle:
            s = QLabel(subtitle); s.setObjectName("body"); s.setWordWrap(True); lay.addWidget(s)
        return w, lay

    def _page_home(self):
        w, lay = self._wrap("Home", "Start the guest system, then sideload apps from APK files. No app store is bundled.")
        self.virt_banner = QLabel(); self.virt_banner.setObjectName("warn"); self.virt_banner.setWordWrap(True); self.virt_banner.setVisible(False)
        lay.addWidget(self.virt_banner)

        row = QHBoxLayout(); lay.addLayout(row)
        card = QFrame(); card.setObjectName("card")
        cv = QVBoxLayout(card); cv.setContentsMargins(22, 22, 22, 22)
        self.home_status = QLabel("Checking engine…"); self.home_status.setObjectName("h2"); cv.addWidget(self.home_status)
        self.home_detail = QLabel(""); self.home_detail.setObjectName("body"); self.home_detail.setWordWrap(True); cv.addWidget(self.home_detail)
        btnrow = QHBoxLayout(); cv.addLayout(btnrow)
        self.b_start = QPushButton("▶  Start guest"); self.b_start.setObjectName("primary"); self.b_start.clicked.connect(self.start_guest)
        self.b_stop = QPushButton("Stop"); self.b_stop.setObjectName("danger"); self.b_stop.clicked.connect(self.stop_guest)
        self.b_dl = QPushButton("Download system image"); self.b_dl.setObjectName("secondary"); self.b_dl.clicked.connect(self.download_image)
        btnrow.addWidget(self.b_start); btnrow.addWidget(self.b_stop); btnrow.addWidget(self.b_dl); btnrow.addStretch(1)
        self.b_virt_help = QPushButton("How to enable virtualization"); self.b_virt_help.setObjectName("flat"); self.b_virt_help.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(VIRT_HELP_URL)))
        cv.addWidget(self.b_virt_help)
        row.addWidget(card, 2)

        side = QFrame(); side.setObjectName("card")
        sv = QVBoxLayout(side); sv.setContentsMargins(18, 18, 18, 18)
        sv.addWidget(QLabel("Quick tips", objectName="h2"))
        tips = QLabel(
            "• First run downloads the Android-x86 ISO (~966 MB) over HTTPS and checks SHA-1.\n"
            "• The guest opens in its own window (QEMU/SDL).\n"
            "• Use Install to sideload any .apk via adb.\n"
            "• Shared folder: Documents/MIXE/Shared\n"
            "• No Google Play Services are included."
        )
        tips.setObjectName("body"); tips.setWordWrap(True); sv.addWidget(tips); sv.addStretch(1)
        row.addWidget(side, 1)
        lay.addStretch(1)
        return w

    def _page_apps(self):
        w, lay = self._wrap("My Apps", "Third-party packages visible to adb once the guest is running.")
        row = QHBoxLayout(); lay.addLayout(row)
        self.b_refresh_apps = QPushButton("Refresh"); self.b_refresh_apps.setObjectName("secondary"); self.b_refresh_apps.clicked.connect(self.refresh_apps)
        row.addWidget(self.b_refresh_apps); row.addStretch(1)
        self.app_list = QListWidget(); lay.addWidget(self.app_list, 1)
        return w

    def _page_install(self):
        w, lay = self._wrap("Install APK", "Sideload a package into the running guest. Requires the guest to be up and adb reachable on port 5555.")
        self.drop = DropInstall(); self.drop.apkDropped.connect(self.install_apk); lay.addWidget(self.drop)
        self.install_log = QLabel(""); self.install_log.setObjectName("body"); self.install_log.setWordWrap(True); lay.addWidget(self.install_log)
        lay.addStretch(1)
        return w

    def _page_keys(self):
        w, lay = self._wrap("Keyboard mapping", "Basic game-oriented shortcuts sent as Android keyevents while the guest is connected.")
        grid = QGridLayout(); lay.addLayout(grid)
        mappings = [
            ("Esc", "BACK", 4), ("Home", "HOME", 3), ("Tab", "APP SWITCH", 187),
            ("F1", "MENU", 82), ("Enter", "ENTER", 66), ("Space", "SPACE", 62),
            ("↑", "DPAD UP", 19), ("↓", "DPAD DOWN", 20), ("←", "DPAD LEFT", 21), ("→", "DPAD RIGHT", 22),
            ("Z", "A / BUTTON A", 96), ("X", "B / BUTTON B", 97),
        ]
        for i, (k, name, code) in enumerate(mappings):
            b = QPushButton("%s  →  %s" % (k, name)); b.setObjectName("secondary")
            b.clicked.connect(lambda _=False, c=code: self.engine.keyevent(c))
            grid.addWidget(b, i // 3, i % 3)
        note = QLabel("Tip: click the guest window to type normally; use these buttons for controller-like keys.")
        note.setObjectName("body"); lay.addWidget(note); lay.addStretch(1)
        return w

    def _page_settings(self):
        w, lay = self._wrap("Settings")
        form = QFormLayout(); lay.addLayout(form)
        self.sp_ram = QSpinBox(); self.sp_ram.setRange(2048, 16384); self.sp_ram.setSingleStep(512)
        self.sp_ram.setValue(int(self.engine.cfg.data.get("ram_mb") or 4096))
        self.sp_cpu = QSpinBox(); self.sp_cpu.setRange(1, 16); self.sp_cpu.setValue(int(self.engine.cfg.data.get("cpus") or 4))
        form.addRow("Guest RAM (MB)", self.sp_ram)
        form.addRow("CPU cores", self.sp_cpu)
        self.lbl_accel = QLabel(""); self.lbl_accel.setObjectName("body"); form.addRow("Acceleration", self.lbl_accel)
        self.lbl_iso = QLabel(""); self.lbl_iso.setObjectName("body"); form.addRow("System image", self.lbl_iso)
        self.lbl_share = QLabel(shared_dir()); self.lbl_share.setObjectName("body"); self.lbl_share.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Shared folder", self.lbl_share)
        self.lbl_cmdline = QLabel(""); self.lbl_cmdline.setObjectName("muted"); self.lbl_cmdline.setWordWrap(True); self.lbl_cmdline.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Launch command", self.lbl_cmdline)
        bsave = QPushButton("Save settings"); bsave.setObjectName("secondary"); bsave.clicked.connect(self.save_settings)
        lay.addWidget(bsave, alignment=Qt.AlignLeft)
        mark = QLabel("Mark disk as installed (skip ISO on next boot)")
        mark.setObjectName("body"); lay.addWidget(mark)
        bmark = QPushButton("I've finished guest setup"); bmark.setObjectName("secondary"); bmark.clicked.connect(self.mark_installed)
        lay.addWidget(bmark, alignment=Qt.AlignLeft)
        lay.addStretch(1)
        return w

    # ---------- navigation ----------
    def show_page(self, key):
        for k, b in self.nav.items():
            b.setChecked(k == key)
        self.stack.setCurrentWidget(self.pages[key])
        if key == "apps":
            self.refresh_apps()
        if key == "settings":
            self.refresh_settings_labels()

    # ---------- status / virt ----------
    def refresh_status(self):
        bundled = self.engine.engine_bundled()
        if bundled:
            self.virt = detect_virtualization(self.engine.qemu_exe())
        iso = self.engine.iso_ready()
        running = self.engine.running()
        parts = []
        if not bundled:
            self.home_status.setText("Engine missing")
            self.home_detail.setText("QEMU / adb binaries were not found next to MIXE. Reinstall the app.")
            self.b_start.setEnabled(False)
        elif running:
            self.home_status.setText("Guest running")
            self.home_detail.setText("The QEMU window should be open. Use the sidebar for Back / Home / Recents, or Install to sideload an APK.")
            self.b_start.setEnabled(False)
        elif not iso:
            self.home_status.setText("System image needed")
            self.home_detail.setText(
                "MIXE will download %s (~966 MB) over HTTPS from the Android-x86 project and verify SHA-1 %s."
                % (ISO_NAME, ISO_SHA1)
            )
            self.b_start.setEnabled(False)
        elif not self.virt.ok:
            self.home_status.setText("Virtualization required")
            self.home_detail.setText(self.virt.detail)
            # Still allow start with TCG if user insists? Task says show clear message.
            # Offer start anyway but warn — under Wine it will fail / be useless.
            self.b_start.setEnabled(True)
            self.b_start.setText("▶  Start anyway (slow / may fail)")
        else:
            self.home_status.setText("Ready")
            self.home_detail.setText("Acceleration: %s. Click Start guest to boot Android-x86." % self.virt.accel.upper())
            self.b_start.setEnabled(True)
            self.b_start.setText("▶  Start guest")

        self.virt_banner.setVisible(not self.virt.ok)
        if not self.virt.ok:
            self.virt_banner.setText(
                "⚠ Hardware virtualization is not available.\n\n%s\n\n"
                "On Windows: enable VT-x/AMD-V in BIOS/UEFI, then enable "
                "\"Windows Hypervisor Platform\" in Windows Features, and restart.\n"
                "Help: %s" % (self.virt.detail, VIRT_HELP_URL)
            )
        self.b_dl.setEnabled(bundled and not iso and not self._busy)
        self.b_stop.setEnabled(running)
        self.refresh_settings_labels()
        self.status.showMessage(
            "%s  ·  accel=%s  ·  iso=%s  ·  guest=%s"
            % (COPYRIGHT, self.virt.accel, "ready" if iso else "missing", "on" if running else "off")
        )

    def refresh_settings_labels(self):
        self.lbl_accel.setText("%s — %s" % (self.virt.accel, self.virt.detail[:120]))
        self.lbl_iso.setText("%s (%s)" % (ISO_NAME, "ready" if self.engine.iso_ready() else "not downloaded"))
        self.lbl_share.setText(shared_dir())
        self.lbl_cmdline.setText(self.engine.launch_cmdline_preview(self.virt))

    def save_settings(self):
        self.engine.cfg.data["ram_mb"] = int(self.sp_ram.value())
        self.engine.cfg.data["cpus"] = int(self.sp_cpu.value())
        self.engine.cfg.save()
        self.status.showMessage("Settings saved", 3000)
        self.refresh_settings_labels()

    def mark_installed(self):
        self.engine.cfg.data["disk_installed"] = True
        self.engine.cfg.save()
        QMessageBox.information(self, APP, "Next launch will boot from the virtual disk first (ISO still kept as fallback).")
        self.refresh_settings_labels()

    # ---------- actions ----------
    def _run_bg(self, fn, on_done=None):
        if self._busy:
            return
        self._busy = True
        self.prog.setVisible(True); self.prog.setValue(0)
        worker = Worker(fn)

        def prog(msg, frac):
            self.status.showMessage(msg)
            if frac < 0:
                self.prog.setRange(0, 0)
            else:
                self.prog.setRange(0, 100)
                self.prog.setValue(int(max(0, min(1, frac)) * 100))

        def done(res):
            self._busy = False; self.prog.setVisible(False)
            if on_done:
                on_done(res)
            self.refresh_status()

        def fail(err):
            self._busy = False; self.prog.setVisible(False)
            QMessageBox.warning(self, APP, err)
            self.refresh_status()

        worker.progress.connect(prog)
        worker.done.connect(done)
        worker.fail.connect(fail)
        threading.Thread(target=worker.run, daemon=True).start()

    def download_image(self):
        def job(cb):
            self.engine.download_iso(cb)
            return True
        self._run_bg(job, lambda _: QMessageBox.information(self, APP, "System image downloaded and verified."))

    def start_guest(self):
        if not self.virt.ok:
            r = QMessageBox.warning(
                self, APP,
                "Hardware virtualization is not available.\n\n%s\n\n"
                "Start anyway using slow software emulation? On Wine/this build machine the guest will not boot usefully."
                % self.virt.detail,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                return
            # force tcg for the attempt
            virt = VirtStatus(False, "tcg", self.virt.detail, wine=self.virt.wine)
        else:
            virt = self.virt

        def job(cb):
            if not self.engine.iso_ready():
                self.engine.download_iso(cb)
            self.engine.ensure_disk(cb)
            self.engine.start(virt, cb)
            return True

        self._run_bg(job, lambda _: self.status.showMessage("Guest started — look for the QEMU window", 5000))

    def stop_guest(self):
        self.engine.stop()
        self.refresh_status()

    def install_apk(self, path):
        def job(cb):
            return self.engine.install_apk(path, cb)
        def done(out):
            self.install_log.setText(str(out)[:2000])
            QMessageBox.information(self, APP, "Install finished.\n\n%s" % str(out)[:500])
            self.refresh_apps()
        self._run_bg(job, done)

    def refresh_apps(self):
        self.app_list.clear()
        if not self.engine.running():
            self.app_list.addItem(QListWidgetItem("Guest is not running — start it to list packages."))
            return
        try:
            pkgs = self.engine.list_packages()
            if not pkgs:
                self.app_list.addItem(QListWidgetItem("No third-party packages (or adb not connected yet)."))
            for p in pkgs:
                self.app_list.addItem(QListWidgetItem(p))
        except Exception as e:
            self.app_list.addItem(QListWidgetItem("Error: %s" % e))

    def rotate_guest(self):
        # user rotation hint via settings secure — best effort
        try:
            self.engine.adb_connect()
            self.engine.adb_shell("settings", "put", "system", "user_rotation", "1")
            self.engine.adb_shell("content", "insert", "--uri", "content://settings/system", "--bind", "name:s:user_rotation", "--bind", "value:i:1")
        except Exception:
            pass

    def about(self):
        QMessageBox.about(
            self, "About " + APP,
            "<b>%s %s</b><br>%s<br><br>"
            "MIXE wraps an open-source QEMU engine and an Android-x86 system image "
            "so you can sideload and run APKs on Windows.<br><br>"
            "Engine: QEMU (GPL) · adb (Apache-2.0) · Android-x86 ISO (downloaded on first run).<br>"
            "No Google Play Services or proprietary store apps are included.<br><br>"
            "Repo: https://github.com/%s"
            % (APP, APP_VERSION, COPYRIGHT, REPO),
        )

    def check_updates(self):
        def job(cb):
            cb("Checking…", 0.2)
            import urllib.request
            with urllib.request.urlopen(UPDATE_URL, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        def done(info):
            remote = str(info.get("version") or "")
            if vtuple(remote) > vtuple(APP_VERSION):
                url = info.get("installer_url") or info.get("url") or ""
                r = QMessageBox.question(self, APP, "Update %s is available (you have %s).\nOpen download page?" % (remote, APP_VERSION))
                if r == QMessageBox.Yes and url:
                    QDesktopServices.openUrl(QUrl(url))
            else:
                QMessageBox.information(self, APP, "You're on the latest version (%s)." % APP_VERSION)
        self._run_bg(job, done)

    def closeEvent(self, e):
        # leave guest running unless user stopped it — but on app exit, stop for cleanliness
        try:
            self.engine.stop()
        except Exception:
            pass
        super().closeEvent(e)


def main():
    # High-DPI
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setOrganizationName("EX Inc.")
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    win = Main()
    win.show()
    # If virt missing, land on home with banner — already done
    return app.exec()


if __name__ == "__main__":
    sys.exit(main() or 0)
