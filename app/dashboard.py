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
    from src.aureus_lens.store.db import DEFAULT_DB_PATH
    from config import PROJECT_ROOT
    _snapshot = PROJECT_ROOT / "data" / "snapshot"
    st.session_state.store = views.load_data(
        store_path=PROJECT_ROOT / DEFAULT_DB_PATH,
        snapshot_dir=_snapshot if _snapshot.exists() else None,
    )
if "upload_reports" not in st.session_state:
    st.session_state.upload_reports = []
if "uploaded_hashes" not in st.session_state:
    st.session_state.uploaded_hashes = None

store = st.session_state.store


# ── helpers ────────────────────────────────────────────────────────────────────

def page_header(view: views.View) -> None:
    """Render title + one-line caption with full labels in expander."""
    st.header(view.title)
    # Compact caption: Source and date-range only
    parts = view.labels().split(" | ")
    short = " · ".join(p for p in parts if p.startswith(("Source:", "Dates:")))
    st.caption(short)
    with st.expander("▸ Full source / unit details", expanded=False):
        st.write(view.labels())


def show_messages(view: views.View) -> None:
    """Show at most one message box (collapsed for multi-messages)."""
    if not view.messages:
        return
    msg = view.messages[0]
    is_warn = msg.startswith(views.NO_SIGNAL) or view.empty
    if len(view.messages) == 1:
        if is_warn:
            st.warning(msg)
        else:
            st.info(msg)
    else:
        # Collapse extra messages into an expander
        if is_warn:
            st.warning(msg)
        else:
            st.info(msg)
        if len(view.messages) > 1:
            with st.expander("More details", expanded=False):
                for m in view.messages[1:]:
                    st.write(m)


def show_table(name: str, table: pd.DataFrame) -> None:
    st.subheader(name)
    if table.empty:
        st.write("(none)")
    else:
        st.dataframe(table, use_container_width=True, hide_index=True)


def show(view: views.View) -> None:
    """Default page renderer: header + messages + all tables."""
    page_header(view)
    show_messages(view)
    for name, table in view.tables.items():
        show_table(name, table)


def chart_layout(fig, title, yaxis):
    fig.update_layout(
        title=title, yaxis_title=yaxis, template="plotly_white", height=420,
        margin=dict(l=40, r=20, t=60, b=40), hovermode="closest",
    )


# Reason icon mapping for scanner short-codes
_REASON_ICONS = {
    "below 2x cost": "💸 spread",
    "inside tender buffer": "📅 tender",
    "stale price": "🔁 stale",
    "no carry estimate": "📉 carry",
}


def _shorten_reason(reason: str) -> str:
    """Map a reason string to a short icon+label."""
    r = reason.lower()
    if "x cost" in r:
        return "💸 spread"
    if "tender" in r:
        return "📅 tender"
    if "volume 0" in r or "unchanged" in r:
        return "🔁 stale"
    if "carry" in r:
        return "📉 carry"
    if "history" in r or "baseline" in r:
        return "⏳ history"
    return "⚠ gate"


# ── sidebar ────────────────────────────────────────────────────────────────────

pages = ["Intro", "Upload", "Data Health", "Normalized View", "Spread Scanner", "Waterfall", "Coverage", "Backtest"]
page = st.sidebar.radio("Page", pages)
st.sidebar.caption(f"Read from: {store.origin or 'in-session uploads (none yet)'}")
st.sidebar.caption(f"Sessions: {len(store.sessions)}")


# ══════════════════════════════════════════════════════════════════════════════
# INTRO
# ══════════════════════════════════════════════════════════════════════════════

