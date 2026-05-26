"""
delivery/email_digest.py
Builds and sends the Monday morning Early Mover email digest via Gmail SMTP.
Same pattern as mlb-pick-bot mailer.
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from jinja2 import Template
from config import GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_RECIPIENTS

logger = logging.getLogger(__name__)

SENTIMENT_EMOJI = {
    "bullish": "🟢",
    "cautiously_bullish": "🟡",
    "speculative": "🟠",
}

VERDICT_STYLE = {
    "BUY":   ("✅ BUY",   "#16a34a", "#dcfce7"),   # green
    "WATCH": ("👀 WATCH", "#d97706", "#fef3c7"),   # amber
    "PASS":  ("❌ PASS",  "#dc2626", "#fee2e2"),   # red
}

EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { font-family: Arial, sans-serif; max-width: 650px; margin: 0 auto; color: #1a1a1a; background: #f9f9f9; }
  .header { background: #0d1117; color: white; padding: 24px 28px; border-radius: 8px 8px 0 0; }
  .header h1 { margin: 0; font-size: 22px; letter-spacing: -0.5px; }
  .header .subtitle { color: #8b949e; font-size: 13px; margin-top: 4px; }
  .summary-box { background: #161b22; color: #c9d1d9; padding: 16px 28px; font-size: 14px; line-height: 1.6; border-left: 3px solid #58a6ff; }
  .content { padding: 20px 28px; background: white; }
  .pick-card { border: 1px solid #e1e4e8; border-radius: 8px; margin-bottom: 20px; overflow: hidden; }
  .pick-header { background: #f6f8fa; padding: 14px 18px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #e1e4e8; }
  .pick-ticker { font-size: 20px; font-weight: bold; color: #0d1117; }
  .pick-score { background: #0d1117; color: white; border-radius: 20px; padding: 4px 12px; font-size: 13px; font-weight: bold; }
  .pick-body { padding: 16px 18px; }
  .pick-meta { font-size: 12px; color: #657786; margin-bottom: 10px; }
  .signal-bars { display: flex; gap: 6px; margin: 12px 0; flex-wrap: wrap; }
  .signal-chip { font-size: 11px; padding: 3px 8px; border-radius: 4px; background: #f0f4ff; color: #3451b2; }
  .rationale { font-size: 13px; line-height: 1.6; color: #24292f; margin: 10px 0; }
  .risk-box { background: #fff8e1; border-left: 3px solid #f59e0b; padding: 8px 12px; font-size: 12px; color: #78350f; margin-top: 8px; border-radius: 0 4px 4px 0; }
  .trade-box { display: flex; gap: 12px; margin-top: 14px; padding-top: 14px; border-top: 1px solid #e1e4e8; }
  .trade-item { flex: 1; text-align: center; }
  .trade-label { font-size: 10px; text-transform: uppercase; color: #8b949e; letter-spacing: 0.5px; }
  .trade-value { font-size: 15px; font-weight: bold; color: #0d1117; margin-top: 2px; }
  .trade-value.green { color: #16a34a; }
  .trade-value.red { color: #dc2626; }
  .catalyst-tag { display: inline-block; background: #dbeafe; color: #1d4ed8; font-size: 11px; padding: 2px 8px; border-radius: 4px; margin-bottom: 8px; }
  .watchlist { background: #f6f8fa; border-radius: 8px; padding: 16px 18px; margin-top: 4px; }
  .watchlist h3 { margin: 0 0 10px; font-size: 14px; color: #0d1117; }
  .watchlist-item { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #e1e4e8; font-size: 13px; }
  .watchlist-item:last-child { border-bottom: none; }
  .footer { padding: 16px 28px; font-size: 11px; color: #8b949e; background: #f6f8fa; border-radius: 0 0 8px 8px; border-top: 1px solid #e1e4e8; }
  .rank-badge { width: 24px; height: 24px; background: #0d1117; color: white; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; margin-right: 8px; }
</style>
</head>
<body>

<div class="header">
  <h1>🚀 Early Mover Weekly</h1>
  <div class="subtitle">{{ date }} · Small-Cap Breakout Intelligence · {{ pick_count }} picks this week</div>
</div>

<div class="summary-box">
  {{ weekly_summary }}
</div>

<div class="content">

{% for pick in picks %}
<div class="pick-card">
  <div class="pick-header">
    <div>
      <span class="rank-badge">{{ loop.index }}</span>
      <span class="pick-ticker">${{ pick.ticker }}</span>
      &nbsp;<span style="font-size:13px; color:#657786;">{{ pick.company_name }}</span>
    </div>
    <span class="pick-score">{{ pick.total_score }}/100 {{ sentiment_emoji.get(pick.sentiment, '🟠') }}</span>
  </div>

  <div class="pick-body">
    <div class="pick-meta">
      {{ pick.sector }} · ${{ pick.price }}/share · {{ pick.sentiment | replace('_', ' ') | title }}
    </div>

    {% if pick.catalysts %}
    {% for cat in pick.catalysts[:1] %}
    <div class="catalyst-tag">⚡ {{ cat.type }} in {{ cat.days_until }}d ({{ cat.date }})</div>
    {% endfor %}
    {% endif %}

    <div class="signal-bars">
      <span class="signal-chip">👤 Insider {{ pick.signal_breakdown.insider }}/100</span>
      <span class="signal-chip">📣 Social {{ pick.signal_breakdown.reddit }}/100</span>
      <span class="signal-chip">📈 Momentum {{ pick.signal_breakdown.options }}/100</span>
      <span class="signal-chip">⚡ Catalyst {{ pick.signal_breakdown.catalyst }}/100</span>
      <span class="signal-chip">🔥 Squeeze {{ pick.signal_breakdown.squeeze }}/100</span>
    </div>

    <div class="rationale">{{ pick.simple_explanation }}</div>

    {% if pick.upside_reason %}
    <div style="font-size:12px; color:#16a34a; font-weight:bold; margin: 8px 0 4px; padding: 6px 10px; background:#f0fdf4; border-radius:4px;">
      🚀 Why it could go up: {{ pick.upside_reason }}
    </div>
    {% endif %}

    {% if pick.downside_reason %}
    <div class="risk-box">⚠️ Why it might not: {{ pick.downside_reason }}</div>
    {% endif %}

    <div class="trade-box">
      <div class="trade-item">
        <div class="trade-label">Suggested Buy</div>
        <div class="trade-value">${{ pick.position_size }}</div>
      </div>
      <div class="trade-item">
        <div class="trade-label">Stop Loss</div>
        <div class="trade-value red">${{ pick.stop_loss }}</div>
      </div>
      <div class="trade-item">
        <div class="trade-label">Price Target</div>
        <div class="trade-value green">${{ pick.price_target }}</div>
      </div>
      <div class="trade-item">
        <div class="trade-label">Reddit (WoW)</div>
        <div class="trade-value">{{ pick.reddit_mentions }} 
          {% if pick.reddit_velocity > 0 %}+{{ (pick.reddit_velocity * 100) | int }}%{% endif %}
        </div>
      </div>
    </div>
  </div>
</div>
{% endfor %}

{% if perf and perf.total_picks and perf.total_picks > 0 %}
<div style="background:#0d1117; color:#c9d1d9; border-radius:8px; padding:16px 18px; margin-bottom:20px;">
  <h3 style="margin:0 0 12px; color:white; font-size:14px;">📊 All-Time Scorecard</h3>
  <div style="display:flex; gap:20px; flex-wrap:wrap;">
    <div style="text-align:center;">
      <div style="font-size:22px; font-weight:bold; color:{% if perf.total_pnl >= 0 %}#3fb950{% else %}#f85149{% endif %}">
        ${{ perf.total_pnl | round(2) }}
      </div>
      <div style="font-size:11px; color:#8b949e;">Total P&L</div>
    </div>
    <div style="text-align:center;">
      <div style="font-size:22px; font-weight:bold; color:{% if perf.total_return_pct >= 0 %}#3fb950{% else %}#f85149{% endif %}">
        {{ perf.total_return_pct }}%
      </div>
      <div style="font-size:11px; color:#8b949e;">Total Return</div>
    </div>
    <div style="text-align:center;">
      <div style="font-size:22px; font-weight:bold; color:white;">{{ perf.win_rate }}%</div>
      <div style="font-size:11px; color:#8b949e;">Win Rate</div>
    </div>
    <div style="text-align:center;">
      <div style="font-size:22px; font-weight:bold; color:white;">{{ perf.total_picks }}</div>
      <div style="font-size:11px; color:#8b949e;">Total Picks</div>
    </div>
    <div style="text-align:center;">
      <div style="font-size:22px; font-weight:bold; color:#58a6ff;">{{ perf.open_positions }}</div>
      <div style="font-size:11px; color:#8b949e;">Open</div>
    </div>
  </div>
  {% if perf.best_pick %}
  <div style="margin-top:10px; font-size:12px; color:#8b949e;">
    🏆 Best: ${{ perf.best_pick.ticker }} +{{ perf.best_pick.pnl_pct }}% ({{ perf.best_pick.pick_date }})
    {% if perf.worst_pick %}
    &nbsp;·&nbsp; 📉 Worst: ${{ perf.worst_pick.ticker }} {{ perf.worst_pick.pnl_pct }}% ({{ perf.worst_pick.pick_date }})
    {% endif %}
  </div>
  {% endif %}
</div>
{% endif %}

{% if watchlist %}
<div class="watchlist">
  <h3>👀 Watch List (Signals Building)</h3>
  {% for w in watchlist %}
  <div class="watchlist-item">
    <span><strong>${{ w.ticker }}</strong> · {{ w.company_name }} · ${{ w.price }}</span>
    <span style="color:#0d1117; font-weight:bold;">{{ w.total_score }}/100</span>
  </div>
  {% endfor %}
</div>
{% endif %}

</div>

{% if core and core.active_holdings %}
<div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; padding:16px 18px; margin-bottom:20px;">
  <h3 style="margin:0 0 14px; color:#15803d; font-size:15px;">💼 This Week's Core Buy — Set It & Forget It</h3>
  <p style="font-size:12px; color:#166534; margin:0 0 14px;">
    These aren't picks — they're your long-term foundation. Your $100 biweekly direct deposit into your Fidelity Roth IRA 
    is already set up. All growth is <strong>100% tax-free</strong> at retirement. Don't touch it.
  </p>
  {% if core.roth_pct_of_limit %}
  <div style="background:#dcfce7; border-radius:4px; padding:6px 12px; margin-bottom:12px; font-size:12px; color:#15803d;">
    📊 Roth IRA Progress: ${{ core.roth_annual_contribution }}/year = 
    <strong>{{ core.roth_pct_of_limit }}% of your $7,000 annual limit</strong> 
    · ${{ core.roth_remaining_limit }} still available to contribute this year
  </div>
  {% endif %}

  {% for h in core.active_holdings %}
  <div style="background:white; border-radius:6px; padding:12px 14px; margin-bottom:10px; border:1px solid #bbf7d0;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
      <div>
        <span style="font-size:16px; font-weight:bold; color:#0d1117;">${{ h.ticker }}</span>
        <span style="font-size:12px; color:#657786; margin-left:6px;">{{ h.name }}</span>
      </div>
      <span style="background:#15803d; color:white; border-radius:20px; padding:3px 10px; font-size:12px; font-weight:bold;">
        BUY ${{ h.weekly_amount }}
      </span>
    </div>

    <div style="display:flex; gap:16px; font-size:12px; color:#374151; margin-bottom:8px;">
      <span>📈 Price: <strong>${{ h.current_price }}</strong></span>
      <span>📦 Shares this week: <strong>{{ h.shares_this_week }}</strong></span>
      {% if h.total_shares > 0 %}
      <span>🏦 You own: <strong>{{ h.total_shares }} shares (${{ h.current_value }})</strong></span>
      {% endif %}
    </div>

    <div style="font-size:11px; color:#6b7280; font-style:italic;">{{ h.why }}</div>
  </div>
  {% endfor %}

  {% if core.projection_30yr %}
  {% set proj = core.projection_30yr %}
  <div style="background:#dcfce7; border-radius:6px; padding:10px 14px; margin-top:8px;">
    <div style="font-size:12px; color:#15803d; font-weight:bold; margin-bottom:4px;">🔮 30-Year Projection (investing ${{ proj.weekly_amount }}/week)</div>
    <div style="display:flex; gap:20px; font-size:13px; color:#166534;">
      <div>You put in: <strong>${{ "{:,.0f}".format(proj.total_contributed) }}</strong></div>
      <div>Market grows it to: <strong>${{ "{:,.0f}".format(proj.projected_value) }}</strong></div>
      <div>That's <strong>{{ proj.multiplier }}x</strong> your money</div>
    </div>
  </div>
  {% endif %}
</div>
{% endif %}

<div class="footer">
  <strong>Early Mover</strong> · Powered by Claude Haiku · Generated {{ date }}<br>
  Signal sources: SEC EDGAR · Reddit PRAW · yfinance · NewsAPI · Finviz<br><br>
  ⚠️ <em>Not financial advice. Small-cap stocks are high risk. Never invest more than you can afford to lose. 
  Always do your own research before buying.</em>
</div>

</body>
</html>
"""


