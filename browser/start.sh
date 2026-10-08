#!/bin/bash
set -eu
umask 077
Xvfb :99 -screen 0 1440x1000x24 -nolisten tcp &
display_pid=$!
for attempt in {1..100}; do
  xdpyinfo -display :99 >/dev/null 2>&1 && break
  kill -0 "$display_pid" || exit 1
  sleep 0.1
done
xdpyinfo -display :99 >/dev/null
openbox &
window_pid=$!
node /app/hd-browser/server.mjs &
worker_pid=$!
cleanup() {
  trap - EXIT INT TERM
  kill -TERM "$worker_pid" 2>/dev/null || true
  for attempt in {1..350}; do
    kill -0 "$worker_pid" 2>/dev/null || break
    sleep 0.1
  done
  kill "$window_pid" "$display_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM
wait -n "$worker_pid" "$display_pid" "$window_pid"
exit 1
