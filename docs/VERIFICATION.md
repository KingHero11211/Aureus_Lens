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
