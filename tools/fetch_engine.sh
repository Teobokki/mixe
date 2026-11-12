#!/bin/sh
# Rebuild the bundled QEMU+adb engine pack (run on the build box).
set -e
cd "$(dirname "$0")/.."
echo "See build notes in README — engine is assembled from qemu.weilnetz.de + Google platform-tools during packaging."
