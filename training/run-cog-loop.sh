#!/bin/bash
# The COG-loop (training/cog_loop.py, build log 73).
#
#   sudo bash /opt/aetherseed/training/run-cog-loop.sh [SESSIONS]
#
# SESSIONS defaults to 1 (about half an hour on Lyra). It starts in the
# background and returns at once. Her notebook is kept per model in
# /var/lib/aetherseed/cog/<model>/, so each new start continues where the last
# one ended - that is what "across sessions" measures. Her memory, trust and
# training runs are never written to.
set -euo pipefail

SESSIONS="${1:-1}"
case "$SESSIONS" in
  ''|*[!0-9]*) echo "SESSIONS must be a whole number, e.g. 1 or 4" >&2; exit 2 ;;
esac
if [ "$(id -u)" -ne 0 ]; then
  echo "run it with sudo: sudo bash $0 $SESSIONS" >&2; exit 2
fi

APP="$(cd "$(dirname "$0")/.." && pwd)"
PY="$APP/venv/bin/python3"
[ -x "$PY" ] || PY=python3

if systemctl list-units --no-legend --state=active 'aetherseed-cog-*' | grep -q .; then
  echo "a COG-loop is already going:" >&2
  systemctl list-units --no-legend --state=active 'aetherseed-cog-*' >&2
  exit 1
fi
STATUS="$(curl -s --max-time 5 http://127.0.0.1:8001/aetherseed/training || true)"
case "$STATUS" in
  *'"status": "running"'*) echo "a training run is on - start the COG-loop after it ends" >&2; exit 1 ;;
esac

# the proxy's own settings (model, tokenizer), so both count the same way
ENVS=()
for kv in $(systemctl show -p Environment --value aetherseed-proxy 2>/dev/null); do
  case "$kv" in AETHERSEED_*=*) ENVS+=(--setenv="$kv") ;; esac
done

MODEL="$(sudo -u aetherseed env "${ENVS[@]/--setenv=/}" "$PY" -c \
  'import sys; sys.path.insert(0, "'"$APP"'"); from logic import served; print(served.served_model())')"
BASE=/var/lib/aetherseed/cog
DIR="$BASE/${MODEL//[^A-Za-z0-9._-]/_}"
STAMP="$(date +%Y%m%d-%H%M%S)"
UNIT="aetherseed-cog-$STAMP"

install -d -o aetherseed -g aetherseed -m 750 "$BASE"
install -d -o aetherseed -g aetherseed -m 750 "$DIR"
rm -f "$DIR/STOP"
systemd-run --quiet --unit="$UNIT" --uid=aetherseed --gid=aetherseed \
  --property=WorkingDirectory=/var/lib/aetherseed "${ENVS[@]}" \
  "$PY" "$APP/training/cog_loop.py" --dir "$DIR" --sessions "$SESSIONS" --model "$MODEL"

cat <<EOF
Started: $UNIT, $SESSIONS session(s), model $MODEL.
  her notebook and sessions:  $DIR
  watch:    journalctl -f -u $UNIT
  so far:   sudo -u aetherseed $PY $APP/training/cog_loop.py --report $DIR
  stop:     sudo -u aetherseed touch $DIR/STOP   (ends before the next session)
            the steward's brake, or a training run, stops it at the next call
Her answers are slower while it runs: it shares the one model.
EOF
