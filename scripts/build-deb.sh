#!/usr/bin/env bash
# Build a .deb from the repository tree (used locally and in CI).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$(tr -d '[:space:]' < "$ROOT/VERSION")}"
ARCH="${ARCH:-amd64}"
STAGING="$(mktemp -d)"
PKG="${STAGING}/codenotch-plasma_${VERSION}_${ARCH}"
DEB_VERSION="${VERSION}-1"
VENDOR="${PKG}/usr/share/codenotch-plasma/vendor"

cleanup() {
  rm -rf "${STAGING}"
}
trap cleanup EXIT

install -d "${PKG}/DEBIAN"
install -d "${PKG}/usr/bin"
install -d "${PKG}/usr/share/codenotch-plasma"
install -d "${PKG}/usr/share/applications"
install -d "${PKG}/etc/xdg/autostart"

if command -v python3 >/dev/null && python3 -c "import cairosvg" 2>/dev/null; then
  python3 "${ROOT}/scripts/render-glyphs.py"
fi

install -m 0755 "${ROOT}/bin/codenotch-plasma" "${PKG}/usr/bin/"
cp -a "${ROOT}/src" "${PKG}/usr/share/codenotch-plasma/"
install -m 0644 "${ROOT}/LICENSE" "${ROOT}/README.md" "${ROOT}/config.example.json" \
  "${PKG}/usr/share/codenotch-plasma/"
install -m 0644 "${ROOT}/debian/codenotch-plasma.desktop" \
  "${PKG}/usr/share/applications/codenotch-plasma.desktop"
install -m 0644 "${ROOT}/debian/codenotch-plasma.desktop" \
  "${PKG}/etc/xdg/autostart/codenotch-plasma.desktop"
if [ -d "${ROOT}/icons/hicolor" ]; then
  install -d "${PKG}/usr/share/icons"
  cp -a "${ROOT}/icons/hicolor" "${PKG}/usr/share/icons/"
  while IFS= read -r icon; do
    cp "${icon}" "$(dirname "${icon}")/codenotch.${icon##*.}"
  done < <(find "${PKG}/usr/share/icons/hicolor" -name 'codenotch-plasma.*')
fi
install -d "${PKG}/usr/share/codenotch-plasma/icons"
install -m 0644 "${ROOT}/icons/codenotch-plasma.svg" \
  "${PKG}/usr/share/codenotch-plasma/icons/codenotch-plasma.svg"

# Bundle browser-cookie3 (not packaged on Ubuntu 24.04 / many Debian derivatives).
python3 -m pip install --disable-pip-version-check --no-cache-dir \
  --target "${VENDOR}" "browser-cookie3>=0.19.0" \
  --break-system-packages 2>/dev/null \
  || python3 -m pip install --disable-pip-version-check --no-cache-dir \
  --target "${VENDOR}" "browser-cookie3>=0.19.0"

cat > "${PKG}/DEBIAN/control" <<EOF
Package: codenotch-plasma
Version: ${DEB_VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10), python3-pyqt5, python3-dbus, python3-pycryptodome
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
