#!/usr/bin/env python3
"""Nightly: fold the per-run files from GitHub Actions (data/raw/, logs/raw/) into
data/YYYY-MM.csv and logs/collector.log, then delete them. Rows are de-duplicated
on (ts_taipei, center, facility), so running this twice, or overlapping runs, is safe."""
import csv
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collector"))
from collect import FIELDS  # noqa: E402


def main():
    raw = sorted(glob.glob(os.path.join(ROOT, "data", "raw", "*.csv")))
    new = {}
    for p in raw:
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                new.setdefault(r["ts_taipei"][:7], []).append(r)
    for month, rows in sorted(new.items()):
        path = os.path.join(ROOT, "data", f"{month}.csv")
        have = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                have = list(csv.DictReader(f))
        seen, merged = set(), []
        for r in have + rows:
            k = (r["ts_taipei"], r["center"], r["facility"])
            if k not in seen:
                seen.add(k)
                merged.append(r)
        merged.sort(key=lambda r: (r["ts_taipei"], r["center"]))
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(merged)
        print(f"{month}: +{len(merged) - len(have)} rows")
    logs = sorted(glob.glob(os.path.join(ROOT, "logs", "raw", "*.log")))
    if logs:
        lines = []
        for p in logs:
            lines += open(p, encoding="utf-8", errors="replace").read().splitlines()
        with open(os.path.join(ROOT, "logs", "collector.log"), "a", encoding="utf-8") as f:
            f.write("\n".join(sorted(lines)) + "\n")
    for p in raw + logs:
        os.remove(p)
    print(f"merged {len(raw)} data files, {len(logs)} logs")


if __name__ == "__main__":
    main()
