# Verification

Every item below is PASS, FAIL or NOT RUN. An item is PASS only when the
command shown was run and its output is quoted. Commands were run on
Windows 11 with Python 3.11.9 in a venv built from `requirements.txt`.

## Step 0: baseline cleanup

| # | Check | Result |
|---|-------|--------|
| 0.1 | Baseline test suite runs before any change | PASS |
| 0.2 | Baseline DuckDB file holds no data | PASS |
| 0.3 | Test suite passes after removing the fetch client and frontend | PASS |
| 0.4 | No network code or MCX URLs remain in tracked files | PASS |

### 0.1 Baseline tests

```
$ python -m pytest -q -p no:cacheprovider
...................................................                      [100%]
51 passed in 7.35s
```

These 51 tests included 18 for the removed MCX client and 1 for the removed
backfill. Passing tests are not evidence that the analytics are correct;
several used invented prices. They are reviewed in Step 3.

### 0.2 Baseline database

```
$ python -c "import duckdb; c=duckdb.connect('data/aureus.duckdb', read_only=True); ..."
bhav (0,)
data_health (0,)
coverage (0,)
[]
```

### 0.3 Tests after cleanup

```
$ python -m pytest -q -p no:cacheprovider
.................................                                        [100%]
33 passed in 1.15s
```

### 0.4 Network references

```
$ git grep -nE "requests|mcxindia|User-Agent" -- . ':!docs'
$ echo $?
1
```

Exit code 1 means no matches.

## Step 1: CSV loader

| # | Check | Test | Result |
|---|-------|------|--------|
| 1.1 | Format A and B detected from header | `test_detects_format_a`, `test_detects_format_b` | PASS |
| 1.2 | Unknown header raises ValueError naming missing columns | `test_unknown_header_*`, `test_cli_returns_error_on_unknown_header` | PASS |
| 1.3 | Only FUTCOM rows for the four targets kept; OPTFUT, FUTIDX, OPTIDX and GOLD 1 kg rejected with a reason | `test_keeps_only_target_futures`, `test_rejects_have_reasons` | PASS |
| 1.4 | No row dropped silently (kept + rejected = source rows) | `test_every_source_row_is_kept_or_rejected` | PASS |
| 1.5 | Space padding stripped | `test_space_padding_stripped` | PASS |
| 1.6 | Blank OHLC (format A) becomes NaN, row kept with zero_volume True | `test_format_a_blank_ohlc_is_nan_and_row_kept` | PASS |
| 1.7 | Zero OHLC on a zero-volume row (format B) becomes NaN | `test_format_b_zero_ohlc_on_zero_volume_is_nan` | PASS |
| 1.8 | Value(Lacs) within 0.5% of lots x lot grams x close per quote unit, 9 Oct 2026 sample rows | `test_value_matches_lots_times_close_in_sample` | PASS |
| 1.9 | Same check, all 23 active target futures in the full 9 Oct 2026 file | `test_value_matches_lots_times_close_full_09102026` | PASS locally; NOT RUN where the file is absent (CI) |
| 1.10 | GOLDTEN + GOLDGUINEA + GOLDPETAL value on 21 Jan 2026 = 8,239.66 crore, in both the format A and format B full files | `test_small_contract_value_21012026` | PASS locally; NOT RUN where the files are absent (CI) |
| 1.11 | Format A and format B files for 21 Jan 2026 give identical rows | `test_both_formats_agree_for_21012026` | PASS locally; NOT RUN where the files are absent (CI) |

Fixtures are rows copied unchanged from the source files. Each fixture line
was checked against its source with `grep -qxF` and none were missing.

Observation, not a documented rule: format B writes `0` for Open, High and
Low on zero-volume rows where format A leaves them blank (GOLD 1 kg,
expiry 4 Dec 2026, in both 21 Jan 2026 files).

### Test run with full files present

```
$ python -m pytest -p no:cacheprovider -rs -v
...
tests/test_csv_loader.py::test_value_matches_lots_times_close_full_09102026 PASSED
tests/test_csv_loader.py::test_small_contract_value_21012026[path0] PASSED
tests/test_csv_loader.py::test_small_contract_value_21012026[path1] PASSED
tests/test_csv_loader.py::test_both_formats_agree_for_21012026 PASSED
...
============================= 57 passed in 5.70s ==============================
```

