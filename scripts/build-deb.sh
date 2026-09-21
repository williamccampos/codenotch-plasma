#!/usr/bin/env bash
# Build a .deb from the repository tree (used locally and in CI).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$(tr -d '[:space:]' < "$ROOT/VERSION")}"
ARCH="${ARCH:-amd64}"
STAGING="$(mktemp -d)"
PKG="${STAGING}/codenotch-plasma_${VERSION}_${ARCH}"
DEB_VERSION="${VERSION}-1"

cleanup() {
  rm -rf "${STAGING}"
}
trap cleanup EXIT

install -d "${PKG}/DEBIAN"
install -d "${PKG}/usr/bin"
install -d "${PKG}/usr/share/codenotch-plasma"
install -d "${PKG}/usr/share/applications"
install -d "${PKG}/etc/xdg/autostart"

install -m 0755 "${ROOT}/bin/codenotch-plasma" "${PKG}/usr/bin/"
cp -a "${ROOT}/src" "${PKG}/usr/share/codenotch-plasma/"
install -m 0644 "${ROOT}/LICENSE" "${ROOT}/README.md" "${ROOT}/config.example.json" \
  "${PKG}/usr/share/codenotch-plasma/"
install -m 0644 "${ROOT}/debian/codenotch-plasma.desktop" \
  "${PKG}/usr/share/applications/codenotch-plasma.desktop"
install -m 0644 "${ROOT}/debian/codenotch-plasma.desktop" \
  "${PKG}/etc/xdg/autostart/codenotch-plasma.desktop"

cat > "${PKG}/DEBIAN/control" <<EOF
Package: codenotch-plasma
Version: ${DEB_VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10), python3-pyqt5, python3-dbus, python3-browser-cookie3, python3-pycryptodome
Recommends: libsecret-tools
Maintainer: William Campos <williamcampos29@gmail.com>
Homepage: https://github.com/williamccampos/codenotch-plasma
Description: Usage notch for coding assistants on KDE Plasma
 Codenotch shows real-time usage rings for Claude, Codex, Cursor,
 Antigravity, Grok, and Kiro on the screen edge in KDE Plasma.
EOF

install -m 0755 "${ROOT}/debian/postinst" "${ROOT}/debian/prerm" "${PKG}/DEBIAN/"

mkdir -p "${ROOT}/dist"
OUTPUT="${ROOT}/dist/codenotch-plasma_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "${PKG}" "${OUTPUT}"
echo "Built ${OUTPUT}"
