# Aureus Lens

Relative-value analytics for four MCX gold futures: GOLDM, GOLDTEN,
GOLDGUINEA and GOLDPETAL. Built for Hack in Hills '26, Problem Statement 03.

The four contracts are the same metal in different sizes. The project
converts each price to rupees per gram of 999 gold, aligns expiries with a
carry estimate from the GOLDM curve, and asks whether the contracts price
consistently with each other, and whether any gap is large and unusual
enough to remain after transaction costs.

## Result

There is no result yet. The backtest has not been run. It needs a
contiguous history long enough for the 60-session z-score window plus the
validation and test periods, and fixed dates in
[PREREGISTRATION.md](PREREGISTRATION.md). The data loaded so far covers
four sessions (5, 6, 7 and 9 October 2026), which cannot support a finding.
"No persistent edge after costs" is an accepted outcome when the backtest
is run.

## Run it

Requires Python 3.11.

```
pip install -r requirements.txt
pytest
streamlit run app/dashboard.py --server.address localhost
```

Create and activate a virtual environment first if you want one
(`py -3.11 -m venv .venv` on Windows, `python3.11 -m venv .venv` elsewhere).
Dependencies are pinned to exact versions.

`--server.address localhost` matters for local runs: without a bound
address Streamlit looks up the machine's external IP at start-up, which is
a network call. The shared `.streamlit/config.toml` leaves the address unset
because Streamlit Community Cloud serves the app itself; usage stats are off
in both cases.

The app reads `data/aureus.duckdb` if it exists and otherwise the committed
snapshot in `data/snapshot/`, so a fresh clone shows the October 2026 data.

Public app: not deployed yet.

## Data

The project never downloads data. Bhavcopy files are downloaded by hand and
placed in `data/raw/`, which is not committed. Two layouts are read:

- Format A, from the MCX Bhavcopy page (`BhavCopyDateWise_DDMMYYYY.csv`).
- Format B, from Samco's Bhav Copy download (`YYYYMMDD_MCX.csv`).

To add data:

1. Download the day's Bhavcopy CSV by hand and save it in `data/raw/`
   without renaming it. The loader checks that the date in the file name
   matches the rows and refuses files where it does not.
2. `python -m scripts.load_csv data/raw/*.csv` loads them into the store,
   runs the continuity check and rewrites `docs/data_notes.md`.
3. `python scripts/build_snapshot.py` rebuilds `data/snapshot/` from the
   store for the public app. Commit the snapshot, never the CSVs.

See [docs/DATA_TERMS.md](docs/DATA_TERMS.md) for where the data comes from
and how it may be used.

## Layout

```
app/              dashboard.py (Streamlit) and views.py (page data, testable)
src/aureus_lens/  ingest (CSV loader), store (DuckDB), core (analytics),
                  reconcile (checks, data notes), snapshot
scripts/          load_csv.py, build_snapshot.py
tests/            pytest suite; fixtures are rows copied from real files
docs/             VERIFICATION.md, data_notes.md (generated), DATA_TERMS.md
data/snapshot/    derived tables used by the public app
```

## Checks

Every check is listed in [docs/VERIFICATION.md](docs/VERIFICATION.md) as
PASS, FAIL or NOT RUN with the command output. Tests that need the raw CSVs
skip in CI with a "NOT RUN" reason and are listed in the CI job summary;
they are not counted as passed.

## Limitations

- Four sessions of data. No z-score, carry or backtest result is shown.
- Bhavcopy closes are end-of-day prices. A gap between closes may not have
  been tradable at the same moment on both legs.
- GOLDTEN has a short history, and few festival seasons fall inside it.
- No exchange holiday calendar is used, so a missing weekday is marked
  unchecked rather than called a gap.
- Cost rates, tender periods, tick sizes and purity are not confirmed from
  MCX sources (below).

## UNVERIFIED

These values are placeholders. They are listed in `config.py` and on the
dashboard, and nothing depending on them should be read as fact.

| Item | Value used | What would verify it |
|---|---|---|
| Cost rates: brokerage, exchange charge, CTT, stamp duty, SEBI fee, GST | 0.03% capped at Rs 20; 0.0021%; 0.01% sell; 0.002% buy; Rs 10 per crore; 18% | Current MCX circular on transaction charges, the Finance Act and stamp duty notification, SEBI fee circular, a broker's published schedule |
| GOLDPETAL tender period | 5 days (placeholder; may be 3) | MCX contract specification or circular for GOLDPETAL |
| GOLDGUINEA tender period | 3 days | Read circular MCX/TRD/456/2025 itself, not the secondary summary |
| GOLDM and GOLDTEN tender periods, carry buffer | 3 days | MCX contract specifications |
| Tick sizes | 1.0 for all four | MCX contract specifications |
| Purity | GOLDM 995, others 999 | MCX contract specifications |
| GOLDTEN launch date | 1 April 2025 | MCX launch circular |
| Exchange holidays | none used | MCX holiday list for each year loaded |
| MCX post figure for 21 Jan 2026 | not used | It does not reconcile with the bhavcopy file (8,239.66 crore for the three small contracts) and is excluded from all outputs |

Parameters chosen by the team rather than derived (z-score window and
min_periods of 60, z threshold 2.0, cost multiple 2, stale-carry limit of
5 sessions, carry minimum of 5 sessions, Rs 1,000,000 notional) are listed
in [PREREGISTRATION.md](PREREGISTRATION.md).

This project is for analysis. It is not trading advice.