### Test run with data/raw/ removed

```
$ python -m pytest -p no:cacheprovider -q -rs tests/test_csv_loader.py
..................ssss..                                                 [100%]
SKIPPED [1] tests\test_csv_loader.py:180: NOT RUN: BhavCopyDateWise_09102026.csv not in data/raw/
SKIPPED [1] tests\test_csv_loader.py:189: NOT RUN: BhavCopyDateWise_21012026.csv not in data/raw/
SKIPPED [1] tests\test_csv_loader.py:189: NOT RUN: 20260121_MCX.csv not in data/raw/
SKIPPED [1] tests\test_csv_loader.py:199: NOT RUN: 20260121_MCX.csv not in data/raw/
20 passed, 4 skipped in 1.75s
```

### Loader on full files (reject counts)

```
data/raw/20260121_MCX.csv               B  24 kept  59666 rejected
  {'instrument OPTFUT': 58464, 'instrument OPTIDX': 1078, 'symbol not targeted': 110,
   'instrument FUTIDX': 8, 'GOLD 1 kg contract excluded': 6}
data/raw/BhavCopyDateWise_21012026.csv  A  24 kept  59666 rejected  (same counts)
data/raw/BhavCopyDateWise_09102026.csv  A  24 kept  15345 rejected
  {'instrument OPTFUT': 14616, 'instrument OPTIDX': 584, 'symbol not targeted': 134,
   'instrument FUTIDX': 6, 'GOLD 1 kg contract excluded': 5}
```

## Step 2: storage and pipeline

| # | Check | Test or command | Result |
|---|-------|-----------------|--------|
| 2.1 | bhav has primary key (date, symbol, expiry_date) and the loader columns | `test_primary_key_is_date_symbol_expiry`, `test_bhav_columns_match_loader_schema` | PASS |
| 2.2 | Reloading a file leaves bhav, load_log and reject_counts unchanged | `test_reload_is_idempotent` | PASS |
| 2.3 | Running load_csv twice stores 0 new rows and writes identical notes | `test_load_command_is_idempotent`, and the real-file run below | PASS |
| 2.4 | load_csv reports per file: format, dates, rows per symbol, rejects by reason, value per contract in crore | `test_cli_reports_both_samples`, run below | PASS |
| 2.5 | Continuity: rows separated by missing weekdays are logged as unchecked, not as gaps | `test_missing_weekdays_mark_rows_unchecked_not_gap` | PASS |
| 2.6 | Continuity: previous_close equals prior close on adjacent real sessions | `test_continuity_on_adjacent_real_sessions` | PASS since step 3 (6 Oct: ok 23, new 1; 7 Oct: ok 24). Was NOT RUN in step 2 |
| 2.7 | Reported value lies within lots x [low, high] for every active row | `test_full_file_values_within_low_high_range` | PASS (47 of 47 rows, both dates) |
| 2.8 | docs/data_notes.md is generated by code and reproducible | regenerated from an empty store; `git diff` shows no change | PASS |
| 2.9 | Data notes never contain the unreconciled MCX post figure | `test_notes_never_contain_unreconciled_mcx_figure` | PASS |
| 2.10 | Tests do not write to data/ or docs/ | full suite run with no store present; `ls data docs` afterwards showed neither file | PASS |

The `ok` and `gap` branches of the continuity check are not covered by any
test. Covering them needs two adjacent trading sessions; inventing prices
for a test is not allowed.

On 21 Jan 2026 the reported value differs from lots x close by up to 1.79%
(GOLDM). The intraday range that day was about 5%, so close is a poor proxy
for the traded price. All rows lie inside the low-high range. The 0.5%
check against close holds on 9 Oct 2026 (largest difference 0.255%).

### Real-file load from an empty store

```
$ python -m scripts.load_csv data/raw/20260121_MCX.csv data/raw/BhavCopyDateWise_21012026.csv data/raw/BhavCopyDateWise_09102026.csv
file:    data\raw\20260121_MCX.csv
stored:  24 new rows
file:    data\raw\BhavCopyDateWise_21012026.csv
stored:  0 new rows
file:    data\raw\BhavCopyDateWise_09102026.csv
stored:  24 new rows
continuity: first 24, unchecked 24
```

