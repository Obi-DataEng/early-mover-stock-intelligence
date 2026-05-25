"""
config.py — Central configuration for Early Mover pipeline.
All tunable parameters live here.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")
REDDIT_CLIENT_ID    = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET= os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT   = os.getenv("REDDIT_USER_AGENT", "EarlyMover/1.0")
NEWS_API_KEY        = os.getenv("NEWS_API_KEY")
QUIVER_API_KEY      = os.getenv("QUIVER_API_KEY")  # None until Phase 2

# ── Email ─────────────────────────────────────────────────────────────────────
GMAIL_USER          = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD  = os.getenv("GMAIL_APP_PASSWORD")
EMAIL_RECIPIENTS    = os.getenv("EMAIL_RECIPIENTS", "").split(",")

# ── Stock Screener Filters ────────────────────────────────────────────────────
MIN_PRICE           = float(os.getenv("MIN_PRICE", 5))       # $5 floor
MAX_PRICE           = float(os.getenv("MAX_PRICE", 35))      # $35 ceiling
MAX_MARKET_CAP      = int(os.getenv("MAX_MARKET_CAP", 500_000_000))  # 500M
MIN_VOLUME          = int(os.getenv("MIN_VOLUME", 100_000))  # Avoid illiquid
MAX_FLOAT_SHARES    = int(os.getenv("MAX_FLOAT", 30_000_000)) # Low float preferred

# ── Scoring Weights (must sum to 1.0) ────────────────────────────────────────
WEIGHTS = {
    "insider_buy":        0.25,   # SEC Form 4 insider purchase in last 14d
    "reddit_velocity":    0.20,   # Combined social score (StockTwits + Twitter + Yahoo)
    "options_activity":   0.20,   # Unusual call options volume
    "catalyst":           0.20,   # Upcoming earnings/FDA/event in 30 days
    "short_squeeze":      0.15,   # High short interest + low float
}

# ── Pipeline Settings ─────────────────────────────────────────────────────────
TOP_N_PICKS         = int(os.getenv("TOP_N_PICKS", 5))       # Picks per email
INSIDER_LOOKBACK_DAYS = 14                                    # Form 4 window
CATALYST_LOOKAHEAD_DAYS = 30                                  # Event horizon
REDDIT_LOOKBACK_DAYS = 7                                      # WoW comparison window

# ── Reddit Subreddits to Monitor ──────────────────────────────────────────────
SUBREDDITS = [
    "pennystocks",
    "smallstreetbets",
    "stocks",
    "RobinhoodPennyStocks",
    "investing",
]
REDDIT_POST_LIMIT = 500   # Posts to scan per subreddit per run

# ── Claude Model ──────────────────────────────────────────────────────────────
CLAUDE_MODEL        = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS   = 1000

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH             = os.path.join(os.path.dirname(__file__), "data", "early_mover.db")

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_RAW_PATH       = os.path.join(os.path.dirname(__file__), "data", "raw")
DATA_PROCESSED_PATH = os.path.join(os.path.dirname(__file__), "data", "processed")