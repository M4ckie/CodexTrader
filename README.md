# CodexTrader

Offline research app for testing an AI-style stock trading bot against simulated market data.

This does not connect to any broker or live trading venue. The first version is built for local experimentation:

- generates deterministic synthetic stock data
- scores tickers with a multi-factor "AI-style" model
- simulates entries, exits, stop losses, take profits, slippage, and commissions
- outputs a JSON report with performance metrics and full trade history

It now supports two strategy providers:

- `heuristic`: local multi-factor model
- `openai`: OpenAI API chooses `BUY` / `SELL` / `HOLD` from recent candle history

It also now supports an end-of-day research workflow:

- `build-brief`: assemble a market brief from local CSV data or external APIs
- `daily-run`: build the brief, send it to OpenAI, and save the resulting decisions
- `scenarios`: inspect portfolio-style presets and their universe rules
- `portfolio-status`: inspect the persisted paper portfolio for a scenario

There is also a Streamlit dashboard in [dashboard.py](/home/jonny/projects/CodexTrader/dashboard.py).

## Quick Start

```bash
python3 main.py generate-data
python3 main.py backtest
```

The backtest report is written to `output/backtest_report.json`.

## OpenAI Strategy

Install dependencies and set your API key:

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="your_api_key_here"
```

Run the backtest with OpenAI making the trade decisions:

```bash
python3 main.py backtest --strategy-provider openai --openai-model gpt-4.1-mini
```

Important note: this first version sends the last 25 candles for each ticker on every backtest step. That works for experimentation, but it will be slow and can consume meaningful API spend on long runs. For a serious research loop, the next step is batching fewer decisions or evaluating weekly instead of daily.

## End-Of-Day Workflow

Build a brief from local CSV data:

```bash
python3 main.py build-brief --provider local --scenario balanced_100k
```

Build a brief and ask OpenAI for a few next-session trades:

```bash
python3 main.py daily-run \
  --provider local \
  --scenario balanced_100k \
  --openai-model gpt-4.1-mini \
  --max-new-trades 3
```

Outputs are written to `output/daily_run/`:

- `daily_brief.json`
- `daily_brief.md`
- `daily_decisions.json`

Paper portfolio state is persisted separately in `output/portfolios/` by scenario.

Inspect it with:

```bash
python3 main.py portfolio-status --scenario balanced_100k
```

Run the dashboard with:

```bash
.venv/bin/streamlit run dashboard.py
```

## External Data Providers

Supported provider modes:

- `local`: reads CSVs in `data/market`
- `alphavantage`: reads prices, overview, and news from Alpha Vantage
- `fmp`: reads prices, profile data, and news from Financial Modeling Prep

Environment variables:

```bash
export OPENAI_API_KEY="..."
export ALPHAVANTAGE_API_KEY="..."
export FMP_API_KEY="..."
export SEC_USER_AGENT="CodexTrader your-email@example.com"
```

The SEC adapter is included for filing enrichment and uses `SEC_USER_AGENT`, but it is not yet wired into the main brief flow because ticker-to-CIK mapping still needs to be added.

## Configurable Universe Rules

The app now treats the candidate universe as explicit configuration rather than hidden logic.

Default `balanced_100k` scenario rules:

- US equities only
- minimum price: `$10`
- minimum market cap: `$2B`
- minimum average daily dollar volume: `$20M`
- ETFs excluded
- discovery pool capped at `60` symbols
- brief limited to top `12` candidates
- max `3` new trades per day

Other built-in scenarios:

- `small_1000`
- `conservative_100k`
- `aggressive_100k`

Inspect them with:

```bash
python3 main.py scenarios --verbose
```

The scenarios are now stored in [scenarios.json](/home/jonny/projects/CodexTrader/config/scenarios.json), so you can add more account sizes and risk profiles without editing Python.

If you pass `--tickers`, those symbols become the candidate pool. If you omit `--tickers`, the app auto-selects candidates from the provider's available universe. That now works with `local` and `fmp`. `alphavantage` still requires explicit tickers in this version.

## Portfolio State

`daily-run` now maintains a scenario-specific paper portfolio across runs:

- existing positions are loaded before the brief is built
- OpenAI decisions are applied after the brief
- `SELL` closes an open position at the brief close price
- `BUY` opens a new position using the scenario's position sizing rules

This is still a simple paper engine. It does not yet model next-day open fills, stop-loss execution between sessions, or tax lots.

## CLI

Generate market data:

```bash
python3 main.py generate-data --days 320 --seed 11 --tickers AAPL MSFT NVDA AMD META TSLA
```

Run the bot:

```bash
python3 main.py backtest --data-dir data/market --initial-cash 100000 --max-positions 4
```

Tune the strategy:

```bash
python3 main.py backtest \
  --buy-threshold 0.60 \
  --sell-threshold -0.15 \
  --stop-loss-pct 0.06 \
  --take-profit-pct 0.20
```

## How the signal model works

The local strategy uses an interpretable scoring model that combines:

- 5-day momentum
- 20-day momentum
- distance from the 20-day average
- short-term trend slope
- recent volatility penalty
- abnormal volume boost

The score is mapped to a confidence value and converted into `BUY`, `SELL`, or `HOLD`.

## Next steps

Good expansions from here:

- load real historical data from CSV exports
- compare multiple strategies side by side
- add walk-forward validation instead of one fixed run
- add a small web dashboard for charts and trade inspection
- cache OpenAI responses to avoid repeated token spend during backtests
- persist a paper portfolio between daily runs
- enrich briefs with SEC filing events and earnings calendars
