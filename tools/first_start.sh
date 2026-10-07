#!/bin/bash
# The first start of a unit that is onboarded where it will live (build log 66).
#
# Andreas, 7 Oct 2026: "Onboarded on-site means the user will pick name passkey
# and start it for the first time." Until now a unit's own Wi-Fi was set up by
# whoever installed it, at a shell (tools/hotspot.sh on), and its clock by the
# network it was built on. A unit that is copied from a source card and opened
# in someone's home has neither a shell nor - since build log 55 - a network
# that tells it the time, and the board has no battery on its clock.
#
# So the first-start screen asks for three things: the companion's name (as it
# always did), the date and time, and a passkey for the unit's own Wi-Fi. The
# name goes where it always went. The other two need root, and the console
# has none and must not get any (it runs unprivileged, NoNewPrivileges). It
# leaves a request in its own runtime directory, as it does for shutdown;
# services/aetherseed-first-start.path sees it and starts this, as root.
#
#   the request, two lines:   2026-10-07 15:30
#                             <the passkey, as typed>
#
# What this does with it, and nothing else:
#   - removes the request at once (tmpfs, mode 600, and now gone);
#   - refuses unless the unit is ARMED: /etc/aetherseed/first-start exists.
#     tools/source_card.sh puts it there when a card is made a source; this
#     removes it when the first start is done. A unit that was set up at a
#     shell (Lyra, Stella, Xena) never has it, and nothing here can change
#     their clock or their passkey;
#   - sets the clock, and saves it where the unit resumes from at start;
#   - sets up the unit's Wi-Fi, named after the companion, with the passkey -
#     through tools/hotspot.sh, which checks both and keeps the passkey in the
#     network profile and nowhere else;
#   - leaves its answer for the console to show: ok, or what went wrong.
#
# The passkey is never written to a log, the journal or the result.
set -u
export PATH=$PATH:/usr/sbin:/sbin

RUN_DIR=${AETHERSEED_GUI_RUN:-/run/aetherseed-gui}
REQUEST=$RUN_DIR/first-start-request
RESULT=$RUN_DIR/first-start-result
FLAG=${AETHERSEED_FIRST_START_FLAG:-/etc/aetherseed/first-start}
HOTSPOT=${AETHERSEED_HOTSPOT:-/opt/aetherseed/tools/hotspot.sh}
STATUS_URL=${AETHERSEED_STATUS_URL:-http://127.0.0.1:8001/aetherseed/status}
SET_CLOCK=${AETHERSEED_SET_CLOCK:-}          # a stand-in for the tests
SAVED_CLOCK=${AETHERSEED_SAVED_CLOCK:-/var/lib/systemd/timesync/clock}

# What the console is told: "ok" and the network's name; or "error", a word
# the console has its own sentence for in each language, and this one.
finish() {      # finish ok NAME | finish error CODE "one line"
  local tmp=$RESULT.tmp
  printf '%s\n' "$@" > "$tmp" && chmod 644 "$tmp" && mv -f "$tmp" "$RESULT"
  echo "first-start: $*"
  [ "$1" = ok ] && exit 0
  exit 1
}

[ -r "$REQUEST" ] || { echo "first-start: no request"; exit 0; }
when=""; key=""
{ IFS= read -r when || true; IFS= read -r key || true; } < "$REQUEST"
rm -f "$REQUEST"

[ -e "$FLAG" ] || { unset key; finish error not_armed "This unit has been started before."; }

# ---- the clock --------------------------------------------------------------
if ! printf '%s' "$when" | grep -Eq '^20[0-9]{2}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01]) ([01][0-9]|2[0-3]):[0-5][0-9]$' \
   || ! date -d "$when" >/dev/null 2>&1; then
  unset key; finish error bad_when "That is not a date and time I can set."
fi
if [ -n "$SET_CLOCK" ]; then
  $SET_CLOCK "$when" || { unset key; finish error clock "The clock could not be set."; }
else
  date -s "$when:00" >/dev/null 2>&1 || { unset key; finish error clock "The clock could not be set."; }
  # The board's own clock, for as long as it has power; and the stamp the
  # unit resumes from at its next start (it asks no network: build log 55).
  hwclock -w >/dev/null 2>&1 || true
  [ -e "$SAVED_CLOCK" ] && touch "$SAVED_CLOCK" 2>/dev/null || true
  systemctl try-restart systemd-timesyncd >/dev/null 2>&1 || true
fi

# ---- the unit's own Wi-Fi ---------------------------------------------------
# Named after the companion. A network name is plain characters only, and a
# companion may be called Bjørn: the name is written in plain letters for the
# network, and the console says what the network is called.
name=$(curl -s --max-time 5 "$STATUS_URL" 2>/dev/null | python3 -c '
import json, sys, unicodedata
try:
    c = json.load(sys.stdin).get("companion") or {}
    n = (c.get("name") or "") if c.get("configured") else ""
except Exception:
    n = ""
for a, b in (("æ", "ae"), ("Æ", "Ae"), ("ø", "o"), ("Ø", "O"), ("å", "a"), ("Å", "A"),
             ("ß", "ss"), ("ð", "d"), ("Ð", "D"), ("þ", "th"), ("Þ", "Th")):
    n = n.replace(a, b)
n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
n = "".join(ch for ch in n if 32 <= ord(ch) < 127 and ch not in "\"\x27\\")
print(" ".join(n.split())[:32])')
[ -n "$name" ] || { unset key; finish error no_name "Name your companion first."; }

out=$(printf '%s\n' "$key" | "$HOTSPOT" on "$name" 2>&1)
rc=$?
unset key
if [ $rc -ne 0 ]; then
  case $out in
    *"not a usable passkey"*) finish error bad_passkey "The passkey must be 8 to 63 plain characters." ;;
    *) finish error wifi "The unit's Wi-Fi could not be set up: $(printf '%s' "$out" | tail -1 | cut -c1-160)" ;;
  esac
fi

rm -f "$FLAG"
finish ok "$name"
