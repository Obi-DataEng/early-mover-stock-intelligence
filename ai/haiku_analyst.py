"""
ai/haiku_analyst.py
Uses Claude Haiku to synthesize all signals into a plain-English
buy/pass/watch recommendation that a novice investor can act on.
"""

import anthropic
import json
import logging
from scoring.engine import StockScore
from scrapers.news_scraper import format_headlines_for_ai
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

ANALYST_SYSTEM_PROMPT = """You are a plain-English stock coach helping a beginner investor 
decide whether to buy a small-cap stock with $10–$20 of their weekly budget.

Your job is to take signal data and explain it simply — like you're texting a smart friend 
who knows nothing about Wall Street. No jargon. No hedge fund language.

Rules:
- Give a clear verdict: BUY, WATCH, or PASS
- Explain WHY in 2-3 sentences a 10th grader could understand
- Tell them the ONE thing that could make this go up
- Tell them the ONE thing that could make this go wrong
- Be honest — if it's risky, say so plainly

Always respond with valid JSON only — no markdown, no extra text."""


def build_prompt(stock: StockScore) -> str:
    """Build a plain-English analysis prompt for a single stock."""

    # Format catalysts in plain English
    if stock.catalysts:
        cat = stock.catalysts[0]
        cat_type = cat.get("type", "Event")
        cat_days = cat.get("days_until", "?")
        if isinstance(cat_days, int) and cat_days < 0:
            catalyst_str = f"The company recently filed important paperwork with the SEC ({abs(cat_days)} days ago) — could contain big news"
        else:
            catalyst_str = f"Upcoming {cat_type} in {cat_days} days — could move the stock"
    else:
        catalyst_str = "No major upcoming events identified"

    # Format insider signal in plain English
    insider_pct = stock.signal_breakdown.get("insider", 0)
    if insider_pct >= 100:
        insider_str = "Company insiders (CEO, CFO, board members) bought a LOT of their own stock recently with their personal money — this is a strong signal they think the price is going up"
    elif insider_pct >= 60:
        insider_str = "Some company insiders bought their own stock recently — they're putting their own money behind it"
    elif insider_pct > 0:
        insider_str = "A small amount of insider buying detected"
    else:
        insider_str = "No insider buying detected recently"

    # Format squeeze in plain English
    squeeze_pct = stock.signal_breakdown.get("squeeze", 0)
    if squeeze_pct >= 70:
        squeeze_str = "Lots of people are betting this stock goes DOWN (short sellers). If it starts going UP instead, those people have to buy shares fast to cover their losses — this can cause a sudden price spike called a short squeeze"
    elif squeeze_pct >= 40:
        squeeze_str = "Some short sellers are betting against this stock — a short squeeze is possible but not guaranteed"
    else:
        squeeze_str = "Not many short sellers — squeeze potential is low"

    # Format social in plain English
    social_pct = stock.signal_breakdown.get("reddit", 0)
    if social_pct >= 50:
        social_str = "This stock is getting a lot of buzz on financial social media right now"
    elif social_pct >= 20:
        social_str = "Some chatter about this stock on financial social media"
    else:
        social_str = "Almost nobody is talking about this stock online yet — it's flying under the radar"

    # News headlines
    news_str = format_headlines_for_ai(stock.ticker, stock.headlines)

    return f"""
Analyze this stock for a beginner investor and give a plain-English recommendation.

STOCK: ${stock.ticker} — {stock.company_name}
WHAT THEY DO: {stock.industry} in the {stock.sector} sector
CURRENT PRICE: ${stock.price} per share

WHAT THE SIGNALS ARE SAYING (in plain English):
- Insider buying: {insider_str}
- Short squeeze setup: {squeeze_str}  
- Social media buzz: {social_str}
- Upcoming catalyst: {catalyst_str}
- Overall confidence score: {stock.total_score}/100

RECENT NEWS:
{news_str}

Now give me your plain-English take. Return ONLY this JSON:
{{
  "verdict": "BUY" or "WATCH" or "PASS",
  "simple_explanation": "2-3 sentences in plain English explaining the verdict. Pretend you're texting a friend. No jargon. Example: 'The people who run this company are buying their own stock — that usually means they think the price is about to go up. There's also a chance short sellers get caught off guard and cause a quick spike. It's risky but the signal is real.'",
  "upside_reason": "One sentence: what's the most likely thing that could make this stock go up? Keep it simple.",
  "downside_reason": "One sentence: what's the most likely thing that could make this stock go down or stay flat? Be honest.",
  "confidence": {stock.total_score},
  "sentiment": "bullish" or "cautiously_bullish" or "speculative"
}}
"""


