#!/usr/bin/env bash
# Install over a normal clone of AAIT123/osu-tools, no sudo by default.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="${OSU_TOOLS_DIR:-$HOME/.local/share/osu-tools}"
BIN_DIR="${OSU_BIN_DIR:-$HOME/.local/bin}"
if [[ ! -f "$HERE/osu" ]]; then
  echo 'This is a refactor OVERLAY. Unpack into a clone of AAIT123/osu-tools first.' >&2
  exit 1
fi
mkdir -p "$TOOLS_DIR" "$BIN_DIR"
# Existing helper entrypoints (backup, current, pp, recent...) remain available.
for source in "$HERE"/osu-*; do
  [[ -f "$source" ]] || continue
  cp -- "$source" "$TOOLS_DIR/$(basename "$source")"
  chmod +x "$TOOLS_DIR/$(basename "$source")"
done
cp -R -- "$HERE/osu_tools" "$TOOLS_DIR/"
# Don't copy __pycache__ from source if present.
find "$TOOLS_DIR/osu_tools" -type d -name __pycache__ -prune -exec rm -rf {} +
cp -- "$HERE/osu" "$BIN_DIR/osu"
chmod +x "$BIN_DIR/osu"
echo "Installed commands to $TOOLS_DIR and launcher to $BIN_DIR/osu"
case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *) echo "Add $BIN_DIR to your PATH to use 'osu' from the shell." ;;
esac
echo "Try: osu doctor; osu collections sync; osu collections sync --apply (with game closed)"
