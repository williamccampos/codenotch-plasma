#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
SHARE="${HOME}/.local/share/codenotch-plasma"
AUTO="${HOME}/.config/autostart"

mkdir -p "$BIN_DIR" "$SHARE" "$AUTO"
cp -a "$ROOT/src" "$ROOT/bin" "$ROOT/LICENSE" "$ROOT/README.md" "$SHARE/"
if [ -d "$ROOT/icons/hicolor" ]; then
  mkdir -p "${HOME}/.local/share/icons"
  cp -a "$ROOT/icons/hicolor" "${HOME}/.local/share/icons/"
  cp -a "$ROOT/icons" "$SHARE/"
fi
if ! python3 -c "import browser_cookie3" >/dev/null 2>&1; then
  echo "Instalando browser-cookie3 para sessão corporativa do Cursor no browser..."
  python3 -m pip install --user --break-system-packages browser-cookie3 >/dev/null 2>&1 || true
fi
if ! command -v secret-tool >/dev/null 2>&1; then
  echo "Antigravity: para ler credenciais do keyring, instale libsecret-tools:"
  echo "  sudo apt install libsecret-tools"
fi
install -m 0755 "$ROOT/bin/codenotch-plasma" "$BIN_DIR/codenotch-plasma"

cat > "$AUTO/codenotch-plasma.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Codenotch
Comment=Usage notch for coding assistants
Exec=${BIN_DIR}/codenotch-plasma
Icon=codenotch-plasma
Terminal=false
StartupNotify=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
X-KDE-autostart-after=panel
X-KDE-StartupNotify=false
EOF

chmod 0644 "$AUTO/codenotch-plasma.desktop"

# Restart a previous instance, then start.
pkill -f 'codenotch_plasma' >/dev/null 2>&1 || true
pkill -f 'bin/codenotch-plasma' >/dev/null 2>&1 || true
nohup "$BIN_DIR/codenotch-plasma" >/tmp/codenotch-plasma.log 2>&1 &
echo "Codenotch instalado. Notch na borda direita; clique direito para sair."
echo "Log: /tmp/codenotch-plasma.log"
