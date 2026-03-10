"""OpenAI-backed strategy provider."""

from __future__ import annotations

import json
import os
import re

from .brief_builder import render_brief_json
from .models import Candle, DailyBrief, Signal

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None


SYSTEM_PROMPT = """You are a disciplined paper-trading strategist.
You are given recent daily market data for several stocks.
Return only JSON as an array, one object per ticker:
[
  {
    "ticker": "AAPL",
    "action": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0 to 1.0,
    "score": -1.0 to 1.0,
    "reason": "short explanation"
  }
]
Rules:
- Prefer HOLD when the edge is weak.
- Use BUY only for the strongest setups.
- Use SELL when recent weakness or risk is material.
- Keep reasons short.
- Output valid JSON only, no markdown fences."""


BRIEF_SYSTEM_PROMPT = """You are a disciplined end-of-day paper-trading strategist.
You receive one compact market brief after the close.
Your job is to propose at most a few next-session trades.

Return only JSON as an array of objects:
[
  {
    "ticker": "AAPL",
    "action": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0,
    "score": 0.0,
    "reason": "short explanation",
    "holding_period_days": 3,
    "risk_note": "main risk",
    "stop_loss_pct": 5.0
  }
]

Rules:
- Propose no more than the requested max number of new BUY trades.
- Prefer HOLD when the brief is mixed or weak.
- SELL only when downside risk is material or the thesis is broken.
- Favor liquid names with clear catalysts and trend alignment.
- Output valid JSON only."""


def _extract_json_array(text: str) -> list[dict]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise ValueError("OpenAI response did not contain a JSON array.")
        return json.loads(match.group(0))


def _build_prompt(market_slice: dict[str, list[Candle]]) -> str:
    payload = []
    for ticker, history in sorted(market_slice.items()):
        recent = history[-25:]
        payload.append(
            {
                "ticker": ticker,
                "recent_candles": [
                    {
                        "date": candle.date,
                        "open": candle.open,
                        "high": candle.high,
                        "low": candle.low,
                        "close": candle.close,
                        "volume": candle.volume,
                    }
                    for candle in recent
                ],
            }
        )
    return json.dumps(payload, separators=(",", ":"))


def _create_client() -> OpenAI:
    if OpenAI is None:
        raise RuntimeError("The `openai` package is not installed. Run `pip install -r requirements.txt`.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=api_key)


def score_with_openai(
    market_slice: dict[str, list[Candle]],
    model: str,
) -> list[Signal]:
    """Ask OpenAI for ticker actions."""
    client = _create_client()
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(market_slice)},
        ],
    )
    text = response.output_text
    raw_signals = _extract_json_array(text)

    signals: list[Signal] = []
    for item in raw_signals:
        ticker = str(item.get("ticker", "")).upper().strip()
        action = str(item.get("action", "HOLD")).upper()
        confidence = float(item.get("confidence", 0.5))
        score = float(item.get("score", 0.0))
        reason = str(item.get("reason", "")).strip()
        if ticker and action in {"BUY", "SELL", "HOLD"}:
            signals.append(
                Signal(
                    ticker=ticker,
                    score=score,
                    confidence=max(0.0, min(confidence, 1.0)),
                    action=action,
                    reason=reason,
                )
            )
    return sorted(signals, key=lambda item: (item.action != "BUY", -abs(item.score), -item.confidence, item.ticker))


def decide_from_brief(brief: DailyBrief, model: str, max_new_trades: int = 3) -> list[Signal]:
    """Ask OpenAI to convert the end-of-day brief into next-session decisions."""
    client = _create_client()
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": BRIEF_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "max_new_trades": max_new_trades,
                        "brief": json.loads(render_brief_json(brief)),
                    },
                    separators=(",", ":"),
                ),
            },
        ],
    )
    raw_signals = _extract_json_array(response.output_text)
    decisions: list[Signal] = []
    buy_count = 0
    for item in raw_signals:
        ticker = str(item.get("ticker", "")).upper().strip()
        action = str(item.get("action", "HOLD")).upper()
        if action == "BUY":
            buy_count += 1
            if buy_count > max_new_trades:
                action = "HOLD"
        if ticker and action in {"BUY", "SELL", "HOLD"}:
            decisions.append(
                Signal(
                    ticker=ticker,
                    score=float(item.get("score", 0.0)),
                    confidence=max(0.0, min(float(item.get("confidence", 0.5)), 1.0)),
                    action=action,
                    reason=str(item.get("reason", "")).strip(),
                )
            )
    return sorted(decisions, key=lambda item: (item.action != "BUY", -item.confidence, -abs(item.score), item.ticker))
