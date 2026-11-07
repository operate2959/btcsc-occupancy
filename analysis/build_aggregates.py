#!/usr/bin/env python3
"""Turn raw samples (data/*.csv) into the small tables the heatmap dashboard reads.

Outputs in analysis/out/:
  slots.json     average crowd per 30-minute slot, by day type and by day of week
  daily.json     average crowd per hour for every date (calendar view)
  coverage.json  how much data there is, per facility
  gaps.json      runs of opening-time minutes with no pull (also written to data/gaps.csv)

Minutes with no pull (site down, collector not running) are missing data: they never
become rows, so they are left out of every average instead of counting as zero.

Day types use Taiwan's official office calendar (calendar/YYYY.json, from the DGPA
calendar mirrored at github.com/ruyut/TaiwanCalendar):
  holiday = a named public holiday or bridge day off (春節, 國慶日, 補假 ...)
  weekend = any other day off (normal Saturday/Sunday)
  weekday = a working day (this includes make-up working Saturdays)
"""
import csv
import glob
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis", "out")
SLOT_MIN = 30
HOURS = {"gym": (6, 22), "swim": (6, 22), "ice": (10, 21)}  # open, close (Taipei)
NAMES = {"gym": "Gym", "swim": "Pool", "ice": "Ice rink"}
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TYPE_ORDER = {"weekday": 0, "weekend": 1, "holiday": 2}
TYPE_LABEL = {"weekday": "Weekday", "weekend": "Weekend", "holiday": "Holiday"}


def load_calendar():
    cal = {}
    for p in glob.glob(os.path.join(ROOT, "calendar", "[0-9][0-9][0-9][0-9].json")):
        for d in json.load(open(p, encoding="utf-8")):
            cal[d["date"]] = d
    return cal


def day_type(date, cal):
    d = cal.get(date.strftime("%Y%m%d"))
    if d is None:  # outside the cached calendar years
        return ("weekend" if date.weekday() >= 5 else "weekday"), ""
    if d["isHoliday"] and d.get("description"):
        return "holiday", d["description"]
    return ("weekend" if d["isHoliday"] else "weekday"), d.get("description", "")


def load_closures():
    p = os.path.join(ROOT, "calendar", "closures.json")
    if not os.path.exists(p):
        return set()
    return {k for k in json.load(open(p, encoding="utf-8")) if not k.startswith("_")}


def closed_dates(samples):
    """Listed closures plus any day where gym and pool read 0 for the whole open period
    (e.g. a typhoon day): those zeros mean "closed", not "quiet"."""
    peak = defaultdict(int)
    for (fac, t), (count, _) in samples.items():
        if fac in ("gym", "swim") and HOURS[fac][0] <= t.hour < HOURS[fac][1]:
            peak[t.date()] = max(peak[t.date()], count)
    return load_closures() | {d.strftime("%Y-%m-%d") for d, m in peak.items() if m == 0}


def closed_facility_days(samples):
    """(facility, date) pairs where one facility looks shut while the centre was open,
    e.g. the pool on a maintenance day: it never reads more than a few people (staff,
    stragglers) across a mostly sampled open period. Those days are left out for that
    facility only, so they don't drag its averages to zero. "A few" = at most 5% of
    capacity all day."""
    peak, n, caps = defaultdict(int), defaultdict(int), {}
    for (fac, t), (count, cap) in samples.items():
        if fac in HOURS and HOURS[fac][0] <= t.hour < HOURS[fac][1]:
            peak[(fac, t.date())] = max(peak[(fac, t.date())], count)
            n[(fac, t.date())] += 1
            if cap:
                caps[fac] = cap
    out = set()
    for (fac, d), m in peak.items():
        open_min = (HOURS[fac][1] - HOURS[fac][0]) * 60
        # normal days peak far higher (pool 25+, gym 50+, ice 28+ even on quiet days)
        if m <= 0.05 * caps.get(fac, 100) and n[(fac, d)] >= open_min * 0.5:
            out.add((fac, d.strftime("%Y-%m-%d")))
    return out


def load_errors():
    """Minute -> error text from the collector's own log (failed pulls write no rows)."""
    # logs/raw/ holds today's per-run logs from GitHub Actions until the nightly merge
    paths = [os.path.join(ROOT, "logs", "collector.log")] + \
        sorted(glob.glob(os.path.join(ROOT, "logs", "raw", "*.log")))
    errs = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8", errors="replace"):
            if line[16:23] == " ERROR ":
                try:
                    errs[datetime.strptime(line[:16], "%Y-%m-%d %H:%M")] = line[23:].strip()
                except ValueError:
                    pass
    return errs


def explain(msgs):
    if not msgs:
        return "not sampled (collector was not running)"
    m = max(set(msgs), key=msgs.count)
    if "Tunnel connection failed" in m or "Name or service" in m or "EAI_AGAIN" in m:
        return "site unreachable"
    if "timed out" in m:
        return "site timed out"
    return "pull failed: " + m[:80]


