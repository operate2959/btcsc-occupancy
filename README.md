# Beitun Sports Center occupancy tracker

Tracks how many people are in the gym, pool and ice rink at 臺中市北屯國民暨兒童運動中心
(https://btcsc.cyc.org.tw/) so we can find the quietest times to go.

## Where the numbers come from

No history is published. The banner on the homepage reads a small JSON endpoint that
the server refreshes every minute:

```
POST https://btcsc.cyc.org.tw/api        (GET also works)
{"gym":["58","100","0"],"swim":["21","150","0"],"ice":["32","300","0"]}
```

Each facility is `[people inside, capacity, third value]`. The third value has always
been "0" so far and is stored raw as `extra`. Other centers run by the same operator
(China Youth Corps) expose the same endpoint on their own subdomain, e.g.
`ngsc.cyc.org.tw/api`, `nhsc.cyc.org.tw/api`.

Opening hours: whole center 06:00–22:00 daily, ice rink 10:00–21:00. Closed on Lunar
New Year's Eve and Day; 08:00–16:00 on days 2–5 of the Lunar New Year; closed when
Taichung suspends work for typhoons.

## How collection runs

On GitHub Actions in this repo (free on a public repo). Nothing runs on anyone's computer.

- `.github/workflows/collect.yml` samples once a minute from 05:50 to 22:51 Taipei time.
  GitHub can't schedule a job every minute, so the day is split into four runs of about
  4h20m (05:50, 10:11, 14:31, 18:51) that each loop inside themselves. Each run is
  scheduled about 50 minutes early because GitHub often starts scheduled runs late,
  then waits for its window. It pushes its samples every 10 minutes to
  `data/raw/<date>_<run>.csv` (and its log to `logs/raw/`).
- `.github/workflows/nightly.yml` (23:23) merges the day's runs into `data/YYYY-MM.csv`
  and `logs/collector.log`, rebuilds `analysis/out/*.json` for the dashboard and, on
  Mondays, snapshots the class timetable.
- Either workflow can be started by hand from the Actions tab ("Run workflow").
- If a run fails or starts very late, those minutes show up in `data/gaps.csv` and are
  left out of the averages.
- From 2026-10-19 to 2026-11-07 the same collector ran in a Claude Code cloud session.

## Files

| Path | What |
|---|---|
| `data/YYYY-MM.csv` | Raw samples: `ts_utc, ts_taipei, center, facility, count, capacity, extra` |
| `data/gaps.csv` | Every stretch of opening time with no pull (site down, collector not running) and why. Rebuilt nightly. Missing minutes are left out of averages, never counted as 0 |
| `data/manual_observations.csv` | Counts people saw in person, kept separate from the feed and not used in averages |
| `calendar/YYYY.json` | Taiwan office calendar (DGPA, via github.com/ruyut/TaiwanCalendar) for weekday/weekend/holiday |
| `calendar/closures.json` | Days the center was closed (e.g. typhoon days). Samples are kept but left out of averages; days where gym and pool read 0 all day are left out automatically |
| `collector/collect.py` | Collector (standard library only). `python3 collect.py` = one sample |
| `analysis/build_aggregates.py` | Builds `analysis/out/{slots,daily,coverage,gaps}.json` for the dashboard, plus `data/gaps.csv` |
| `logs/collector.log` | Collector output |
| `data/raw/`, `logs/raw/` | Today's per-run files from Actions, merged nightly |
| `analysis/out/` | Tables the dashboard reads, rebuilt nightly |
| `scripts/` | `run_window.sh` (one collection run), `merge_raw.py` (nightly merge) |

Day types: **holiday** = a named public holiday or bridge day off; **weekend** = any other
day off; **weekday** = a working day, including make-up working Saturdays.

Dashboard: a private heatmap page built from `analysis/out/`.

## Other public signals

- `collector/classes.py` snapshots the public class timetable weekly into `classes/YYYY-MM-DD.json`
  (`scr.cyc.org.tw/tp26.aspx?module=class_booking&files=class_info&A=全部&B=<category>&C=0&D=&E=1`).
  Swim lessons (泳訓團體) run in the pool on weekday evenings (17:00–21:00) and weekend
  mornings and afternoons; ice-rink classes take part of the rink.
- Fixed closures, from the FAQ: pool cleared 10:00–10:30 daily (not during school breaks);
  ice resurfaced 13:30–14:00 and 17:30–18:00.
- Not available: per-zone counts (weights vs cardio), cameras, court bookings (need a login).

## Known quirk: counts don't return to 0 at closing

The feed is almost certainly an entry/exit gate counter (people in = entries − exits). Anyone
who leaves without being counted out stays "inside" until the system resets overnight.
On 2026-10-19 the ice rink sat at exactly 12 from 21:14 to 22:10 (rink closes 21:00) and
the gym at 13 at 22:10; by 00:46 all three read 0. So each evening's count carries a
phantom remainder that builds up through the day. The collector samples until 22:50 to
measure that remainder each night, so the analysis can correct for it.
