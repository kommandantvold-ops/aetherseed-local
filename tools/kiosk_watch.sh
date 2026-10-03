#!/bin/bash
# kiosk_watch.sh - restart the screen when the browser is up and the console is not on it.
#
# Build log 53. On 3 Oct 2026 a pilot unit (Stella) came up twice on a blank
# white page with every service active. The browser had started while the
# network was still coming up: the Ethernet address arrived in the same second
# as the page load (16:40:46), Chromium cut the load off, and a kiosk browser
# does not try again. Waiting for the console to answer before starting the
# browser (the kiosk unit's ExecStartPre) did not prevent it - the server was
# answering; the browser's own load was what failed.
#
# So this watches the result instead of guessing the cause. The console page
# asks for /aetherseed/status every 15 seconds while it is loaded, and the
# console server touches SEEN on each one (gui/serve.py). If the kiosk has
# been active for GRACE seconds and SEEN is older than STALE seconds - or was
# never written - the page is not on the screen, whatever the reason, and the
# kiosk is restarted. It reads two timestamps and restarts one unit; it reads
# nothing anybody typed.
set -u
SEEN="${AETHERSEED_CONSOLE_SEEN:-/run/aetherseed-gui/console-seen}"
KIOSK="${AETHERSEED_KIOSK_UNIT:-aetherseed-kiosk.service}"
GUI="${AETHERSEED_GUI_UNIT:-aetherseed-gui.service}"
QUIET="${AETHERSEED_KIOSK_QUIET:-90}"     # seconds without a poll before the screen is restarted
EVERY="${AETHERSEED_KIOSK_EVERY:-20}"

# 0 = leave it, 1 = restart. Arguments: now, kiosk-active-since, console-server-
# active-since (0 = not active), seen-mtime (0 = never). The clock for "quiet"
# starts at the latest of: the last poll, the browser's start, the console
# server's start - so a browser still starting, or a console server that was
# just restarted (its runtime directory, and SEEN with it, is new), is given
# QUIET seconds before anything is concluded. A function, so it can be tested
# without systemd.
decide() {
  local now="$1" kiosk="$2" gui="$3" seen="$4" last
  [ "$kiosk" -gt 0 ] || return 0            # the screen is not running: not ours to start
  [ "$gui" -gt 0 ] || return 0              # no console to show: the kiosk waits for it itself
  last="$seen"
  [ "$kiosk" -gt "$last" ] && last="$kiosk"
  [ "$gui" -gt "$last" ] && last="$gui"
  [ $((now - last)) -ge "$QUIET" ] && return 1
  return 0
}

since() {   # when a unit became active, in epoch seconds; 0 if it is not active
  [ "$(systemctl is-active "$1" 2>/dev/null)" = "active" ] || { echo 0; return; }
  date -d "$(systemctl show -p ActiveEnterTimestamp --value "$1")" +%s 2>/dev/null || echo 0
}

if [ "${1:-}" = "--decide" ]; then decide "$2" "$3" "$4" "$5"; exit $?; fi

while sleep "$EVERY"; do
  now="$(date +%s)"
  seen="$(stat -c %Y "$SEEN" 2>/dev/null || echo 0)"
  if ! decide "$now" "$(since "$KIOSK")" "$(since "$GUI")" "$seen"; then
    echo "[kiosk-watch] no poll from the console page for ${QUIET}s or more - restarting $KIOSK"
    systemctl restart "$KIOSK"
  fi
done