The second file adds no rows because it holds the same 21 Jan 2026 rows as
the first, in the other format.

### Test run

```
$ python -m pytest -p no:cacheprovider -q -rs
SKIPPED [1] tests\test_reconcile.py:76: NOT RUN: no two adjacent trading sessions in data/raw/
72 passed, 1 skipped in 16.01s
```

## Step 3: core analytics

Data: 5, 6, 7 and 9 Oct 2026. `BhavCopyDateWise_08102026.csv` has the same
MD5 as the 9 Oct file and every row is dated 9 Oct, so it is refused and
8 Oct is missing. Fixtures in `tests/fixtures/oct2026/` are the target
FUTCOM rows of the other four files, copied unchanged (96 rows, each
checked with `grep -qxF` against its source).

Hand-checked values were computed with plain arithmetic on the closes, not
with the project code:

```
carry 5 Oct 0.097737  9 Oct 0.11101
PETAL-TEN 36.6213  GUINEA-TEN 31.8027  GUINEA-PETAL -4.801
TEN vs GOLDM raw 21.9143 purity -18.2134 aligned 15045.8726 carry 0.0182
tick PETAL+TEN 0.7287
pair cost 4.3824
z-score PETAL-TEN 9 Oct, window 3: median 42.3343, MAD 2.2739, z -1.6946
```

| # | Check | Test | Result |
|---|-------|------|--------|
| 3.1 | Normalization hand checks: GOLDM 150000 -> 15060.30; GOLDTEN 150600, GOLDGUINEA 120480, GOLDPETAL 15060 -> 15060.00 | `test_hand_checked_values` | PASS |
| 3.2 | Normalization on real 9 Oct rows | `test_real_rows_9_oct` | PASS |
| 3.3 | Carry from GOLDM curve, hand-checked on 9 Oct (0.111010) and 5 Oct (0.097737) | `test_hand_checked_carry_9_oct`, `test_expiry_inside_buffer_excluded_5_oct` | PASS |
| 3.4 | Carry excludes an expiry inside the buffer (GOLDM 5 Oct 2026 on 5 Oct) and zero-volume expiries | same, `test_zero_volume_expiry_excluded` | PASS |
| 3.5 | Carry uses only data up to each date | `test_series_uses_no_later_data` | PASS |
| 3.6 | carry_source empirical, stale, none | `test_series_all_empirical_for_october`, `test_stale_when_curve_missing`, `test_none_without_any_curve` | PASS |
| 3.7 | Spreads hand-checked: small-small and small-GOLDM with purity and carry steps | `test_small_small_hand_checked`, `test_small_goldm_hand_checked` | PASS |
| 3.8 | Z-score baseline uses shift(1) | `test_baseline_is_lagged`, `test_hand_checked_real_spread` | PASS |
| 3.9 | MAD computed inside each window | `test_mad_inside_window_not_global`, `test_min_periods_below_window_uses_available_history` | PASS (the second fails on the old code, checked by running it against the previous signals.py) |
| 3.10 | Zero MAD returns NaN | `test_zero_mad_gives_nan_not_inf` | PASS |
| 3.11 | Gate returns every failing reason | `test_returns_every_failing_reason` (4 reasons from real rows) | PASS |
| 3.12 | Gate uses per-symbol tender periods (GOLDPETAL 5 days) | `test_petal_uses_its_own_five_day_buffer` | PASS |
| 3.13 | Waterfall keeps sign and floors edge at zero | `test_negative_gap_keeps_sign`, `test_edge_floored_at_zero`, `test_deltas_sum_to_edge_minus_raw` | PASS |
| 3.14 | Costs match the hand-checked example (buy 69.56, sell 149.56) with UNVERIFIED rates | `tests/test_costs.py` | PASS |
| 3.15 | No signal without enough history | `test_no_signal_without_history` | PASS |
| 3.16 | A misnamed file is refused, logged once, and listed in the notes | `test_file_named_for_another_date_is_refused` | PASS |

Notes:

- Two inputs in tests are not copied from files: the GOLDPETAL tender test
  moves a real row's trade date to 26 Oct to reach 4 days to expiry, and
  the stale-close test sets one real row's close equal to its previous
  close. Prices are not invented in either case.
