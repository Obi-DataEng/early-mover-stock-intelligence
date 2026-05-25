"""
dashboard/app.py
Streamlit dashboard for Early Mover picks, signal breakdowns, and P&L tracking.
Run with: streamlit run dashboard/app.py
"""

import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH

st.set_page_config(
    page_title="Early Mover Dashboard",
    page_icon="🚀",
    layout="wide",
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_picks() -> pd.DataFrame:
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM weekly_picks ORDER BY run_date DESC, total_score DESC", conn)
    conn.close()
    return df


def load_run_log() -> pd.DataFrame:
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM run_log ORDER BY run_date DESC", conn)
    conn.close()
    return df


def score_color(score: float) -> str:
    if score >= 75:
        return "🟢"
    elif score >= 55:
        return "🟡"
    return "🟠"


# ── Layout ─────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.metric-card { background: #f6f8fa; border-radius: 8px; padding: 16px; border: 1px solid #e1e4e8; }
.ticker-big { font-size: 28px; font-weight: bold; }
.score-big { font-size: 36px; font-weight: bold; color: #0d1117; }
</style>
""", unsafe_allow_html=True)

st.title("🚀 Early Mover — Small Cap Intelligence Dashboard")

picks_df = load_picks()
run_log = load_run_log()

# ── Top Stats ──────────────────────────────────────────────────────────────────

col1, col2, col3, col4 = st.columns(4)

if not picks_df.empty:
    total_runs = len(run_log)
    total_picks = len(picks_df)
    avg_score = picks_df["total_score"].mean()
    latest_date = picks_df["run_date"].max()

    with col1:
        st.metric("Total Runs", total_runs)
    with col2:
        st.metric("Total Picks Generated", total_picks)
    with col3:
        st.metric("Avg Pick Score", f"{avg_score:.1f}/100")
    with col4:
        st.metric("Last Run", latest_date)
else:
    st.info("No data yet. Run `python main.py --run` to generate picks.")

st.divider()

# ── Week Selector ──────────────────────────────────────────────────────────────

if not picks_df.empty:
    run_dates = sorted(picks_df["run_date"].unique(), reverse=True)
    selected_date = st.selectbox("📅 Select Week", run_dates)

    week_df = picks_df[picks_df["run_date"] == selected_date].reset_index(drop=True)

    st.subheader(f"Top Picks — {selected_date}")

    # ── Pick Cards ─────────────────────────────────────────────────────────────
    for i, row in week_df.iterrows():
        with st.container():
            c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])

            with c1:
                st.markdown(f"**${row['ticker']}** — {row.get('company_name', '')}")
                st.caption(f"{score_color(row['total_score'])} {row.get('sentiment', '').replace('_', ' ').title()}")

            with c2:
                st.metric("Score", f"{row['total_score']:.0f}/100")

            with c3:
                st.metric("Price", f"${row.get('price', 0):.2f}")

            with c4:
                st.metric("Target", f"${row.get('price_target', 0):.2f}")

            with c5:
                st.metric("Stop", f"${row.get('stop_loss', 0):.2f}")

            if row.get("rationale"):
                st.caption(f"💬 {row['rationale'][:200]}...")

            st.divider()

    # ── Signal Breakdown Chart ─────────────────────────────────────────────────
    st.subheader("📊 Signal Breakdown This Week")

    chart_data = []
    for _, row in week_df.iterrows():
        chart_data.extend([
            {"Ticker": f"${row['ticker']}", "Signal": "Insider", "Score": row.get("insider_score", 0) * 100},
            {"Ticker": f"${row['ticker']}", "Signal": "Reddit", "Score": row.get("reddit_score", 0) * 100},
            {"Ticker": f"${row['ticker']}", "Signal": "Catalyst", "Score": row.get("catalyst_score", 0) * 100},
            {"Ticker": f"${row['ticker']}", "Signal": "Squeeze", "Score": row.get("squeeze_score", 0) * 100},
        ])

    if chart_data:
        chart_df = pd.DataFrame(chart_data)
        fig = px.bar(
            chart_df,
            x="Ticker",
            y="Score",
            color="Signal",
            barmode="group",
            color_discrete_sequence=["#0d1117", "#58a6ff", "#3fb950", "#f78166"],
            height=350,
        )
        fig.update_layout(
            plot_bgcolor="white",
            paper_bgcolor="white",
            font=dict(size=12),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            yaxis=dict(range=[0, 100]),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Score Over Time ────────────────────────────────────────────────────────
    if len(run_dates) > 1:
        st.subheader("📈 Pick Scores Over Time")

        trend_df = picks_df.groupby("run_date")["total_score"].agg(["mean", "max"]).reset_index()
        trend_df.columns = ["Date", "Avg Score", "Top Score"]

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=trend_df["Date"], y=trend_df["Top Score"],
                                   name="Top Score", line=dict(color="#3fb950", width=2)))
        fig2.add_trace(go.Scatter(x=trend_df["Date"], y=trend_df["Avg Score"],
                                   name="Avg Score", line=dict(color="#58a6ff", width=2, dash="dot")))
        fig2.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            yaxis=dict(range=[0, 100]),
            height=300,
        )
        st.plotly_chart(fig2, use_container_width=True)

    # ── Run History ───────────────────────────────────────────────────────────
    if not run_log.empty:
        st.subheader("🔄 Pipeline Run History")
        st.dataframe(
            run_log[["run_date", "stocks_screened", "stocks_scored", "picks_generated", "runtime_seconds"]],
            use_container_width=True,
            hide_index=True,
        )

else:
    st.warning("No picks in database yet. Run the pipeline first.")

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Config")
    st.caption("Signal Weights")
    from config import WEIGHTS
    for signal, weight in WEIGHTS.items():
        st.progress(weight, text=f"{signal.replace('_', ' ').title()}: {int(weight*100)}%")

    st.divider()
    st.caption("To run manually:")
    st.code("python main.py --run", language="bash")
    st.caption("To test email:")
    st.code("python main.py --test-email", language="bash")

    st.divider()
    st.caption("⚠️ Not financial advice. Small-cap stocks are high risk.")
