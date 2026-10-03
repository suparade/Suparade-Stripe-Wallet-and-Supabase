#!/usr/bin/env bash
# Render each src/NN-*.html to NN-*.png at the size set in its :root (--w/--h).
#
# PHASE (default 0) switches on the content for the Supabase Compute build phases:
#   0  nothing runs on Compute yet (today)
#   1  the scout runs on Supabase Compute
# Raise it only after that phase is deployed and verified. Pages marked
# "min-phase: N" are skipped below that phase.
# OUT (default: the folder above src) is where the PNGs are written.
set -euo pipefail
cd "$(dirname "$0")"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PHASE="${PHASE:-0}"
OUT="${OUT:-..}"
mkdir -p "$OUT"
OUT_ABS="$(cd "$OUT" && pwd)"
for f in [0-9][0-9]-*.html; do
  min=$(grep -oE 'min-phase: *[0-9]+' "$f" | grep -oE '[0-9]+' || echo 0)
  if [ "$min" -gt "$PHASE" ]; then
    echo "skip $f (needs PHASE=$min)"
    continue
  fi
  w=$(grep -oE -- '--w: *[0-9]+px' "$f" | grep -oE '[0-9]+')
  h=$(grep -oE -- '--h: *[0-9]+px' "$f" | grep -oE '[0-9]+')
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
    --virtual-time-budget=4000 --window-size="$w,$h" \
    --screenshot="$OUT_ABS/${f%.html}.png" "file://$PWD/$f?phase=$PHASE" >/dev/null 2>&1
  echo "$OUT/${f%.html}.png (${w}x${h} @2x, phase $PHASE)"
done
