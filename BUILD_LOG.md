# BUILD_LOG.md — gta6-trophy-rarity-forecast-01

## What was built
`main.py` (Python 3.13, stdlib only, deterministic, no network) at the repo
root. It reads every `*.in` case in `$MAKEFUN_INPUT_DIR` (else `/input/`) and
writes one `<id>.out` per case to `$MAKEFUN_OUTPUT_DIR` (else `/output/`):
`{"trophies": [{"id": n, "q": [q05, q25, q50, q75, q95]}, ...]}`, one row per
trophy, quantiles non-decreasing, each 0.01–99.99, at most 65,536 bytes.

## Forecasting approach
Exophase refreshes a game's counts on its own schedule, hours apart, so the
house's reads are a step function: long flat stretches, then a jump at each
refresh. Two regimes:

1. **Moving history (the final case).** Per trophy, a saturating curve in
   linear time, `rate = Rinf − A·exp(−λ·t)`, fitted by recency-weighted least
   squares over the distinct reads (consecutive identical reads collapsed to
   one state; λ by grid search over 0.02–2.0/day). The pool of players who
   will ever earn a given trophy is finite, so growth bends toward a ceiling
   instead of running on — a log-time linear fit over-extrapolates a
   decelerating curve, which I confirmed on synthetic final-like cases (see
   below). A logit-linear-in-log-time fit stands by as fallback when the
   saturating curve cannot be identified. Total move from the last read is
   capped at 2.5 logit units. Spread = sqrt(residual² + (0.5·√horizon_days)²
   + 0.25²), residual floored at 0.3 and capped at 1.2.
2. **Flat history (the practice cases).** Every read shows the same page, so
   no trend exists — but a page unchanged for hours has its next refresh
   overdue, and a refresh dilutes every rate: the tracked-player base grows
   between refreshes while newly tracked players hold far fewer trophies, so
   every rate but the one at 100% falls. Median shifted down by up to −1.2
   logit units (scaled by page age + horizon over 4 h), spread 0.7 logit
   units plus the random-walk term, covering the refresh landing or not and
   trophies falling by different amounts.

## Validation
The kit ships no practice answers (the scorer and reference data stay on the
server), so I reconstructed them from the facts the RULES publish: the
04:30Z read had 3,868 players tracked and 4,276 trophies earned (launch
night: 638 players, 943 earned), every rate but the 100% one lower. The
proportional reconstruction (each rate ×0.2208, the 100% trophy unchanged)
reproduces the published baseline figures: typical miss 0.677 pp vs the
published "about 0.68", coverage 0. Scores below are the mean pinball loss
on the logit scale over both practice cases (550 items).

| forecast | proportional answers | max-dilution answers | f=0.9 answers |
|---|---|---|---|
| house baseline (starter) | 1.401 | 1.688 | 0.827 |
| this entry | **0.215** | **0.323** | **0.205** |

Practice details for this entry: typical miss 0.072 pp (baseline 0.677 pp),
90% coverage 0.982 (baseline 0.000). The three answer reconstructions span
the plausible range (proportional split of the new trophies earned, the
maximum-dilution extreme, and 90% of new players holding the 100% trophy);
this entry beats the baseline under every one of them. The published
baseline loss of "about 1.51" sits between the proportional and
maximum-dilution reconstructions, consistent with per-trophy variation in
how far each rate falls.

Trend-path check on synthetic final-like cases (2 days of 10-minute reads,
refreshes every ~4 h, players 638 → ~127k, target 4.5 days out; truth a
saturating curve): loss 0.293 / 0.329 / 0.285 across base/fast/slow growth
scenarios (mean 0.302) vs persistence baseline 0.320 / 0.279 / 0.403 (mean
0.334); typical miss 1.4–1.9 pp. The first (log-time linear) version of the
trend path scored 0.383 on the base scenario with a 12.7 pp typical miss —
it over-extrapolated the decelerating curve — which is why the saturating
fit replaced it.

Determinism: both practice cases run twice produce byte-identical outputs.
Runtime ~0.07–0.17 s per run (limit 8 s). Output files 2,785 bytes each
(limit 65,536).

## Files
- `main.py` — the forecaster (only entrypoint; `main.ts` removed)
- `LICENSE` — MIT (from the kit starter)
- `README.md`, `BUILD_LOG.md` (this file)
- `.makefun/owner.json` — `{"wallet": "Cfdgeggmd6ij5dLpqwmqAaGExTbi4JPZJYcRdi4iSjSW"}`

## Notes / open items
- No local grade exists for this competition (the scorer and reference data
  are server-side); the practice numbers above use the reconstructed
  answers described here, not the sealed ones.
- The kit check (`makefun check`) needs the transcript bundle, which the
  main agent produces at submit time; see the check output in the build
  report for what passed locally.
- Not bundled, not submitted — the main agent does that.
