"""Scrape public finance headlines for ticker-level research enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .models import NewsItem


_DEFAULT_USER_AGENT = os.getenv(
    "NEWS_SCRAPER_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) CodexTrader/1.0",
)


def _fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xml,application/rss+xml;q=0.9,*/*;q=0.8",
            **(headers or {}),
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, context=context, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class ScrapedHeadline:
    title: str
    summary: str
    source: str
    published_at: str
    url: str


class _FinvizNewsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._table_depth = 0
        self._row_depth = 0
        self._cell_depth = 0
        self._current_row: list[dict[str, str]] = []
        self._cell_parts: list[str] = []
        self._cell_link = ""
        self._rows: list[list[dict[str, str]]] = []

    @property
    def rows(self) -> list[list[dict[str, str]]]:
        return self._rows

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag == "table" and (
            attr_map.get("id") == "news-table"
            or "fullview-news-outer" in attr_map.get("class", "")
        ):
            self._table_depth += 1
            return
        if self._table_depth == 0:
            return
        if tag == "tr":
            self._row_depth += 1
            self._current_row = []
            return
        if tag == "td" and self._row_depth > 0:
            self._cell_depth += 1
            self._cell_parts = []
            self._cell_link = ""
            return
        if tag == "a" and self._cell_depth > 0 and not self._cell_link:
            self._cell_link = attr_map.get("href", "")

    def handle_endtag(self, tag: str) -> None:
        if self._table_depth == 0:
            return
        if tag == "td" and self._cell_depth > 0:
            self._current_row.append(
                {
                    "text": _strip_html("".join(self._cell_parts)),
                    "url": urllib.parse.urljoin("https://finviz.com/", self._cell_link),
                }
            )
            self._cell_parts = []
            self._cell_link = ""
            self._cell_depth -= 1
            return
        if tag == "tr" and self._row_depth > 0:
            if len(self._current_row) >= 2:
                self._rows.append(self._current_row[:2])
            self._current_row = []
            self._row_depth -= 1
            return
        if tag == "table" and self._table_depth > 0:
            self._table_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._table_depth > 0 and self._cell_depth > 0:
            self._cell_parts.append(data)


def _yahoo_finance_rss_urls(ticker: str) -> list[str]:
    encoded = urllib.parse.quote(ticker.upper())
    return [
        f"https://finance.yahoo.com/rss/headline?s={encoded}",
        f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={encoded}&region=US&lang=en-US",
    ]


def _cache_dir() -> Path:
    return Path(os.getenv("NEWS_CACHE_DIR", "output/news_cache"))


def _cache_ttl_seconds() -> int:
    raw = os.getenv("NEWS_CACHE_TTL_SECONDS", "21600").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 21600


def _cache_path(provider: str, ticker: str) -> Path:
    return _cache_dir() / provider / f"{ticker.upper()}.json"


def _load_cache(provider: str, ticker: str) -> list[ScrapedHeadline]:
    path = _cache_path(provider, ticker)
    ttl = _cache_ttl_seconds()
    if ttl == 0 or not path.exists():
        return []
    age_seconds = datetime.now().timestamp() - path.stat().st_mtime
    if age_seconds > ttl:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    headlines: list[ScrapedHeadline] = []
    for item in payload:
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        headlines.append(
            ScrapedHeadline(
                title=title,
                summary=str(item.get("summary", "")).strip() or title,
                source=str(item.get("source", "")).strip(),
                published_at=str(item.get("published_at", "")).strip(),
                url=str(item.get("url", "")).strip(),
            )
        )
    return headlines


def _save_cache(provider: str, ticker: str, headlines: list[ScrapedHeadline]) -> None:
    if _cache_ttl_seconds() == 0:
        return
    path = _cache_path(provider, ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "title": item.title,
            "summary": item.summary,
            "source": item.source,
            "published_at": item.published_at,
            "url": item.url,
        }
        for item in headlines
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_yahoo_rss(ticker: str, max_items: int) -> list[ScrapedHeadline]:
    cached = _load_cache("yahoo", ticker)
    if cached:
        return cached[:max_items]
    for url in _yahoo_finance_rss_urls(ticker):
        try:
            payload = _fetch_text(url, headers={"Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8"})
            root = ET.fromstring(payload)
        except Exception:
            continue
        headlines: list[ScrapedHeadline] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            summary = _strip_html(item.findtext("description") or title)
            published_at = (item.findtext("pubDate") or "").strip()
            headlines.append(
                ScrapedHeadline(
                    title=title,
                    summary=summary or title,
                    source="Yahoo Finance",
                    published_at=published_at,
                    url=(item.findtext("link") or "").strip(),
                )
            )
            if len(headlines) >= max_items:
                break
        if headlines:
            _save_cache("yahoo", ticker, headlines)
            return headlines
    return []


def _load_finviz_news(ticker: str, max_items: int) -> list[ScrapedHeadline]:
    cached = _load_cache("finviz", ticker)
    if cached:
        return cached[:max_items]
    try:
        payload = _fetch_text(f"https://finviz.com/quote.ashx?t={urllib.parse.quote(ticker.upper())}")
    except Exception:
        return []

    parser = _FinvizNewsParser()
    parser.feed(payload)
    headlines: list[ScrapedHeadline] = []
    today = datetime.now().date().isoformat()
    for row in parser.rows:
        timestamp = row[0]["text"].strip()
        title = row[1]["text"].strip()
        if not title:
            continue
        published_at = timestamp or today
        if re.fullmatch(r"\d{1,2}:\d{2}(AM|PM)", published_at, flags=re.IGNORECASE):
            published_at = f"{today} {published_at}"
        headlines.append(
            ScrapedHeadline(
                title=title,
                summary=title,
                source="Finviz",
                published_at=published_at,
                url=row[1]["url"],
            )
        )
        if len(headlines) >= max_items:
            break
    if headlines:
        _save_cache("finviz", ticker, headlines)
    return headlines


def scrape_public_headlines(ticker: str, max_items: int = 3) -> list[NewsItem]:
    """Fetch a few public headlines from sites a human would typically read."""
    if os.getenv("NEWS_SCRAPER_ENABLED", "true").strip().lower() in {"0", "false", "no"}:
        return []

    provider = os.getenv("NEWS_SCRAPER_PROVIDER", "auto").strip().lower()
    scraped: list[ScrapedHeadline]
    if provider == "yahoo":
        scraped = _load_yahoo_rss(ticker, max_items)
    elif provider == "finviz":
        scraped = _load_finviz_news(ticker, max_items)
    else:
        scraped = _load_yahoo_rss(ticker, max_items)
        if not scraped:
            scraped = _load_finviz_news(ticker, max_items)

    return [
        NewsItem(
            title=item.title,
            summary=item.summary,
            source=item.source,
            published_at=item.published_at,
            url=item.url,
        )
        for item in scraped[:max_items]
    ]
