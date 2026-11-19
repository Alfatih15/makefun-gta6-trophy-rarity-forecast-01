"""GTA VI trophy-rarity forecaster for make.fun gta6-trophy-rarity-forecast-01.

Forecasts, for every trophy of Grand Theft Auto VI on PlayStation 5, its earn
rate on Exophase at the case's target, as five quantiles (5/25/50/75/95%),
from the house's reads of the game's trophy page held in the case's history.

How it works
-------------
Exophase refreshes a game's counts on its own schedule, hours apart, so the
reads the house keeps are a step function: long flat stretches, then a jump
at each refresh.  Two regimes follow from that.

1. Moving history (the final case).  Each trophy's earn rate is fitted
   with a saturating curve in linear time, rate = Rinf - A * exp(-lam * t),
   by recency-weighted least squares over the distinct reads (consecutive
   identical reads collapsed to one state): the pool of players who will
   ever earn a given trophy is finite, so growth bends toward a ceiling
   instead of running on.  A logit-linear-in-log-time fit stands by as the
   fallback when the saturating curve cannot be identified.  The total move
   from the last read is capped.  The spread combines the fit's residual
   scale with a random-walk term that widens with the horizon and a floor
   for refresh jumpiness.

2. Flat history (the practice cases).  Every read shows the same page, so no
   trend exists to fit -- but a page that has sat unchanged for hours is a
   page whose next refresh is overdue, and a refresh dilutes every rate: the
   tracked-player base grows between refreshes while the new players hold
   far fewer trophies than the players already tracked, so the rate of every
   trophy but the one at 100% falls at the refresh.  The median is therefore
   shifted down in logit space by an amount that grows with how stale the
   page is and with the horizon, and the spread is widened to cover both the
   refresh happening and it not happening, and the per-trophy variation in
   how far each rate falls.

Everything is deterministic standard library only: no randomness, no
network, no clock reads inside the forecast itself.  The program reads every
``*.in`` file in the input directory (``$MAKEFUN_INPUT_DIR`` when set, else
``/input/``) and writes one ``<id>.out`` per case to the output directory
(``$MAKEFUN_OUTPUT_DIR`` when set, else ``/output/``).
"""

import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The release day began at 2026-11-19T00:00:00Z; log time is measured from it.
RELEASE = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)

# Quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
_NORM = statistics.NormalDist()
Z = [_NORM.inv_cdf(tau) for tau in LEVELS]

# --- launch-week priors (see BUILD_LOG.md for the reasoning) -----------------
# Logit shift applied to a trophy's last rate when the page is flat/stale:
# one overdue refresh dilutes a small rate by roughly a factor of five.
STALE_SHIFT = -1.2
# How stale (page age + horizon, in hours) it takes for the full shift.
STALE_FULL_HOURS = 4.0
# Spread (logit units) of the flat-history forecast: wide enough to cover
# the refresh landing or not, and trophies falling by different amounts.
STALE_SPREAD = 0.7
# Random-walk spread per square-root day of horizon (same scale as the
# house baseline's), used by the trend path.
WALK_SIGMA = 0.5
# Floor and cap for the trend fit's residual spread.
RESID_FLOOR = 0.3
RESID_CAP = 1.2
# Floor for refresh/model uncertainty added to every trend forecast.
MODEL_FLOOR = 0.25
# Largest logit move the trend path may forecast away from the last read.
MAX_MOVE = 2.5
# Minimum distinct reads needed before a trend line is trusted at all.
MIN_TREND_STATES = 3


def clamp_rate(x: float) -> float:
    """Clamp a percent into the range the logit is defined on."""
    return min(99.99, max(0.01, x))


def logit(pct: float) -> float:
    p = clamp_rate(pct) / 100.0
    return math.log(p / (1.0 - p))


def inv_logit(lg: float) -> float:
    return 100.0 / (1.0 + math.exp(-lg))


def round4(x: float) -> float:
    """Round to 4 decimals, half up, returning an int for whole numbers."""
    whole = math.floor(x * 10000 + 0.5)
    value = whole / 10000
    return int(value) if float(value).is_integer() else value


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def hours_since_release(moment: datetime) -> float:
    return max(0.0, (moment - RELEASE).total_seconds() / 3600.0)


def log_time(moment: datetime) -> float:
    return math.log1p(hours_since_release(moment))


