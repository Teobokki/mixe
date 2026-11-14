# -*- mode: python ; coding: utf-8 -*-
import os
ONEFILE = bool(os.environ.get("MIXE_ONEFILE"))
excl = ['matplotlib', 'scipy', 'pandas', 'IPython', 'pytest', 'torch', 'cv2', 'tkinter',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtBluetooth',
        'PySide6.QtSensors', 'PySide6.QtSerialPort', 'PySide6.QtDesigner', 'PySide6.QtHelp',
        'PySide6.QtSpatialAudio', 'PySide6.QtGraphs', 'PySide6.QtQuick3D', 'PySide6.QtRemoteObjects',
        'PySide6.QtScxml', 'PySide6.QtStateMachine', 'PySide6.QtTextToSpeech', 'PySide6.QtVirtualKeyboard',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
        'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtQuickWidgets', 'PySide6.QtWebChannel',
        'PySide6.QtPositioning', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtNfc',
        'PySide6.QtHttpServer', 'PySide6.QtLocation', 'PySide6.QtAxContainer', 'PySide6.QtMultimedia']
a = Analysis(
    ['mixe.py'],
    datas=[('assets', 'assets')],
    binaries=[],
    hiddenimports=[],
    excludes=excl,
    noarchive=False,
)
def _keep(entry):
    dst = entry[0].replace('/', '\\').lower()
    if 'pyside6\\qml\\' in dst or 'pyside6\\resources\\' in dst:
        return False
    base = dst.rsplit('\\', 1)[-1]
    if base.startswith(('qt6webengine', 'qtwebengine', 'qt6quick', 'qt6qml', 'qt6pdf', 'qt6webchannel', 'qt6positioning', 'opengl32sw')):
        return False
    if 'pyside6\\translations\\' in dst and not dst.endswith('en-us.pak'):
        return False
    return True
a.datas = [e for e in a.datas if _keep(e)]
a.binaries = [e for e in a.binaries if _keep(e)]
pyz = PYZ(a.pure)
if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='MIXE Portable', console=False, upx=False,
              version='version.txt', icon=['assets/logo.ico'])
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MIXE', console=False, upx=False,
              version='version.txt', icon=['assets/logo.ico'])
    coll = COLLECT(exe, a.binaries, a.datas, upx=False, name='MIXE')
