# Pre-registration

Status: draft. The train, validation and test dates are not set, so this
file is not tagged. It is tagged `pre-registration` once the dates are
fixed, and the test period is not opened before that tag exists.

## Purpose

The four MCX gold futures (GOLDM, GOLDTEN, GOLDGUINEA, GOLDPETAL) are the
same metal in different sizes. The study asks whether their prices, once
converted to rupees per gram of 999 gold and aligned to a common expiry,
agree with each other; and, where they do not, whether the gap is large and
unusual enough to remain after transaction costs. "No persistent edge after
costs" is an accepted answer.

## Hypotheses

Not filled in. The project brief refers to hypotheses H0 to H5, but no
copy of the brief given to us contains them, and they are not invented
here. Each hypothesis is to be added with:

- the statement,
- the test that answers it (code path and statistic),
- the result that would count against it.

They must be added before the dates below are fixed.

## Parameters

| Parameter | Value | Source |
|---|---|---|
| Lot size (grams) | GOLDM 100, GOLDTEN 10, GOLDGUINEA 8, GOLDPETAL 1 | Verified: reproduces reported value within 0.5% for every active gold future on 9 Oct 2026 (`tests/test_csv_loader.py`) |
| Quote unit (grams) | GOLDM 10, GOLDTEN 10, GOLDGUINEA 8, GOLDPETAL 1 | Verified, same test |
| Purity | GOLDM 995, others 999 | UNVERIFIED; matches the hand-checked normalization only |
| Tender period (days) | GOLDM 3, GOLDTEN 3, GOLDGUINEA 3, GOLDPETAL 5 | UNVERIFIED. GOLDGUINEA from a secondary summary of MCX/TRD/456/2025; GOLDPETAL 5 is a conservative placeholder |
| Carry buffer (`STAGGERED_DELIVERY_DAYS`) | 3 calendar days | UNVERIFIED; GOLDM tender window length has no source |
| Tick size | 1.0 for all four | UNVERIFIED |
| Cost rates | brokerage 0.03% capped at Rs 20, exchange 0.0021%, CTT 0.01% sell, stamp 0.002% buy, SEBI Rs 10 per crore, GST 18% | UNVERIFIED; arithmetic checked against the Rs 1,000,000 example (buy 69.56, sell 149.56) |
| Notional per leg for cost in bps | Rs 1,000,000 | Chosen by the team, not derived |
| Cost multiple (`DEFAULT_COST_MARGIN`) | 2 | Chosen by the team, not derived |
| Z-score threshold (`DEFAULT_Z_THRESHOLD`) | 2.0 | Chosen by the team, not derived |
| Z-score window | 60 sessions | Chosen by the team, not derived (from the baseline code) |
| Z-score `min_periods` | 60 sessions | Chosen by the team, not derived. Equal to the window, so the first z-score needs 60 earlier sessions and appears on session 61 of a series. The dashboard applies the same rule |
| MAD scale | 1.4826 | Standard constant that makes MAD match a standard deviation for normal data |
| Stale-carry limit (`max_stale_sessions`) | 5 sessions | Chosen by the team, not derived |
| Carry minimum history | none in config; one session with two eligible GOLDM expiries gives a value | From the code |

## Periods

| Period | Dates |
|---|---|
| Train | TBD, to be set after the history is loaded |
| Validation | TBD, to be set after the history is loaded |
| Test | TBD, to be set after the history is loaded |

The backtest needs one contiguous run of sessions that covers the z-score
window plus the validation and test periods. The dates are not set from
the four sessions currently loaded (5, 6, 7 and 9 Oct 2026).

## Rules

1. All parameters above are frozen before the test period is opened.
2. The test period is opened once, after the `pre-registration` tag.
3. Any change after opening is recorded in a Deviations section below,
   with the date, the change and the reason. Results are reported with and
   without the change.
4. Parameters are tuned on train and validation only.
5. Results are reported net of costs, with attribution to the gold price
   and a placebo test. A null result is reported as the finding.

## Known limitations

- GOLDTEN has a short history (launch reported as 1 April 2025, UNVERIFIED),
  which limits how early the train period can start.
- Few festival seasons fall inside the available history, so any seasonal
  effect on the small contracts cannot be separated from noise.
- Bhavcopy closes are settlement-style prices, not prices at which both legs
  could have been traded at the same moment. A gap in closes may not have
  been executable.
- Cost rates, tender periods, tick sizes and purity are unverified. A result
  that depends on them inherits that uncertainty.
- No exchange holiday calendar is used, so a missing weekday cannot be told
  from a holiday.

## Deviations

None yet.
