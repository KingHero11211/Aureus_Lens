"""Streamlit Analytics Dashboard for Aureus Lens.

Contract-Native Relative-Value Engine for MCX Gold Futures.
Hack in Hills '26 - Phase 5 / Master Spec Refinement
"""

from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (
    BROKERAGE_MAX_PER_ORDER,
    BROKERAGE_RATE_PCT,
    CONTRACT_SPECS,
    CTT_SELL_PCT,
    EXCHANGE_TRANSACTION_CHARGE_PCT,
    GST_PCT,
    SEBI_TURNOVER_FEE_PCT,
    STAGGERED_DELIVERY_DAYS,
    STAMP_DUTY_BUY_PCT,
    TARGET_SYMBOLS,
    UNVERIFIED_ITEMS,
)
from src.aureus_lens.core.costs import compute_roundtrip_costs
from src.aureus_lens.core.curve import adjust_to_expiry, compute_carry
from src.aureus_lens.core.gate import executability_gate
from src.aureus_lens.core.normalize import normalize_ppg999
from src.aureus_lens.core.signals import compute_zscore
from src.aureus_lens.core.spread import compute_spread_bps
from src.aureus_lens.core.waterfall import compute_waterfall
from src.aureus_lens.store.db import DEFAULT_DB_PATH

st.set_page_config(
    page_title="Aureus Lens - MCX Gold RV Engine",
    page_icon="🪙",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=30)
