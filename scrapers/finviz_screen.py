"""
scrapers/finviz_screen.py
Pulls a filtered universe of small-cap stocks from Finviz.
Uses free public screener — no API key needed.
"""

import requests
import pandas as pd
from bs4 import BeautifulSoup
import logging
import time
from config import MIN_PRICE, MAX_PRICE

logger = logging.getLogger(__name__)

FINVIZ_URL = "https://finviz.com/screener.ashx"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

FINVIZ_FILTERS = "cap_smallover,sh_price_u20,sh_price_o5,sh_avgvol_o100"


def get_screener_universe(max_stocks: int = 200) -> list[str]:
    tickers = []
    row = 1

    while len(tickers) < max_stocks:
        params = {
            "v": "111",
            "f": FINVIZ_FILTERS,
            "r": row,
            "o": "-change",
        }

        try:
            resp = requests.get(FINVIZ_URL, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "lxml")
            batch = []

            # Method 1: anchor tags with screener-link-primary class
            links = soup.find_all("a", class_="screener-link-primary")
            for link in links:
                text = link.text.strip()
                if text and 1 < len(text) <= 5 and text.isupper():
                    batch.append(text)

            # Method 2: look inside styled-row table rows
            if not batch:
                for tr in soup.find_all("tr", class_="styled-row"):
                    tds = tr.find_all("td")
                    if tds:
                        candidate = tds[1].get_text(strip=True) if len(tds) > 1 else ""
                        if candidate and candidate.isupper() and len(candidate) <= 5:
                            batch.append(candidate)

            if not batch:
                logger.warning("Finviz: no tickers found — may be blocked or layout changed")
                break

            batch = list(dict.fromkeys(batch))
            tickers.extend(batch)
            logger.info(f"Finviz: fetched {len(tickers)} tickers so far...")

            if len(batch) < 15:
                break

            row += 20
            time.sleep(2.0)

        except Exception as e:
            logger.error(f"Finviz scrape failed at row {row}: {e}")
            break

    unique = list(dict.fromkeys(tickers))[:max_stocks]
    logger.info(f"Finviz universe: {len(unique)} stocks")
    return unique


def get_fallback_universe() -> list[str]:
    return [
        # Crypto / Digital Assets
        "MARA", "RIOT", "CIFR", "BTBT", "CLSK", "IREN", "CORZ",
        # Biotech / Healthcare
        "SNDX", "ACMR", "CLOV", "NVAX", "OCGN", "ATOS", "NKTR",
        # Tech / Software
        "PAYO", "MAXN", "MAPS", "GETY",
        # Energy
        "TELL", "AMPY", "REI", "INDO", "IMPP",
        # EV / Clean Energy
        "BLNK", "CHPT", "PTRA", "GOEV",
        # Retail / Consumer
        "PRTY", "EXPR", "VZIO",
        # Finance / Fintech
        "PFIS", "AROW", "UWMC", "CURO",
        # High short interest / squeeze setups
        "SPCE", "WKHS", "NKLA",
    ]


def get_universe(use_fallback: bool = False) -> list[str]:
    if use_fallback:
        return get_fallback_universe()

    universe = get_screener_universe()

    if len(universe) < 10:
        logger.warning("Finviz returned too few stocks, using fallback universe")
        return get_fallback_universe()

    return universe


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tickers = get_universe()
    print(f"Universe ({len(tickers)} stocks): {tickers[:20]}")