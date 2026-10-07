#!/bin/bash
# A card that other cards are copied from (build log 66).
#
# Andreas, 7 Oct 2026: "install a fresh build on the pi on the 4th pi ... and
# that sd card will be copied for new pilot units." - units whose user "will
# pick name passkey and start it for the first time".
#
# A copy of a card is that card: its name, its memory, its Wi-Fi passkey, its
# SSH identity. So a source is a unit that was installed and NEVER STARTED -
# no companion named, no turn stored, no Wi-Fi of its own - and that hands
# each copy an identity of its own at the copy's first boot. This tool says
# whether a unit is that (`check`), and makes a freshly installed one so
# (`seal`).
#
#        tools/source_card.sh check   what a copy of this card would carry.
#                                     Changes nothing. (sudo, to see it all)
#   sudo tools/source_card.sh seal    make this card a source, and power off.
#
# `seal` REFUSES a unit that has been started: one with a named companion, a
# stored turn, a Wi-Fi of its own, or a steward's document. It is not a
# factory reset and must never be one by accident - Lyra's memory is Lyra.
# On a unit that passes, it:
#   - stops the companion, and removes what running it left behind: the empty
#     memory store, the logs of the model server and the keepalive, the
#     screen's browser profile;
#   - ARMS THE FIRST START: /etc/aetherseed/first-start. With it, the unit's
#     own screen asks - after the name - for the date and time and a passkey
#     for the unit's Wi-Fi (tools/first_start.sh), once;
#   - arranges a new identity for each copy: /etc/aetherseed/new-identity,
#     which services/aetherseed-new-identity.service acts on at the next boot
#     (new SSH host keys, a new machine id) and removes. The source's own are
#     deleted here, so no two cards ever share them;
#   - forgets the network it was built on (the address lease, the unit's
#     network secret), the journal, the installer's files in the admin
#     account's home, and that account's shell history;
#   - powers off. THE NEXT BOOT OF THIS CARD, OR OF ANY COPY, IS A FIRST
#     START: do not boot the source again before copying it, or seal it again
#     afterwards (a first boot only makes a new identity; a first START, at
#     the screen, is what cannot be undone here).
#
# What it leaves: the admin account, its password and its SSH keys - the
# pilot arrangement (INSTALL 14, build log 63) - and everything the cartridge
# describes.
set -u
export PATH=$PATH:/usr/sbin:/sbin

STATE=${AETHERSEED_STATE:-/var/lib/aetherseed}
ETC=${AETHERSEED_ETC:-/etc/aetherseed}
FLAG=$ETC/first-start
IDENTITY=$ETC/new-identity
HOTSPOT=${AETHERSEED_HOTSPOT:-/opt/aetherseed/tools/hotspot.sh}
DRY=${AETHERSEED_DRY:-0}           # the tests: say what would be done

die() { echo "source-card: $*" >&2; exit 2; }
say() { echo "source-card: $*"; }
run() { if [ "$DRY" = 1 ]; then echo "  would: $*"; else "$@"; fi; }

# ---- what this card holds ------------------------------------------------------
named() {       # the companion's name, or nothing
  python3 - "$STATE/.aetherseed/companion.json" <<'PY' 2>/dev/null
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("name") or "")
except Exception:
    print("")
PY
}

turns() {       # stored turns, 0 if there is no store
  python3 - "$STATE/.aetherseed/aetherroot/memory.db" <<'PY' 2>/dev/null
import os, sqlite3, sys
p = sys.argv[1]
if not os.path.exists(p):
    print(0); raise SystemExit
try:
    c = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
    print(c.execute("select count(*) from episodes").fetchone()[0])
except Exception:
    print("?")
PY
}

wifi_set_up() { nmcli -t -f NAME,TYPE connection show 2>/dev/null | grep -c ':802-11-wireless$'; }

documents() {
  local d=$STATE/aetherseed-shelf
  [ -d "$d" ] && find "$d" -type f 2>/dev/null | wc -l || echo 0
}

started() {     # the reasons this unit is not a source; nothing if it is one
  local n t w d
  n=$(named); t=$(turns); w=$(wifi_set_up); d=$(documents)
  [ -z "$n" ] || echo "its companion is named ($n)"
  [ "$t" = 0 ] || echo "its memory holds $t turn(s)"
  [ "$w" = 0 ] || echo "$w Wi-Fi network(s) are saved on it"
  [ "$d" = 0 ] || echo "$d document(s) of a steward are on it"
  [ ! -s "$STATE/.aetherseed/trust_state.json" ] || echo "it has a trust record"
}