def find_gaps(samples, closed):
    """Runs of opening-time minutes (06:00-22:00) with no pull at all, from the first
    sample to the last. These minutes are missing data: they are left out of every
    average, never counted as zero."""
    got = {t for (_, t) in samples}
    if not got:
        return []
    errs = load_errors()
    first, last = min(got), max(got)
    gaps, run = [], None
    t = first
    while t <= last:
        if 6 <= t.hour < 22 and t not in got:
            if run and run["end"] == t - timedelta(minutes=1):
                run["end"] = t
                run["msgs"] += [errs[t]] if t in errs else []
            else:
                if run:
                    gaps.append(run)
                run = {"start": t, "end": t, "msgs": [errs[t]] if t in errs else []}
        t += timedelta(minutes=1)
    if run:
        gaps.append(run)
    out = []
    for g in gaps:
        ds = g["start"].strftime("%Y-%m-%d")
        out.append({
            "date": ds, "dow": DOW[g["start"].weekday()],
            "start": g["start"].strftime("%H:%M"),
            "end": (g["end"] + timedelta(minutes=1)).strftime("%H:%M"),
            "minutes": int((g["end"] - g["start"]).total_seconds() // 60) + 1,
            "cause": explain(g["msgs"]),
            "closed_day": ds in closed,
        })
    return out


def load_samples():
    seen = {}
    # data/raw/ holds today's per-run files from GitHub Actions until the nightly merge
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "[0-9][0-9][0-9][0-9]-[0-9][0-9].csv"))) + \
            sorted(glob.glob(os.path.join(ROOT, "data", "raw", "*.csv"))):
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("center", "btcsc") != "btcsc":
                    continue
                t = datetime.strptime(r["ts_taipei"], "%Y-%m-%d %H:%M")
                # one sample per facility per minute (the site refreshes once a minute)
                key = (r["facility"], t)
                seen[key] = (int(r["count"]), int(r["capacity"] or 0))
    return seen


def main():
    cal = load_calendar()
    samples = load_samples()
    closed = closed_dates(samples)
    closed_fac = closed_facility_days(samples)
    slot_acc = defaultdict(list)    # (fac, view, row, slot) -> [(count, pct, date)]
    daily_acc = defaultdict(list)   # (fac, date, hour) -> [(count, pct)]
    cov = defaultdict(lambda: {"samples": 0, "dates": set(), "first": None, "last": None})

    for (fac, t), (count, cap) in samples.items():
        if fac not in HOURS:
            continue
        open_h, close_h = HOURS[fac]
        if not (open_h <= t.hour < close_h):
            continue
        if t.strftime("%Y-%m-%d") in closed or (fac, t.strftime("%Y-%m-%d")) in closed_fac:
            continue
        pct = count / cap if cap else None
        dt, _ = day_type(t.date(), cal)
        mins = (t.hour * 60 + t.minute) // SLOT_MIN * SLOT_MIN
        slot = f"{mins // 60:02d}:{mins % 60:02d}"
        ds = t.strftime("%Y-%m-%d")
        slot_acc[(fac, "type", dt, slot)].append((count, pct, ds))
        slot_acc[(fac, "dow", DOW[t.weekday()], slot)].append((count, pct, ds))
        daily_acc[(fac, ds, t.hour)].append((count, pct))
        c = cov[fac]
        c["samples"] += 1
        c["dates"].add(ds)
        stamp = t.strftime("%Y-%m-%d %H:%M")
        c["first"] = min(c["first"] or stamp, stamp)
        c["last"] = max(c["last"] or stamp, stamp)

    def avg(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 4) if xs else None

    slots = []
    for (fac, view, row, slot), v in sorted(slot_acc.items()):
        slots.append({
            "facility": NAMES[fac], "view": view,
            "row": TYPE_LABEL.get(row, row),
            "row_order": TYPE_ORDER[row] if view == "type" else DOW.index(row),
            "slot": slot,
            "avg_count": round(sum(x[0] for x in v) / len(v), 1),
            "avg_pct": avg([x[1] for x in v]),
            "max_count": max(x[0] for x in v),
            "samples": len(v),
            "days": len({x[2] for x in v}),
        })

    daily = []
    for (fac, ds, hour), v in sorted(daily_acc.items()):
        d = datetime.strptime(ds, "%Y-%m-%d").date()
        dt, name = day_type(d, cal)
        daily.append({
            "facility": NAMES[fac], "date": ds, "dow": DOW[d.weekday()],
            "day_type": TYPE_LABEL[dt], "holiday_name": name if dt == "holiday" else "",
            "hour": hour,
            "avg_count": round(sum(x[0] for x in v) / len(v), 1),
            "avg_pct": avg([x[1] for x in v]),
            "samples": len(v),
        })

    coverage = [{
        "facility": NAMES[f], "samples": c["samples"], "days": len(c["dates"]),
        "first_sample": c["first"], "last_sample": c["last"],
        "weekday_days": len({d for d in c["dates"] if day_type(datetime.strptime(d, "%Y-%m-%d").date(), cal)[0] == "weekday"}),
        "weekend_days": len({d for d in c["dates"] if day_type(datetime.strptime(d, "%Y-%m-%d").date(), cal)[0] == "weekend"}),
        "holiday_days": len({d for d in c["dates"] if day_type(datetime.strptime(d, "%Y-%m-%d").date(), cal)[0] == "holiday"}),
    } for f, c in sorted(cov.items(), key=lambda kv: list(NAMES).index(kv[0]))]

    gaps = find_gaps(samples, closed)
    open_gaps = [g for g in gaps if not g["closed_day"]]
    for c in coverage:
        c["gap_minutes"] = sum(g["minutes"] for g in open_gaps)
        c["gaps"] = len(open_gaps)

    # A plain record of every gap next to the raw data, so it survives any dashboard change.
    with open(os.path.join(ROOT, "data", "gaps.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "dow", "start", "end", "minutes", "cause", "closed_day"])
        w.writeheader()
        w.writerows(gaps)

    os.makedirs(OUT, exist_ok=True)
    for name, rows in (("slots", slots), ("daily", daily), ("coverage", coverage), ("gaps", gaps)):
        with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
        print(name, len(rows), "rows")
    print("left out (closed):", ", ".join(sorted(closed)) or "none")
    print("left out (one facility closed):",
          ", ".join(f"{NAMES[f]} {d}" for f, d in sorted(closed_fac) if d not in closed) or "none")


if __name__ == "__main__":
    main()
