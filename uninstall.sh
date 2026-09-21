#!/usr/bin/env bash
set -euo pipefail

BIN="${HOME}/.local/bin/codenotch-plasma"
AUTO="${HOME}/.config/autostart/codenotch-plasma.desktop"
SHARE="${HOME}/.local/share/codenotch-plasma"

pkill -f 'python3.*codenotch-plasma' >/dev/null 2>&1 || true
pkill -f 'bin/codenotch-plasma' >/dev/null 2>&1 || true

rm -f "$BIN" "$AUTO"
rm -rf "$SHARE"

echo "Codenotch Plasma removido."
echo "Config e cache preservados em:"
echo "  ~/.config/codenotch-plasma/"
echo "  ~/.cache/codenotch/"
