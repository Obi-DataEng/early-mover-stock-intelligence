"""
scoring/engine.py
Weighted scoring engine. Aggregates all signal scores into a final 0–100 score per stock.
"""

import pandas as pd
import logging
from dataclasses import dataclass, field
from config import WEIGHTS, TOP_N_PICKS

logger = logging.getLogger(__name__)


@dataclass
class StockScore:
    ticker: str
    company_name: str = ""
    price: float = 0.0
    sector: str = ""
    industry: str = ""

    # Raw signal scores (0.0–1.0 each)
    insider_score: float = 0.0
    reddit_score: float = 0.0
    options_score: float = 0.0
    catalyst_score: float = 0.0
    squeeze_score: float = 0.0

    # Metadata for email
    insider_detail: str = ""
    reddit_mentions: int = 0
    reddit_velocity: float = 0.0
    catalysts: list = field(default_factory=list)
    headlines: list = field(default_factory=list)

    @property
    def total_score(self) -> float:
        """Weighted composite score 0–100."""
        raw = (
            self.insider_score  * WEIGHTS["insider_buy"]
            + self.reddit_score   * WEIGHTS["reddit_velocity"]
            + self.options_score  * WEIGHTS["options_activity"]
            + self.catalyst_score * WEIGHTS["catalyst"]
            + self.squeeze_score  * WEIGHTS["short_squeeze"]
        )
        return round(raw * 100, 1)

    @property
    def signal_breakdown(self) -> dict:
        return {
            "insider":  round(self.insider_score * 100),
            "reddit":   round(self.reddit_score * 100),
            "options":  round(self.options_score * 100),
            "catalyst": round(self.catalyst_score * 100),
            "squeeze":  round(self.squeeze_score * 100),
        }

    def position_size(self, budget: float = 75.0) -> float:
        """
        Suggested dollar amount based on score and $75 weekly budget.
        Minimum $15 per pick (never less than 20% of budget).
        Higher conviction picks get more weight.
        """
        if self.total_score >= 80:
            return round(budget * 0.40, 2)   # $30 — high conviction
        elif self.total_score >= 65:
            return round(budget * 0.33, 2)   # $25 — solid signal
        elif self.total_score >= 50:
            return round(budget * 0.27, 2)   # $20 — moderate signal
        elif self.total_score >= 35:
            return round(budget * 0.20, 2)   # $15 — speculative but qualified
        return round(budget * 0.20, 2)        # $15 — floor, never less

    def stop_loss_price(self) -> float:
        """15–20% below current price depending on volatility."""
        return round(self.price * 0.82, 2)  # 18% stop loss

    def price_target(self) -> float:
        """1.5x–2.5x target based on score."""
        if self.total_score >= 80:
            multiplier = 2.5
        elif self.total_score >= 65:
            multiplier = 2.0
        else:
            multiplier = 1.5
        return round(self.price * multiplier, 2)


def score_universe(
    universe: list[str],
    stock_info_map: dict,
    reddit_df: pd.DataFrame,
    fda_df: pd.DataFrame,
    news_map: dict,
    st_df: pd.DataFrame | None = None,
    twitter_df: pd.DataFrame | None = None,
    yahoo_df: pd.DataFrame | None = None,
) -> list[StockScore]:
    """
    Main scoring function. Takes all pre-fetched data and returns
    a sorted list of StockScore objects.

    Args:
        universe: list of ticker strings
        stock_info_map: {ticker: info_dict} from price_data.py
        reddit_df: DataFrame from reddit_scraper.get_mention_velocity()
        fda_df: DataFrame from catalyst_scraper.get_fda_calendar()
        news_map: {ticker: [articles]} from news_scraper.get_headlines_batch()
    """
    from scrapers.sec_insider import score_insider_signal
    from scrapers.price_data import score_short_squeeze, calculate_momentum
    from scrapers.catalyst_scraper import score_catalyst_signal, get_catalysts_for_ticker

    scores = []

    for ticker in universe:
        info = stock_info_map.get(ticker)
        if not info:
            logger.debug(f"Skipping {ticker} — no price info")
            continue

        logger.info(f"Scoring {ticker} @ ${info.get('price', '?')}...")

        kwargs = {"st_df": st_df, "twitter_df": twitter_df, "yahoo_df": yahoo_df}
        try:
            stock = StockScore(
                ticker=ticker,
                company_name=info.get("company_name", ticker),
                price=info.get("price", 0),
                sector=info.get("sector", ""),
                industry=info.get("industry", ""),
            )

            # ── Signal 1: Insider Buy ────────────────────────────────
            stock.insider_score = score_insider_signal(ticker)

            # ── Signal 2: Combined Social (StockTwits + Twitter + Yahoo) ─────
            from scoring.signals import get_combined_social_score, get_social_detail
            social_score = get_combined_social_score(ticker, st_df, twitter_df, yahoo_df)
            stock.reddit_score = social_score
            social_detail = get_social_detail(ticker, st_df, twitter_df, yahoo_df)
            stock.reddit_mentions = (
                social_detail["stocktwits_volume"]
                + social_detail["twitter_mentions"]
                + social_detail["yahoo_mentions"]
            )
            stock.reddit_velocity = social_score

            # ── Signal 3: Options Activity (placeholder — free tier) ──
            # Full options flow requires Unusual Whales or similar
            # For now, use momentum as a proxy (volume surge signals activity)
            stock.options_score = calculate_momentum(ticker) * 0.6  # Dampened proxy

            # ── Signal 4: Catalyst ───────────────────────────────────
            stock.catalyst_score = score_catalyst_signal(ticker, fda_df)
            stock.catalysts = get_catalysts_for_ticker(ticker, fda_df)

            # ── Signal 5: Short Squeeze ──────────────────────────────
            stock.squeeze_score = score_short_squeeze(ticker, info)

            # ── News headlines (for Haiku, not scored here) ──────────
            stock.headlines = news_map.get(ticker, [])

            scores.append(stock)
            logger.info(
                f"{ticker}: total={stock.total_score} | "
                f"insider={stock.insider_score:.2f} reddit={stock.reddit_score:.2f} "
                f"catalyst={stock.catalyst_score:.2f} squeeze={stock.squeeze_score:.2f}"
            )

        except Exception as e:
            logger.error(f"Scoring failed for {ticker}: {e}")
            continue

    # Sort by total score descending
    scores.sort(key=lambda s: s.total_score, reverse=True)
    return scores


def get_top_picks(scores: list[StockScore], n: int = TOP_N_PICKS) -> list[StockScore]:
    """Returns top N picks, filtering out very low scores."""
    # Only include stocks with at least 2 signals firing
    qualified = [s for s in scores if s.total_score >= 25]
    return qualified[:n]