"""
scrapers/schwab_integration.py
Charles Schwab API integration for Early Mover pipeline.
Pulls account balance, positions, and transaction history.
Uses the official Schwab Developer API with OAuth 2.0.

Setup:
1. Register at developer.schwab.com
2. Create app, get App Key and App Secret
3. Add to .env: SCHWAB_APP_KEY, SCHWAB_APP_SECRET
4. Run python scrapers/schwab_integration.py --auth to do one-time login
5. Tokens auto-refresh after that

Install: pip install schwabdev
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from config import DB_PATH

logger = logging.getLogger(__name__)

SCHWAB_APP_KEY    = os.getenv("SCHWAB_APP_KEY")
SCHWAB_APP_SECRET = os.getenv("SCHWAB_APP_SECRET")
SCHWAB_TOKEN_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "schwab_tokens.json")


def get_schwab_client():
    """
    Initialize and return authenticated Schwab client.
    Requires schwabdev to be installed and tokens to exist.
    """
    if not SCHWAB_APP_KEY or not SCHWAB_APP_SECRET:
        logger.warning("Schwab credentials not set — skipping Schwab integration")
        return None

    try:
        import schwabdev
        client = schwabdev.Client(
            app_key=SCHWAB_APP_KEY,
            app_secret=SCHWAB_APP_SECRET,
            callback_url="https://127.0.0.1",
            tokens_file=SCHWAB_TOKEN_PATH,
            capture_callback_url=False,
        )
        return client
    except ImportError:
        logger.warning("schwabdev not installed — run: pip install schwabdev")
        return None
    except Exception as e:
        logger.error(f"Schwab client init failed: {e}")
        return None


def get_account_summary() -> dict:
    """
    Pull account balance and buying power from Schwab.
    Returns dict with cash_balance, buying_power, total_value.
    """
    client = get_schwab_client()
    if not client:
        return {}

    try:
        response = client.account_linked()
        if not response.ok:
            logger.error(f"Schwab account fetch failed: {response.status_code}")
            return {}

        accounts = response.json()
        if not accounts:
            return {}

        # Use first account (most people have one brokerage account)
        account = accounts[0]
        account_hash = account.get("hashValue", "")

        # Get detailed account info
        detail = client.account_details(account_hash, fields="positions").json()
        securities_account = detail.get("securitiesAccount", {})
        current_balances = securities_account.get("currentBalances", {})

        return {
            "account_hash": account_hash,
            "account_type": securities_account.get("type", ""),
            "cash_balance": current_balances.get("cashBalance", 0),
            "buying_power": current_balances.get("buyingPower", 0),
            "total_value": current_balances.get("liquidationValue", 0),
            "day_pnl": current_balances.get("dayProfitLoss", 0),
            "day_pnl_pct": current_balances.get("dayProfitLossPercentage", 0),
        }

    except Exception as e:
        logger.error(f"Schwab account summary failed: {e}")
        return {}


def get_current_positions() -> list[dict]:
    """
    Pull all current holdings from Schwab account.
    Returns list of position dicts with ticker, quantity, avg_price, current_value, pnl.
    """
    client = get_schwab_client()
    if not client:
        return []

    try:
        response = client.account_linked()
        if not response.ok:
            return []

        accounts = response.json()
        if not accounts:
            return []

        account_hash = accounts[0].get("hashValue", "")
        detail = client.account_details(account_hash, fields="positions").json()
        securities_account = detail.get("securitiesAccount", {})
        positions = securities_account.get("positions", [])

        result = []
        for pos in positions:
            instrument = pos.get("instrument", {})
            ticker = instrument.get("symbol", "")
            if not ticker:
                continue

            result.append({
                "ticker": ticker,
                "quantity": pos.get("longQuantity", 0),
                "avg_price": pos.get("averagePrice", 0),
                "current_price": pos.get("marketValue", 0) / pos.get("longQuantity", 1)
                                 if pos.get("longQuantity", 0) > 0 else 0,
                "current_value": pos.get("marketValue", 0),
                "cost_basis": pos.get("averagePrice", 0) * pos.get("longQuantity", 0),
                "pnl_dollar": pos.get("currentDayProfitLoss", 0),
                "pnl_pct": pos.get("currentDayProfitLossPercentage", 0),
                "asset_type": instrument.get("assetType", "EQUITY"),
            })

        logger.info(f"Schwab positions: {len(result)} holdings")
        return result

    except Exception as e:
        logger.error(f"Schwab positions fetch failed: {e}")
        return []


def get_sector_exposure(positions: list[dict]) -> dict[str, float]:
    """
    Calculate sector exposure percentages from current positions.
    Used to avoid over-concentrating in one sector.
    """
    if not positions:
        return {}

    import yfinance as yf

    total_value = sum(p["current_value"] for p in positions)
    if total_value == 0:
        return {}

    sector_values = {}
    for pos in positions:
        try:
            info = yf.Ticker(pos["ticker"]).info
            sector = info.get("sector", "Unknown")
            sector_values[sector] = sector_values.get(sector, 0) + pos["current_value"]
        except Exception:
            pass

    return {
        sector: round(value / total_value * 100, 1)
        for sector, value in sector_values.items()
    }


def filter_picks_by_portfolio(
    picks: list[dict],
    positions: list[dict],
    account_summary: dict,
) -> list[dict]:
    """
    Filter and adjust picks based on current portfolio.
    - Skip tickers already held
    - Warn if sector is overexposed (>40% of portfolio)
    - Adjust position sizes based on available buying power
    """
    if not positions and not account_summary:
        return picks  # No Schwab data — return picks unchanged

    held_tickers = {p["ticker"] for p in positions}
    buying_power = account_summary.get("buying_power", float("inf"))
    sector_exposure = get_sector_exposure(positions)

    filtered = []
    for pick in picks:
        ticker = pick["ticker"]

        # Skip if already held
        if ticker in held_tickers:
            logger.info(f"Skipping {ticker} — already in Schwab portfolio")
            pick["schwab_note"] = "Already held in your account"
            pick["verdict"] = "SKIP"
            filtered.append(pick)
            continue

        # Warn if sector is overexposed
        sector = pick.get("sector", "")
        if sector and sector_exposure.get(sector, 0) > 40:
            pick["schwab_note"] = (
                f"⚠️ You already have {sector_exposure[sector]:.0f}% "
                f"of your portfolio in {sector}"
            )

        # Adjust position size if buying power is limited
        if buying_power < pick.get("position_size", 0):
            pick["position_size"] = round(min(pick["position_size"], buying_power * 0.25), 2)
            pick["schwab_note"] = pick.get("schwab_note", "") + " (Position sized to buying power)"

        filtered.append(pick)

    return filtered


def get_portfolio_context(positions: list[dict], account_summary: dict) -> str:
    """
    Generate plain-English portfolio context string for Haiku prompt.
    Helps Haiku give personalized recommendations.
    """
    if not positions and not account_summary:
        return ""

    lines = []

    if account_summary:
        buying_power = account_summary.get("buying_power", 0)
        total_value = account_summary.get("total_value", 0)
        lines.append(f"Account total value: ${total_value:,.2f}")
        lines.append(f"Available buying power: ${buying_power:,.2f}")

    if positions:
        held = [p["ticker"] for p in positions]
        lines.append(f"Currently holding: {', '.join(held)}")

        sector_exposure = get_sector_exposure(positions)
        if sector_exposure:
            top_sectors = sorted(sector_exposure.items(), key=lambda x: x[1], reverse=True)[:3]
            lines.append(f"Sector exposure: {', '.join(f'{s} {v}%' for s, v in top_sectors)}")

    return "\n".join(lines)


def one_time_auth():
    """
    Run this once to authenticate with Schwab and save tokens.
    After this, tokens auto-refresh.
    Usage: python scrapers/schwab_integration.py --auth
    """
    if not SCHWAB_APP_KEY or not SCHWAB_APP_SECRET:
        print("ERROR: Set SCHWAB_APP_KEY and SCHWAB_APP_SECRET in your .env first")
        return

    try:
        import schwabdev
        print("Starting Schwab OAuth flow...")
        print("A browser window will open — log in with your Schwab credentials")
        print("After login, copy the full callback URL and paste it here\n")

        client = schwabdev.Client(
            app_key=SCHWAB_APP_KEY,
            app_secret=SCHWAB_APP_SECRET,
            callback_url="https://127.0.0.1",
            tokens_file=SCHWAB_TOKEN_PATH,
        )

        print(f"\nTokens saved to: {SCHWAB_TOKEN_PATH}")
        print("Authentication complete! The pipeline will now use your Schwab account.")

        # Test the connection
        summary = get_account_summary()
        if summary:
            print(f"\nAccount connected successfully!")
            print(f"Total value: ${summary.get('total_value', 0):,.2f}")
            print(f"Buying power: ${summary.get('buying_power', 0):,.2f}")
        else:
            print("Connection test failed — check your credentials")

    except ImportError:
        print("Run: pip install schwabdev")
    except Exception as e:
        print(f"Auth failed: {e}")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if "--auth" in sys.argv:
        one_time_auth()
    else:
        print("Schwab Integration Module")
        print("To authenticate: python scrapers/schwab_integration.py --auth")
        print("\nTesting connection...")
        summary = get_account_summary()
        if summary:
            print(f"Account value: ${summary.get('total_value', 0):,.2f}")
            positions = get_current_positions()
            print(f"Positions: {[p['ticker'] for p in positions]}")
        else:
            print("Not connected yet — run with --auth flag first")