"""Streamlit dashboard. Computes everything in-session from user-uploaded
MCX Bhavcopy CSV files. No market data in the repository, no network calls,
and nothing written to disk.

Run: streamlit run app/dashboard.py --server.address localhost
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app import views  # noqa: E402
from src.aureus_lens.ingest.uploader import FileUploadReport, process_uploaded_files  # noqa: E402

# Categorical slots, validated for four series on a light surface.
SERIES = {"GOLDM": "#2a78d6", "GOLDTEN": "#eb6834", "GOLDGUINEA": "#1baf7a", "GOLDPETAL": "#eda100"}
MARKERS = {"GOLDM": "circle", "GOLDTEN": "square", "GOLDGUINEA": "diamond", "GOLDPETAL": "triangle-up"}
UP, DOWN, TOTAL = "#2a78d6", "#eb6834", "#898781"

st.set_page_config(page_title="Aureus Lens", layout="wide")

# In-session state initialization
if "store" not in st.session_state:
    st.session_state.store = views.load_data()
if "upload_reports" not in st.session_state:
    st.session_state.upload_reports = []
if "uploaded_hashes" not in st.session_state:
    st.session_state.uploaded_hashes = None

store = st.session_state.store


def show(view: views.View) -> None:
    st.header(view.title)
    st.caption(view.labels())
    for msg in view.messages:
        if msg.startswith(views.NO_SIGNAL) or view.empty:
            st.warning(msg)
        else:
            st.info(msg)
    for name, table in view.tables.items():
        st.subheader(name)
        if table.empty:
            st.write("(none)")
        else:
            st.dataframe(table, width="stretch", hide_index=True)


def chart_layout(fig, title, yaxis):
    fig.update_layout(title=title, yaxis_title=yaxis, template="plotly_white", height=420,
                      margin=dict(l=40, r=20, t=60, b=40), hovermode="closest")


pages = ["Upload", "Data Health", "Normalized View", "Spread Scanner", "Waterfall", "Coverage", "Backtest"]
page = st.sidebar.radio("Page", pages)
st.sidebar.caption(f"Read from: {store.origin or 'in-session uploads (none uploaded yet)'}")
st.sidebar.caption(f"Sessions stored: {len(store.sessions)}")

if page == "Upload":
    st.header("Upload Bhavcopy CSV Files")
    st.caption("Upload one or more MCX Bhavcopy CSV files (Format A or Format B). Files are processed strictly in memory.")

    uploaded = st.file_uploader(
        "Upload Bhavcopy CSV files",
        type=["csv"],
        accept_multiple_files=True,
        key="bhav_uploader",
    )

    if uploaded:
        # Check if upload set changed
        file_hashes = tuple((f.name, getattr(f, "size", 0)) for f in uploaded)
        if file_hashes != st.session_state.uploaded_hashes:
            derived, reports = process_uploaded_files(uploaded)
            st.session_state.store = derived
            st.session_state.upload_reports = reports
            st.session_state.uploaded_hashes = file_hashes
            store = derived

    if st.session_state.upload_reports:
        st.subheader("Upload Summary")
        summary_rows = []
        for r in st.session_state.upload_reports:
            summary_rows.append({
                "File Name": r.name,
                "Format": r.format,
                "Internal Date": r.internal_date,
                "Rows Kept": r.rows_kept,
                "Rejects": r.rejects,
                "Date Match": r.date_match,
                "Status": r.status,
                "Detail": r.detail,
            })
        st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)

        loaded_files = [r for r in st.session_state.upload_reports if r.status == "Loaded"]
        refused_files = [r for r in st.session_state.upload_reports if r.status != "Loaded"]
        total_kept = sum(r.rows_kept for r in loaded_files)

        cols = st.columns(3)
        cols[0].metric("Files Loaded", len(loaded_files))
        cols[1].metric("Files Refused", len(refused_files))
        cols[2].metric("Total Rows Stored", total_kept)

        # Reject breakdowns
        reject_breakdowns = []
        for r in st.session_state.upload_reports:
            for reason, count in r.reject_reasons.items():
                reject_breakdowns.append({
                    "File Name": r.name,
                    "Rejection Reason": reason,
                    "Count": count,
                })
        if reject_breakdowns:
            st.subheader("Rejected Row Details")
            st.dataframe(pd.DataFrame(reject_breakdowns), width="stretch", hide_index=True)
    else:
        st.info("Upload Bhavcopy CSV files to begin")

elif page == "Data Health":
    show(views.data_health_view(store))

elif page == "Normalized View":
    view = views.normalized_view(store)
    if not view.empty:
        day = st.selectbox("Session", store.sessions, index=len(store.sessions) - 1)
        b = view.tables["Price at 999, per gram"]
        fig = go.Figure()
        for sym, color in SERIES.items():
            s = b[(b["date"] == day) & (b["symbol"] == sym)].sort_values("expiry_date")
            fig.add_scatter(x=s["expiry_date"], y=s["ppg999"], name=sym, mode="lines+markers",
                            line=dict(color=color, width=2),
                            marker=dict(symbol=MARKERS[sym], size=9, color=color))
        chart_layout(fig, f"Close by expiry on {day} | {view.labels()}", "rupees per gram, 999")
        st.plotly_chart(fig, width="stretch")
    show(view)

elif page == "Spread Scanner":
    if store.empty:
        show(views.scanner_view(store))
    else:
        day = st.selectbox("Session", store.sessions, index=len(store.sessions) - 1)
        show(views.scanner_view(store, day))

elif page == "Waterfall":
    if store.empty:
        show(views.waterfall_view(store, None, None, None, None, None))
    else:
        day = st.selectbox("Session", store.sessions, index=len(store.sessions) - 1)
        opts = views.pair_options(store, day)
        labels = [f"{r.leg_a} {r.expiry_a} vs {r.leg_b} {r.expiry_b} ({views.KIND_LABEL[r.kind]})"
                  for r in opts.itertuples()]
        i = st.selectbox("Pair", range(len(labels)), format_func=lambda k: labels[k])
        r = opts.iloc[i]
        view = views.waterfall_view(store, day, r["kind"], r["leg_a"], r["expiry_a"], r["leg_b"])
        if view.tables:
            stages = next(iter(view.tables.values()))
            measure = ["absolute"] + ["relative"] * 4 + ["total"]
            fig = go.Figure(go.Waterfall(
                x=stages["stage"], measure=measure,
                y=[stages["value"].iloc[0]] + list(stages["delta"].iloc[1:5]) + [stages["value"].iloc[-1]],
                text=[f"{v:.2f}" for v in stages["value"]], textposition="outside",
                increasing=dict(marker=dict(color=UP)), decreasing=dict(marker=dict(color=DOWN)),
                totals=dict(marker=dict(color=TOTAL)), connector=dict(line=dict(color=TOTAL, width=1))))
            chart_layout(fig, f"{labels[i]} | {view.labels()}", "bps")
            st.plotly_chart(fig, width="stretch")
        show(view)

elif page == "Coverage":
    show(views.coverage_view(store))

elif page == "Backtest":
    show(views.backtest_view(store))
