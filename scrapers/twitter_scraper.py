"""
scrapers/twitter_scraper.py
Scrapes $TICKER cashtag mentions from X/Twitter public search.
Uses snscrape — no API key needed.
Install: pip install snscrape
Falls back to 0.0 gracefully if snscrape is unavailable.
"""

import pandas as pd
from datetime import datetime, timedelta
import logging
import time

logger = logging.getLogger(__name__)

POSITIVE_KW = ["bull", "buy", "long", "moon", "breakout", "calls", "squeeze", "upside", "rocket"]
NEGATIVE_KW = ["bear", "sell", "short", "puts", "dump", "crash", "avoid", "scam"]


def scrape_cashtag_mentions(ticker: str, days_back: int = 7) -> dict:
    """Scrape recent $TICKER mentions from X/Twitter."""
    try:
        import snscrape.modules.twitter as sntwitter

        query = f"${ticker} lang:en"
        start_date = datetime.utcnow() - timedelta(days=days_back)
        mentions, positive, negative = 0, 0, 0

        for tweet in sntwitter.TwitterSearchScraper(query).get_items():
            if tweet.date.replace(tzinfo=None) < start_date:
                break
            if mentions >= 200:
                break
            mentions += 1
            text = tweet.rawContent.lower()
            if any(kw in text for kw in POSITIVE_KW):
                positive += 1
            if any(kw in text for kw in NEGATIVE_KW):
                negative += 1

        total = positive + negative
        bullish_pct = (positive / total * 100) if total > 0 else 50.0
        return {"ticker": ticker, "mentions": mentions, "bullish_pct": round(bullish_pct, 1)}

    except ImportError:
        logger.warning("snscrape not installed — run: pip install snscrape")
        return {"ticker": ticker, "mentions": 0, "bullish_pct": 50.0}
    except Exception as e:
        logger.debug(f"Twitter scrape failed for {ticker}: {e}")
        return {"ticker": ticker, "mentions": 0, "bullish_pct": 50.0}


def score_twitter_signal(ticker: str, twitter_df: pd.DataFrame | None = None) -> float:
    if twitter_df is not None and not twitter_df.empty:
        row = twitter_df[twitter_df["ticker"] == ticker]
        if not row.empty:
            return float(row.iloc[0]["twitter_score"])
    result = scrape_cashtag_mentions(ticker)
    volume_score = min(result["mentions"] / 100, 1.0)
    sentiment_score = max((result["bullish_pct"] - 40) / 60, 0.0)
    return round((volume_score * 0.6) + (sentiment_score * 0.4), 3)


def get_twitter_scores(universe: list[str]) -> pd.DataFrame:
    rows = []
    for ticker in universe:
        result = scrape_cashtag_mentions(ticker)
        volume_score = min(result["mentions"] / 100, 1.0)
        sentiment_score = max((result["bullish_pct"] - 40) / 60, 0.0)
        rows.append({"ticker": ticker, "twitter_mentions": result["mentions"],
                     "twitter_bullish_pct": result["bullish_pct"],
                     "twitter_score": round((volume_score * 0.6) + (sentiment_score * 0.4), 3)})
        time.sleep(1.0)
    return pd.DataFrame(rows).sort_values("twitter_score", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(scrape_cashtag_mentions("VITL"))