def load_duckdb_data() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read exclusively from DuckDB (data/aureus.duckdb). Never calls external APIs."""
    db_file = Path(DEFAULT_DB_PATH)
    bhav_df = pd.DataFrame()
    health_df = pd.DataFrame()
    coverage_df = pd.DataFrame()
    listing_df = pd.DataFrame()

    if db_file.exists():
        try:
            conn = duckdb.connect(database=str(db_file), read_only=True)
            bhav_df = conn.execute("SELECT * FROM bhav ORDER BY date ASC, symbol ASC").df()
            health_df = conn.execute("SELECT * FROM data_health ORDER BY date DESC").df()
            coverage_df = conn.execute("SELECT * FROM coverage ORDER BY date DESC, symbol ASC").df()
            listing_df = conn.execute("SELECT * FROM contract_listing ORDER BY symbol ASC, expiry_date ASC").df()
            conn.close()
        except Exception:
            pass

    if not bhav_df.empty:
        bhav_df["date"] = pd.to_datetime(bhav_df["date"]).dt.date
        bhav_df["expiry_date"] = pd.to_datetime(bhav_df["expiry_date"]).dt.date
        bhav_df["ppg999"] = bhav_df.apply(normalize_ppg999, axis=1)

    if not health_df.empty:
        health_df["date"] = pd.to_datetime(health_df["date"]).dt.date

    if not listing_df.empty:
        listing_df["expiry_date"] = pd.to_datetime(listing_df["expiry_date"]).dt.date
        listing_df["first_session"] = pd.to_datetime(listing_df["first_session"]).dt.date
        listing_df["last_session"] = pd.to_datetime(listing_df["last_session"]).dt.date

    return bhav_df, health_df, coverage_df, listing_df


bhav_df, health_df, coverage_df, listing_df = load_duckdb_data()

# Navigation
st.sidebar.title("🪙 Aureus Lens")
st.sidebar.caption("Contract-Native Relative-Value Engine • MCX Gold")

pages = [
    "Data Health",
    "Normalized View",
    "Spread Scanner",
    "Spread Waterfall",
    "Coverage",
    "Backtest",
]
selected_page = st.sidebar.selectbox("Navigation", pages)

st.sidebar.markdown("---")
st.sidebar.caption("Target Contracts: `GOLDM`, `GOLDTEN`, `GOLDGUINEA`, `GOLDPETAL`")
st.sidebar.caption("Storage: `data/aureus.duckdb` (Strict local queries)")

# ==============================================================================
# Page 1: Data Health
# ==============================================================================
if selected_page == "Data Health":
    st.header("📊 Ingestion & Data Health Audit")
    st.caption("Tracks MCX Bhavcopy ingestion sessions, date mismatches, weekend rejections, and continuity gaps.")

    if bhav_df.empty:
        st.warning("Database is empty (0 rows in 'bhav'). No market data loaded.")
        if not health_df.empty:
            st.subheader("Data Health Audit Event Log")
            st.dataframe(health_df[["date", "event", "detail"]], use_container_width=True, height=400)
        else:
            st.info("No recorded data health logs in database.")
    else:
        col1, col2, col3 = st.columns(3)

        rejected_count = len(health_df[health_df["event"].str.contains("mismatch|error|rejected", case=False, na=False)])
        last_fetch = bhav_df["date"].max().strftime("%Y-%m-%d")
        total_sessions = bhav_df["date"].nunique()

        with col1:
            st.metric("Last Successful Fetch", last_fetch)
        with col2:
            st.metric("Total Trading Sessions", total_sessions)
        with col3:
            st.metric("Rejected Dates / Anomalies", rejected_count)

        st.subheader("Data Health Audit Event Log")
        if not health_df.empty:
            st.dataframe(health_df[["date", "event", "detail"]], use_container_width=True, height=400)
        else:
            st.info("No recorded data health warnings or anomalies in database.")


# ==============================================================================
# Page 2: Normalized View
# ==============================================================================
elif selected_page == "Normalized View":
    st.header("📈 Normalized Price Parity (PPG999)")
    st.caption("All contract quotes standardized to ₹ per gram of 999 purity gold over time.")

    if bhav_df.empty:
        st.warning("No data loaded in database.")
    else:
        all_expiries = sorted(bhav_df["expiry_date"].unique())
        selected_expiry = st.selectbox(
            "Filter Expiry Date",
            ["All Expiries"] + [e.strftime("%Y-%m-%d") for e in all_expiries],
        )

        filtered_df = bhav_df.copy()
        if selected_expiry != "All Expiries":
            exp_date = datetime.strptime(selected_expiry, "%Y-%m-%d").date()
            filtered_df = filtered_df[filtered_df["expiry_date"] == exp_date]

        if filtered_df.empty:
            st.warning("No contracts available for the selected expiry.")
        else:
            fig = go.Figure()
            color_map = {
                "GOLDM": "#f59e0b",
                "GOLDTEN": "#06b6d4",
                "GOLDGUINEA": "#8b5cf6",
                "GOLDPETAL": "#10b981",
            }

            for sym in ["GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL"]:
                sym_data = filtered_df[filtered_df["symbol"] == sym].sort_values("date")
                if not sym_data.empty:
                    fig.add_trace(
                        go.Scatter(
                            x=sym_data["date"],
                            y=sym_data["ppg999"],
                            mode="lines+markers",
                            name=f"{sym} (PPG999)",
                            line=dict(color=color_map.get(sym, "#ffffff"), width=2),
                            marker=dict(size=4),
                        )
                    )

            date_range_str = f"{bhav_df['date'].min()} to {bhav_df['date'].max()}"
            fig.update_layout(
                title=f"Normalized Price per Gram (PPG999) | Source: DuckDB (bhav) | Range: {date_range_str} | Unit: ₹/g",
                xaxis_title="Trade Date",
                yaxis_title="Price (₹ / gram 999)",
                template="plotly_dark",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                height=500,
            )
            st.plotly_chart(fig, use_container_width=True)

            st.caption(f"**Data Source:** DuckDB table `bhav` | **Date Range:** {date_range_str} | **Unit:** ₹ per gram of 999 gold")


# ==============================================================================
# Page 3: Spread Scanner
# ==============================================================================
elif selected_page == "Spread Scanner":
    st.header("🎯 Relative-Value Spread & Executability Scanner")
    st.caption("Analyzes basis points spread, rolling lagged Z-score, carry source, and hard executability suppressions.")

    if bhav_df.empty:
        st.warning("No data loaded in database. No actionable signal.")
    else:
        col_pair, col_date = st.columns(2)
        pairs = ["GOLDTEN vs GOLDM", "GOLDPETAL vs GOLDM", "GOLDGUINEA vs GOLDM"]

        with col_pair:
            selected_pair = st.selectbox("Select Contract Pair", pairs)
        with col_date:
            dates_available = sorted(bhav_df["date"].unique(), reverse=True)
            selected_date = st.selectbox(
                "Evaluation Date",
                dates_available,
                format_func=lambda d: d.strftime("%Y-%m-%d"),
            )

        small_sym = selected_pair.split(" vs ")[0]
        ref_sym = selected_pair.split(" vs ")[1]

        day_small = bhav_df[(bhav_df["date"] == selected_date) & (bhav_df["symbol"] == small_sym)]
        day_ref = bhav_df[(bhav_df["date"] == selected_date) & (bhav_df["symbol"] == ref_sym)]

        if day_small.empty or day_ref.empty:
            st.warning("No actionable signal: Insufficient contract quote data for selected date.")
        else:
            row_small = day_small.iloc[0]
            row_ref = day_ref.iloc[0]

            ppg_small = float(row_small["ppg999"])
            ppg_ref = float(row_ref["ppg999"])

            # Compute carry from DuckDB strictly on this date
            conn = duckdb.connect(database=DEFAULT_DB_PATH, read_only=True)
            carry_val, carry_source = compute_carry(conn, selected_date, theoretical_fallback=0.065)
            conn.close()

            # Merged spread series
            merged_time = pd.merge(
                bhav_df[bhav_df["symbol"] == small_sym][["date", "ppg999", "expiry_date"]],
                bhav_df[bhav_df["symbol"] == ref_sym][["date", "ppg999"]],
                on="date",
                suffixes=("_small", "_ref"),
            ).sort_values("date")

            merged_time["spread_bps"] = 10000.0 * (merged_time["ppg999_small"] - merged_time["ppg999_ref"]) / merged_time["ppg999_ref"]
            merged_time["zscore"] = compute_zscore(
                merged_time["spread_bps"],
                window=20,
                min_periods=5,
                expiry_series=merged_time["expiry_date"],
            )

            current_row = merged_time[merged_time["date"] == selected_date]
            current_spread_bps = float(current_row["spread_bps"].iloc[0]) if not current_row.empty else compute_spread_bps(ppg_small, ppg_ref)
            current_z = float(current_row["zscore"].iloc[0]) if not current_row.empty and not pd.isna(current_row["zscore"].iloc[0]) else 0.0

            # Cost hurdle from statutory model
            cost_res = compute_roundtrip_costs(1_000_000, 1_000_000)
            cost_bps = cost_res["total_bps"]

            is_executable, reasons = executability_gate(row_small, row_ref, current_spread_bps, cost_bps)

            # Suppress signal if carry_source == 'none'
            if carry_source == "none":
                is_executable = False
                reasons.append("carry_source is 'none' (insufficient liquid curve contracts)")

            # Top KPI metrics
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Spread (bps)", f"{current_spread_bps:+.2f} bps")
            with c2:
                st.metric("Lagged Robust Z-Score", f"{current_z:+.2f} σ")
            with c3:
                st.metric("Carry Source", carry_source.upper())
            with c4:
                status_badge = "🟢 EXECUTABLE" if is_executable else "🔴 SUPPRESSED"
                st.metric("Gate Status", status_badge)

            st.markdown("---")
            if not is_executable:
                st.error(f"⚠️ **No Actionable Signal**:\n" + "\n".join(f"- {r}" for r in reasons))
            else:
                action = "BUY RETAIL / SELL GOLDM" if current_z < -1.5 else "SELL RETAIL / BUY GOLDM"
                st.success(f"🚀 **Actionable Relative-Value Opportunity**: {action} (Net edge cleared 2x cost hurdle)")

            # Chart with labels
            st.subheader("Historical Spread & Hurdle Trajectory")
            fig_spread = go.Figure()
            fig_spread.add_trace(
                go.Scatter(
                    x=merged_time["date"],
                    y=merged_time["spread_bps"],
                    name="Spread (bps)",
                    line=dict(color="#f59e0b", width=2),
                )
            )
            fig_spread.add_hline(y=cost_bps * 2.0, line_dash="dash", line_color="#ef4444", annotation_text="+2x Cost Hurdle")
            fig_spread.add_hline(y=-cost_bps * 2.0, line_dash="dash", line_color="#ef4444", annotation_text="-2x Cost Hurdle")

            d_range = f"{merged_time['date'].min()} to {merged_time['date'].max()}"
            fig_spread.update_layout(
                title=f"{selected_pair} Spread | Source: DuckDB | Range: {d_range} | Unit: Basis Points (bps) | Carry Source: {carry_source}",
                template="plotly_dark",
                height=380,
                xaxis_title="Date",
                yaxis_title="Spread (bps)",
            )
            st.plotly_chart(fig_spread, use_container_width=True)
            st.caption(f"**Data Source:** DuckDB table `bhav` | **Date Range:** {d_range} | **Unit:** Basis points (bps) | **Carry Source:** `{carry_source}`")


# ==============================================================================
# Page 4: Spread Waterfall
# ==============================================================================
elif selected_page == "Spread Waterfall":
    st.header("🌊 Relative-Value Spread Waterfall")
    st.caption("Decomposes raw quote gap into purity adjustment, forward carry, tick floor, cost, and net edge.")

    if bhav_df.empty:
        st.warning("No data loaded in database.")
    else:
        col_pair, col_date = st.columns(2)
        pairs = ["GOLDTEN vs GOLDM", "GOLDPETAL vs GOLDM", "GOLDGUINEA vs GOLDM"]

        with col_pair:
            selected_pair = st.selectbox("Select Pair for Waterfall", pairs)
        with col_date:
            dates_available = sorted(bhav_df["date"].unique(), reverse=True)
            selected_date = st.selectbox(
                "Evaluation Date",
                dates_available,
                key="wf_date",
                format_func=lambda d: d.strftime("%Y-%m-%d"),
            )

        small_sym = selected_pair.split(" vs ")[0]
        ref_sym = selected_pair.split(" vs ")[1]

        day_small = bhav_df[(bhav_df["date"] == selected_date) & (bhav_df["symbol"] == small_sym)]
        day_ref = bhav_df[(bhav_df["date"] == selected_date) & (bhav_df["symbol"] == ref_sym)]

        if day_small.empty or day_ref.empty:
            st.warning("Insufficient quote data for this session.")
        else:
            r_small = day_small.iloc[0]
            r_ref = day_ref.iloc[0]

            # 1. Raw gap (per quote unit scaling only, no purity, no carry)
            spec_small = CONTRACT_SPECS.get(small_sym, {"lot_size_grams": 10})
            spec_ref = CONTRACT_SPECS.get(ref_sym, {"lot_size_grams": 100})

            # Quote units in grams: GOLDM: 10g, GOLDTEN: 10g, GOLDGUINEA: 8g, GOLDPETAL: 1g
            q_unit_small = 10.0 if small_sym in ("GOLDM", "GOLDTEN") else (8.0 if small_sym == "GOLDGUINEA" else 1.0)
            q_unit_ref = 10.0

            raw_ppg_small = float(r_small["close"]) / q_unit_small
            raw_ppg_ref = float(r_ref["close"]) / q_unit_ref  # Raw unadjusted for purity
            raw_gap_bps = 10000.0 * (raw_ppg_small - raw_ppg_ref) / raw_ppg_ref

            # 2. Purity gap (PPG999, adjusts GOLDM to 999)
            ppg_small = float(r_small["ppg999"])
            ppg_ref = float(r_ref["ppg999"])
            purity_gap_bps = 10000.0 * (ppg_small - ppg_ref) / ppg_ref

            # 3. Carry gap
            days_diff = (r_ref["expiry_date"] - r_small["expiry_date"]).days
            conn = duckdb.connect(database=DEFAULT_DB_PATH, read_only=True)
            carry_val, carry_source = compute_carry(conn, selected_date, theoretical_fallback=0.065)
            conn.close()

            adj_ppg_small = adjust_to_expiry(ppg_small, carry_val or 0.0, days_diff)
            carry_gap_bps = 10000.0 * (adj_ppg_small - ppg_ref) / ppg_ref

            # 4. Tick floor & cost
            tick_floor_bps = 1.30
            cost_res = compute_roundtrip_costs(1_000_000, 1_000_000)
            cost_bps = cost_res["total_bps"]

            stages = compute_waterfall(
                raw_gap_bps=raw_gap_bps,
                purity_gap_bps=purity_gap_bps,
                carry_gap_bps=carry_gap_bps,
                tick_floor_bps=tick_floor_bps,
                cost_bps=cost_bps,
            )

            x_labels = [s["stage"].title() for s in stages]
            measure_types = ["relative", "relative", "relative", "relative", "relative", "total"]
            deltas = [
                stages[0]["value"],
                stages[1]["delta"],
                stages[2]["delta"],
                stages[3]["delta"],
                stages[4]["delta"],
                stages[5]["value"],
            ]

            fig_wf = go.Figure(
                go.Waterfall(
                    name="Spread Attribution",
                    orientation="v",
                    measure=measure_types,
                    x=x_labels,
                    textposition="outside",
                    text=[f"{d:+.2f} bps" if m == "relative" else f"{d:.2f} bps" for d, m in zip(deltas, measure_types)],
                    y=deltas,
                    connector={"line": {"color": "rgb(63, 63, 63)"}},
                    decreasing={"marker": {"color": "#ef4444"}},
                    increasing={"marker": {"color": "#10b981"}},
                    totals={"marker": {"color": "#38bdf8"}},
                )
            )

            fig_wf.update_layout(
                title=f"Waterfall: {selected_pair} ({selected_date}) | Source: DuckDB | Unit: bps | Carry: {carry_source}",
                yaxis_title="Basis Points (bps)",
                template="plotly_dark",
                height=480,
            )
            st.plotly_chart(fig_wf, use_container_width=True)

            st.caption(f"**Data Source:** DuckDB `bhav` | **Evaluation Date:** {selected_date} | **Unit:** Basis points (bps) | **Carry Source:** `{carry_source}`")
            st.dataframe(pd.DataFrame(stages)[["stage", "value", "delta"]], use_container_width=True)


# ==============================================================================
# Page 5: Coverage
# ==============================================================================
elif selected_page == "Coverage":
    st.header("📋 Contract Coverage & Lifespan Matrix")
    st.caption("Detailed breakdown of session coverage and contract listings from DuckDB.")

    if listing_df.empty and coverage_df.empty:
        st.warning("No data loaded in database.")
    else:
        st.subheader("Contract Listing View (contract_listing)")
        if not listing_df.empty:
            st.dataframe(listing_df, use_container_width=True)

        st.subheader("Daily Contract Coverage (coverage)")
        if not coverage_df.empty:
            st.dataframe(coverage_df, use_container_width=True, height=400)


# ==============================================================================
# Page 6: Backtest
# ==============================================================================
elif selected_page == "Backtest":
    st.header("⚡ Backtest Performance & Execution Simulator")

    # Required placeholder from Part 3
    st.info("⚠️ **Not yet run** (Backtest engine pending Phase 6).")

    # Show statutory cost model from config
    st.subheader("MCX Statutory Cost Model Parameters")
    cost_data = [
        {"Fee Parameter": "Brokerage Rate", "Value": f"{BROKERAGE_RATE_PCT * 100:.2f}% (capped at ₹{BROKERAGE_MAX_PER_ORDER:.0f})", "Status": "VERIFIED (Standard Discount Broker)"},
        {"Fee Parameter": "Exchange Transaction Fee", "Value": f"{EXCHANGE_TRANSACTION_CHARGE_PCT * 100:.4f}%", "Status": "VERIFIED (MCX Circular)"},
        {"Fee Parameter": "Commodity Transaction Tax (CTT)", "Value": f"{CTT_SELL_PCT * 100:.2f}% (sell side)", "Status": "VERIFIED (Finance Act)"},
        {"Fee Parameter": "Goods & Services Tax (GST)", "Value": f"{GST_PCT * 100:.0f}% on charges", "Status": "VERIFIED (Statutory)"},
        {"Fee Parameter": "SEBI Turnover Fee", "Value": f"₹{SEBI_TURNOVER_FEE_PCT * 10000000:.0f} per crore", "Status": "VERIFIED (SEBI Circular)"},
        {"Fee Parameter": "Stamp Duty", "Value": f"{STAMP_DUTY_BUY_PCT * 100:.3f}% (buy side)", "Status": "VERIFIED (Indian Stamp Act)"},
        {"Fee Parameter": "GOLDPETAL Tender Period", "Value": f"{CONTRACT_SPECS['GOLDPETAL']['tender_period_days']} trading days", "Status": "UNVERIFIED (Conservative default)"},
    ]
    st.dataframe(pd.DataFrame(cost_data), use_container_width=True)

    st.subheader("Unverified Items Registry")
    for item_key, note in UNVERIFIED_ITEMS.items():
        st.warning(f"**UNVERIFIED [{item_key}]:** {note}")
