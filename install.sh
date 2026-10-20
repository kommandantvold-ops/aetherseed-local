#!/bin/bash
# AetherSeed Companion installer.
#
#   sudo ./install.sh [--lan] [--kiosk] [--check]
#
#   --check   only check the prerequisites; change nothing
#   --lan     let the console be reached from your network (default: this
#             device only, http://127.0.0.1:2077)
#   --kiosk   also install the full-screen display service (needs labwc and
#             chromium, as on Raspberry Pi OS with desktop)
#
# Safe to run again. It does not install the Hailo runtime, the driver or the
# model: those come from Hailo (see docs/INSTALL.md).
set -eu

SRC=$(cd "$(dirname "$0")" && pwd)
APP=/opt/aetherseed
STATE=/var/lib/aetherseed
MODEL=qwen3:1.7b
LAN=0; KIOSK=0; CHECK=0
for a in "$@"; do
  case $a in
    --lan) LAN=1 ;; --kiosk) KIOSK=1 ;; --check) CHECK=1 ;;
    -h|--help) sed -n 2,13p "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

fail=0
need() { # need <description> <command...>
  local d=$1; shift
  if "$@" >/dev/null 2>&1; then echo "  ok       $d"; else echo "  MISSING  $d"; fail=1; fi
}

echo "Checking prerequisites"
need "running as root"                      test "$(id -u)" = 0
need "systemd"                              test -d /run/systemd/system
need "python3 (3.11 or newer)"              python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'
need "python3 venv"                         python3 -c 'import venv, ensurepip'
need "curl"                                 command -v curl
need "Hailo device (/dev/h1x-0)"            test -e /dev/h1x-0
need "hailortcli"                           command -v hailortcli
need "hailo-ollama"                         command -v hailo-ollama
if [ -e /dev/h1x-0 ] && command -v hailortcli >/dev/null; then
  need "HailoRT 5.4.0"                      sh -c 'hailortcli --version 2>&1 | grep -q "5\.4\.0"'
fi
need "model $MODEL file in hailo-ollama's store" \
     sh -c 'ls /usr/share/hailo-ollama/models/blob/ 2>/dev/null | grep -qi qwen3'
need "tokenizer qwen3-1.7b.tokenizer.json"  sh -c "test -e $STATE/qwen3-1.7b.tokenizer.json || test -e $SRC/qwen3-1.7b.tokenizer.json"

if [ $fail = 1 ]; then
  echo
  echo "Some prerequisites are missing. See docs/INSTALL.md, 'Prerequisites'."
  [ $CHECK = 1 ] && exit 1
  echo "Nothing was changed."
  exit 1
fi
[ $CHECK = 1 ] && { echo "All prerequisites met."; exit 0; }

echo "Accounts"
getent group hailo >/dev/null || groupadd --system hailo
id aetherseed >/dev/null 2>&1 || useradd --system --home-dir "$STATE" --create-home \
  --shell /usr/sbin/nologin --comment "AetherSeed Companion" aetherseed
usermod -aG hailo aetherseed

echo "Application -> $APP"
install -d -o root -g root -m 755 "$APP"
( cd "$SRC" && tar --exclude=__pycache__ --exclude='test_*.py' --exclude=.git \
    --exclude=docs --exclude=install.sh --exclude=venv -cf - \
    *.py gui kiosk knowledge library logic tools training requirements.txt ) | tar -x -C "$APP" --no-same-owner
chown -R root:root "$APP"; chmod -R a+rX,go-w "$APP"

echo "Python environment"
[ -x "$APP/venv/bin/python3" ] || python3 -m venv --system-site-packages "$APP/venv"
"$APP/venv/bin/pip" install --quiet -r "$APP/requirements.txt"

echo "Model and state"
install -d -o root -g root -m 755 /etc/aetherseed
echo "AETHERSEED_MODEL=$MODEL" > /etc/aetherseed/model.env
chmod 644 /etc/aetherseed/model.env
install -d -o aetherseed -g aetherseed -m 750 "$STATE"
if [ ! -e "$STATE/qwen3-1.7b.tokenizer.json" ] && [ -e "$SRC/qwen3-1.7b.tokenizer.json" ]; then
  install -o aetherseed -g aetherseed -m 644 "$SRC/qwen3-1.7b.tokenizer.json" "$STATE/"
fi

echo "Services"
UNITS="hailo-ollama aetherseed-proxy aetherseed-warmup aetherseed-gui aetherseed-keepalive"
for u in $UNITS; do
  install -o root -g root -m 644 "$SRC/services/$u.service" "/etc/systemd/system/$u.service"
done
install -d /etc/systemd/system/hailo-ollama.service.d
install -o root -g root -m 644 "$SRC/services/hailo-ollama.hailort540.conf" \
  /etc/systemd/system/hailo-ollama.service.d/hailort-540.conf
install -o root -g root -m 644 "$SRC/services/99-aetherseed-hailo1x.rules" /etc/udev/rules.d/
if [ $LAN = 0 ]; then
  install -d /etc/systemd/system/aetherseed-gui.service.d
  printf '[Service]\nEnvironment=AETHERSEED_GUI_BIND=127.0.0.1\n' \
    > /etc/systemd/system/aetherseed-gui.service.d/bind.conf
else
  rm -f /etc/systemd/system/aetherseed-gui.service.d/bind.conf
fi
if [ $KIOSK = 1 ]; then
  id aetherseed-kiosk >/dev/null 2>&1 || useradd --create-home --shell /usr/sbin/nologin \
    --comment "AetherSeed Companion screen" --groups video,render,input aetherseed-kiosk
  for u in aetherseed-kiosk aetherseed-kiosk-watch; do
    install -o root -g root -m 644 "$SRC/services/$u.service" "/etc/systemd/system/$u.service"
  done
  UNITS="$UNITS aetherseed-kiosk aetherseed-kiosk-watch"
fi
udevadm control --reload-rules
udevadm trigger --subsystem-match=hailo1x || true
systemctl daemon-reload

echo "Manual"
( cd "$APP" && HOME="$STATE" "$APP/venv/bin/python3" -m logic.manual ) || \
  echo "  (manual not built; the console still works)"

echo "Starting"
systemctl enable --now $UNITS

echo
echo "Done. Check:  systemctl --failed   and   journalctl -u aetherseed-proxy -n 20"
echo "Console:      http://127.0.0.1:2077"
