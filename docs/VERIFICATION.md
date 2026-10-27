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
