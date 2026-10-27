# Data terms

## Source

The data are MCX Bhavcopy files: the exchange's end-of-day report of every
contract traded on a session. Two copies of the same reports are used:

- Files from the MCX Bhavcopy page (format A, `BhavCopyDateWise_DDMMYYYY.csv`).
- Files from Samco's Bhav Copy download page, which serves the MCX
  Bhavcopy (format B, `YYYYMMDD_MCX.csv`).

For 21 January 2026 both copies were loaded and give identical rows for the
four gold futures (docs/VERIFICATION.md item 1.11).

## How the files were obtained

Every file was downloaded by hand from those pages and saved in
`data/raw/`. The project contains no code that downloads from MCX, Samco or
any other site, and no code that works around access controls.

## What is redistributed

Raw Bhavcopy files are not redistributed. `data/raw/` is excluded from the
repository by `.gitignore`.

The repository contains:

- `tests/fixtures/`: a small number of rows copied unchanged from the files,
  used as test inputs.
- `data/snapshot/`: tables derived from the files (prices per gram of 999
  gold, pair spreads, carry, check results). `data/snapshot/manifest.json`
  lists the source files and their SHA-256 checksums.

## Use

This project is for analysis only. It is not trading advice, and nothing in
it is a recommendation to buy or sell any contract. Several inputs, including
all cost rates, are unverified placeholders (see README.md).