def distinct_states(case: dict) -> list:
    """Collapse the history into its distinct states, oldest first.

    Consecutive reads with identical rates and players-tracked are one
    state, kept at the time it was first seen: Exophase's page only changes
    at a refresh, so the repeats carry no new information.
    """
    states = []
    for read in case["history"]:
        key = (tuple(read["rates"]), read["players_tracked"])
        if states and states[-1][0] == key:
            continue
        states.append((key, parse_time(read["at"])))
    return states


def weighted_line(xs, ys, ws):
    """Recency-weighted least-squares line; returns (intercept, slope)."""
    total_w = sum(ws)
    mean_x = sum(w * x for w, x in zip(ws, xs)) / total_w
    mean_y = sum(w * y for w, y in zip(ws, ys)) / total_w
    sxx = sum(w * (x - mean_x) ** 2 for w, x in zip(ws, xs))
    if sxx <= 1e-12:
        return mean_y, 0.0
    sxy = sum(w * (x - mean_x) * (y - mean_y) for w, x, y in zip(ws, xs, ys))
    slope = sxy / sxx
    return mean_y - slope * mean_x, slope


def saturating_fit(points, target_days):
    """Fit rate = Rinf - A * exp(-lam * t) to one trophy's reads.

    Trophy earn rates saturate: the pool of players who will ever earn a
    given trophy is finite, so growth in linear time bends toward a ceiling
    instead of running on.  ``lam`` (per day) is found by grid search and
    Rinf / A by weighted least squares at each grid value.  ``points`` is a
    list of (days_since_release, rate_percent, weight).  Returns
    (predicted_rate_at_target, residual_logit_sd) or None when the fit is
    degenerate (for instance every read identical).
    """
    best = None
    lam = 0.02
    while lam <= 2.0:
        exps = [math.exp(-lam * t) for t, _r, _w in points]
        total_w = sum(w for _t, _r, w in points)
        mean_e = sum(w * e for w, e in zip([p[2] for p in points], exps)) / total_w
        mean_r = sum(w * r for (_t, r, w) in points) / total_w
        see = sum(w * (e - mean_e) ** 2 for w, e in zip([p[2] for p in points], exps))
        if see > 1e-12:
            ser = sum(
                w * (e - mean_e) * (r - mean_r)
                for (_t, r, w), e in zip(points, exps)
            )
            slope = ser / see  # = -A
            intercept = mean_r - slope * mean_e  # = Rinf
            sse = sum(
                w * (r - (intercept + slope * e)) ** 2
                for (_t, r, w), e in zip(points, exps)
            )
            if best is None or sse < best[0]:
                best = (sse, intercept, slope, lam)
        lam *= 1.35
    if best is None:
        return None
    _sse, rinf, slope, lam = best
    pred = rinf + slope * math.exp(-lam * target_days)
    pred = min(99.99, max(0.01, pred))
    sq = 0.0
    for t, r, _w in points:
        fitted = rinf + slope * math.exp(-lam * t)
        fitted = min(99.99, max(0.01, fitted))
        sq += (logit(r) - logit(fitted)) ** 2
    resid = math.sqrt(sq / len(points))
    return pred, resid


