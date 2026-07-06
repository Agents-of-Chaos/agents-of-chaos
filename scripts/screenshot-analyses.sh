#!/usr/bin/env bash
# Screenshot every /networks/analyses panel from the built site with headless
# Chrome (no extra deps). Run after `npm run build`:
#   ./scripts/screenshot-analyses.sh [outdir]
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${1:-.screenshots/analyses}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT=4390
mkdir -p "$OUT"

npx serve dist -l "$PORT" >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
sleep 1.5

slugs=$(python3 -c "
import json, pathlib
order = [s.strip().strip('\",') for s in pathlib.Path('src/data/analyses-types.ts').read_text().split('ANALYSES_ORDER: string[] = [')[1].split(']')[0].splitlines() if s.strip().strip('\",')]
have = {p.stem for p in pathlib.Path('src/data/analyses').glob('*.json')}
print(' '.join(s for s in order if s in have))")

for slug in $slugs; do
  "$CHROME" --headless=new --disable-gpu --window-size=1400,1100 \
    --screenshot="$OUT/$slug.png" --virtual-time-budget=9000 \
    "http://localhost:$PORT/networks/analyses/?a=$slug" 2>/dev/null
  echo "  $slug.png"
done

# two mobile spot-checks
for slug in $(echo "$slugs" | awk '{print $1, $2}'); do
  "$CHROME" --headless=new --disable-gpu --window-size=390,900 \
    --screenshot="$OUT/$slug-mobile.png" --virtual-time-budget=9000 \
    "http://localhost:$PORT/networks/analyses/?a=$slug" 2>/dev/null
  echo "  $slug-mobile.png"
done

echo "[screenshots] $OUT"