def analyze_pick(stock: StockScore, portfolio_context: str = "") -> dict:
    """
    Call Claude Haiku to analyze a single stock pick.
    Returns enriched dict with plain-English rationale.
    Portfolio context personalizes recommendations to actual holdings.
    """
    prompt = build_prompt(stock)
    if portfolio_context:
        prompt += f"\n\nYOUR SCHWAB PORTFOLIO CONTEXT:\n{portfolio_context}\n"
        prompt += "Consider this when giving your recommendation — especially if the sector is already overexposed."

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=ANALYST_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Haiku returned invalid JSON for {stock.ticker}: {e}")
        return {
            "verdict": "WATCH",
            "simple_explanation": f"${stock.ticker} has a composite signal score of {stock.total_score}/100. The insider buying signal is the strongest factor. Worth keeping an eye on but do your own research before buying.",
            "upside_reason": "Insider buying suggests management sees value at current prices.",
            "downside_reason": "Limited social momentum means no clear short-term catalyst to drive price up.",
            "confidence": stock.total_score,
            "sentiment": "speculative",
        }
    except Exception as e:
        logger.error(f"Haiku API call failed for {stock.ticker}: {e}")
        return {}


def analyze_all_picks(picks: list[StockScore], portfolio_context: str = "") -> list[dict]:
    """
    Analyze all top picks and return enriched list of dicts.
    Budget is allocated proportionally based on score.
    Portfolio context from Schwab personalizes the analysis.
    """
    results = []
    WEEKLY_BUDGET = 75.0

    for stock in picks:
        logger.info(f"Haiku analyzing ${stock.ticker}...")
        analysis = analyze_pick(stock, portfolio_context=portfolio_context)

        if not analysis:
            continue

        results.append({
            "ticker": stock.ticker,
            "company_name": stock.company_name,
            "price": stock.price,
            "sector": stock.sector,
            "industry": stock.industry,
            "total_score": stock.total_score,
            "signal_breakdown": stock.signal_breakdown,
            "position_size": 0,  # Set proportionally below
            "stop_loss": stock.stop_loss_price(),
            "price_target": stock.price_target(),
            "reddit_mentions": stock.reddit_mentions,
            "reddit_velocity": stock.reddit_velocity,
            "catalysts": stock.catalysts,
            "headlines": stock.headlines[:3],
            # Plain English fields
            "verdict": analysis.get("verdict", "WATCH"),
            "simple_explanation": analysis.get("simple_explanation", ""),
            "upside_reason": analysis.get("upside_reason", ""),
            "downside_reason": analysis.get("downside_reason", ""),
            "sentiment": analysis.get("sentiment", "speculative"),
            # Keep rationale fields for backwards compatibility
            "rationale": analysis.get("simple_explanation", ""),
            "top_signal": analysis.get("upside_reason", ""),
            "risk": analysis.get("downside_reason", ""),
        })

    # Allocate $75 budget proportionally based on score
    if results:
        total_score = sum(r["total_score"] for r in results)
        for r in results:
            weight = r["total_score"] / total_score if total_score > 0 else 1 / len(results)
            r["position_size"] = round(WEEKLY_BUDGET * weight, 2)

    return results


def generate_weekly_summary(picks: list[dict]) -> str:
    """
    Plain-English intro paragraph for the top of the email.
    """
    if not picks:
        return "No strong picks this week. The signals are quiet — sometimes the best move is to wait."

    buy_picks = [p for p in picks if p.get("verdict") == "BUY"]
    watch_picks = [p for p in picks if p.get("verdict") == "WATCH"]

    tickers = [p["ticker"] for p in picks]

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    f"Write a 2-sentence plain-English intro for a weekly small-cap stock picks email. "
                    f"This week's picks are: {', '.join(tickers)}. "
                    f"BUY signals: {[p['ticker'] for p in buy_picks]}. "
                    f"WATCH signals: {[p['ticker'] for p in watch_picks]}. "
                    f"Write it like you're briefing a friend before the market opens. "
                    f"Keep it short, honest, and jargon-free. No hype."
                )
            }],
        )
        return response.content[0].text.strip()
    except Exception:
        if buy_picks:
            return f"This week's scan found {len(buy_picks)} BUY signal(s) — {', '.join(p['ticker'] for p in buy_picks)} — and {len(watch_picks)} stocks worth keeping on your radar."
        return f"This week's scan flagged {len(picks)} small-cap stocks worth watching: {', '.join(tickers)}."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Haiku analyst module loaded. Run main.py to test full pipeline.")