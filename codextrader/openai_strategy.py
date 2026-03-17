"""OpenAI-backed strategy provider."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .brief_builder import render_brief_payload
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


def _market_prompt_payload(market_slice: dict[str, list[Candle]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
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
    return payload


def _build_market_prompt(market_slice: dict[str, list[Candle]]) -> str:
    return json.dumps(_market_prompt_payload(market_slice), separators=(",", ":"))


def _build_brief_prompt(brief: DailyBrief, max_new_trades: int) -> str:
    return json.dumps(
        {
            "max_new_trades": max_new_trades,
            "brief": render_brief_payload(brief),
        },
        separators=(",", ":"),
    )


def _create_client() -> OpenAI:
    if OpenAI is None:
        raise RuntimeError("The `openai` package is not installed. Run `pip install -r requirements.txt`.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=api_key)


def _request_openai_text(model: str, system_prompt: str, user_content: str, client: OpenAI | None = None) -> str:
    selected_client = client or _create_client()
    response = selected_client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return response.output_text


def _normalize_signal_item(item: dict[str, Any], buy_slot_available: bool = True) -> Signal | None:
    ticker = str(item.get("ticker", "")).upper().strip()
    action = str(item.get("action", "HOLD")).upper()
    if not ticker or action not in {"BUY", "SELL", "HOLD"}:
        return None
    if action == "BUY" and not buy_slot_available:
        action = "HOLD"
    return Signal(
        ticker=ticker,
        score=float(item.get("score", 0.0)),
        confidence=max(0.0, min(float(item.get("confidence", 0.5)), 1.0)),
        action=action,
        reason=str(item.get("reason", "")).strip(),
    )


def _normalize_signals(raw_signals: list[dict[str, Any]]) -> list[Signal]:
    signals = []
    for item in raw_signals:
        signal = _normalize_signal_item(item)
        if signal:
            signals.append(signal)
    return sorted(signals, key=lambda item: (item.action != "BUY", -abs(item.score), -item.confidence, item.ticker))


def _normalize_brief_decisions(raw_signals: list[dict[str, Any]], max_new_trades: int) -> list[Signal]:
    decisions: list[Signal] = []
    buy_count = 0
    for item in raw_signals:
        action = str(item.get("action", "HOLD")).upper()
        buy_slot_available = True
        if action == "BUY":
            buy_count += 1
            buy_slot_available = buy_count <= max_new_trades
        signal = _normalize_signal_item(item, buy_slot_available=buy_slot_available)
        if signal:
            decisions.append(signal)
    return sorted(decisions, key=lambda item: (item.action != "BUY", -item.confidence, -abs(item.score), item.ticker))


def score_with_openai(
    market_slice: dict[str, list[Candle]],
    model: str,
) -> list[Signal]:
    """Ask OpenAI for ticker actions."""
    text = _request_openai_text(model, SYSTEM_PROMPT, _build_market_prompt(market_slice))
    raw_signals = _extract_json_array(text)
    return _normalize_signals(raw_signals)


def decide_from_brief(brief: DailyBrief, model: str, max_new_trades: int = 3) -> list[Signal]:
    """Ask OpenAI to convert the end-of-day brief into next-session decisions."""
    text = _request_openai_text(model, BRIEF_SYSTEM_PROMPT, _build_brief_prompt(brief, max_new_trades))
    raw_signals = _extract_json_array(text)
    return _normalize_brief_decisions(raw_signals, max_new_trades)
