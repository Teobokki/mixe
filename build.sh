#!/bin/sh
# ONE Windows build: PyInstaller onedir -> Inno Setup installer, plus a standalone one-file portable .exe (no zip)
set -e
export PATH=/workspace/wine-portable/current/bin:$PATH WINEPREFIX=/workspace/exwifi/.wine WINEDEBUG=-all
cd /workspace/mixe
V=1.0.0
rm -rf build dist build1f
wine 'C:\Python311\python.exe' -m PyInstaller --noconfirm MIXE.spec > pyi.log 2>&1; echo PYI_DONE
# engine lives in _internal/engine (datas); engine_root() finds it there. Do NOT duplicate.
wine 'C:\InnoSetup\ISCC.exe' installer.iss > iss.log 2>&1; echo ISS_DONE
MIXE_ONEFILE=1 wine 'C:\Python311\python.exe' -m PyInstaller --noconfirm --workpath build1f MIXE.spec > pyi1f.log 2>&1; echo PYI1F_DONE
cd dist && mv -f "MIXE Portable.exe" "MIXE-Portable-$V.exe"
ls -la "MIXE-Setup-$V.exe" "MIXE-Portable-$V.exe"
sha256sum "MIXE-Setup-$V.exe" "MIXE-Portable-$V.exe"
