"""
finance.py — up-to-date financial market news via free APIs (advanced level).

Primary: Finnhub (free 60 req/min) for company news and quotes.
Fallback: yfinance (no key) for prices.

Exposed both as plain functions and as a LangChain @tool for the agents.
"""

import os
from datetime import date, timedelta

import requests


def company_news(ticker: str, days: int = 7) -> list[dict]:
    """Recent headlines for a ticker from Finnhub. Returns [{headline, summary, url}]."""
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        raise RuntimeError("No FINNHUB_API_KEY found in environment / .env")
    to = date.today()
    frm = to - timedelta(days=days)
    r = requests.get(
        "https://finnhub.io/api/v1/company-news",
        params={"symbol": ticker, "from": frm.isoformat(),
                "to": to.isoformat(), "token": key},
        timeout=30,
    )
    r.raise_for_status()
    news = r.json()[:5]
    return [{"headline": n.get("headline", ""), "summary": n.get("summary", "")[:200],
             "url": n.get("url", "")} for n in news]


def quote(ticker: str) -> dict:
    """Current price snapshot. Tries Finnhub, falls back to yfinance."""
    key = os.getenv("FINNHUB_API_KEY")
    if key:
        r = requests.get("https://finnhub.io/api/v1/quote",
                        params={"symbol": ticker, "token": key}, timeout=30)
        if r.ok:
            d = r.json()
            return {"ticker": ticker, "price": d.get("c"), "change_pct": d.get("dp")}
    # Fallback: yfinance. fast_info exposes previous_close, so we can still
    # compute today's change% even without Finnhub.
    import yfinance as yf
    fast = yf.Ticker(ticker).fast_info
    price = getattr(fast, "last_price", None)
    prev = getattr(fast, "previous_close", None)
    change_pct = None
    if price is not None and prev:
        change_pct = (price - prev) / prev * 100
    return {"ticker": ticker, "price": price, "change_pct": change_pct,
            "currency": getattr(fast, "currency", "USD")}


def market_summary(ticker: str) -> str:
    """Human-readable market summary combining a quote and top headlines."""
    q = quote(ticker)
    price, change = q.get("price"), q.get("change_pct")
    cur = q.get("currency") or "USD"
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(cur, "")
    price_s = f"{sym}{price:,.2f}" if isinstance(price, (int, float)) else "n/d"
    if isinstance(change, (int, float)):
        change_s = f" ({change:+.2f}% hoy)"
    else:
        change_s = ""
    lines = [f"{ticker}: {price_s}{change_s}"]
    try:
        for n in company_news(ticker):
            lines.append(f"- {n['headline']}")
    except Exception:
        pass
    return "\n".join(lines)


def as_langchain_tool():
    """Return a LangChain StructuredTool wrapping market_summary, for agents."""
    from langchain_core.tools import tool

    @tool
    def financial_news(ticker: str) -> str:
        """Return a short market summary and recent headlines for a stock ticker (e.g. AAPL)."""
        return market_summary(ticker)

    return financial_news
