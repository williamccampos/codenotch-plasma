#!/usr/bin/env bash
# Workaround for Antigravity 1.x on Linux: bundled localhost TLS cert expired
# (notAfter=2026-09-04). See https://github.com/williamccampos/codenotch-plasma/issues/1
set -euo pipefail

DESKTOP_DIR="${HOME}/.local/share/applications"
DESKTOP_FILE="${DESKTOP_DIR}/antigravity.desktop"

mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_FILE" << 'EOF'
[Desktop Entry]
Name=Antigravity
Comment=Experience liftoff
GenericName=Text Editor
Exec=env NODE_TLS_REJECT_UNAUTHORIZED=0 /usr/share/antigravity/antigravity %F
Icon=antigravity
Type=Application
StartupNotify=false
StartupWMClass=Antigravity
Categories=TextEditor;Development;IDE;
MimeType=application/x-antigravity-workspace;
Actions=new-empty-window;
Keywords=vscode;

[Desktop Action new-empty-window]
Name=New Empty Window
Exec=env NODE_TLS_REJECT_UNAUTHORIZED=0 /usr/share/antigravity/antigravity --new-window %F
Icon=antigravity
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

echo "Antigravity launcher patched: ${DESKTOP_FILE}"
echo "Feche o Antigravity e abra de novo pelo menu do KDE."
echo ""
echo "Aviso: NODE_TLS_REJECT_UNAUTHORIZED=0 desativa verificação TLS local."
echo "Use só para o loopback 127.0.0.1 do language server. Solução definitiva: Antigravity 2.x."
