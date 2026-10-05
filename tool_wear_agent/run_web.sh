#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PORT="${TWA_PORT:-8001}"
python3 -m uvicorn api:app --host 0.0.0.0 --port "$PORT"
