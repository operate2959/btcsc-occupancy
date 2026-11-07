#!/usr/bin/env python3
"""Export the last 48 hours of raw pulls (one row per minute) for the dashboard's log page.

Writes analysis/out/recent.json: [{ts_taipei, gym, gym_cap, swim, swim_cap, ice, ice_cap}]
"""
import csv
import glob
import json
import os
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPE = timezone(timedelta(hours=8))


def main(hours=48):
    cutoff = (datetime.now(TPE) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
    rows = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "[0-9][0-9][0-9][0-9]-[0-9][0-9].csv")))[-2:] + \
            sorted(glob.glob(os.path.join(ROOT, "data", "raw", "*.csv"))):
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("center", "btcsc") != "btcsc" or r["ts_taipei"] < cutoff:
                    continue
                row = rows.setdefault(r["ts_taipei"], {"ts_taipei": r["ts_taipei"]})
                row[r["facility"]] = int(r["count"])
                row[r["facility"] + "_cap"] = int(r["capacity"]) if r["capacity"] else None
    out = [rows[k] for k in sorted(rows)]
    os.makedirs(os.path.join(ROOT, "analysis", "out"), exist_ok=True)
    with open(os.path.join(ROOT, "analysis", "out", "recent.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print("recent", len(out), "rows")


if __name__ == "__main__":
    main()
