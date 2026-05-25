"""
scrapers/catalyst_scraper.py
THREE catalyst sources combined:
  1. yfinance earnings calendar (already installed)
  2. SEC EDGAR 8-K filings (material events — contracts, leadership, etc.)
  3. Earnings Whispers scrape (expected surprise direction)

Final score = best signal across all three sources.
"""

import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import yfinance as yf
import logging
import time
from config import CATALYST_LOOKAHEAD_DAYS

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
EDGAR_HEADERS = {"User-Agent": "EarlyMover research@gmail.com"}


# ── SOURCE 1: yfinance Earnings Calendar ─────────────────────────────────────

def get_earnings_date(ticker: str) -> dict | None:
    """Get next earnings date via yfinance."""
    try:
        stock = yf.Ticker(ticker)
        cal = stock.calendar

        if cal is None:
            return None

        # Handle both DataFrame and dict formats (yfinance changed this)
        if hasattr(cal, "empty") and cal.empty:
            return None

        earnings_date = None

        if isinstance(cal, dict):
            earnings_date = cal.get("Earnings Date")
            if isinstance(earnings_date, list) and earnings_date:
                earnings_date = earnings_date[0]
        elif hasattr(cal, "columns") and "Earnings Date" in cal.columns:
            earnings_date = cal["Earnings Date"].iloc[0]
        elif hasattr(cal, "index") and "Earnings Date" in cal.index:
            earnings_date = cal.loc["Earnings Date"].iloc[0]

        if earnings_date is None or (hasattr(earnings_date, '__class__') and 'NaT' in str(earnings_date)):
            return None

        earnings_dt = pd.to_datetime(earnings_date)
        if hasattr(earnings_dt, 'tzinfo') and earnings_dt.tzinfo:
            earnings_dt = earnings_dt.tz_localize(None)

        days_until = (earnings_dt - pd.Timestamp.now()).days

        if 0 <= days_until <= CATALYST_LOOKAHEAD_DAYS:
            return {
                "type": "Earnings",
                "date": earnings_dt.strftime("%Y-%m-%d"),
                "days_until": int(days_until),
                "urgency": "HIGH" if days_until <= 14 else "MEDIUM",
                "source": "yfinance",
            }
    except Exception as e:
        logger.debug(f"yfinance earnings failed for {ticker}: {e}")
    return None


# ── SOURCE 2: SEC EDGAR 8-K Filings ──────────────────────────────────────────

def get_recent_8k_filings(ticker: str) -> list[dict]:
    """
    Pull recent 8-K filings from SEC EDGAR for a ticker.
    8-Ks are material events: earnings releases, contracts, leadership changes,
    acquisitions, FDA decisions — all the catalysts we care about.
    """
    end_date = datetime.today()
    start_date = end_date - timedelta(days=CATALYST_LOOKAHEAD_DAYS)

    try:
        resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={
                "q": f'"{ticker}"',
                "forms": "8-K",
                "dateRange": "custom",
                "startdt": start_date.strftime("%Y-%m-%d"),
                "enddt": end_date.strftime("%Y-%m-%d"),
            },
            headers=EDGAR_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])

        events = []
        for hit in hits[:5]:
            source = hit.get("_source", {})
            file_date = source.get("file_date", "")
            entity = source.get("entity_name", ticker)
            description = source.get("period_of_report", "")

            if file_date:
                try:
                    filed_dt = datetime.strptime(file_date[:10], "%Y-%m-%d")
                    days_ago = (datetime.today() - filed_dt).days
                    events.append({
                        "type": "8-K Filing",
                        "date": file_date[:10],
                        "days_until": -days_ago,  # negative = already filed
                        "days_ago": days_ago,
                        "entity": entity,
                        "urgency": "HIGH" if days_ago <= 7 else "MEDIUM",
                        "source": "SEC EDGAR 8-K",
                    })
                except Exception:
                    pass

        return events

    except Exception as e:
        logger.debug(f"8-K lookup failed for {ticker}: {e}")
        return []


def score_8k_signal(ticker: str) -> float:
    """
    Score based on recent 8-K activity.
    Recent 8-K = material event happened = catalyst signal.
    """
    filings = get_recent_8k_filings(ticker)
    if not filings:
        return 0.0
    # Most recent filing gets the score
    most_recent = min(filings, key=lambda x: x.get("days_ago", 999))
    days_ago = most_recent.get("days_ago", 30)
    # Filed today = 1.0, filed 30 days ago = 0.0
    score = max(0.0, 1.0 - (days_ago / 30))
    return round(score, 3)


# ── SOURCE 3: Earnings Whispers ───────────────────────────────────────────────

