#!/usr/bin/env bash
set -euo pipefail

PORT="${DASHBOARD_PORT:-8512}"

echo "Starting CodexTrader dashboard on port ${PORT}..."
exec streamlit run dashboard.py \
  --server.address 0.0.0.0 \
  --server.port "${PORT}" \
  --server.headless true