- The z-score arithmetic tests use plain number series (1, 2, 3, ...).
  They are not prices.
- Four sessions are fewer than `min_periods` (10), so every z-score is NaN
  and no pair signals.
- On 9 Oct 2026, GOLDGUINEA is 31 to 47 bps and GOLDPETAL 36 to 53 bps above
  GOLDTEN on every shared expiry. Both clear the cost hurdle. With four
  sessions this cannot be called a mispricing, since it may be the usual
  level for these pairs. The cause is not established.

### Test run

```
$ python -m pytest -p no:cacheprovider -q -rs
102 passed in 30.80s
```

## Step 5: pre-registration and dashboard

The store was rebuilt from the October 2026 files only (5, 6, 7 and 9 Oct;
the 8 Oct file is refused). The 21 Jan 2026 files stay in data/raw/ for the
loader tests but are not in the store.

| # | Check | Evidence | Result |
|---|-------|----------|--------|
| 5.1 | PREREGISTRATION.md committed before the dashboard | commit c1c5323 precedes d492a7b and fc9a612 (originally 8702bc2 precedes 24750c1 and f3a305a prior to history rewrite) | PASS |
| 5.2 | Train, validation and test dates are placeholders; no `pre-registration` tag | file text; `git tag` lists nothing | PASS |
| 5.3 | Hypotheses H0 to H5 written as in the brief | brief text with H0 to H5 not available | NOT RUN |
| 5.4 | Every view shows source, date range and unit; carry_source on scanner and waterfall | `test_every_view_has_source_dates_and_unit`, `test_carry_source_shown_where_carry_is_used` | PASS |
| 5.5 | Below 60 sessions the z-score shows "insufficient history (X of 60 sessions)" and no number | `test_zscore_column_shows_insufficient_history_not_numbers` | PASS |
| 5.6 | No signal below the window, even if the code path marks one | `test_no_signal_below_window_even_if_code_would_signal` | PASS |
| 5.7 | "No actionable signal" with reasons when nothing signals | `test_no_actionable_signal_with_reasons` | PASS |
| 5.8 | Small-small pairs listed first; GOLDM pairs labelled "depends on purity assumption" | `test_small_small_first_and_goldm_labelled` | PASS |
| 5.9 | Gate shows every failing reason | `test_all_failing_reasons_listed` | PASS |
| 5.10 | Waterfall stages in order, sign kept, edge floored at zero | `test_waterfall_stage_order_and_values`, step 3 waterfall tests | PASS |
| 5.11 | Coverage flags the missing weekday as unchecked | `test_coverage_flags_missing_weekday_as_unchecked` | PASS |
| 5.12 | Backtest page shows only "Not run" and cost rates marked UNVERIFIED | `test_backtest_lists_every_cost_rate_unverified`, page dump | PASS |
| 5.13 | Empty state on every page with no store | `test_empty_store_shows_empty_state_on_every_page`; AppTest run with the store moved away, 0 exceptions on all six pages | PASS |
| 5.14 | Unreconciled MCX figure appears on no page | `test_no_view_shows_unreconciled_mcx_figure` | PASS |
| 5.15 | All six pages render in Streamlit without exceptions | AppTest run below | PASS |
| 5.16 | `streamlit run app/dashboard.py` starts and serves the page | health endpoint `ok`, page HTTP 200 | PASS |
| 5.17 | No network calls from the app | grep below; Streamlit external-IP lookup disabled by `.streamlit/config.toml` | PASS for project code and Streamlit start-up; Streamlit internals beyond start-up not audited |
| 5.18 | Fresh clone shows data | fresh clone test, item 6.12 | PASS since step 6; was NOT RUN in step 5 |
| 5.19 | Tests do not write to data/ or docs/ | smoke test checks store mtime unchanged; other view tests use in-memory stores | PASS |

### AppTest render, real store

```
===== Data Health | exceptions: 0 | plotly charts: 0
===== Normalized View | exceptions: 0 | plotly charts: 1
===== Spread Scanner | exceptions: 0 | plotly charts: 0
msg: No actionable signal. Reasons: history below 60 sessions (4 of 60); below 2x cost: 8 pairs
===== Waterfall | exceptions: 0 | plotly charts: 1
===== Coverage | exceptions: 0 | plotly charts: 0
===== Backtest | exceptions: 0 | plotly charts: 0
msg: Not run: awaiting contiguous history and pre-registration
```

