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
# Keep the existing launcher and all its subcommands. Only an invocation with
# no arguments checks the optional prelaunch policy before the game starts.
# Do this on the installed copy rather than assuming the user's Wine launch
# command or modifying the checked-in launcher.
python3 - "$BIN_DIR/osu" <<'PYHOOK'
from pathlib import Path
import sys
launcher = Path(sys.argv[1])
head, separator, body = launcher.read_bytes().partition(b'\n')
if not head.startswith(b'#!') or not separator:
    raise SystemExit('Cannot install prelaunch hook: osu launcher has no shebang')
hook = r'''# --- osu-tools extensions (installed copy only) ---
# The original launcher predates the offline score browser. Route this one new
# subcommand without touching existing command handling or the game launch.
if [ "${1:-}" = "scores" ]; then
  _osu_scores="${OSU_TOOLS_DIR:-$HOME/.local/share/osu-tools}/osu-scores"
  if [ -x "$_osu_scores" ]; then
    shift
    exec "$_osu_scores" "$@"
  fi
  printf 'osu-tools: osu-scores is missing; reinstall osu-tools\n' >&2
  exit 1
fi
# --- osu-tools optional prelaunch hook ---
if [ "$#" -eq 0 ] && [ "${OSU_TOOLS_SKIP_PRELAUNCH:-0}" != "1" ]; then
  _osu_cfg="${XDG_CONFIG_HOME:-$HOME/.config}/osu-tools/prelaunch.json"
  _osu_helper="${OSU_TOOLS_DIR:-$HOME/.local/share/osu-tools}/osu-prelaunch"
  if [ -f "$_osu_cfg" ] && [ -x "$_osu_helper" ]; then
    "$_osu_helper" run --quiet || printf 'osu-tools: prelaunch check failed (game will still start)\n' >&2
  fi
  unset _osu_cfg _osu_helper
fi
# --- end osu-tools prelaunch hook ---
'''
launcher.write_bytes(head + b'\n' + hook.encode() + body)
PYHOOK
chmod +x "$BIN_DIR/osu"
echo "Installed commands to $TOOLS_DIR and launcher to $BIN_DIR/osu"
case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *) echo "Add $BIN_DIR to your PATH to use 'osu' from the shell." ;;
esac
echo "Try: osu doctor; osu collections sync; osu collections sync --apply (with game closed)"
