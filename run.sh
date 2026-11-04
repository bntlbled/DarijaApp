#!/usr/bin/env bash
# Start the app at http://localhost:8000
set -e
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
