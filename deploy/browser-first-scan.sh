#!/bin/bash
# One bounded smoke scan after the existing cooldown, run entirely on Unraid.
set -eu
exec 9>/var/lock/hdscanner-browser-first-scan.lock
flock -n 9 || exit 1
deadline=$((SECONDS + 5400))
echo 'Waiting for the saved Home Depot cooldown before one limited browser scan.'
while docker exec hdscanner python -c 'from hd.config import Settings; from hd.http.cooldown import ThrottleCooldown; s=Settings(); raise SystemExit(0 if ThrottleCooldown(s.throttle_cooldown_path).is_active() else 1)'; do
  if (( SECONDS > deadline )); then
    echo 'Cooldown is still active; no scan was attempted.'
    exit 1
  fi
  sleep 30
done
date -u
docker exec -e BROWSE_REQUEST_BUDGET=12 hdscanner hd browse --tier shelf
docker exec hdscanner python -c 'import sqlite3; c=sqlite3.connect("file:/data/dev.db?mode=ro",uri=True); print("Saved price snapshots:",c.execute("select count(*) from store_snapshots where price_value is not null").fetchone()[0])'
echo 'First browser scan finished; see the dashboard for products and coverage.'