if page == "Intro":
    st.markdown(
        """
        <div style="text-align: center; padding: 3rem 1rem 1.5rem;">
            <h1 style="font-size: 3rem; font-weight: 800; letter-spacing: -1px; margin-bottom: 0.4rem;">
                ✨ Aureus Lens
            </h1>
            <p style="font-size: 1.1rem; color: #555; max-width: 540px; margin: 0 auto 1.5rem;">
                Relative-value analytics for MCX gold futures.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)
    col1.info("**Normalise** — convert every contract to ₹/gram of 999 gold, adjusting for purity and carry.")
    col2.info("**Scan** — flag spreads that exceed transaction costs and pass the gate filters.")
    col3.info("**Waterfall** — decompose each spread into raw, purity, carry, tick-floor and cost steps.")

    # Show a small sparkline of normalized prices if data is loaded
    if not store.empty:
        day = store.sessions[-1]
        n = store.normalized
        today = n[n["date"] == day]
        fig = go.Figure()
        for sym, color in SERIES.items():
            s = today[today["symbol"] == sym].sort_values("expiry_date")
            if not s.empty:
                fig.add_scatter(
                    x=s["expiry_date"], y=s["ppg999"].round(2), name=sym,
                    mode="lines+markers",
                    line=dict(color=color, width=2),
                    marker=dict(symbol=MARKERS[sym], size=8, color=color),
                )
        fig.update_layout(
            title=f"Latest session: {day} — price at 999, per gram (₹)",
            template="plotly_white", height=320,
            margin=dict(l=40, r=20, t=50, b=30), hovermode="closest",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Upload Bhavcopy CSV files (Upload page) to populate charts.")

    st.caption("Built for **Hack in Hills** · Powered by **Tinyfish**")


# ══════════════════════════════════════════════════════════════════════════════
# UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Upload":
    st.header("Upload Bhavcopy CSV Files")
    st.caption("Format A or Format B. Processed strictly in memory — nothing written to disk.")

    uploaded = st.file_uploader(
        "Upload Bhavcopy CSV files",
        type=["csv"],
        accept_multiple_files=True,
        key="bhav_uploader",
    )

    if uploaded:
        file_hashes = tuple((f.name, getattr(f, "size", 0)) for f in uploaded)
        if file_hashes != st.session_state.uploaded_hashes:
            derived, reports = process_uploaded_files(uploaded)
            st.session_state.store = derived
            st.session_state.upload_reports = reports
            st.session_state.uploaded_hashes = file_hashes
            store = derived

    if st.session_state.upload_reports:
        loaded_files = [r for r in st.session_state.upload_reports if r.status == "Loaded"]
        refused_files = [r for r in st.session_state.upload_reports if r.status != "Loaded"]
        total_kept = sum(r.rows_kept for r in loaded_files)

        cols = st.columns(3)
        cols[0].metric("Files Loaded", len(loaded_files))
        cols[1].metric("Files Refused", len(refused_files))
        cols[2].metric("Total Rows Stored", total_kept)

        st.subheader("Upload Summary")
        summary_rows = [
            {
                "File": r.name, "Format": r.format, "Date": r.internal_date,
                "Kept": r.rows_kept, "Rejects": r.rejects,
                "Status": r.status, "Detail": r.detail,
            }
            for r in st.session_state.upload_reports
        ]
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        reject_breakdowns = [
            {"File": r.name, "Reason": reason, "Count": count}
            for r in st.session_state.upload_reports
            for reason, count in r.reject_reasons.items()
        ]
        if reject_breakdowns:
            with st.expander("Rejected row details", expanded=False):
                st.dataframe(pd.DataFrame(reject_breakdowns), use_container_width=True, hide_index=True)
    else:
        st.info("Upload Bhavcopy CSV files to begin.")


# ══════════════════════════════════════════════════════════════════════════════
# DATA HEALTH
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Data Health":
    view = views.data_health_view(store)
    page_header(view)
    show_messages(view)

    if view.empty:
        # Empty path — just show NOT RUN table
        for name, table in view.tables.items():
            show_table(name, table)
    else:
        # ── Continuity metric cards ──────────────────────────────────────────
        counts = view.tables.get("Continuity (previous close vs prior stored close)")
        if counts is not None and not counts.empty:
            st.subheader("Continuity (previous close vs prior stored close)")
            cnt = counts.set_index("status")["rows"]
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("✅ ok", int(cnt.get("ok", 0)))
            c2.metric("🔴 gap", int(cnt.get("gap", 0)))
            c3.metric("⬜ unchecked", int(cnt.get("unchecked", 0)))
            c4.metric("🆕 new", int(cnt.get("new", 0)))
            c5.metric("1️⃣ first", int(cnt.get("first", 0)))

        # ── Continuity gaps expander ─────────────────────────────────────────
        gaps = view.tables.get("Continuity gaps (unexplained)", pd.DataFrame())
        with st.expander(f"Continuity gaps — unexplained ({len(gaps)} rows)", expanded=not gaps.empty):
            if gaps.empty:
                st.write("No gap rows.")
            else:
                st.dataframe(gaps, use_container_width=True, hide_index=True)

        # ── Files loaded ─────────────────────────────────────────────────────
        files = view.tables.get("Files loaded")
        if files is not None:
            show_table("Files loaded", files)

        # ── Value check exclusions expander ──────────────────────────────────
        excl = view.tables.get("Value check exclusions (zero volume)", pd.DataFrame())
        with st.expander(f"Value check exclusions — zero volume ({len(excl)} rows)", expanded=not excl.empty):
            if excl.empty:
                st.write("No zero-volume exclusions.")
            else:
                st.dataframe(excl, use_container_width=True, hide_index=True)

        # ── Files not stored ─────────────────────────────────────────────────
        refused = view.tables.get("Files not stored")
        if refused is not None:
            show_table("Files not stored", refused)

        # ── NOT RUN checks expander ──────────────────────────────────────────
        not_run = view.tables.get("NOT RUN checks (docs/VERIFICATION.md)")
        if not_run is not None:
            with st.expander(f"NOT RUN checks — {len(not_run)} items", expanded=False):
                if not_run.empty:
                    st.write("All checks run.")
                else:
                    st.dataframe(not_run, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# NORMALIZED VIEW
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Normalized View":
    view = views.normalized_view(store)
    page_header(view)
    show_messages(view)

    if not view.empty:
        day = st.selectbox("Session", store.sessions, index=len(store.sessions) - 1)
        b = view.tables["Price at 999, per gram"]
        fig = go.Figure()
        for sym, color in SERIES.items():
            s = b[(b["date"] == day) & (b["symbol"] == sym)].sort_values("expiry_date")
            fig.add_scatter(
                x=s["expiry_date"], y=s["ppg999"], name=sym, mode="lines+markers",
                line=dict(color=color, width=2),
                marker=dict(symbol=MARKERS[sym], size=9, color=color),
            )
        chart_layout(fig, f"Close by expiry — {day}", "rupees per gram, 999")
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("Raw table — price at 999, per gram", expanded=False):
            st.dataframe(b, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# SPREAD SCANNER
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Spread Scanner":
    if store.empty:
        show(views.scanner_view(store))
    else:
        day = st.selectbox("Session", store.sessions, index=len(store.sessions) - 1)
        view = views.scanner_view(store, day)

        page_header(view)
        show_messages(view)

        carry_tbl = view.tables.get("Carry from GOLDM curve (per year, continuous)")

        for kind_label in views.PAIR_TABLES:
            table = view.tables.get(kind_label)
            if table is None:
                continue

            st.subheader(kind_label)

            # Build a display copy with short-code failing reasons
            display = table.copy()
            if "failing reasons" in display.columns:
                # Short icon codes; full text available in the expander below
                display["reasons"] = display["failing reasons"].map(
                    lambda txt: " · ".join(_shorten_reason(r.strip()) for r in txt.split(";") if r.strip())
                    if txt else ""
                )
                # Drop verbose column from main view; keep short one
                display = display.drop(columns=["failing reasons"])
                # Reorder: put short reasons near gate
                cols_order = [c for c in display.columns if c not in ("reasons", "status")]
                gate_idx = cols_order.index("gate") if "gate" in cols_order else len(cols_order)
                cols_order.insert(gate_idx + 1, "reasons")
                if "status" in display.columns:
                    cols_order.append("status")
                display = display[cols_order]

            st.dataframe(display, use_container_width=True, hide_index=True)

            # Full failing-reasons detail in expander
            if "failing reasons" in table.columns:
                failed = table[table["failing reasons"] != ""]
                if not failed.empty:
                    with st.expander(f"Full gate-fail reasons ({len(failed)} rows)", expanded=False):
                        st.dataframe(
                            failed[["pair", "gate", "failing reasons"]],
                            use_container_width=True, hide_index=True,
                        )

        # Carry table in expander
        if carry_tbl is not None:
            with st.expander("Carry from GOLDM curve (per year, continuous)", expanded=False):
                st.dataframe(carry_tbl, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# WATERFALL
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Waterfall":
    if store.empty:
        show(views.waterfall_view(store, None, None, None, None, None))
    else:
        day = st.selectbox("Session", store.sessions, index=len(store.sessions) - 1)
        opts = views.pair_options(store, day)
        labels = [
            f"{r.leg_a} {r.expiry_a} vs {r.leg_b} {r.expiry_b} ({views.KIND_LABEL[r.kind]})"
            for r in opts.itertuples()
        ]
        i = st.selectbox("Pair", range(len(labels)), format_func=lambda k: labels[k])
        r = opts.iloc[i]
        view = views.waterfall_view(store, day, r["kind"], r["leg_a"], r["expiry_a"], r["leg_b"])

        st.header("Waterfall")
        # Compact caption
        st.caption(f"{labels[i]}  ·  {day}")
        with st.expander("▸ Full source / unit details", expanded=False):
            st.write(view.labels())

        # One status line only
        if view.messages:
            msg = view.messages[0]
            if "UNVERIFIED" in msg:
                st.info(msg)
            else:
                st.warning(msg)

        if view.tables:
            stages = next(iter(view.tables.values()))
            measure = ["absolute"] + ["relative"] * 4 + ["total"]
            fig = go.Figure(go.Waterfall(
                x=stages["stage"], measure=measure,
                y=[stages["value"].iloc[0]] + list(stages["delta"].iloc[1:5]) + [stages["value"].iloc[-1]],
                text=[f"{v:.2f}" for v in stages["value"]], textposition="outside",
                increasing=dict(marker=dict(color=UP)), decreasing=dict(marker=dict(color=DOWN)),
                totals=dict(marker=dict(color=TOTAL)), connector=dict(line=dict(color=TOTAL, width=1)),
            ))
            chart_layout(fig, labels[i], "bps")
            st.plotly_chart(fig, use_container_width=True)

            # Raw table in expander
            tbl_name = next(iter(view.tables))
            with st.expander("Stage values (table)", expanded=False):
                st.dataframe(stages, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# COVERAGE
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Coverage":
    view = views.coverage_view(store)
    page_header(view)
    show_messages(view)
    for name, table in view.tables.items():
        show_table(name, table)


# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Backtest":
    view = views.backtest_view(store)
    page_header(view)
    # Single info box max
    if view.messages:
        st.warning(view.messages[0])
    for name, table in view.tables.items():
        show_table(name, table)
