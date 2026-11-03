#!/usr/bin/env bash
set -euo pipefail
: "${STEELFLOW_DEMO_PASSWORD:?Set a strong STEELFLOW_DEMO_PASSWORD in hosting environment}"
export STEELFLOW_DEMO_MODE=1
python -m app.seed_demo
python -m app.seed_showcase
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"
