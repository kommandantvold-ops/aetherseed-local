#!/bin/bash
# The offline proof (training/offline_proof.py says what it is and claims).
#
#   sudo bash /opt/aetherseed/training/run-offline-proof.sh [MINUTES]
#
# MINUTES is how long she is questioned once the unit is isolated; 10 unless
# told otherwise. It returns at once. Then: pull the cable, wait MINUTES plus
# one, put it back. Her own memory and trust are never written to. Build log 56.
set -euo pipefail

MINUTES="${1:-10}"
case "$MINUTES" in
  ''|*[!0-9.]*) echo "MINUTES must be a number, e.g. 10" >&2; exit 2 ;;
esac
if [ "$(id -u)" -ne 0 ]; then
  echo "run it with sudo: sudo bash $0 $MINUTES" >&2; exit 2
fi

APP="$(cd "$(dirname "$0")/.." && pwd)"
BASE=/var/lib/aetherseed/training
STAMP="$(date +%Y%m%d-%H%M%S)"
DIR="$BASE/offline-$STAMP"
UNIT="aetherseed-training-offline-$STAMP"

if systemctl list-units --no-legend --state=active 'aetherseed-training-*' | grep -q .; then
  echo "a training run is already going:" >&2
  systemctl list-units --no-legend --state=active 'aetherseed-training-*' >&2
  exit 1
fi
[ -f /var/lib/aetherseed/.aetherseed/aetherroot/memory.db ] || { echo "no memory on this unit" >&2; exit 1; }
# A unit with its own Wi-Fi puts it up when the cable is pulled (build log
# 60) - and the proof waits for every radio to be off. Say so, rather than
# wait twenty minutes for it.
if systemctl is-active --quiet aetherseed-hotspot 2>/dev/null \
   && nmcli -t -f NAME connection show 2>/dev/null | grep -qx aetherseed-hotspot; then
  echo "this unit puts up its own Wi-Fi when the cable is pulled, and the proof needs" >&2
  echo "every radio off. For the proof:" >&2
  echo "  sudo systemctl stop aetherseed-hotspot && sudo nmcli radio wifi off" >&2
  echo "and afterwards:" >&2
  echo "  sudo systemctl start aetherseed-hotspot" >&2
  exit 1
fi

install -d -o aetherseed -g aetherseed -m 750 "$BASE"
systemd-run --quiet --unit="$UNIT" --setenv=PYTHONDONTWRITEBYTECODE=1 \
  "$APP/venv/bin/python3" "$APP/training/offline_proof.py" --dir "$DIR" --minutes "$MINUTES"

cat <<EOF
Started: $UNIT. It is watching the unit now.
  1. Pull the network cable. Radios must be off already:
$(rfkill list 2>/dev/null | sed 's/^/       /')
  2. The questions start by themselves when there is no link, no default
     route and no radio, and go on for $MINUTES minutes. It waits 20 minutes
     for that, then gives up.
  3. Put the cable back any time after that.
  report:   $DIR/report.txt
  watch:    journalctl -f -u $UNIT        (on the unit's own keyboard)
Her answers are slower while it runs: it shares the one model.
EOF
