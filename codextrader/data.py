"""Synthetic market data generator and CSV loader."""

from __future__ import annotations

import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

from .models import Candle


def generate_synthetic_dataset(
    output_dir: Path,
    tickers: list[str],
    start_date: date,
    days: int,
    seed: int = 7,
) -> list[Path]:
    """Create deterministic pseudo-market data for experiments."""
    output_dir.mkdir(parents=True, exist_ok=True)
    random.seed(seed)
    written_files: list[Path] = []

    for index, ticker in enumerate(tickers):
        drift = 0.0005 + (index * 0.00008)
        volatility = 0.018 + (index % 3) * 0.006
        price = 80.0 + index * 35.0
        file_path = output_dir / f"{ticker}.csv"
        current_day = start_date

        with file_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "ticker", "open", "high", "low", "close", "volume"])

            emitted = 0
            while emitted < days:
                if current_day.weekday() >= 5:
                    current_day += timedelta(days=1)
                    continue

                cycle = math.sin(emitted / 17.0 + index) * 0.004
                shock = random.gauss(drift + cycle, volatility)
                open_price = price
                close = max(5.0, price * (1 + shock))
                intraday_range = abs(random.gauss(0.012, 0.006))
                high = max(open_price, close) * (1 + intraday_range)
                low = min(open_price, close) * (1 - intraday_range)
                volume = int(900_000 + abs(shock) * 40_000_000 + random.randint(0, 400_000))

                writer.writerow([
                    current_day.isoformat(),
                    ticker,
                    f"{open_price:.2f}",
                    f"{high:.2f}",
                    f"{low:.2f}",
                    f"{close:.2f}",
                    volume,
                ])

                price = close
                emitted += 1
                current_day += timedelta(days=1)

        written_files.append(file_path)

    return written_files


def load_market_data(data_dir: Path) -> dict[str, list[Candle]]:
    """Load ticker CSV files from disk."""
    market_data: dict[str, list[Candle]] = {}

    for csv_path in sorted(data_dir.glob("*.csv")):
        candles: list[Candle] = []
        with csv_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                candles.append(
                    Candle(
                        date=row["date"],
                        ticker=row["ticker"],
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(row["volume"]),
                    )
                )
        if candles:
            market_data[candles[0].ticker] = candles

    return market_data