def get_earnings_whispers(ticker: str) -> dict | None:
    """
    Scrape earningswhispers.com for upcoming earnings + whisper direction.
    Whisper numbers often indicate expected surprise direction.
    """
    try:
        url = f"https://www.earningswhispers.com/stocks/{ticker.lower()}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        # Find earnings date
        date_el = soup.find("div", id="epsdatetime") or \
                  soup.find(class_=lambda x: x and "earnings-date" in x.lower() if x else False)

        # Find whisper vs estimate direction
        whisper_el = soup.find("div", id="whisper") or \
                     soup.find(class_=lambda x: x and "whisper" in x.lower() if x else False)

        estimate_el = soup.find("div", id="estimate") or \
                      soup.find(class_=lambda x: x and "estimate" in x.lower() if x else False)

        if not date_el:
            return None

        date_text = date_el.get_text(strip=True)
        try:
            # Parse various date formats
            for fmt in ["%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"]:
                try:
                    earnings_dt = datetime.strptime(date_text[:12], fmt)
                    break
                except Exception:
                    continue
            else:
                return None

            days_until = (earnings_dt - datetime.now()).days
            if not (0 <= days_until <= CATALYST_LOOKAHEAD_DAYS):
                return None

            # Whisper beat signal
            whisper_beat = False
            if whisper_el and estimate_el:
                try:
                    whisper_val = float(whisper_el.get_text(strip=True).replace("$", ""))
                    estimate_val = float(estimate_el.get_text(strip=True).replace("$", ""))
                    whisper_beat = whisper_val > estimate_val
                except Exception:
                    pass

            return {
                "type": "Earnings (Whisper)",
                "date": earnings_dt.strftime("%Y-%m-%d"),
                "days_until": days_until,
                "whisper_beat_expected": whisper_beat,
                "urgency": "HIGH" if days_until <= 14 else "MEDIUM",
                "source": "EarningsWhispers",
            }

        except Exception:
            return None

    except Exception as e:
        logger.debug(f"EarningsWhispers failed for {ticker}: {e}")
        return None


# ── COMBINED SCORING ──────────────────────────────────────────────────────────

def get_all_catalysts(ticker: str) -> list[dict]:
    """
    Pull catalysts from ALL three sources for a ticker.
    Returns combined deduplicated list.
    """
    catalysts = []

    # Source 1: yfinance earnings
    earnings = get_earnings_date(ticker)
    if earnings:
        catalysts.append(earnings)

    # Source 2: SEC 8-K filings
    filings = get_recent_8k_filings(ticker)
    catalysts.extend(filings[:2])  # Max 2 most recent 8-Ks

    # Source 3: Earnings Whispers
    whisper = get_earnings_whispers(ticker)
    if whisper:
        # Only add if not duplicate of yfinance earnings
        existing_dates = [c.get("date") for c in catalysts]
        if whisper["date"] not in existing_dates:
            catalysts.append(whisper)

    return catalysts


def score_catalyst_signal(ticker: str, fda_df: pd.DataFrame | None = None) -> float:
    """
    Returns 0.0–1.0 combined catalyst score from all three sources.
    """
    scores = []

    # yfinance earnings
    earnings = get_earnings_date(ticker)
    if earnings:
        days = earnings.get("days_until", CATALYST_LOOKAHEAD_DAYS)
        scores.append(max(0, 1.0 - (days / CATALYST_LOOKAHEAD_DAYS) * 0.9))

    # 8-K recent filing
    eight_k_score = score_8k_signal(ticker)
    if eight_k_score > 0:
        scores.append(eight_k_score)

    # Earnings Whispers
    whisper = get_earnings_whispers(ticker)
    if whisper:
        days = whisper.get("days_until", CATALYST_LOOKAHEAD_DAYS)
        w_score = max(0, 1.0 - (days / CATALYST_LOOKAHEAD_DAYS) * 0.9)
        # Bonus if whisper expects a beat
        if whisper.get("whisper_beat_expected"):
            w_score = min(w_score * 1.25, 1.0)
        scores.append(w_score)

    # FDA calendar (legacy support)
    if fda_df is not None and not fda_df.empty:
        fda_rows = fda_df[fda_df["ticker"] == ticker] if "ticker" in fda_df.columns else pd.DataFrame()
        for _, row in fda_rows.iterrows():
            days = row.get("days_until", CATALYST_LOOKAHEAD_DAYS)
            scores.append(min(max(0, 1.0 - (days / CATALYST_LOOKAHEAD_DAYS) * 0.9) * 1.2, 1.0))

    return round(max(scores), 3) if scores else 0.0


def get_catalysts_for_ticker(ticker: str, fda_df: pd.DataFrame | None = None) -> list[dict]:
    """Wrapper for backwards compatibility with scoring engine."""
    return get_all_catalysts(ticker)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing all catalyst sources...")
    ticker = "VITL"
    print(f"\nyfinance: {get_earnings_date(ticker)}")
    print(f"\n8-K filings: {get_recent_8k_filings(ticker)}")
    print(f"\nEarnings Whispers: {get_earnings_whispers(ticker)}")
    print(f"\nCombined score: {score_catalyst_signal(ticker)}")
    print(f"\nAll catalysts: {get_all_catalysts(ticker)}")