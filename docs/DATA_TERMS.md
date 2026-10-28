# Data terms

## Source and Ownership

The data are Multi Commodity Exchange of India (MCX) Bhavcopy reports: the
exchange's end-of-day record of contracts traded on each session. MCX owns
the Bhavcopy data.

The application and repository distribute zero market data. No CSV files, no
snapshot files, no database store files, and no derived price tables are held
or tracked in the repository.

Two Bhavcopy layouts are supported by the in-memory loader:

- Format A, from the official MCX Bhavcopy portal (`BhavCopyDateWise_DDMMYYYY.csv`).
- Format B, from Samco's Bhav Copy download archive (`YYYYMMDD_MCX.csv`).

## In-Session Processing

Users upload their own Bhavcopy files directly into the web application. All
processing is conducted entirely in memory (in-session DuckDB). Uploaded files
are never written to disk on the host, are never logged beyond session-level
file names and counts, and are cleared when the session terminates. Each user
session is isolated and independent.

The repository contains no automated scrapers, no code that downloads from
MCX, Samco or any third-party website, and no network calls to external market
data endpoints.

## Use

This project is for relative-value research and analysis only. It is not
financial or trading advice, and nothing in this repository or application
constitutes an offer or recommendation to buy or sell any commodity, contract
or derivative. Several inputs, including transaction cost rates, contract tender
periods and tick sizes, remain unverified placeholders (see README.md and
docs/VERIFICATION.md).
