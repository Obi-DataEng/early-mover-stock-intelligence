# 🚀 Early Mover — Small Cap Breakout Predictor

A weekly automated stock intelligence pipeline that identifies small-cap stocks ($5–$20) 
with converging breakout signals before they move. Delivers a Monday morning email digest 
with scored picks, rationale from Claude Haiku, and suggested position sizes.

---

## How It Works

Every Monday at 7 AM ET, GitHub Actions runs the full pipeline:

```
[Scrapers] → [Screener] → [Scoring Engine] → [Haiku AI] → [Email Digest]
     ↓
[SQLite DB] → [Streamlit Dashboard]
```

### Signal Sources (All Free to Start)
| Source | Signal | Module |
|---|---|---|
| SEC EDGAR Form 4 | Insider buying | `scrapers/sec_insider.py` |
| Reddit PRAW | Mention velocity (WoW) | `scrapers/reddit_scraper.py` |
| yfinance | Price, float, short interest | `scrapers/price_data.py` |
| Finviz | Screener universe | `scrapers/finviz_screen.py` |
| NewsAPI | Headline sentiment | `scrapers/news_scraper.py` |
| Stockanalysis.com | Catalyst calendar | `scrapers/catalyst_scraper.py` |

### Scoring Weights
| Signal | Weight |
|---|---|
| SEC Insider Buy (14d) | 25% |
| Reddit Mention Velocity | 20% |
| Unusual Options Activity | 20% |
| Upcoming Catalyst (30d) | 20% |
| Short Interest / Float | 15% |

---

## Setup

### 1. Clone & Install
```bash
git clone https://github.com/yourusername/early-mover.git
cd early-mover
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

Required keys:
- `ANTHROPIC_API_KEY` — Claude Haiku for AI synthesis
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` — PRAW
- `NEWS_API_KEY` — NewsAPI.org (free tier)
- `GMAIL_USER` / `GMAIL_APP_PASSWORD` — Email delivery
- `EMAIL_RECIPIENTS` — Comma-separated list of recipient emails

Optional (add when ready):
- `QUIVER_API_KEY` — Quiver Quantitative (upgrade ~$15/mo)

### 3. Initialize the Database
```bash
python main.py --init-db
```

### 4. Run Manually (Test)
```bash
python main.py --run
```

### 5. Deploy to GitHub Actions
Push to GitHub. The workflow in `.github/workflows/weekly_run.yml` fires every Monday at 7 AM ET automatically.

Add all `.env` values as **GitHub Secrets** (Settings → Secrets → Actions).

---

## Project Structure

```
early-mover/
├── main.py                     # Pipeline orchestrator
├── config.py                   # All settings & constants
├── requirements.txt
├── .env.example
├── scrapers/
│   ├── sec_insider.py          # SEC EDGAR Form 4 insider trades
│   ├── reddit_scraper.py       # Reddit mention velocity
│   ├── price_data.py           # yfinance price + fundamentals
│   ├── finviz_screen.py        # Finviz screener universe
│   ├── news_scraper.py         # NewsAPI headlines
│   └── catalyst_scraper.py     # Upcoming earnings/FDA/events
├── scoring/
│   ├── engine.py               # Weighted scoring model
│   └── signals.py              # Individual signal calculators
├── ai/
│   └── haiku_analyst.py        # Claude Haiku synthesis + rationale
├── delivery/
│   ├── email_digest.py         # Gmail SMTP email builder
│   └── templates/
│       └── weekly_email.html   # Email HTML template
├── dashboard/
│   └── app.py                  # Streamlit dashboard
├── data/
│   ├── raw/                    # Raw scraped data (gitignored)
│   ├── processed/              # Scored weekly outputs
│   └── early_mover.db          # SQLite database
├── tests/
│   ├── test_scrapers.py
│   └── test_scoring.py
└── .github/
    └── workflows/
        └── weekly_run.yml      # GitHub Actions cron job
```

---

## Upgrade Path

| Phase | When | What |
|---|---|---|
| Phase 1 | Now | All free sources, full pipeline |
| Phase 2 | After 4–6 weeks of picks | Add Quiver Quantitative ($15/mo) |
| Phase 3 | Once picks are performing | Add Benzinga Pro ($40/mo) real-time news |
| Phase 4 | Long term | Add Backtrader backtesting + Quantstats P&L tearsheet |

---

## Disclaimer
This tool is for educational and personal use only. Not financial advice. Small-cap stocks
are high risk — never invest more than you can afford to lose.
