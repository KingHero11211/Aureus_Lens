# Aureus Lens

Relative-value analytics for four MCX gold futures: GOLDM, GOLDTEN, GOLDGUINEA
and GOLDPETAL. Built for Hack in Hills '26, Problem Statement 03.

Work in progress. This README will be completed once the loader, pipeline and
backtest are in place.

## Setup

Requires Python 3.11.

```
py -3.11 -m venv .venv            # Windows; use python3.11 on Linux/macOS
.venv/Scripts/activate            # or: source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Dependencies are pinned to exact versions in `requirements.txt`.

## Data

The project does not download data. Bhavcopy CSV files are downloaded by hand
and placed in `data/raw/`, which is not committed.
