"""
scrapers/news_scraper.py
Pulls recent headlines for a ticker from NewsAPI.
Sentiment is scored by Claude Haiku in the ai/ module.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import logging
from config import NEWS_API_KEY, REDDIT_LOOKBACK_DAYS

logger = logging.getLogger(__name__)

NEWSAPI_URL = "https://newsapi.org/v2/everything"


def get_headlines(ticker: str, company_name: str = "", days_back: int = 7) -> list[dict]:
    """
    Pull recent news headlines for a ticker from NewsAPI.
    Returns list of article dicts with title, description, url, publishedAt.
    """
    if not NEWS_API_KEY:
        logger.warning("NEWS_API_KEY not set — skipping news scrape")
        return []

    from_date = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    # Build query — strict financial context to avoid celebrity/entertainment results
    # Use company name in quotes for exact match, add stock/finance context
    if company_name:
        # Exact company name match + financial context keywords
        query = f'"{company_name}" AND (stock OR shares OR earnings OR revenue OR SEC OR investor)'
    else:
        query = f'"{ticker}" stock'

    try:
        resp = requests.get(
            NEWSAPI_URL,
            params={
                "q": query,
                "from": from_date,
                "sortBy": "relevancy",
                "language": "en",
                "pageSize": 10,
                "apiKey": NEWS_API_KEY,
                "domains": (
                    "reuters.com,bloomberg.com,wsj.com,cnbc.com,marketwatch.com,"
                    "seekingalpha.com,fool.com,benzinga.com,businesswire.com,"
                    "prnewswire.com,globenewswire.com,sec.gov,finance.yahoo.com"
                ),
            },
            timeout=10,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])

        # Clean up fields
        # Filter out non-financial articles
        financial_keywords = [
            ticker.lower(), "stock", "share", "earning", "revenue", "sec",
            "investor", "quarter", "fiscal", "analyst", "market", "trade",
            company_name.lower()[:8] if company_name else ticker.lower()
        ]

        filtered = []
        for a in articles:
            title = a.get("title", "").lower()
            desc = (a.get("description", "") or "").lower()
            combined = title + " " + desc

            # Skip removed articles
            if "[Removed]" in a.get("title", ""):
                continue

            # Must contain at least one financial keyword
            if any(kw in combined for kw in financial_keywords if len(kw) > 2):
                filtered.append({
                    "ticker": ticker,
                    "title": a.get("title", ""),
                    "description": a.get("description", ""),
                    "source": a.get("source", {}).get("name", ""),
                    "url": a.get("url", ""),
                    "published_at": a.get("publishedAt", ""),
                })

        return filtered

    except Exception as e:
        logger.error(f"NewsAPI failed for {ticker}: {e}")
        return []


def get_headlines_batch(stocks: list[dict], days_back: int = 7) -> dict[str, list[dict]]:
    """
    Pull headlines for a list of stocks.
    stocks = [{"ticker": "AAPL", "company_name": "Apple Inc"}, ...]
    Returns {ticker: [articles]}
    """
    results = {}
    for stock in stocks:
        ticker = stock.get("ticker", "")
        name = stock.get("company_name", "")
        results[ticker] = get_headlines(ticker, name, days_back)
        logger.debug(f"{ticker}: {len(results[ticker])} articles found")

    return results


def format_headlines_for_ai(ticker: str, articles: list[dict]) -> str:
    """
    Format headlines into a compact string for Claude Haiku to analyze.
    """
    if not articles:
        return f"No recent news found for {ticker}."

    lines = [f"Recent news for ${ticker}:"]
    for i, a in enumerate(articles[:5], 1):
        lines.append(f"{i}. [{a['source']}] {a['title']}")
        if a.get("description"):
            lines.append(f"   {a['description'][:100]}...")

    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    articles = get_headlines("MARA", "Marathon Digital Holdings")
    print(f"Found {len(articles)} articles")
    print(format_headlines_for_ai("MARA", articles))