#!/usr/bin/env bash
# Installs osu-tools: the 'osu' dispatcher onto PATH, everything else into
# ~/.local/share/osu-tools/. Safe to re-run to pick up updates.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="${OSU_TOOLS_DIR:-$HOME/.local/share/osu-tools}"
BIN_DIR="/usr/local/bin"

mkdir -p "$TOOLS_DIR"
for f in osu-current osu-fix-video osu-bpm-offset osu-pp osu-recent osu-collections osu-backup; do
    cp "$HERE/$f" "$TOOLS_DIR/$f"
    chmod +x "$TOOLS_DIR/$f"
done
echo "Installed to $TOOLS_DIR"

if [ -w "$BIN_DIR" ]; then
    cp "$HERE/osu" "$BIN_DIR/osu"
else
    sudo cp "$HERE/osu" "$BIN_DIR/osu"
fi
chmod +x "$BIN_DIR/osu" 2>/dev/null || sudo chmod +x "$BIN_DIR/osu"
echo "Installed $BIN_DIR/osu"

echo
echo "Done. Run 'osu' to launch the game (and start the map tracker), or"
echo "'osu current watch &' to start tracking without launching the game."
