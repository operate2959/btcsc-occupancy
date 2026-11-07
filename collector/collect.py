#!/usr/bin/env python3
"""Record live occupancy for CYC-run sports centers (default: Beitun, btcsc).

The site banner reads a tiny JSON endpoint, refreshed by the server every minute:
    POST https://<center>.cyc.org.tw/api
    -> {"gym":["58","100","0"],"swim":["21","150","0"],"ice":["32","300","0"]}
Each facility is [people inside, capacity, third value (always "0" so far; kept raw)].

One run = one snapshot appended to data/YYYY-MM.csv. Use --loop to keep sampling.
Standard library only, so it runs anywhere (GitHub Actions, a laptop, a container).
"""
import argparse
import csv
import json
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

TPE = timezone(timedelta(hours=8))
FIELDS = ["ts_utc", "ts_taipei", "center", "facility", "count", "capacity", "extra"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Opening hours (Taipei time). Source: btcsc.cyc.org.tw footer, checked 2026-10-19.
# Whole center 06:00-22:00 daily; ice rink 10:00-21:00. We sample a few minutes past
# both ends so we see the ramp-up, the last people leaving, and any count left over
# after closing (the counter does not always return to 0, see README).
OPEN_FROM, OPEN_TO = (5, 50), (22, 50)


def _ssl_context():
    # Full certificate verification stays on. Python 3.13 adds an extra "strict"
    # X.509 check that some older certificate chains fail, so turn only that off.
    ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE"))
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return ctx


def fetch(center, tries=5):
    url = f"https://{center}.cyc.org.tw/api"
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, data=b"", method="POST",
                headers={"User-Agent": "Mozilla/5.0 (occupancy-tracker)",
                         "X-Requested-With": "XMLHttpRequest"})
            with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # network blips are common; retry with backoff
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{center}: {last}")


def snapshot(center, data_dir, out=None):
    now = datetime.now(timezone.utc)
    payload = fetch(center)
    rows = []
    for facility, vals in payload.items():
        if not isinstance(vals, list) or not vals or not str(vals[0]).strip().isdigit():
            continue  # e.g. "找不到資源" when a facility feed is down
        rows.append({
            "ts_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ts_taipei": now.astimezone(TPE).strftime("%Y-%m-%d %H:%M"),
            "center": center,
            "facility": facility,
            "count": int(vals[0]),
            "capacity": int(vals[1]) if len(vals) > 1 and str(vals[1]).isdigit() else "",
            "extra": vals[2] if len(vals) > 2 else "",
        })
    path = out or os.path.join(data_dir, now.astimezone(TPE).strftime("%Y-%m") + ".csv")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    return rows


LOG_PATH = os.path.join(ROOT, "logs", "collector.log")


def log(line):
    # Append-and-close per line, so a crash never loses earlier lines.
    path = LOG_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def is_open(t):
    hm = (t.hour, t.minute)
    return OPEN_FROM <= hm <= OPEN_TO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--center", action="append", help="subdomain, e.g. btcsc (repeatable)")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    ap.add_argument("--loop", action="store_true", help="keep sampling")
    ap.add_argument("--interval", type=int, default=300, help="seconds between samples")
    ap.add_argument("--always", action="store_true", help="ignore opening hours")
    ap.add_argument("--duration", type=float, default=0,
                    help="with --loop: stop after this many minutes (0 = forever)")
    ap.add_argument("--aligned", action="store_true",
                    help="with --loop: only sample on interval boundaries (:00, :05 ...), "
                         "so back-to-back runs never double-sample")
    ap.add_argument("--until-minute", type=int, default=None,
                    help="with --loop: stop at the next HH:<minute>:30 at least 30 minutes away. "
                         "Hourly runs then hand over without a gap: the old run keeps sampling "
                         "until the new one (waiting for it to exit) takes over.")
    ap.add_argument("--out", help="append samples to this CSV instead of data/YYYY-MM.csv")
    ap.add_argument("--log", help="write the log here instead of logs/collector.log")
    ap.add_argument("--from", dest="start", help="with --loop: wait until this Taipei time (HH:MM) today")
    ap.add_argument("--to", dest="end", help="with --loop: stop after the sample at this Taipei time (HH:MM) today")
    a = ap.parse_args()
    if a.log:
        global LOG_PATH
        LOG_PATH = a.log
    centers = a.center or ["btcsc"]

    stop_at = time.time() + a.duration * 60 if a.duration else None
    if a.until_minute is not None:
        now = datetime.now(TPE)
        t = now.replace(minute=a.until_minute, second=30, microsecond=0)
        while t - now < timedelta(minutes=30):
            t += timedelta(hours=1)
        stop_at = t.timestamp()
    today = datetime.now(TPE)
    if a.end:
        h, m = map(int, a.end.split(":"))
        stop_at = today.replace(hour=h, minute=m, second=30, microsecond=0).timestamp()
    if a.start:
        h, m = map(int, a.start.split(":"))
        begin = today.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()
        if begin - time.time() > 5:
            time.sleep(begin - time.time() - 5)  # the aligned sleep below lands on HH:MM
    if a.loop and a.aligned:
        time.sleep(a.interval - (time.time() % a.interval) + 1)
    while True:
        if stop_at and time.time() >= stop_at:
            break
        now = datetime.now(TPE)
        if a.always or is_open(now):
            for c in centers:
                try:
                    rows = snapshot(c, a.data_dir, a.out)
                    line = " ".join([now.strftime("%F %H:%M"), c] +
                                    [f"{r['facility']}={r['count']}/{r['capacity']}" for r in rows])
                    print(line, flush=True)
                    log(line)
                except Exception as e:
                    line = f"{now.strftime('%F %H:%M')} ERROR {e}"
                    print(line, file=sys.stderr, flush=True)
                    log(line)
        if not a.loop:
            break
        if stop_at and time.time() + (a.interval - time.time() % a.interval) >= stop_at:
            break
        # sleep to the next interval boundary (e.g. :00, :05, :10 ...)
        time.sleep(a.interval - (time.time() % a.interval) + 1)


if __name__ == "__main__":
    main()
