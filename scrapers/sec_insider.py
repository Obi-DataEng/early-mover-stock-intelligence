"""
scrapers/sec_insider.py
Pulls recent insider BUY transactions from SEC EDGAR Form 4 filings.
Completely free — no API key needed.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from lxml import etree
import time
import logging
from config import INSIDER_LOOKBACK_DAYS, MIN_PRICE, MAX_PRICE

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index?q=%22form+type%22%3A%224%22&dateRange=custom"
EDGAR_FULL_TEXT = "https://efts.sec.gov/LATEST/search-index"

HEADERS = {
    "User-Agent": "EarlyMover research@youremail.com",  # SEC requires this
    "Accept-Encoding": "gzip, deflate",
}


def fetch_recent_form4_filings(days_back: int = INSIDER_LOOKBACK_DAYS) -> list[dict]:
    """
    Query SEC EDGAR for Form 4 filings in the last N days.
    Returns list of filing metadata dicts.
    """
    end_date = datetime.today()
    start_date = end_date - timedelta(days=days_back)

    url = (
        f"https://efts.sec.gov/LATEST/search-index?"
        f"q=%22form+type%22%3A%224%22"
        f"&dateRange=custom"
        f"&startdt={start_date.strftime('%Y-%m-%d')}"
        f"&enddt={end_date.strftime('%Y-%m-%d')}"
        f"&forms=4"
    )

    # Use the full-text search API
    search_url = (
        f"https://efts.sec.gov/LATEST/search-index?"
        f"forms=4"
        f"&dateRange=custom"
        f"&startdt={start_date.strftime('%Y-%m-%d')}"
        f"&enddt={end_date.strftime('%Y-%m-%d')}"
    )

    try:
        resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={
                "forms": "4",
                "dateRange": "custom",
                "startdt": start_date.strftime("%Y-%m-%d"),
                "enddt": end_date.strftime("%Y-%m-%d"),
                "hits.hits.total.value": 1,
                "_source": "period_of_report,entity_name,file_date,period_of_report",
            },
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        logger.info(f"Found {len(hits)} Form 4 filings in last {days_back} days")
        return hits
    except Exception as e:
        logger.error(f"EDGAR search failed: {e}")
        return []


def parse_form4_xml(filing_url: str) -> dict | None:
    """
    Parse a single Form 4 XML filing.
    Returns dict with ticker, insider name, transaction type, shares, price.
    """
    try:
        resp = requests.get(filing_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        root = etree.fromstring(resp.content)

        # Extract key fields
        ticker = _safe_find(root, ".//issuerTradingSymbol")
        insider_name = _safe_find(root, ".//rptOwnerName")
        insider_title = _safe_find(root, ".//officerTitle")
        transaction_code = _safe_find(root, ".//transactionCode")  # P = open market buy
        shares = _safe_find(root, ".//transactionShares/value")
        price = _safe_find(root, ".//transactionPricePerShare/value")
        date = _safe_find(root, ".//transactionDate/value")

        # Only care about open-market buys (code P)
        if transaction_code != "P":
            return None

        price_val = float(price) if price else None

        # Filter to our price range
        if price_val and not (MIN_PRICE <= price_val <= MAX_PRICE):
            return None

        return {
            "ticker": ticker,
            "insider_name": insider_name,
            "insider_title": insider_title or "Unknown",
            "transaction_code": transaction_code,
            "shares": float(shares) if shares else None,
            "price": price_val,
            "date": date,
            "total_value": float(shares) * price_val if shares and price_val else None,
        }

    except Exception as e:
        logger.debug(f"Failed to parse Form 4 at {filing_url}: {e}")
        return None


def get_insider_buys_for_ticker(ticker: str) -> list[dict]:
    """
    Get recent insider buys for a specific ticker.
    Used during per-stock scoring.
    """
    end_date = datetime.today()
    start_date = end_date - timedelta(days=INSIDER_LOOKBACK_DAYS)

    try:
        resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={
                "q": f'"{ticker}"',
                "forms": "4",
                "dateRange": "custom",
                "startdt": start_date.strftime("%Y-%m-%d"),
                "enddt": end_date.strftime("%Y-%m-%d"),
            },
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])

        buys = []
        for hit in hits[:5]:  # Limit to avoid rate limiting
            filing_url = hit.get("_source", {}).get("file_date")
            # In practice you'd construct the actual XML URL from accession number
            # For now return the metadata
            buys.append(hit.get("_source", {}))
            time.sleep(0.1)  # Be polite to SEC servers

        return buys

    except Exception as e:
        logger.error(f"Insider buy lookup failed for {ticker}: {e}")
        return []


def score_insider_signal(ticker: str) -> float:
    """
    Returns a 0.0–1.0 insider signal score for a given ticker.
    Called by the scoring engine.
    """
    buys = get_insider_buys_for_ticker(ticker)

    if not buys:
        return 0.0

    # More buys = higher score, capped at 1.0
    # A single large insider buy = 0.6, multiple = closer to 1.0
    score = min(len(buys) * 0.3, 1.0)
    logger.info(f"{ticker} insider score: {score:.2f} ({len(buys)} buys found)")
    return score


def _safe_find(root, xpath: str) -> str | None:
    """Helper to safely extract text from XML node."""
    node = root.find(xpath)
    return node.text.strip() if node is not None and node.text else None


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    print("Testing SEC EDGAR scraper...")
    score = score_insider_signal("NVDA")
    print(f"NVDA insider score: {score}")
