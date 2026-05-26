"""
main.py — Early Mover Pipeline Orchestrator
Runs the full weekly pipeline: scrape → screen → score → analyze → deliver.
Usage:
  python main.py --run        # Full pipeline run
  python main.py --init-db    # Initialize SQLite database
  python main.py --test-email # Send test email with dummy data
  python main.py --dry-run    # Run pipeline but don't send email
"""

import argparse
import logging
import sqlite3
import json
import os
from datetime import datetime
from config import (
    DB_PATH, DATA_RAW_PATH, DATA_PROCESSED_PATH,
    TOP_N_PICKS, WEIGHTS
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("early-mover")


# ── Database Setup ─────────────────────────────────────────────────────────────

def init_db():
    """Initialize the SQLite database with required tables."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS weekly_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            company_name TEXT,
            price REAL,
            total_score REAL,
            insider_score REAL,
            reddit_score REAL,
            catalyst_score REAL,
            squeeze_score REAL,
            sentiment TEXT,
            rationale TEXT,
            position_size REAL,
            stop_loss REAL,
            price_target REAL,
            catalysts TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS performance_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pick_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            entry_price REAL,
            current_price REAL,
            price_target REAL,
            stop_loss REAL,
            position_size REAL,
            shares REAL,
            pnl_dollar REAL,
            pnl_pct REAL,
            status TEXT DEFAULT 'open',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            stocks_screened INTEGER,
            stocks_scored INTEGER,
            picks_generated INTEGER,
            email_sent INTEGER,
            runtime_seconds REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")


def save_picks_to_db(picks: list[dict], run_date: str):
    """Save weekly picks to SQLite for tracking."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for pick in picks:
        cur.execute("""
            INSERT INTO weekly_picks 
            (run_date, ticker, company_name, price, total_score,
             insider_score, reddit_score, catalyst_score, squeeze_score,
             sentiment, rationale, position_size, stop_loss, price_target, catalysts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_date,
            pick["ticker"],
            pick.get("company_name", ""),
            pick.get("price", 0),
            pick.get("total_score", 0),
            pick.get("signal_breakdown", {}).get("insider", 0),
            pick.get("signal_breakdown", {}).get("reddit", 0),
            pick.get("signal_breakdown", {}).get("catalyst", 0),
            pick.get("signal_breakdown", {}).get("squeeze", 0),
            pick.get("sentiment", "speculative"),
            pick.get("rationale", ""),
            pick.get("position_size", 0),
            pick.get("stop_loss", 0),
            pick.get("price_target", 0),
            json.dumps(pick.get("catalysts", [])),
        ))

    conn.commit()
    conn.close()
    logger.info(f"Saved {len(picks)} picks to database")


# ── Main Pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(dry_run: bool = False):
    """Execute the full Early Mover pipeline."""
    start_time = datetime.now()
    run_date = start_time.strftime("%Y-%m-%d")
    logger.info(f"=== Early Mover Pipeline Starting — {run_date} ===")

    # ── Step 1: Get Universe ──────────────────────────────────────────────────
    logger.info("Step 1/6: Building stock universe via Finviz...")
    from scrapers.finviz_screen import get_universe
    universe = get_universe()
    logger.info(f"Universe: {len(universe)} stocks to analyze")

    # ── Step 2: Get Price Data ────────────────────────────────────────────────
    logger.info("Step 2/6: Fetching price data via yfinance...")
    from scrapers.price_data import get_stock_info, meets_screen_criteria
    stock_info_map = {}
    for ticker in universe:
        info = get_stock_info(ticker)
        if info and meets_screen_criteria(info):
            stock_info_map[ticker] = info

    filtered_universe = list(stock_info_map.keys())
    logger.info(f"After price filter: {len(filtered_universe)} stocks remain")

    if len(filtered_universe) == 0:
        logger.warning("No stocks passed price filter — Finviz likely rate limited. Using fallback universe.")
        from scrapers.finviz_screen import get_fallback_universe
        from scrapers.price_data import get_stock_info, meets_screen_criteria
        fallback = get_fallback_universe()
        for ticker in fallback:
            info = get_stock_info(ticker)
            if info and meets_screen_criteria(info):
                stock_info_map[ticker] = info
        filtered_universe = list(stock_info_map.keys())
        logger.info(f"Fallback universe: {len(filtered_universe)} stocks")

    # ── Step 3: Social Signals (StockTwits + Twitter + Yahoo) ───────────────
    logger.info("Step 3/6: Scraping social signals (StockTwits, Twitter, Yahoo)...")
    from scrapers.stocktwits_scraper import get_social_scores as get_st_scores
    from scrapers.twitter_scraper import get_twitter_scores
    from scrapers.yahoo_scraper import get_yahoo_scores
    from scoring.signals import get_combined_social_score, get_social_detail

    st_df = get_st_scores(filtered_universe)
    logger.info(f"StockTwits: {len(st_df[st_df['st_score'] > 0])} tickers with signal")

    twitter_df = get_twitter_scores(filtered_universe)
    logger.info(f"Twitter: {len(twitter_df[twitter_df['twitter_score'] > 0])} tickers with signal")

    yahoo_df = get_yahoo_scores(filtered_universe)
    logger.info(f"Yahoo: {len(yahoo_df[yahoo_df['yahoo_score'] > 0])} tickers with signal")

    # Keep reddit_df as empty for backwards compatibility
    import pandas as pd
    reddit_df = pd.DataFrame()

    # ── Step 4: Catalysts ─────────────────────────────────────────────────────
    logger.info("Step 4/6: Pre-fetching catalyst data for all tickers...")
    import pandas as _pd

    # Pre-fetch earnings dates in bulk to avoid per-stock external calls
    from scrapers.catalyst_scraper import get_earnings_date, get_recent_8k_filings
    earnings_map = {}
    eight_k_map = {}
    for t in filtered_universe:
        try:
            earnings_map[t] = get_earnings_date(t)
        except Exception:
            earnings_map[t] = None
        try:
            eight_k_map[t] = get_recent_8k_filings(t)
        except Exception:
            eight_k_map[t] = []

    fda_df = _pd.DataFrame()  # Legacy placeholder

    # ── Step 5: News Headlines ────────────────────────────────────────────────
    logger.info("Step 5/6: Pulling news headlines...")
    from scrapers.news_scraper import get_headlines_batch
    # Only pull news for top Reddit movers (save API calls on free tier)
    news_targets = []
    # Use StockTwits top movers for news targeting
    if not st_df.empty:
        top_social = st_df.head(30)["ticker"].tolist()
    else:
        top_social = filtered_universe[:30]
    news_targets = [
        {"ticker": t, "company_name": stock_info_map.get(t, {}).get("company_name", "")}
        for t in top_social if t in stock_info_map
    ]
    news_map = get_headlines_batch(news_targets)

    # ── Step 6: Score Everything ──────────────────────────────────────────────
    logger.info("Step 6/6: Running scoring engine...")
    from scoring.engine import score_universe, get_top_picks
    all_scores = score_universe(
        universe=filtered_universe,
        stock_info_map=stock_info_map,
        reddit_df=reddit_df,
        fda_df=fda_df,
        news_map=news_map,
        st_df=st_df,
        twitter_df=twitter_df,
        yahoo_df=yahoo_df,
    )

    top_picks_raw = get_top_picks(all_scores, n=TOP_N_PICKS)
    watchlist_raw = get_top_picks(all_scores, n=TOP_N_PICKS + 5)[TOP_N_PICKS:]

    logger.info(f"Top picks: {[s.ticker for s in top_picks_raw]}")

    # ── Schwab Portfolio Context ──────────────────────────────────────────────
    logger.info("Fetching Schwab portfolio context...")
    from scrapers.schwab_integration import (
        get_account_summary, get_current_positions,
        filter_picks_by_portfolio, get_portfolio_context
    )
    schwab_account  = get_account_summary()
    schwab_positions = get_current_positions()
    if schwab_account:
        logger.info(
            f"Schwab: ${schwab_account.get('total_value',0):,.2f} total | "
            f"${schwab_account.get('buying_power',0):,.2f} buying power | "
            f"{len(schwab_positions)} positions"
        )
    else:
        logger.info("Schwab not connected — running without portfolio context")

    # ── Update existing position prices first ────────────────────────────────
    logger.info("Updating existing position prices...")
    from scrapers.performance_tracker import update_current_prices, get_weekly_report
    update_current_prices()
    weekly_report = get_weekly_report()
    if weekly_report:
        logger.info(f"\n{weekly_report}")

    # ── Haiku Analysis ────────────────────────────────────────────────────────
    logger.info("Running Claude Haiku analysis...")
    from ai.haiku_analyst import analyze_all_picks, generate_weekly_summary
    portfolio_ctx = get_portfolio_context(schwab_positions, schwab_account)
    picks = analyze_all_picks(top_picks_raw, portfolio_context=portfolio_ctx)

    # Filter picks by what's already in portfolio
    if schwab_positions or schwab_account:
        picks = filter_picks_by_portfolio(picks, schwab_positions, schwab_account)
    watchlist = analyze_all_picks(watchlist_raw)
    weekly_summary = generate_weekly_summary(picks)

    # ── Record picks for performance tracking ────────────────────────────────
    from scrapers.performance_tracker import record_new_picks
    record_new_picks(picks, run_date)

    # ── Save to DB ────────────────────────────────────────────────────────────
    save_picks_to_db(picks, run_date)

    # ── Save Processed Output ─────────────────────────────────────────────────
    os.makedirs(DATA_PROCESSED_PATH, exist_ok=True)
    output_path = os.path.join(DATA_PROCESSED_PATH, f"picks_{run_date}.json")
    with open(output_path, "w") as f:
        json.dump({
            "run_date": run_date,
            "picks": picks,
            "watchlist": watchlist,
            "weekly_summary": weekly_summary,
            "metadata": {
                "stocks_screened": len(universe),
                "stocks_scored": len(all_scores),
                "picks_generated": len(picks),
            }
        }, f, indent=2, default=str)
    logger.info(f"Saved output to {output_path}")

    # ── Email Delivery ────────────────────────────────────────────────────────
    if not dry_run:
        logger.info("Sending email digest...")
        from delivery.email_digest import deliver
        from scrapers.performance_tracker import get_performance_summary
        from scrapers.core_holdings import get_weekly_core_reminder
        perf_summary = get_performance_summary()
        core_data = get_weekly_core_reminder()
        sent = deliver(picks, weekly_summary, watchlist, perf_summary, core_data)
        logger.info(f"Email sent: {sent}")
    else:
        logger.info("Dry run — skipping email delivery")

    # ── Run Log ───────────────────────────────────────────────────────────────
    runtime = (datetime.now() - start_time).total_seconds()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO run_log (run_date, stocks_screened, stocks_scored, picks_generated, email_sent, runtime_seconds)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (run_date, len(universe), len(all_scores), len(picks), int(not dry_run), runtime))
    conn.commit()
    conn.close()

    logger.info(f"=== Pipeline complete in {runtime:.1f}s ===")
    logger.info(f"Picks: {[p['ticker'] for p in picks]}")
    return picks


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Early Mover — Small Cap Breakout Pipeline")
    parser.add_argument("--run", action="store_true", help="Run the full pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Run pipeline, skip email")
    parser.add_argument("--init-db", action="store_true", help="Initialize database")
    parser.add_argument("--test-email", action="store_true", help="Send test email")
    args = parser.parse_args()

    if args.init_db:
        init_db()

    elif args.test_email:
        from delivery.email_digest import deliver
        dummy_picks = [{
            "ticker": "TEST",
            "company_name": "Test Corp",
            "price": 12.50,
            "sector": "Technology",
            "total_score": 72.0,
            "signal_breakdown": {"insider": 80, "reddit": 60, "options": 55, "catalyst": 70, "squeeze": 65},
            "position_size": 25.0,
            "stop_loss": 10.25,
            "price_target": 22.50,
            "reddit_mentions": 180,
            "reddit_velocity": 1.4,
            "catalysts": [],
            "headlines": [],
            "rationale": "This is a test pick to verify email delivery is working correctly.",
            "top_signal": "Strong insider buying detected.",
            "risk": "Speculative — test data only.",
            "sentiment": "cautiously_bullish",
        }]
        deliver(dummy_picks, "Test run — verifying email delivery pipeline.")
        logger.info("Test email sent")

    elif args.run or args.dry_run:
        init_db()  # Ensure DB exists
        run_pipeline(dry_run=args.dry_run)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()