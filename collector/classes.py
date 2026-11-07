#!/usr/bin/env python3
"""Snapshot the center's public class timetable (scr.cyc.org.tw/tp26.aspx, 課程查詢).

Classes explain crowd changes: swim lessons (泳訓) take pool lanes, ice-rink classes
take part of the rink, and aerobics/yoga classes pull people out of the gym.
Writes classes/YYYY-MM-DD.json (one row per class). Standard library only.
"""
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

URL = "https://scr.cyc.org.tw/tp26.aspx?module=class_booking&files=class_info"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPE = timezone(timedelta(hours=8))
DOW = {"一": "Mon", "二": "Tue", "三": "Wed", "四": "Thu", "五": "Fri", "六": "Sat", "日": "Sun"}


# 課程類別 radio values on the page
CATEGORIES = {"1": "有氧", "3": "瑜珈", "5": "武術", "2": "舞蹈", "7": "幼兒/兒童", "11": "球類",
              "16": "公益", "12": "泳訓團體", "20": "冰上樂園", "6": "專業運動"}


def get(url, tries=5, data=None):
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0 (occupancy-tracker)"})
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(last)


def parse(page):
    t = re.sub(r"<(script|style).*?</\1>", "", page, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", html.unescape(t))
    pat = re.compile(
        r"授課教師：(?P<teacher>.*?) 課程名稱：(?P<name>.*?) 課程代碼：(?P<code>\S+) 授課教室：(?P<room>.*?) "
        r"(?P<start>\d{4}-\d{2}-\d{2})~(?P<end>\d{4}-\d{2}-\d{2}) (?P<days>[一二三四五六日、,，]+) "
        r"(?P<t0>\d{2}:\d{2})~(?P<t1>\d{2}:\d{2}) 滿班人數：(?P<cap>\d+) ?人 可報名人數：(?P<left>\d+) ?人")
    rows = []
    for m in pat.finditer(t):
        d = m.groupdict()
        for ch in re.findall(r"[一二三四五六日]", d["days"]):
            rows.append({
                "code": d["code"], "name": d["name"].strip(),  # instructor names are not kept
                "room": d["room"].strip(), "start_date": d["start"], "end_date": d["end"],
                "dow": DOW[ch], "start": d["t0"], "end": d["t1"],
                "capacity": int(d["cap"]), "spots_left": int(d["left"]),
            })
    return rows


def fetch_all():
    rows = []
    for value, label in CATEGORIES.items():
        q = urllib.parse.urlencode({"A": "全部", "B": value, "C": "0", "D": "", "E": "1"})
        got = parse(get(URL + "&" + q))
        for r in got:
            r["category"] = label
        rows += got
        time.sleep(1)
    return rows


def main():
    rows = fetch_all()
    if not rows:
        sys.exit("no classes parsed; page layout may have changed")
    out = os.path.join(ROOT, "classes")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, datetime.now(TPE).strftime("%Y-%m-%d") + ".json")
    json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(path, len(rows), "class sessions")


if __name__ == "__main__":
    main()
