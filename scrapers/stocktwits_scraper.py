"""
scrapers/stocktwits_scraper.py
Pulls ticker sentiment and message volume from StockTwits.
Free public API — no key needed for basic symbol streams.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import logging
import time

logger = logging.getLogger(__name__)
STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def get_ticker_stream(ticker: str) -> dict:
    try:
        resp = requests.get(STOCKTWITS_URL.format(ticker=ticker), headers=HEADERS, timeout=10)
        if resp.status_code == 429:
            time.sleep(10)
            resp = requests.get(STOCKTWITS_URL.format(ticker=ticker), headers=HEADERS, timeout=10)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug(f"StockTwits failed for {ticker}: {e}")
        return {}


def parse_sentiment(stream_data: dict) -> dict:
    messages = stream_data.get("messages", [])
    if not messages:
        return {"bullish": 0, "bearish": 0, "total": 0, "bullish_pct": 50.0, "volume": 0}

    bullish, bearish, total = 0, 0, len(messages)
    cutoff = datetime.utcnow() - timedelta(days=7)

    for msg in messages:
        try:
            msg_time = datetime.strptime(msg.get("created_at", "")[:19], "%Y-%m-%dT%H:%M:%S")
            if msg_time < cutoff:
                continue
        except Exception:
            pass
        sentiment = msg.get("entities", {}).get("sentiment", {})
        if sentiment:
            if sentiment.get("basic") == "Bullish":
                bullish += 1
            elif sentiment.get("basic") == "Bearish":
                bearish += 1

    sentiment_total = bullish + bearish
    bullish_pct = (bullish / sentiment_total * 100) if sentiment_total > 0 else 50.0
    return {"bullish": bullish, "bearish": bearish, "total": total,
            "bullish_pct": round(bullish_pct, 1), "volume": total}


def score_stocktwits_signal(ticker: str, st_df: pd.DataFrame | None = None) -> float:
    if st_df is not None and not st_df.empty:
        row = st_df[st_df["ticker"] == ticker]
        if not row.empty:
            return float(row.iloc[0]["st_score"])
    stream = get_ticker_stream(ticker)
    if not stream:
        return 0.0
    s = parse_sentiment(stream)
    volume_score = min(s["volume"] / 50, 1.0)
    sentiment_score = max((s["bullish_pct"] - 40) / 60, 0.0)
    return round((volume_score * 0.6) + (sentiment_score * 0.4), 3)


def get_social_scores(universe: list[str]) -> pd.DataFrame:
    rows = []
    for ticker in universe:
        stream = get_ticker_stream(ticker)
        s = parse_sentiment(stream) if stream else {"volume": 0, "bullish_pct": 50.0}
        volume_score = min(s["volume"] / 50, 1.0)
        sentiment_score = max((s["bullish_pct"] - 40) / 60, 0.0)
        rows.append({"ticker": ticker, "st_volume": s["volume"],
                     "st_bullish_pct": s["bullish_pct"],
                     "st_score": round((volume_score * 0.6) + (sentiment_score * 0.4), 3)})
        time.sleep(0.5)
    return pd.DataFrame(rows).sort_values("st_score", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = get_ticker_stream("VITL")
    print(f"VITL: {parse_sentiment(result)}")