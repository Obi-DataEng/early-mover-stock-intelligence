"""
scoring/signals.py
Aggregates all social signals (StockTwits + Twitter + Yahoo)
into a single combined social score per ticker.
Replaces the single Reddit signal with a multi-source composite.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Weights for each social source
SOCIAL_WEIGHTS = {
    "stocktwits": 0.45,  # Most reliable, finance-specific
    "twitter":    0.35,  # High volume, broader reach
    "yahoo":      0.20,  # Lower volume but engaged investors
}


def get_combined_social_score(
    ticker: str,
    st_df: pd.DataFrame | None = None,
    twitter_df: pd.DataFrame | None = None,
    yahoo_df: pd.DataFrame | None = None,
) -> float:
    """
    Combine StockTwits + Twitter + Yahoo into a single 0.0–1.0 social score.
    Any missing source contributes 0.0 to its weighted slot.
    """
    st_score, tw_score, yh_score = 0.0, 0.0, 0.0

    # StockTwits
    if st_df is not None and not st_df.empty:
        row = st_df[st_df["ticker"] == ticker]
        if not row.empty:
            st_score = float(row.iloc[0].get("st_score", 0.0))

    # Twitter
    if twitter_df is not None and not twitter_df.empty:
        row = twitter_df[twitter_df["ticker"] == ticker]
        if not row.empty:
            tw_score = float(row.iloc[0].get("twitter_score", 0.0))

    # Yahoo
    if yahoo_df is not None and not yahoo_df.empty:
        row = yahoo_df[yahoo_df["ticker"] == ticker]
        if not row.empty:
            yh_score = float(row.iloc[0].get("yahoo_score", 0.0))

    combined = (
        st_score  * SOCIAL_WEIGHTS["stocktwits"]
        + tw_score  * SOCIAL_WEIGHTS["twitter"]
        + yh_score  * SOCIAL_WEIGHTS["yahoo"]
    )

    # Normalize: if only 1 source has data, scale up proportionally
    active_weight = 0.0
    if st_score > 0: active_weight += SOCIAL_WEIGHTS["stocktwits"]
    if tw_score > 0: active_weight += SOCIAL_WEIGHTS["twitter"]
    if yh_score > 0: active_weight += SOCIAL_WEIGHTS["yahoo"]

    if 0 < active_weight < 1.0:
        combined = combined / active_weight

    return round(min(combined, 1.0), 3)


def get_social_detail(
    ticker: str,
    st_df: pd.DataFrame | None = None,
    twitter_df: pd.DataFrame | None = None,
    yahoo_df: pd.DataFrame | None = None,
) -> dict:
    """
    Returns detailed social breakdown for email/dashboard display.
    """
    detail = {
        "stocktwits_volume": 0,
        "stocktwits_bullish": 50.0,
        "twitter_mentions": 0,
        "twitter_bullish": 50.0,
        "yahoo_mentions": 0,
        "yahoo_bullish": 50.0,
    }

    if st_df is not None and not st_df.empty:
        row = st_df[st_df["ticker"] == ticker]
        if not row.empty:
            detail["stocktwits_volume"] = int(row.iloc[0].get("st_volume", 0))
            detail["stocktwits_bullish"] = float(row.iloc[0].get("st_bullish_pct", 50.0))

    if twitter_df is not None and not twitter_df.empty:
        row = twitter_df[twitter_df["ticker"] == ticker]
        if not row.empty:
            detail["twitter_mentions"] = int(row.iloc[0].get("twitter_mentions", 0))
            detail["twitter_bullish"] = float(row.iloc[0].get("twitter_bullish_pct", 50.0))

    if yahoo_df is not None and not yahoo_df.empty:
        row = yahoo_df[yahoo_df["ticker"] == ticker]
        if not row.empty:
            detail["yahoo_mentions"] = int(row.iloc[0].get("yahoo_mentions", 0))
            detail["yahoo_bullish"] = float(row.iloc[0].get("yahoo_bullish_pct", 50.0))

    return detail