def build_email_html(
    picks: list[dict],
    weekly_summary: str,
    watchlist: list[dict] | None = None,
    perf_summary: dict | None = None,
    core_data: dict | None = None,
) -> str:
    """Render the email HTML from picks data."""
    template = Template(EMAIL_TEMPLATE)
    return template.render(
        date=datetime.today().strftime("%B %d, %Y"),
        pick_count=len(picks),
        picks=picks,
        watchlist=watchlist or [],
        weekly_summary=weekly_summary,
        sentiment_emoji=SENTIMENT_EMOJI,
        verdict_style=VERDICT_STYLE,
        perf=perf_summary or {},
        core=core_data or {},
    )


def send_email(html_content: str, subject: str | None = None) -> bool:
    """
    Send the digest email via Gmail SMTP.
    Returns True on success.
    """
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        logger.error("Gmail credentials not configured — cannot send email")
        return False

    if not EMAIL_RECIPIENTS or EMAIL_RECIPIENTS == [""]:
        logger.error("No recipients configured")
        return False

    if subject is None:
        subject = f"🚀 Early Mover Weekly Picks — {datetime.today().strftime('%b %d, %Y')}"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Early Mover <{GMAIL_USER}>"
        msg["To"] = ", ".join(EMAIL_RECIPIENTS)

        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, EMAIL_RECIPIENTS, msg.as_string())

        logger.info(f"Email sent to {EMAIL_RECIPIENTS}")
        return True

    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False


