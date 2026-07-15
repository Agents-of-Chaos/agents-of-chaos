#!/usr/bin/env bash
# Screenshot every /networks question state from the built site with headless
# Chrome (no extra deps). Run after `npm run build`:
#   ./scripts/screenshot-questions.sh [outdir]
# Covers: the idle strip, each ?q= state (canvas answer + drawer), one re-aimed
# state per question (?focus= picks the seat), the qselftest camera-restore
# check (a red FAIL banner would show in the shot), and two mobile spot-checks.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${1:-.screenshots/questions}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT=4391
SEAT="lakera" # any non-default company: exercises the live-kernel re-aim path
mkdir -p "$OUT"

npx serve dist -l "$PORT" >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
sleep 1.5

slugs=$(python3 -c "
import json
print(' '.join(json.load(open('src/data/questions/questions-companies.json'))['questions']))")

shot() { # url out [size]
  "$CHROME" --headless=new --disable-gpu --window-size="${3:-1400,1100}" \
    --screenshot="$OUT/$2.png" --virtual-time-budget=9000 \
    "http://localhost:$PORT$1" 2>/dev/null
  echo "  $2.png"
}

shot "/networks" "0-idle-strip"
for slug in $slugs; do
  shot "/networks/?q=$slug" "q-$slug"
  shot "/networks/?focus=$SEAT&q=$slug" "q-$slug-reaim"
done
first=$(echo "$slugs" | awk '{print $1}')
shot "/networks/?q=$first&qselftest=1" "selftest-$first"
shot "/networks/?q=$first" "q-$first-mobile" "390,900"
shot "/networks" "0-idle-mobile" "390,900"

echo "[screenshots] $OUT"
