#!/usr/bin/env bash
# Rebake every /networks/analyses artifact from the CURRENT public graphs,
# then run the strict gate. Run from anywhere: ./experiments/analyses/bake.sh
set -euo pipefail
cd "$(dirname "$0")"

uv run prep_shared.py
for f in *.py; do
  case "$f" in
    _*|prep_*) continue ;;
  esac
  uv run "$f"
done
uv run prep_questions.py

cd ../..
ANALYSES_STRICT=1 python3 -m pytest experiments/analyses/tests -q
echo "[bake] all analyses rebaked + strict gate green"
