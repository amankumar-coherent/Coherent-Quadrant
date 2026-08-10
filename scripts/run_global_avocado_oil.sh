#!/usr/bin/env bash
# Run main quality pipeline + Coherent Quadrant for Global Avocado Oil (Docker).
# Prerequisites:
#   1. cp .env.example .env   && paste LLM key, USE_MOCK_DATA=false, QUADRANT_ENABLED=true
#   2. Docker Desktop running
#
# Usage (from repo root):
#   bash scripts/run_global_avocado_oil.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: .env missing. Copy .env.example → .env and paste an LLM API key."
  exit 1
fi

mkdir -p output/pipeline output/quadrant

echo "==> Starting postgres + searxng…"
docker compose up -d --build postgres searxng

echo "==> Waiting for SearXNG on :8080…"
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:8080" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "==> Pipeline + Quadrant: Avocado Oil Market (global)"
# --no-deps: app image only; reach host SearXNG via host.docker.internal (Compose also
# sets SEARXNG_BASE_URL=http://searxng:8080 when app is on the compose network — here
# we attach to the default network so searxng DNS works).
docker compose run --rm --entrypoint "" \
  -e SEARXNG_BASE_URL=http://searxng:8080 \
  -e QUADRANT_ENABLED=true \
  -e USE_MOCK_DATA=false \
  app \
  python run_pipeline.py \
    --input-json queries/briefs/global_avocado_oil.json \
    --global \
    --live \
    --profile quality

echo ""
echo "==> Done. Look for:"
echo "  output/pipeline/pipeline_avocado_oil_market_global.*"
echo "  output/quadrant/*avocado*oil*_quadrant.json"
ls -la output/quadrant/*avocado* 2>/dev/null || ls -la output/quadrant/ || true