### AppTest render, no store

```
NO STORE | Data Health | exceptions: 0 | ['The store has no rows. Load CSV files with: python -m scripts.load_csv data/raw/*.csv']
NO STORE | Normalized View | exceptions: 0 | [same]
NO STORE | Spread Scanner | exceptions: 0 | [same]
NO STORE | Waterfall | exceptions: 0 | [same]
NO STORE | Coverage | exceptions: 0 | [same]
NO STORE | Backtest | exceptions: 0 | ['Not run: awaiting contiguous history and pre-registration']
```

### Server start

Before `.streamlit/config.toml`, the start-up log printed
`External URL: http://104.28.225.15:8599`, which Streamlit gets from
`checkip.amazonaws.com` (`streamlit/net_util.py`, called from
`web/bootstrap.py` only when `server.address` is not set). After:

```
$ streamlit run app/dashboard.py --server.port 8599
Uvicorn server started on localhost:8599
  URL: http://localhost:8599
$ curl localhost:8599/_stcore/health
ok
$ curl -o /dev/null -w "%{http_code}" localhost:8599/
200
```

### Network grep

```
$ grep -rnE "requests|urllib|http\.client|socket|httpx|mcxindia" --include=*.py app src scripts config.py
$ echo $?
1
```

### Test run

```
$ python -m pytest -p no:cacheprovider -v -rs
============================ 120 passed in 40.34s =============================
```

## Step 6: fixes, snapshot, deployment

| # | Check | Evidence | Result |
|---|-------|----------|--------|
| 6.1 | `CARRY_MIN_SESSIONS = 5` in config, marked chosen by the team | `test_carry_min_sessions_in_config` | PASS |
| 6.2 | Single-session carry not shown; four October sessions not shown; five sessions with valid carry shown | `test_single_session_carry_not_shown`, `test_four_october_sessions_carry_not_shown`, `test_five_sessions_with_valid_carry_are_shown` (21 Jan 2026 sample plus 5, 6, 7, 9 Oct) | PASS |
| 6.3 | z-score `min_periods` = 60 in core/signals.py and PREREGISTRATION.md | `test_thresholds_read_from_code`, file text | PASS |
| 6.4 | First z-score appears after 60 earlier sessions, and dashboard and code agree | `test_default_first_value_on_session_61`, `test_dashboard_and_code_agree_on_first_zscore` | PASS. The brief says "session 60"; with a lagged 60-session baseline the first value is at index 60, the 61st session. Code and dashboard both use this |
| 6.5 | Snapshot holds derived tables only, no raw bhavcopy field names | `test_no_raw_bhavcopy_field_names` | PASS, with date, symbol and expiry date exempt as keys (see notes) |
| 6.6 | Manifest records source names, SHA-256, sessions, code commit, build time | `test_manifest_records_sources_sessions_commit_and_time`; data/snapshot/manifest.json | PASS |
| 6.7 | App from snapshot shows the same values as app from store | `test_snapshot_pages_match_store_pages`: every page, every session and every waterfall pair on the October fixtures (over 100 views), tables compared with `assert_frame_equal` | PASS |
| 6.8 | App reads the snapshot when the store is absent | `test_load_data_prefers_store_then_snapshot`; fresh clone render below | PASS |
| 6.9 | Python 3.11 pinned in a file the platform reads | `runtime.txt` contains `python-3.11`. Whether Community Cloud reads it was not checked | NOT RUN |
| 6.10 | requirements.txt pinned and installs in a new venv | fresh clone: `pip install -r requirements.txt` exit 0 | PASS |
| 6.11 | Usage stats off; no localhost binding in shared config; local runs bind localhost | `.streamlit/config.toml`; README; fresh clone server log shows only `URL: http://localhost:8599` | PASS |
| 6.12 | Fresh clone: clone, venv, install, pytest, app | log below | PASS |
| 6.13 | Raw-CSV tests skip with a named NOT RUN reason when files are absent | fresh clone pytest: 8 skipped, each "NOT RUN: ..." | PASS |
| 6.14 | GitHub Actions workflow runs pytest on push and PR and fails on failure | `.github/workflows/tests.yml`; the repo has no GitHub remote, so the workflow has never run | NOT RUN |
| 6.15 | Workflow lists skipped tests as NOT RUN in the job summary | step written; not run on GitHub | NOT RUN |
| 6.16 | Workflow has no secret, token or MCX request | `grep -niE "secret|token|mcx|curl|wget" .github/workflows/tests.yml` exit 1 | PASS |
| 6.17 | No raw CSV committed | `git ls-files` lists only six fixture CSVs under tests/fixtures/ | PASS |
| 6.18 | README and DATA_TERMS written; no unsourced "verified" text | `git grep -niE "\bverified\b"` outside this file returns only UNVERIFIED and "not verified" | PASS |
| 6.19 | Deployed to Streamlit Community Cloud, URL in README | Snapshot publication not confirmed by owner; data/snapshot/ excluded from push; deployment not run | NOT RUN |
| 6.20 | Public URL renders every page from the snapshot; Backtest says "Not run" | Snapshot publication not confirmed by owner; app not deployed | NOT RUN |
| 6.21 | Backtest stays NOT RUN; no `pre-registration` tag | Backtest page text; `git tag` lists nothing | PASS |

