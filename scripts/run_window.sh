#!/usr/bin/env bash
# Used by .github/workflows/collect.yml: run the collector for one time window
# and push its samples every 10 minutes, so a crash loses at most 10 minutes.
#
# The collector writes to private files outside the repo. Each push starts from
# the latest main and merges this run's rows into the shared file there, so two
# runs writing the same day's file can never leave a merge conflict behind.
# (Before 2026-11-13 a run rebased its commit onto main; when another run had
# appended to the same file, the rebase stopped on a conflict that nothing
# cleared, and every later push in that run failed: 5-6 hours lost on 11-11
# and again on 11-13.)
set -u
DAY=$(TZ=Asia/Taipei date +%F)
OUT="data/raw/${DAY}_${TAG}.csv"
LOG="logs/raw/${DAY}_${TAG}.log"
PRIV="${RUNNER_TEMP:-/tmp}/collect-${TAG}"
PRIV_OUT="$PRIV.csv"
PRIV_LOG="$PRIV.log"

# merge_rows DEST SRC: DEST becomes the union of DEST and SRC lines, in time
# order, without duplicates. A CSV header line (starting "ts_utc,") stays on top.
merge_rows() {
  python3 - "$1" "$2" <<'PY'
import os, sys
dest, src = sys.argv[1], sys.argv[2]
header, rows, seen = None, [], set()
for path in (dest, src):
    if not os.path.exists(path):
        continue
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f.read().splitlines():
            if not line.strip():
                continue
            if line.startswith("ts_utc,"):
                header = header or line
                continue
            if line not in seen:
                seen.add(line)
                rows.append(line)
# Both formats start with a sortable timestamp: ISO UTC in the CSV, Taipei
# "YYYY-MM-DD HH:MM" in the log. Sort on it only, keeping row order within a minute.
key = (lambda l: l.split(",", 1)[0]) if header else (lambda l: l[:16])
rows.sort(key=key)
if rows:
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(([header] if header else []) + rows) + "\n")
    os.replace(tmp, dest)
PY
}

push() {
  [ -s "$PRIV_OUT" ] || [ -s "$PRIV_LOG" ] || return 0
  for i in 1 2 3 4 5; do
    # Clear anything a failed attempt left behind, then start from the latest main.
    git rebase --abort >/dev/null 2>&1
    git merge --abort >/dev/null 2>&1
    if git fetch -q origin main && git reset -q --hard FETCH_HEAD; then
      merge_rows "$OUT" "$PRIV_OUT"
      merge_rows "$LOG" "$PRIV_LOG"
      git add -f "$OUT" "$LOG" 2>/dev/null
      git diff --cached --quiet && return 0
      git commit -q -m "samples $DAY run $TAG ($(TZ=Asia/Taipei date +%H:%M))"
      git push -q origin HEAD:main && return 0
    fi
    sleep $((i * 5))
  done
  echo "push failed, will retry next round"
}

# Sourced by the test: stop here, with the functions defined.
[ "${BASH_SOURCE[0]}" = "$0" ] || return 0

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

ARGS=(--loop --aligned --interval 60 --to "$TO" --out "$PRIV_OUT" --log "$PRIV_LOG")
[ -n "${FROM:-}" ] && ARGS+=(--from "$FROM")
[ "${ALWAYS:-}" = "true" ] && ARGS+=(--always)
python3 collector/collect.py "${ARGS[@]}" &
PID=$!
while kill -0 $PID 2>/dev/null; do
  for _ in $(seq 60); do kill -0 $PID 2>/dev/null || break; sleep 10; done
  push
done
wait $PID
push
