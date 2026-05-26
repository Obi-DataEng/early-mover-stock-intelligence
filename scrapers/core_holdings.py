"""
scrapers/core_holdings.py
Tracks core long-term ETF holdings separately from speculative picks.
Generates weekly auto-buy reminders for VOO, QQQ, SCHD etc.
These don't need signal scoring — just consistent weekly DCA.
"""

import sqlite3
import yfinance as yf
import pandas as pd
from datetime import datetime
import logging
from config import DB_PATH

logger = logging.getLogger(__name__)

# Your core ETF targets — edit these to match your goals
CORE_HOLDINGS = [
    {
        "ticker": "VOO",
        "name": "Vanguard S&P 500 ETF",
        "weekly_amount": 40.0,
        "description": "Tracks the S&P 500 — 500 biggest US companies. The foundation of any long-term portfolio.",
        "why": "Historically returns ~10% per year over any 20-year period. Warren Buffett recommends this for most people.",
    },
    {
        "ticker": "SCHD",
        "name": "Schwab US Dividend Equity ETF",
        "weekly_amount": 0.0,   # Set to >0 when ready to add dividends
        "description": "High-quality dividend-paying US stocks. Currently yields ~3.5% annually.",
        "why": "Dividends that get reinvested compound powerfully over 20-30 years.",
    },
]


def init_core_table():
    """Create core_holdings tracking table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS core_holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            price REAL,
            amount_invested REAL,
            shares REAL,
            total_shares REAL,
            total_invested REAL,
            current_value REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def get_current_price(ticker: str) -> float:
    """Get current price for an ETF."""
    try:
        stock = yf.Ticker(ticker)
        price = stock.fast_info.get("lastPrice")
        if not price:
            price = stock.info.get("currentPrice") or stock.info.get("regularMarketPrice")
        return float(price) if price else 0.0
    except Exception as e:
        logger.debug(f"Price fetch failed for {ticker}: {e}")
        return 0.0


def get_core_summary() -> list[dict]:
    """
    Get current state of all core holdings.
    Returns list of dicts with ticker, total invested, current value, gain/loss.
    """
    init_core_table()
    conn = sqlite3.connect(DB_PATH)

    results = []
    for holding in CORE_HOLDINGS:
        ticker = holding["ticker"]
        weekly_amount = holding["weekly_amount"]

        try:
            df = pd.read_sql(
                "SELECT * FROM core_holdings WHERE ticker=? ORDER BY purchase_date DESC",
                conn, params=(ticker,)
            )
        except Exception:
            df = pd.DataFrame()

        current_price = get_current_price(ticker)
        total_shares = float(df["shares"].sum()) if not df.empty else 0.0
        total_invested = float(df["amount_invested"].sum()) if not df.empty else 0.0
        current_value = total_shares * current_price if current_price > 0 else 0.0
        gain_loss = current_value - total_invested
        gain_loss_pct = (gain_loss / total_invested * 100) if total_invested > 0 else 0.0

        shares_this_week = round(weekly_amount / current_price, 4) if current_price > 0 else 0

        results.append({
            "ticker": ticker,
            "name": holding["name"],
            "weekly_amount": weekly_amount,
            "description": holding["description"],
            "why": holding["why"],
            "current_price": round(current_price, 2),
            "total_shares": round(total_shares, 4),
            "total_invested": round(total_invested, 2),
            "current_value": round(current_value, 2),
            "gain_loss": round(gain_loss, 2),
            "gain_loss_pct": round(gain_loss_pct, 1),
            "shares_this_week": shares_this_week,
            "weeks_invested": len(df) if not df.empty else 0,
        })

    conn.close()
    return results


def record_core_purchase(ticker: str, amount: float, price: float):
    """
    Record a core ETF purchase.
    Call this manually after you actually buy, or automate with Schwab API.
    """
    init_core_table()
    shares = round(amount / price, 6) if price > 0 else 0

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get running totals
    row = cur.execute(
        "SELECT SUM(shares), SUM(amount_invested) FROM core_holdings WHERE ticker=?",
        (ticker,)
    ).fetchone()
    prev_shares = row[0] or 0
    prev_invested = row[1] or 0

    total_shares = prev_shares + shares
    total_invested = prev_invested + amount
    current_value = total_shares * price

    cur.execute("""
        INSERT INTO core_holdings
        (purchase_date, ticker, price, amount_invested, shares, total_shares, total_invested, current_value)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.today().strftime("%Y-%m-%d"),
        ticker, price, amount, shares,
        total_shares, total_invested, current_value
    ))

    conn.commit()
    conn.close()
    logger.info(f"Recorded core purchase: {ticker} ${amount} @ ${price} = {shares} shares")


def get_portfolio_projection(
    weekly_amount: float = 40.0,
    annual_return: float = 0.10,
    years: int = 30,
) -> dict:
    """
    Project portfolio value based on weekly DCA contributions.
    Uses compound interest formula with weekly contributions.
    """
    weekly_rate = annual_return / 52
    weeks = years * 52

    # Future value of weekly contributions (annuity formula)
    if weekly_rate > 0:
        future_value = weekly_amount * (((1 + weekly_rate) ** weeks - 1) / weekly_rate)
    else:
        future_value = weekly_amount * weeks

    total_contributed = weekly_amount * weeks

    return {
        "years": years,
        "weekly_amount": weekly_amount,
        "total_contributed": round(total_contributed, 2),
        "projected_value": round(future_value, 2),
        "growth": round(future_value - total_contributed, 2),
        "multiplier": round(future_value / total_contributed, 1),
    }


def get_weekly_core_reminder() -> dict:
    """
    Main function — returns everything needed for the email core buy section.
    """
    init_core_table()
    holdings = get_core_summary()
    active = [h for h in holdings if h["weekly_amount"] > 0]

    # Total weekly core investment
    total_weekly = sum(h["weekly_amount"] for h in active)
    total_core_value = sum(h["current_value"] for h in holdings)
    total_core_invested = sum(h["total_invested"] for h in holdings)

    # 30-year projection for VOO contribution
    voo_projection = get_portfolio_projection(
        weekly_amount=next((h["weekly_amount"] for h in active if h["ticker"] == "VOO"), 40),
        annual_return=0.10,
        years=30,
    )

    return {
        "holdings": holdings,
        "active_holdings": active,
        "total_weekly": total_weekly,
        "total_core_value": round(total_core_value, 2),
        "total_core_invested": round(total_core_invested, 2),
        "total_gain_loss": round(total_core_value - total_core_invested, 2),
        "projection_30yr": voo_projection,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Core Holdings Summary")
    print("=" * 40)
    reminder = get_weekly_core_reminder()

    for h in reminder["holdings"]:
        print(f"\n{h['ticker']} — {h['name']}")
        print(f"  Price: ${h['current_price']}")
        print(f"  Weekly buy: ${h['weekly_amount']}")
        print(f"  Shares this week: {h['shares_this_week']}")
        print(f"  Total held: {h['total_shares']} shares (${h['current_value']})")

    proj = reminder["projection_30yr"]
    print(f"\n30-Year Projection (${proj['weekly_amount']}/week @ 10%):")
    print(f"  You contribute: ${proj['total_contributed']:,.0f}")
    print(f"  Projected value: ${proj['projected_value']:,.0f}")
    print(f"  Market grows it {proj['multiplier']}x")