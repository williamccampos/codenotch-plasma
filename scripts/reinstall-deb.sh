#!/usr/bin/env bash
set -euo pipefail

DEB="${1:-$HOME/Downloads/codenotch-plasma_0.1.6_amd64.deb}"

if [[ ! -f "$DEB" ]]; then
  echo "Pacote não encontrado: $DEB" >&2
  exit 1
fi

cd "$HOME"
pkill -f codenotch-plasma 2>/dev/null || true
sudo apt remove --purge -y codenotch-plasma
rm -f "$HOME/.cache/icon-cache.kcache" "$HOME"/.cache/ksycoca5_* "$HOME"/.cache/ksycoca6_*
sudo apt install -y "$DEB"
kbuildsycoca6 --noincremental 2>/dev/null || kbuildsycoca5 --noincremental 2>/dev/null || true
echo "Instalado. Iniciando Codenotch..."
codenotch-plasma &
