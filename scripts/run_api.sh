#!/usr/bin/env bash
# Run the VAOS API server locally with autoreload enabled.
set -euo pipefail

uvicorn api.main:app --reload --host "${VAOS_API_HOST:-0.0.0.0}" --port "${VAOS_API_PORT:-8000}"
