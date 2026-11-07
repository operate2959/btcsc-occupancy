#!/usr/bin/env bash
# Used by .github/workflows/collect.yml: run the collector for one time window
# and push its samples every 10 minutes, so a crash loses at most 10 minutes.
set -u
DAY=$(TZ=Asia/Taipei date +%F)
OUT="data/raw/${DAY}_${TAG}.csv"
LOG="logs/raw/${DAY}_${TAG}.log"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

push() {
  [ -e "$OUT" ] || [ -e "$LOG" ] || return 0
  git add -f "$OUT" "$LOG" 2>/dev/null
  git diff --cached --quiet && return 0
  git commit -q -m "samples $DAY run $TAG ($(TZ=Asia/Taipei date +%H:%M))"
  for i in 1 2 3 4 5; do
    git pull -q --rebase origin main && git push -q origin HEAD:main && return 0
    sleep $((i * 5))
  done
  echo "push failed, will retry next round"
}

ARGS=(--loop --aligned --interval 60 --to "$TO" --out "$OUT" --log "$LOG")
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
