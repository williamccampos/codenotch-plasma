#!/usr/bin/env bash
set -euo pipefail

echo "==> Parando Codenotch..."
pkill -f 'python3.*codenotch-plasma' 2>/dev/null || true
pkill -f 'codenotch_plasma' 2>/dev/null || true
pkill -f '/usr/bin/codenotch-plasma' 2>/dev/null || true
sleep 1

echo "==> Removendo pacote .deb (purge)..."
sudo apt-get remove --purge -y codenotch-plasma || true
sudo dpkg --remove --force-remove-reinstreq codenotch-plasma 2>/dev/null || true
sudo apt-get autoremove -y 2>/dev/null || true

echo "==> Limpando instalação manual antiga..."
rm -rf "$HOME/.local/share/codenotch-plasma"
rm -f "$HOME/.local/bin/codenotch-plasma"
rm -f "$HOME/.config/autostart/codenotch-plasma.desktop"

echo "==> Limpando ícones do usuário..."
find "$HOME/.local/share/icons" -name 'codenotch-plasma.*' -delete 2>/dev/null || true
find "$HOME/.local/share/icons" -name 'codenotch.*' -delete 2>/dev/null || true

echo "==> Limpando cache de ícones do KDE..."
rm -f "$HOME/.cache/icon-cache.kcache"
find "$HOME/.cache" -maxdepth 1 -name 'ksycoca5_*' -delete 2>/dev/null || true
find "$HOME/.cache" -maxdepth 1 -name 'ksycoca6_*' -delete 2>/dev/null || true

echo "==> Atualizando caches do sistema..."
if command -v gtk-update-icon-cache >/dev/null; then
  sudo gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
fi
kbuildsycoca6 --noincremental 2>/dev/null || kbuildsycoca5 --noincremental 2>/dev/null || true

echo "==> Verificando estado do apt..."
sudo dpkg --configure -a
sudo apt-get check

echo
echo "Expurgo concluído. Para reinstalar:"
echo "  sudo apt install ~/Downloads/codenotch-plasma_0.2.1_amd64.deb"
