#!/bin/bash
# The ecosystem soak, on a copy of the companion's memory (training/README.md).
#
#   sudo bash /opt/aetherseed/training/run-ecosystem-soak.sh [HOURS]
#
# HOURS defaults to 1. It starts in the background and returns at once; the
# report is written when the time is up. Her own memory and trust are never
# written to. Build log 49.
set -euo pipefail

HOURS="${1:-1}"
case "$HOURS" in
  ''|*[!0-9.]*) echo "HOURS must be a number, e.g. 1 or 0.5" >&2; exit 2 ;;
esac
if [ "$(id -u)" -ne 0 ]; then
  echo "run it with sudo: sudo bash $0 $HOURS" >&2; exit 2
fi

APP="$(cd "$(dirname "$0")/.." && pwd)"
STATE=/var/lib/aetherseed/.aetherseed
BASE=/var/lib/aetherseed/training
STAMP="$(date +%Y%m%d-%H%M%S)"
DIR="$BASE/ecosystem-$STAMP"
UNIT="aetherseed-training-$STAMP"

if systemctl list-units --no-legend --state=active 'aetherseed-training-*' | grep -q .; then
  echo "a training run is already going:" >&2
  systemctl list-units --no-legend --state=active 'aetherseed-training-*' >&2
  exit 1
fi
[ -f "$STATE/aetherroot/memory.db" ] || { echo "no memory at $STATE" >&2; exit 1; }

install -d -o aetherseed -g aetherseed -m 750 "$BASE"
systemd-run --quiet --unit="$UNIT" --uid=aetherseed --gid=aetherseed \
  --property=WorkingDirectory=/var/lib/aetherseed \
  "$APP/venv/bin/python3" "$APP/training/ecosystem_soak.py" \
  --dir "$DIR" --copy-from "$STATE" --hours "$HOURS"

cat <<EOF
Started: $UNIT, for $HOURS hour(s).
  results:  $DIR
  watch:    journalctl -f -u $UNIT
  so far:   sudo -u aetherseed $APP/venv/bin/python3 $APP/training/ecosystem_soak.py --report $DIR
  stop:     sudo -u aetherseed touch $DIR/STOP   (it finishes the turn and writes the report)
  report:   $DIR/report.txt, when it ends
Her answers are slower while it runs: the soak shares the one model.
EOF
