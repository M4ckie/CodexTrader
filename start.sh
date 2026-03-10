#!/usr/bin/env bash
set -euo pipefail

PORT="${DASHBOARD_PORT:-8512}"
TRADE_PROVIDER="${TRADE_PROVIDER:-alphavantage}"
SCHEDULE_SCENARIOS="${SCHEDULE_SCENARIOS:-balanced_100k}"
OPENAI_MODEL="${OPENAI_MODEL:-gpt-4.1-mini}"
SCHEDULE_TIME="${SCHEDULE_TIME:-16:35}"
SCHEDULE_TIMEZONE="${SCHEDULE_TIMEZONE:-America/New_York}"

echo "Starting CodexTrader scheduler for scenarios ${SCHEDULE_SCENARIOS} at ${SCHEDULE_TIME} ${SCHEDULE_TIMEZONE}..."
python main.py schedule \
  --provider "${TRADE_PROVIDER}" \
  --scenario ${SCHEDULE_SCENARIOS} \
  --output-root output/scheduled_runs \
  --portfolio-dir output/portfolios \
  --openai-model "${OPENAI_MODEL}" \
  --time "${SCHEDULE_TIME}" \
  --timezone "${SCHEDULE_TIMEZONE}" &

echo "Starting CodexTrader dashboard on port ${PORT}..."
exec streamlit run dashboard.py \
  --server.address 0.0.0.0 \
  --server.port "${PORT}" \
  --server.headless true
