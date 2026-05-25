"""
scrapers/yahoo_scraper.py
Scrapes Yahoo Finance conversation/comment sections per ticker.
Free, no auth needed. Third social signal to complement StockTwits + Twitter.
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import logging
import time
import re

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

POSITIVE_KW = ["buy", "bull", "long", "moon", "breakout", "squeeze", "calls", "upside", "strong"]
NEGATIVE_KW = ["sell", "bear", "short", "puts", "dump", "avoid", "crash", "down"]


def get_yahoo_conversations(ticker: str) -> dict:
    """
    Pull recent conversation posts from Yahoo Finance for a ticker.
    Returns mention count and rough sentiment.
    """
    try:
        url = f"https://finance.yahoo.com/quote/{ticker}/community/"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        # Find comment/post containers
        posts = soup.find_all("div", attrs={"data-testid": "message-item"})
        if not posts:
            # Try alternate selectors
            posts = soup.find_all("li", class_=re.compile("comment|post|message", re.I))

        mentions = len(posts)
        positive, negative = 0, 0

        for post in posts:
            text = post.get_text(separator=" ").lower()
            if any(kw in text for kw in POSITIVE_KW):
                positive += 1
            if any(kw in text for kw in NEGATIVE_KW):
                negative += 1

        total = positive + negative
        bullish_pct = (positive / total * 100) if total > 0 else 50.0

        return {"ticker": ticker, "mentions": mentions,
                "bullish_pct": round(bullish_pct, 1), "source": "yahoo"}

    except Exception as e:
        logger.debug(f"Yahoo Finance scrape failed for {ticker}: {e}")
        return {"ticker": ticker, "mentions": 0, "bullish_pct": 50.0, "source": "yahoo"}


def score_yahoo_signal(ticker: str) -> float:
    result = get_yahoo_conversations(ticker)
    mentions = result["mentions"]
    bullish_pct = result["bullish_pct"]
    volume_score = min(mentions / 30, 1.0)   # Yahoo has lower volume than Twitter
    sentiment_score = max((bullish_pct - 40) / 60, 0.0)
    return round((volume_score * 0.6) + (sentiment_score * 0.4), 3)


def get_yahoo_scores(universe: list[str]) -> pd.DataFrame:
    rows = []
    for ticker in universe:
        result = get_yahoo_conversations(ticker)
        volume_score = min(result["mentions"] / 30, 1.0)
        sentiment_score = max((result["bullish_pct"] - 40) / 60, 0.0)
        rows.append({"ticker": ticker, "yahoo_mentions": result["mentions"],
                     "yahoo_bullish_pct": result["bullish_pct"],
                     "yahoo_score": round((volume_score * 0.6) + (sentiment_score * 0.4), 3)})
        time.sleep(1.0)
    return pd.DataFrame(rows).sort_values("yahoo_score", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(get_yahoo_conversations("VITL"))