def deliver(
    picks: list[dict],
    weekly_summary: str,
    watchlist: list[dict] | None = None,
    perf_summary: dict | None = None,
    core_data: dict | None = None,
) -> bool:
    """Main entry point for email delivery."""
    html = build_email_html(picks, weekly_summary, watchlist, perf_summary, core_data)
    return send_email(html)


if __name__ == "__main__":
    # Test with dummy data
    logging.basicConfig(level=logging.INFO)
    dummy_picks = [
        {
            "ticker": "MARA",
            "company_name": "Marathon Digital Holdings",
            "price": 14.20,
            "sector": "Technology",
            "total_score": 78.5,
            "signal_breakdown": {"insider": 80, "reddit": 70, "options": 60, "catalyst": 75, "squeeze": 65},
            "position_size": 30.0,
            "stop_loss": 11.64,
            "price_target": 28.40,
            "reddit_mentions": 342,
            "reddit_velocity": 1.8,
            "catalysts": [{"type": "Earnings", "date": "2026-05-28", "days_until": 12}],
            "headlines": [],
            "rationale": "Strong insider buying signal combined with elevated Reddit velocity and upcoming earnings catalyst create a compelling setup. Short interest at 22% of float adds squeeze potential if the stock moves on positive earnings guidance.",
            "top_signal": "CFO purchased $180K in open market shares on 5/10.",
            "risk": "Bitcoin price correlation means broader crypto selloff could invalidate thesis regardless of fundamentals.",
            "sentiment": "bullish",
        }
    ]
    html = build_email_html(dummy_picks, "This week's scan highlights digital asset exposure and biotech setups with near-term catalysts.")
    with open("/tmp/test_email.html", "w") as f:
        f.write(html)
    print("Test email written to /tmp/test_email.html")