Notes:

- The fresh clone test found that `.gitignore` had silently excluded
  `tests/fixtures/oct2026/*.csv`. Commit 58e411a (originally a68d588, "Add October 2026 futures
  fixtures") contained only `conftest.py`; in a clone, 17 tests failed and 26
  errored while all passed in the working copy. Fixed in 3cb768a (originally 21abb72). The step 3
  to 5 results were obtained in the working copy, where the files existed.
- 6.5: trade date, symbol and expiry date are kept as keys. All other raw
  fields (prices, volume, value, OI, instrument, option type, strike) are
  absent. `ppg999` is derived from close, so close can be recovered from it
  with the purity and quote unit.
- The snapshot was built from commit c070a83 (originally 69d151d). Later commits changed
  presentation and documentation only, not `derive()` or the analytics.
- History rewrite: Prior to first push, the repository history was rewritten using
  `git-filter-repo` to redact test placeholder strings (`REDACTED_TEST_TOKEN` ->
  `REDACTED_TEST_TOKEN` and `ASP.NET_SessionId=test123;__RequestVerificationToken=REDACTED_TEST_COOKIE`
  -> `REDACTED_TEST_COOKIE`). A verified bundle backup was saved to
  `../aureus-lens-backup.bundle`. Subsequent scans (`git log --all -p -S"..."` and
  `git grep`) confirmed zero occurrences across history. The rewrite changed commit
  hashes across the 51 baseline commits.

### Test counts

```
Local, raw files and store present:
134 passed in 58.58s

Fresh clone (same inputs as CI: no data/raw/, no store):
126 passed, 8 skipped in 38.61s
```

### Snapshot build

```
$ python scripts/build_snapshot.py
snapshot: <repo>\data\snapshot
  normalized        96 rows
  pairs            144 rows
  carry              4 rows
  continuity        96 rows
  load_log           4 rows
  refused            1 rows
  value_summary      4 rows
sessions: 2026-10-05, 2026-10-06, 2026-10-07, 2026-10-09
commit:   69d151dc7855fafba53304583fe835ad2fd8605c (clean tree: True)
```

The refused 8 Oct file has the same SHA-256 as the 9 Oct file
(`8e95a4b6...297b317`), confirming it is a copy.

### Fresh clone log

```
$ git clone -q <repo> aureus-fresh
[exit 0]
$ git log --oneline -1
71eff0e List small-vs-small pairs first in the waterfall picker
[exit 0]
$ ls data data/snapshot
data:
snapshot
data/snapshot:
carry.parquet
continuity.parquet
load_log.parquet
manifest.json
normalized.parquet
pairs.parquet
refused.parquet
value_summary.parquet
[exit 0]
$ py -3.11 -m venv .venv
[exit 0]
$ .venv/Scripts/python --version
Python 3.11.9
[exit 0]
$ .venv/Scripts/python -m pip install -q -r requirements.txt
[exit 0]
$ .venv/Scripts/python -m pytest -p no:cacheprovider -q -rs
......................ssss.............................................. [ 53%]
..s.s.....s.................................s.................           [100%]
=========================== short test summary info ===========================
SKIPPED [1] tests\test_csv_loader.py:174: NOT RUN: BhavCopyDateWise_09102026.csv not in data/raw/
SKIPPED [1] tests\test_csv_loader.py:183: NOT RUN: BhavCopyDateWise_21012026.csv not in data/raw/
SKIPPED [1] tests\test_csv_loader.py:183: NOT RUN: 20260121_MCX.csv not in data/raw/
SKIPPED [1] tests\test_csv_loader.py:193: NOT RUN: 20260121_MCX.csv not in data/raw/
SKIPPED [1] tests\test_reconcile.py:76: NOT RUN: no two adjacent trading sessions in data/raw/
SKIPPED [1] tests\test_reconcile.py:96: NOT RUN: no files in data/raw/
SKIPPED [1] tests\test_reconcile.py:157: NOT RUN: no files in data/raw/
SKIPPED [1] tests\test_views.py:215: NOT RUN: data/aureus.duckdb not present
126 passed, 8 skipped in 38.61s
[exit 0]
$ python apptest_tmp.py   # AppTest render of all six pages, no store present
== Data Health | exceptions: 0 | charts: 0
   sidebar: ['Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78', 'Sessions stored: 4']
   caption: Source: load_log, data_health and bhav tables | Dates: 2026-10-05 to 2026-10-09 (4 sessions) | Unit: rows | Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78
== Normalized View | exceptions: 0 | charts: 1
   sidebar: ['Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78', 'Sessions stored: 4']
   caption: Source: BhavCopyDateWise_05102026.csv to BhavCopyDateWise_09102026.csv (4 files) | Dates: 2026-10-05 to 2026-10-09 (4 sessions) | Unit: rupees per gram of 999 gold | Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78
   msg: Purity factors are UNVERIFIED (GOLDM 995, others 999).
== Spread Scanner | exceptions: 0 | charts: 0
   sidebar: ['Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78', 'Sessions stored: 4']
   caption: Source: BhavCopyDateWise_09102026.csv | Dates: 2026-10-09 (history: 2026-10-05 to 2026-10-09 (4 sessions)) | Unit: bps of leg b; cost is pair round trip; carry per year, continuous | carry_source: empirical 1 | Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78
   msg: No actionable signal. Reasons: z-score history below 60 sessions on 36 pairs (longest 3 of 60); GOLDM pairs not evaluated: carry insufficient history (4 of 5 sessions); below 2x cost: 4 pairs
== Waterfall | exceptions: 0 | charts: 1
   sidebar: ['Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78', 'Sessions stored: 4']
   caption: Source: BhavCopyDateWise_09102026.csv | Dates: 2026-10-09 | Unit: bps of leg b | carry_source: not needed | Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78
   msg: Tick sizes and cost rates are UNVERIFIED. The edge is not a finding: insufficient history (3 of 60 sessions) for a z-score.
== Coverage | exceptions: 0 | charts: 0
   sidebar: ['Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78', 'Sessions stored: 4']
   caption: Source: BhavCopyDateWise_05102026.csv to BhavCopyDateWise_09102026.csv (4 files) | Dates: 2026-10-05 to 2026-10-09 (4 sessions) | Unit: sessions | Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78
== Backtest | exceptions: 0 | charts: 0
   sidebar: ['Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78', 'Sessions stored: 4']
   caption: Source: PREREGISTRATION.md and config.py | Dates: 2026-10-05 to 2026-10-09 (4 sessions) | Unit: rates | Read from: snapshot built 2026-10-27T19:19:16+00:00 from commit 69d151dc78
   msg: Not run: awaiting contiguous history and pre-registration
[exit 0]
$ streamlit run app/dashboard.py --server.address localhost --server.port 8599
2026-10-28 01:08:58.046 Uvicorn server started on localhost:8599
  You can now view your Streamlit app in your browser.
  URL: http://localhost:8599
$ curl localhost:8599/_stcore/health
ok
$ curl -o /dev/null -w "%{http_code}" localhost:8599/
200
$ git status --short; ls data   # after tests and app run
snapshot
```