case ${1:-} in
  check)
    why=$(started)
    if [ -z "$why" ]; then say "never started: no name, no turn, no Wi-Fi, no document"
    else say "STARTED - a copy of this card would be this unit:"; printf '%s\n' "$why" | sed 's/^/  - /'
    fi
    [ -e "$FLAG" ] && say "armed for its first start ($FLAG)" || say "not armed for a first start"
    [ -e "$IDENTITY" ] && say "the next boot makes a new identity ($IDENTITY)" \
      || say "identity: machine id $(cut -c1-8 /etc/machine-id 2>/dev/null)..., $(ls /etc/ssh/ssh_host_*_key.pub 2>/dev/null | wc -l) SSH host key(s) - a copy would share them"
    for u in aetherseed-first-start.path aetherseed-new-identity.service; do
      say "$u: $(systemctl is-enabled "$u" 2>/dev/null || echo not installed)"
    done
    for h in /home/*; do
      [ -d "$h" ] || continue
      k=$(grep -c . "$h/.ssh/authorized_keys" 2>/dev/null || true)
      [ -z "$k" ] || [ "$k" = 0 ] || say "$(basename "$h"): $k SSH key(s) may log in"
    done
    if [ "$(id -u)" = 0 ]; then
      say "SSH by password: $(sshd -T 2>/dev/null | awk '$1=="passwordauthentication"{print $2}')"
    fi
    say "the unit's clock: $(date '+%Y-%m-%d %H:%M')"
    [ -z "$why" ] && [ -e "$FLAG" ] && [ -e "$IDENTITY" ] && say "THIS CARD IS A SOURCE" || true
    ;;

  seal)
    [ "$(id -u)" = 0 ] || die "run with sudo"
    why=$(started)
    [ -z "$why" ] || die "this unit has been started, and is not made a source:
$(printf '%s\n' "$why" | sed 's/^/  - /')"
    for u in aetherseed-first-start.path aetherseed-first-start.service aetherseed-new-identity.service; do
      [ "$DRY" = 1 ] || systemctl cat "$u" >/dev/null 2>&1 || die "$u is not installed (services/, INSTALL 18)"
    done
    [ -x /opt/aetherseed/tools/first_start.sh ] || [ "$DRY" = 1 ] || die "tools/first_start.sh is not installed"

    say "stopping the companion"
    run systemctl stop aetherseed-kiosk-watch aetherseed-kiosk aetherseed-keepalive \
        aetherseed-gui aetherseed-warmup aetherseed-proxy hailo-ollama

    say "removing what running it left behind"
    run rm -rf "$STATE/.aetherseed" "$STATE/.hailo" "$STATE/hailort.log" \
        "$STATE/aetherseed-workspace" "$STATE/aetherseed-shelf" "$STATE/training"
    run find /var/lib/aetherseed-keepalive -mindepth 1 -delete
    for h in /home/aetherseed-kiosk; do
      [ -d "$h" ] && run find "$h" -mindepth 1 -maxdepth 1 \( -name .config -o -name .cache -o -name .local \) -exec rm -rf {} +
    done

    say "arming the first start, and a new identity for each copy"
    run install -d -o root -g root -m 755 "$ETC"
    run touch "$FLAG" "$IDENTITY"
    run systemctl enable aetherseed-first-start.path aetherseed-new-identity.service
    run rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub
    run rm -f /var/lib/systemd/random-seed
    run find /var/lib/NetworkManager -maxdepth 1 -type f \( -name '*.lease' -o -name secret_key \
        -o -name seen-bssids -o -name timestamps \) -delete

    say "forgetting the installer"
    for h in /home/*; do
      [ -d "$h" ] || continue
      case $(basename "$h") in aetherseed-kiosk) continue ;; esac
      run find "$h" -mindepth 1 -maxdepth 1 \( -name 'aetherseed-*' -o -name 'ptest*' -o -name 'step*' \
          -o -name 'cart*.manifest' -o -name 'app-files-*.txt' -o -name 'hailort.log' \
          -o -name .bash_history -o -name .xsession-errors -o -name .lesshst -o -name .python_history \
          -o -name .sudo_as_admin_successful \) -exec rm -rf {} +
    done
    run rm -f /root/.bash_history
    run find /tmp /var/tmp -mindepth 1 -maxdepth 1 -not -name 'systemd-private-*' -exec rm -rf {} +
    run journalctl --rotate
    run journalctl --vacuum-time=1s
    run find /var/log -type f \( -name '*.gz' -o -name '*.1' -o -name '*.old' \) -delete

    say "sealed. Powering off - copy this card before it is booted again."
    run sync
    run systemctl --no-block poweroff
    ;;

  *)
    sed -n '2,/^set -u/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