def linear_fallback(points, target_x):
    """Logit rate linear in log time; the guard when the saturating fit
    cannot be identified.  ``points`` carries (x, logit_rate, weight)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    ws = [p[2] for p in points]
    intercept, slope = weighted_line(xs, ys, ws)
    n = len(points)
    slope *= n / (n + 2.0)
    median = intercept + slope * target_x
    resid = math.sqrt(
        sum(w * (y - (intercept + slope * x)) ** 2 for x, y, w in points)
        / sum(ws)
    )
    return median, resid


def forecast_trophy(last_logit, points, horizon_days, target_days, target_x):
    """Return (median_logit, spread) for one trophy.

    ``points`` is a list of (moment, rate_percent, weight) from the distinct
    states.  The saturating curve is the primary model; the log-time line
    is its fallback.
    """
    if len(points) >= MIN_TREND_STATES:
        fitted = saturating_fit(
            [
                (hours_since_release(m) / 24.0, r, w)
                for m, r, w in points
            ],
            target_days,
        )
        if fitted is not None:
            pred_rate, resid = fitted
            median = logit(pred_rate)
        else:
            median, resid = linear_fallback(
                [(log_time(m), logit(r), w) for m, r, w in points], target_x
            )
        # Never forecast a wild swing away from the last read.
        median = min(last_logit + MAX_MOVE, max(last_logit - MAX_MOVE, median))
        # Residual spread of the fit, floored and capped.
        resid = min(RESID_CAP, max(RESID_FLOOR, resid))
        spread = math.sqrt(
            resid ** 2
            + (WALK_SIGMA * math.sqrt(horizon_days)) ** 2
            + MODEL_FLOOR ** 2
        )
        return median, spread
    # Too few distinct states to fit a curve: fall back to the last rate
    # with a wide spread (the stale path below refines this when the
    # history is entirely flat).
    spread = math.sqrt(
        STALE_SPREAD ** 2 + (WALK_SIGMA * math.sqrt(horizon_days)) ** 2
    )
    return last_logit, spread


def forecast_case(case: dict) -> dict:
    if case["levels"] != LEVELS:
        raise ValueError("unexpected levels in case")
    if not case["history"]:
        raise ValueError("case has no history")

    checkpoint = parse_time(case["at"])
    horizon_hours = case["horizon_minutes"] / 60.0
    horizon_days = case["horizon_minutes"] / 1440.0
    target_x = log_time(parse_time(case["target"]))
    states = distinct_states(case)
    last_rates = case["history"][-1]["rates"]

    # How long the current page has been showing, in hours: from the first
    # read that showed it to the checkpoint.
    last_state_since = states[-1][1]
    stale_hours = max(0.0, (checkpoint - last_state_since).total_seconds() / 3600.0)
    flat = len(states) <= 1

    # Per-trophy trend points, built once and reused for every trophy.
    # Weight grows with recency so the latest refreshes count most.
    points_by_trophy = []
    for i in range(len(case["trophies"])):
        pts = []
        for j, ((rates, _players), moment) in enumerate(states):
            rate = rates[i]
            if rate is None:
                continue
            pts.append((moment, rate, 1.0 + j))
        points_by_trophy.append(pts)

    rows = []
    for i, trophy in enumerate(case["trophies"]):
        rate = last_rates[i]
        if rate is None:
            # The last read lacked this trophy: use its most recent rate.
            rate = next(
                (states[j][0][0][i] for j in range(len(states) - 1, -1, -1)
                 if states[j][0][0][i] is not None),
                0.0,
            )
        last_lg = logit(rate)
        if flat:
            # Stale page: the next refresh dilutes the rate.  The shift
            # scales with how overdue the refresh is (page age + horizon).
            due = min(1.0, (stale_hours + horizon_hours) / STALE_FULL_HOURS)
            median = last_lg + STALE_SHIFT * due
            spread = math.sqrt(
                STALE_SPREAD ** 2
                + (WALK_SIGMA * math.sqrt(horizon_days)) ** 2
            )
        else:
            median, spread = forecast_trophy(
                last_lg,
                points_by_trophy[i],
                horizon_days,
                hours_since_release(parse_time(case["target"])) / 24.0,
                target_x,
            )
        median = min(9.0, max(-9.0, median))
        qs = [inv_logit(median + z * spread) for z in Z]
        qs = [clamp_rate(q) for q in qs]
        qs = [round4(q) for q in qs]
        # Rounding must not break the non-decreasing order.
        for k in range(1, 5):
            if qs[k] < qs[k - 1]:
                qs[k] = qs[k - 1]
        rows.append({"id": trophy["id"], "q": qs})
    return {"trophies": rows}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        try:
            forecast = forecast_case(case)
        except Exception:
            # Never leave a case without a file: fall back to persistence
            # with a wide spread so the case stays valid.
            last = case["history"][-1]["rates"] if case.get("history") else []
            rows = []
            for i, trophy in enumerate(case["trophies"]):
                rate = last[i] if i < len(last) and last[i] is not None else 1.0
                lg = logit(rate)
                qs = [round4(clamp_rate(inv_logit(lg + z * 1.5))) for z in Z]
                for k in range(1, 5):
                    if qs[k] < qs[k - 1]:
                        qs[k] = qs[k - 1]
                rows.append({"id": trophy["id"], "q": qs})
            forecast = {"trophies": rows}
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
