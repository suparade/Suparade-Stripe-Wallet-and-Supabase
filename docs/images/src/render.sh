#!/usr/bin/env bash
# Render each src/NN-*.html to ../NN-*.png at the size set in its :root (--w/--h).
set -euo pipefail
cd "$(dirname "$0")"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
for f in [0-9][0-9]-*.html; do
  w=$(grep -oE -- '--w: *[0-9]+px' "$f" | grep -oE '[0-9]+')
  h=$(grep -oE -- '--h: *[0-9]+px' "$f" | grep -oE '[0-9]+')
  out="../${f%.html}.png"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
    --virtual-time-budget=4000 --window-size="$w,$h" --screenshot="$PWD/$out" "file://$PWD/$f" >/dev/null 2>&1
  echo "$out (${w}x${h} @2x)"
done
