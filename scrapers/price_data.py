"""
scrapers/price_data.py
Pulls price, float, short interest, volume, and fundamentals via yfinance.
Used both for initial universe screening and per-stock signal scoring.
"""

import yfinance as yf
import pandas as pd
import logging
from config import MIN_PRICE, MAX_PRICE, MAX_MARKET_CAP, MIN_VOLUME, MAX_FLOAT_SHARES

logger = logging.getLogger(__name__)


def get_stock_info(ticker: str) -> dict | None:
    """
    Pull full stock info dict for a single ticker.
    Returns None if data is unavailable or stock doesn't meet basic criteria.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or "currentPrice" not in info:
            return None

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price:
            return None

        return {
            "ticker": ticker,
            "price": price,
            "market_cap": info.get("marketCap"),
            "float_shares": info.get("floatShares"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "short_ratio": info.get("shortRatio"),              # Days to cover
            "short_percent_float": info.get("shortPercentOfFloat"),  # % of float shorted
            "avg_volume": info.get("averageVolume"),
            "volume": info.get("volume"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "pe_ratio": info.get("trailingPE"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "company_name": info.get("longName") or info.get("shortName"),
            "description": (info.get("longBusinessSummary") or "")[:300],
        }

    except Exception as e:
        logger.debug(f"Failed to get info for {ticker}: {e}")
        return None


def get_price_history(ticker: str, period: str = "3mo") -> pd.DataFrame:
    """
    Returns OHLCV price history DataFrame.
    period options: 1mo, 3mo, 6mo, 1y
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        return hist
    except Exception as e:
        logger.debug(f"Failed to get history for {ticker}: {e}")
        return pd.DataFrame()


def calculate_momentum(ticker: str) -> float:
    """
    Simple momentum score based on price action in last 30 days.
    Returns 0.0–1.0
    """
    hist = get_price_history(ticker, period="3mo")
    if hist.empty or len(hist) < 20:
        return 0.0

    try:
        # 30-day return
        month_return = (hist["Close"].iloc[-1] - hist["Close"].iloc[-21]) / hist["Close"].iloc[-21]

        # Volume surge — is current volume elevated vs 20-day avg?
        avg_vol = hist["Volume"].iloc[-21:-1].mean()
        cur_vol = hist["Volume"].iloc[-1]
        vol_surge = cur_vol / avg_vol if avg_vol > 0 else 1.0

        # RSI (simple)
        delta = hist["Close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, float("inf"))
        rsi = 100 - (100 / (1 + rs))
        current_rsi = float(rsi.iloc[-1]) if not rsi.empty else 50.0

        # Score components
        momentum_score = min(max(month_return * 2, 0), 1.0)   # 50% monthly return = max
        vol_score = min((vol_surge - 1) / 2, 1.0)             # 3x volume = max
        rsi_score = (current_rsi - 30) / 70 if current_rsi > 30 else 0.0  # RSI 30–100 → 0–1

        # Weight: momentum 40%, volume 30%, RSI 30%
        final = (momentum_score * 0.4) + (vol_score * 0.3) + (rsi_score * 0.3)
        return round(min(max(final, 0.0), 1.0), 3)

    except Exception as e:
        logger.debug(f"Momentum calc failed for {ticker}: {e}")
        return 0.0


def score_short_squeeze(ticker: str, info: dict | None = None) -> float:
    """
    Returns 0.0–1.0 short squeeze potential score.
    High short interest + low float + rising price = squeeze conditions.
    """
    if info is None:
        info = get_stock_info(ticker)
    if not info:
        return 0.0

    short_pct = info.get("short_percent_float") or 0.0
    float_shares = info.get("float_shares") or float("inf")
    short_ratio = info.get("short_ratio") or 0.0

    # Score short interest (>20% float = high, >40% = very high)
    si_score = min(short_pct / 0.4, 1.0) if short_pct else 0.0

    # Score float (lower is better for squeezes — under 10M is ideal)
    float_score = 1.0 if float_shares < 10_000_000 else \
                  0.7 if float_shares < 20_000_000 else \
                  0.4 if float_shares < 50_000_000 else 0.1

    # Days to cover (short ratio) — higher = harder to exit shorts
    days_score = min(short_ratio / 10, 1.0) if short_ratio else 0.0

    final = (si_score * 0.5) + (float_score * 0.3) + (days_score * 0.2)
    return round(min(max(final, 0.0), 1.0), 3)


def meets_screen_criteria(info: dict) -> bool:
    """
    Returns True if a stock passes the basic screener filters.
    """
    price = info.get("price", 0)
    market_cap = info.get("market_cap", float("inf"))
    avg_volume = info.get("avg_volume", 0)
    float_shares = info.get("float_shares", float("inf"))

    return (
        MIN_PRICE <= price <= MAX_PRICE
        and (market_cap or 0) <= MAX_MARKET_CAP
        and (avg_volume or 0) >= MIN_VOLUME
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ticker = "SNDX"  # Example small cap
    info = get_stock_info(ticker)
    print(f"Info: {info}")
    print(f"Momentum: {calculate_momentum(ticker)}")
    print(f"Short squeeze: {score_short_squeeze(ticker, info)}")
