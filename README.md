# MIXE

**MIXE** is a BlueStacks-style Windows shell by EX Inc. that runs Android apps using a real open-source stack:

- **QEMU** (bundled, GPL) — `qemu-system-x86_64`
- **Android-x86 9.0-r2** ISO — downloaded on first run over HTTPS and SHA-1 verified (not bundled; ~966 MB)
- **adb** (bundled platform-tools) — sideload any `.apk` you provide

No Google Play Services and no proprietary store apps are included.

©2026 EX Inc./HYPERION DIGITAL ©2026

## Requirements (real Windows PC)

- 64-bit Windows 10/11
- Hardware virtualization enabled in BIOS/UEFI (VT-x / AMD-V)
- **Windows Hypervisor Platform** enabled (WHPX)
- ~2 GB free for MIXE + ~1 GB for the system image download + guest disk space

## First run

1. Install MIXE (or run the portable exe).
2. Open MIXE → **Download system image** (Android-x86 ISO from SourceForge, SHA-1 `1cc85b5ed7c830ff71aecf8405c7281a9c995aa0`).
3. Click **Start guest**. The QEMU window boots Android-x86.
4. Use **Install** to sideload an `.apk` (drag-and-drop or browse). MIXE uses `adb connect 127.0.0.1:5555` then `adb push` + `pm install`.

## Shared folder

`Documents\MIXE\Shared` on Windows. Exposed to QEMU via virtfs mount tag `mixeshare` (manual mount inside the guest may be required depending on the build).

## Honesty note

Hardware virtualization does **not** work under Wine on the build machine. MIXE detects that and shows clear instructions. Android boot is verified on real Windows with WHPX; the build/test box verifies the shell UI, bundled engine binaries, launch command wiring, APK/adb wiring, and the virtualization-missing path.

## License

MIXE UI/shell: ©2026 EX Inc./HYPERION DIGITAL ©2026  
QEMU, adb, Android-x86: their respective open-source licenses (see `engine/NOTICE.txt`).
