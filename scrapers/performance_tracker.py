"""
scrapers/performance_tracker.py
Tracks weekly pick performance against actual price movement.
Records entry prices, checks current prices, calculates P&L.
Updates the database every Monday before new picks are generated.
"""

import sqlite3
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging
from config import DB_PATH

logger = logging.getLogger(__name__)


def record_new_picks(picks: list[dict], run_date: str):
    """
    Record this week's picks into performance_tracking table at entry price.
    Called right after picks are generated.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for pick in picks:
        ticker = pick["ticker"]
        entry_price = pick["price"]
        position_size = pick["position_size"]
        price_target = pick["price_target"]
        stop_loss = pick["stop_loss"]
        shares = round(position_size / entry_price, 4) if entry_price > 0 else 0

        # Check if already recorded for this week
        existing = cur.execute(
            "SELECT id FROM performance_tracking WHERE ticker=? AND pick_date=?",
            (ticker, run_date)
        ).fetchone()

        if not existing:
            cur.execute("""
                INSERT INTO performance_tracking
                (pick_date, ticker, entry_price, current_price, price_target,
                 stop_loss, position_size, shares, pnl_dollar, pnl_pct, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'open')
            """, (
                run_date, ticker, entry_price, entry_price,
                price_target, stop_loss, position_size, shares
            ))
            logger.info(f"Recorded new pick: {ticker} @ ${entry_price} ({shares} shares, ${position_size})")

    conn.commit()
    conn.close()


def update_current_prices():
    """
    Pull current prices for all open positions and update P&L.
    Called at the start of each weekly run.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get all open positions
    open_positions = cur.execute("""
        SELECT id, ticker, entry_price, price_target, stop_loss, position_size, shares
        FROM performance_tracking
        WHERE status = 'open'
    """).fetchall()

    if not open_positions:
        logger.info("No open positions to update")
        conn.close()
        return

    updated = 0
    for row in open_positions:
        pos_id, ticker, entry_price, target, stop, position_size, shares = row

        try:
            stock = yf.Ticker(ticker)
            current_price = stock.fast_info.get("lastPrice") or stock.fast_info.last_price
            if not current_price:
                info = stock.info
                current_price = info.get("currentPrice") or info.get("regularMarketPrice")

            if not current_price:
                continue

            pnl_dollar = round((current_price - entry_price) * shares, 2)
            pnl_pct = round((current_price - entry_price) / entry_price * 100, 2)

            # Determine status
            status = "open"
            if current_price >= target:
                status = "hit_target"
            elif current_price <= stop:
                status = "hit_stop"

            cur.execute("""
                UPDATE performance_tracking
                SET current_price=?, pnl_dollar=?, pnl_pct=?, status=?, updated_at=?
                WHERE id=?
            """, (current_price, pnl_dollar, pnl_pct, status, datetime.now().isoformat(), pos_id))

            updated += 1
            logger.info(
                f"{ticker}: ${entry_price} → ${current_price:.2f} | "
                f"P&L: ${pnl_dollar:+.2f} ({pnl_pct:+.1f}%) | {status}"
            )

        except Exception as e:
            logger.debug(f"Price update failed for {ticker}: {e}")

    conn.commit()
    conn.close()
    logger.info(f"Updated prices for {updated} open positions")


def get_performance_summary() -> dict:
    """
    Returns a summary of all-time pick performance.
    Used in email and dashboard.
    """
    conn = sqlite3.connect(DB_PATH)

    try:
        df = pd.read_sql("""
            SELECT * FROM performance_tracking
            ORDER BY pick_date DESC
        """, conn)
    except Exception:
        conn.close()
        return {}

    conn.close()

    if df.empty:
        return {}

    total_invested = df["position_size"].sum()
    total_pnl = df["pnl_dollar"].sum()
    total_return_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    wins = df[df["pnl_dollar"] > 0]
    losses = df[df["pnl_dollar"] < 0]
    open_pos = df[df["status"] == "open"]
    hit_target = df[df["status"] == "hit_target"]
    hit_stop = df[df["status"] == "hit_stop"]

    best_pick = df.loc[df["pnl_pct"].idxmax()] if not df.empty else None
    worst_pick = df.loc[df["pnl_pct"].idxmin()] if not df.empty else None

    return {
        "total_picks": len(df),
        "open_positions": len(open_pos),
        "total_invested": round(total_invested, 2),
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(df) * 100, 1) if len(df) > 0 else 0,
        "hit_target_count": len(hit_target),
        "hit_stop_count": len(hit_stop),
        "avg_win_pct": round(wins["pnl_pct"].mean(), 1) if not wins.empty else 0,
        "avg_loss_pct": round(losses["pnl_pct"].mean(), 1) if not losses.empty else 0,
        "best_pick": {
            "ticker": best_pick["ticker"],
            "pnl_pct": round(best_pick["pnl_pct"], 1),
            "pick_date": best_pick["pick_date"],
        } if best_pick is not None else None,
        "worst_pick": {
            "ticker": worst_pick["ticker"],
            "pnl_pct": round(worst_pick["pnl_pct"], 1),
            "pick_date": worst_pick["pick_date"],
        } if worst_pick is not None else None,
        "recent_picks": df.head(10).to_dict("records"),
    }


def get_open_positions() -> list[dict]:
    """Returns list of all currently open positions with current P&L."""
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql("""
            SELECT ticker, pick_date, entry_price, current_price,
                   price_target, stop_loss, position_size, pnl_dollar, pnl_pct, status
            FROM performance_tracking
            WHERE status = 'open'
            ORDER BY pick_date DESC
        """, conn)
        return df.to_dict("records")
    except Exception:
        return []
    finally:
        conn.close()


def get_weekly_report() -> str:
    """
    Plain-English weekly P&L report for the email digest.
    Shows how last week's picks performed.
    """
    conn = sqlite3.connect(DB_PATH)
    last_week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        df = pd.read_sql(f"""
            SELECT ticker, entry_price, current_price, pnl_dollar, pnl_pct, status
            FROM performance_tracking
            WHERE pick_date >= '{last_week}'
            ORDER BY pnl_pct DESC
        """, conn)
    except Exception:
        conn.close()
        return ""
    finally:
        conn.close()

    if df.empty:
        return ""

    total_pnl = df["pnl_dollar"].sum()
    lines = [f"📊 Last Week's Results — ${total_pnl:+.2f} total P&L"]

    for _, row in df.iterrows():
        emoji = "✅" if row["pnl_pct"] > 0 else "❌" if row["pnl_pct"] < -5 else "➡️"
        status_tag = " 🎯" if row["status"] == "hit_target" else " 🛑" if row["status"] == "hit_stop" else ""
        lines.append(
            f"{emoji} ${row['ticker']}: ${row['entry_price']} → ${row['current_price']:.2f} "
            f"({row['pnl_pct']:+.1f}%){status_tag}"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Updating current prices...")
    update_current_prices()
    summary = get_performance_summary()
    print(f"\nPerformance Summary:")
    for k, v in summary.items():
        if k != "recent_picks":
            print(f"  {k}: {v}")