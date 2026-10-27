"""Streamlit dashboard. Reads the local DuckDB store if present, otherwise the
committed snapshot in data/snapshot/, and files in docs/. No network calls.

Run: streamlit run app/dashboard.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app import views  # noqa: E402
from src.aureus_lens.store.db import DEFAULT_DB_PATH  # noqa: E402

# Categorical slots, validated for four series on a light surface. Contrast
# is below 3:1 for two of them, so every chart has a table and marker shapes.
SERIES = {"GOLDM": "#2a78d6", "GOLDTEN": "#eb6834", "GOLDGUINEA": "#1baf7a", "GOLDPETAL": "#eda100"}
MARKERS = {"GOLDM": "circle", "GOLDTEN": "square", "GOLDGUINEA": "diamond", "GOLDPETAL": "triangle-up"}
UP, DOWN, TOTAL = "#2a78d6", "#eb6834", "#898781"

st.set_page_config(page_title="Aureus Lens", layout="wide")


@st.cache_data(ttl=60)
def load():
    return views.load_data(ROOT / DEFAULT_DB_PATH, ROOT / "data" / "snapshot")


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


store = load()
pages = ["Data Health", "Normalized View", "Spread Scanner", "Waterfall", "Coverage", "Backtest"]
page = st.sidebar.radio("Page", pages)
st.sidebar.caption(f"Read from: {store.origin or 'nothing (no store or snapshot)'}")
st.sidebar.caption(f"Sessions stored: {len(store.sessions)}")

if page == "Data Health":
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
