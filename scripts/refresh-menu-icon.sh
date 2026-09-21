#!/usr/bin/env bash
set -euo pipefail

echo "Removendo ícones antigos do usuário..."
find "$HOME/.local/share/icons/hicolor" -name 'codenotch-plasma.*' -delete 2>/dev/null || true
find "$HOME/.local/share/icons/hicolor" -name 'codenotch.*' -delete 2>/dev/null || true
rm -f "$HOME/.cache/icon-cache.kcache"
rm -f "$HOME"/.cache/ksycoca5_* "$HOME"/.cache/ksycoca6_* 2>/dev/null || true

echo "Atualizando cache do sistema..."
if command -v gtk-update-icon-cache >/dev/null; then
  sudo gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
fi
kbuildsycoca6 --noincremental 2>/dev/null || kbuildsycoca5 --noincremental 2>/dev/null || true

echo "Reiniciando Codenotch..."
pkill -f codenotch-plasma 2>/dev/null || true
codenotch-plasma &
echo "Pronto. Abra o menu de aplicativos novamente."
