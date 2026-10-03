#!/bin/bash
# The unit's own Wi-Fi (build log 54).
#
# Andreas, 4 Oct 2026: "if no LAN was connected, the wifi would emmit ssid
# Stella and with the correct passkey I could access the gui through the device
# I connected to the companions wifi" - "it is to use as the companion screen,
# not support, the device should remain private."
#
# A phone or laptop that joins the network named after the companion, with the
# steward's passkey, opens the console at http://10.42.0.1:2077 - the same
# page as on the unit's own screen. Tested on Stella, 4 Oct, with Andreas's
# iPhone: it joined, opened the console, and one turn was stored ("its great").
#
#   sudo tools/hotspot.sh on [NAME]    set it up; NAME defaults to the
#                                      companion's name. The passkey is read
#                                      from standard input (one line), or
#                                      asked for without echo at a terminal.
#   sudo tools/hotspot.sh off          take it down and remove it
#        tools/hotspot.sh status       is it set up, is it up, who is on it
#        tools/hotspot.sh --check NAME validate NAME and a passkey on standard
#                                      input; changes nothing (the tests)
#
# What it is: one NetworkManager profile, `aetherseed-hotspot`, that comes up
# at every start - cable or no cable. NetworkManager runs the access point
# (wpa_supplicant) and hands out addresses (its own dnsmasq, 10.42.0.10-254).
# The firewall (services/nftables.conf) admits the address request and the
# console port from wlan0 and nothing else; it does not pass a phone's traffic
# on to the cable network, and there is no name service on the unit's Wi-Fi,
# so a phone will say "no internet". That is the design.
#
# The passkey is kept in the profile only (root, mode 600), never in the
# build, a log or the cartridge. Whoever holds it is at the console: it is the
# steward's, like the screen.
set -u
export PATH=$PATH:/usr/sbin:/sbin

PROFILE=aetherseed-hotspot
ADDRESS=10.42.0.1/24
CHANNEL=6
STATUS_URL=${AETHERSEED_STATUS_URL:-http://127.0.0.1:8001/aetherseed/status}

die() { echo "hotspot: $*" >&2; exit 2; }

# A network name: 1-32 bytes, printable, no quote or backslash to trip a shell.
check_name() {
  local n=$1 bytes
  bytes=$(printf '%s' "$n" | wc -c)
  [ "$bytes" -ge 1 ] && [ "$bytes" -le 32 ] || return 1
  printf '%s' "$n" | LC_ALL=C grep -q '[^ -~]' && return 1
  case $n in *\"*|*\'*|*\\*) return 1 ;; esac
  case $n in " "*|*" ") return 1 ;; esac
  return 0
}

# A WPA2 passkey: 8-63 printable ASCII characters.
check_passkey() {
  local k=$1 len=${#1}
  [ "$len" -ge 8 ] && [ "$len" -le 63 ] || return 1
  printf '%s' "$k" | LC_ALL=C grep -q '[^ -~]' && return 1
  return 0
}

read_passkey() {
  local k=""
  if [ -t 0 ]; then
    read -r -s -p "Passkey for the unit's Wi-Fi (8-63 characters): " k; echo >&2
  else
    IFS= read -r k || true
  fi
  printf '%s' "$k"
}

companion_name() {
  curl -s --max-time 5 "$STATUS_URL" 2>/dev/null | python3 -c '
import json, sys
try:
    c = json.load(sys.stdin).get("companion") or {}
    print(c.get("name") or "" if c.get("configured") else "")
except Exception:
    print("")'
}

case ${1:-} in
  --check)
    check_name "${2:-}" || die "not a usable network name (1-32 plain characters)"
    check_passkey "$(read_passkey)" || die "not a usable passkey (8-63 plain characters)"
    echo ok
    ;;

  on)
    [ "$(id -u)" = 0 ] || die "run with sudo"
    name=${2:-$(companion_name)}
    [ -n "$name" ] || die "the companion has no name yet - name it on the unit's screen first, or give one"
    check_name "$name" || die "not a usable network name (1-32 plain characters): $name"
    key=$(read_passkey)
    check_passkey "$key" || die "not a usable passkey (8-63 plain characters)"
    # Another saved Wi-Fi network would be joined instead of this one being
    # put up (found on Lyra, 4 Oct: a home network from her first setup).
    others=$(nmcli -t -f NAME,TYPE connection show | grep ':802-11-wireless$' | grep -v "^$PROFILE:" | cut -d: -f1)
    [ -z "$others" ] || die "another Wi-Fi network is saved on this unit ($others); remove it first: nmcli connection delete NAME"
    systemctl enable --now wpa_supplicant >/dev/null 2>&1 || die "wpa_supplicant would not start"
    nmcli radio wifi on || die "the radio would not switch on"
    nmcli connection delete "$PROFILE" >/dev/null 2>&1
    nmcli connection add type wifi ifname wlan0 con-name "$PROFILE" ssid "$name" \
      connection.autoconnect yes connection.autoconnect-priority 100 \
      802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel "$CHANNEL" \
      wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp \
      wifi-sec.psk "$key" \
      ipv4.method shared ipv4.addresses "$ADDRESS" ipv6.method disabled >/dev/null \
      || die "the profile could not be written"
    unset key
    for _ in 1 2 3 4 5 6; do
      nmcli connection up "$PROFILE" >/dev/null 2>&1 && break
      sleep 2
    done
    "$0" status
    ;;

  off)
    [ "$(id -u)" = 0 ] || die "run with sudo"
    nmcli connection down "$PROFILE" >/dev/null 2>&1
    nmcli connection delete "$PROFILE" >/dev/null 2>&1
    nmcli radio wifi off
    systemctl disable --now wpa_supplicant >/dev/null 2>&1
    sysctl -q -w net.ipv4.ip_forward=0
    "$0" status
    ;;

  status)
    if ! nmcli -t -f NAME connection show | grep -qx "$PROFILE"; then
      echo "hotspot: not set up"; exit 0
    fi
    ssid=$(nmcli -g 802-11-wireless.ssid connection show "$PROFILE")
    if nmcli -t -f NAME connection show --active | grep -qx "$PROFILE"; then
      addr=$(ip -4 -o addr show wlan0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
      n=$(iw dev wlan0 station dump 2>/dev/null | grep -c '^Station')
      echo "hotspot: up - network \"$ssid\", console at http://$addr:2077, $n device(s) joined"
    else
      echo "hotspot: set up as \"$ssid\" but not up"
    fi
    ;;

  *)
    sed -n '2,/^set -u/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
