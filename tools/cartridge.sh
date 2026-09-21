#!/usr/bin/env bash
#
# cartridge.sh — capture or verify the frozen state of an AetherSeed Companion.
#
# The Companion ships like a cartridge, not a service: one fixed artifact, no
# updates in the field. That only means something if "the shipped article" can
# be checked rather than asserted. This produces a manifest of everything that
# determines how the node behaves, and can later prove a device still matches it.
#
#   ./cartridge.sh capture  [manifest]     write the manifest
#   ./cartridge.sh verify   [manifest]     compare this device against it
#   ./cartridge.sh show     [manifest]     print the cartridge ID only
#
# Exit codes:  0 match / captured   1 DRIFT   2 could not run the check
#
# WHAT THIS DOES NOT DO: it verifies bytes, not behaviour. Identical files are
# necessary for identical behaviour, not sufficient — the NPU, the firmware and
# the model's own sampling all sit outside it. Treat a pass as "this is the
# shipped article", never as "this node is behaving correctly".

set -uo pipefail
IFS=$'\n\t'

MODE="${1:-}"
MANIFEST="${2:-cartridge.manifest}"
BLOB_DIR=/usr/share/hailo-ollama/models/blob

# Files whose contents constrain the node: what it binds to, what it may write,
# who may open the NPU. A change in any of these is a different cartridge.
IDENTITY_FILES=(
  /etc/xdg/hailo-ollama/hailo-ollama.json
  /etc/systemd/system/hailo-ollama.service
  /etc/systemd/system/aetherseed-proxy.service
  /etc/systemd/system/aetherseed-warmup.service
  /etc/systemd/system/aetherseed-gui.service
  /etc/systemd/system/aetherseed-kiosk.service
  /etc/udev/rules.d/99-aetherseed-hailo.rules
  /etc/nftables.conf
)
APP_DIR=/opt/aetherseed

die() { echo "cartridge: $*" >&2; exit 2; }

emit() { printf '%s\t%s\n' "$1" "$2"; }

installed_packages() {
  dpkg-query -W -f='${db:Status-Status} ${Package}=${Version}\n' 2>/dev/null \
    | awk '$1=="installed"{print $2}'
}

hash_file() {
  # Prints the sha256 of $1, or "MISSING". Never fails the whole run.
  if [ -r "$1" ]; then sha256sum "$1" 2>/dev/null | cut -d' ' -f1
  elif [ -e "$1" ]; then echo "UNREADABLE"
  else echo "MISSING"; fi
}

collect() {
  # Every line is key<TAB>value, sorted at the end, so the output is
  # deterministic across runs and across machines.
  emit kernel.release       "$(uname -r)"
  emit kernel.arch          "$(uname -m)"
  emit firmware.version     "$(vcgencmd version 2>/dev/null | tail -1 | tr -s ' ')"

  # Package set. The individual Hailo versions are called out because they are
  # the ones a reader cares about; the digest catches everything else drifting.
  # NB: IFS is \n\t for the whole script, so `read` is given a space IFS
  # explicitly here or it puts the entire line into $pkg.
  while IFS=' ' read -r pkg ver; do
    emit "pkg.$pkg" "$ver"
  done < <(installed_packages \
           | grep -E '^(h10-hailort|h10-hailort-pcie-driver|hailo-gen-ai-model-zoo|python3-h10-hailort|dkms)=' \
           | tr '=' ' ')

  # Only genuinely installed packages: dpkg-query -W also lists ones that are
  # removed with config files left behind.
  #
  # This count will NOT equal `dpkg -l | grep -c ^ii` on this device, and that
  # is correct. apt-mark hold sets the want-flag to hold, so a held package
  # shows as "hi", not "ii" — `grep ^ii` silently undercounts a held system by
  # exactly the number of holds (9 here). Measured 2026-09-18: 1650 installed
  # vs 1641 reported by grep ^ii. Do not "fix" this to match.
  emit packages.count  "$(installed_packages | wc -l | tr -d ' ')"
  emit packages.digest "$(installed_packages | LC_ALL=C sort | sha256sum | cut -d' ' -f1)"
  emit packages.held   "$(apt-mark showhold 2>/dev/null | LC_ALL=C sort | tr '\n' ',' | sed 's/,$//')"

  # The model. Its name is its hash, but trusting the name is the whole mistake
  # this script exists to prevent, so the content is hashed unless --quick.
  local blob
  blob="$(ls -1 "$BLOB_DIR" 2>/dev/null | head -1)"
  if [ -n "$blob" ]; then
    emit model.file  "$blob"
    emit model.bytes "$(stat -c %s "$BLOB_DIR/$blob" 2>/dev/null)"
    if [ "${QUICK:-0}" = "1" ]; then
      emit model.sha256 "SKIPPED(--quick)"
    else
      emit model.sha256 "$(hash_file "$BLOB_DIR/$blob")"
    fi
  else
    emit model.file MISSING
  fi

  local f
  for f in "${IDENTITY_FILES[@]}"; do
    emit "file.$f" "$(hash_file "$f")"
  done

  # The application itself. Every guard the frozen server lacks lives here
  # (build log steps 7 and 10), and the charter decides what the node says
  # about itself, so all of it is part of the cartridge. The venv is excluded
  # from the digest - pip writes timestamps into its metadata, which would make
  # the hash differ between two identical installs - and the versions that
  # matter are recorded explicitly instead.
  if [ -d "$APP_DIR" ]; then
    emit app.digest "$(cd "$APP_DIR" && find . -path ./venv -prune -o -type f -print \
                        | LC_ALL=C sort | xargs sha256sum 2>/dev/null | sha256sum | cut -d' ' -f1)"
    emit app.files  "$(cd "$APP_DIR" && find . -path ./venv -prune -o -type f -print | wc -l | tr -d ' ')"
    emit app.tokenizers "$("$APP_DIR/venv/bin/python3" -c 'import tokenizers;print(tokenizers.__version__)' 2>/dev/null || echo MISSING)"
    emit app.numpy      "$("$APP_DIR/venv/bin/python3" -c 'import numpy;print(numpy.__version__)' 2>/dev/null || echo MISSING)"
  else
    emit app.digest MISSING
  fi
  emit file.tokenizer_json "$(hash_file /var/lib/aetherseed/tokenizer.json)"

  emit device.node_mode  "$(stat -c '%a %U:%G' /dev/hailo0 2>/dev/null || echo MISSING)"
  emit service.hailo_ollama.enabled "$(systemctl is-enabled hailo-ollama 2>/dev/null || echo unknown)"
  emit service.proxy.enabled        "$(systemctl is-enabled aetherseed-proxy 2>/dev/null || echo unknown)"
  emit service.nftables.enabled     "$(systemctl is-enabled nftables 2>/dev/null || echo unknown)"
  emit service.warmup.enabled       "$(systemctl is-enabled aetherseed-warmup 2>/dev/null || echo unknown)"
  # The console and the screen. Added at step 18: until then the cartridge-id
  # could not see the kiosk at all, so every flag that makes the screen work -
  # the stateless profile, no keyring prompt, the scale - could have changed
  # without the id changing. getty@tty2 is the escape hatch from the kiosk; a
  # unit without it is a different and worse device.
  emit service.gui.enabled          "$(systemctl is-enabled aetherseed-gui 2>/dev/null || echo unknown)"
  emit service.kiosk.enabled        "$(systemctl is-enabled aetherseed-kiosk 2>/dev/null || echo unknown)"
  emit service.getty_tty2.enabled   "$(systemctl is-enabled getty@tty2 2>/dev/null || echo unknown)"
}

fingerprint() {  # one hash over the whole sorted body
  LC_ALL=C sort | sha256sum | cut -d' ' -f1
}

case "$MODE" in
  capture)
    body="$(collect | LC_ALL=C sort)"
    fp="$(printf '%s\n' "$body" | fingerprint)"
    {
      echo "# AetherSeed Companion — cartridge manifest"
      echo "# Captured $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname)"
      echo "# Verify with: ./cartridge.sh verify $(basename "$MANIFEST")"
      echo "#"
      echo "# cartridge-id is a hash over every line below it. Quote that one"
      echo "# value to name a build; the lines are there to say what differs."
      echo "cartridge-id	$fp"
      printf '%s\n' "$body"
    } > "$MANIFEST" || die "could not write $MANIFEST"
    echo "captured: $MANIFEST"
    echo "cartridge-id: $fp"
    ;;

  verify)
    [ -r "$MANIFEST" ] || die "no manifest at $MANIFEST"
    expected_fp="$(grep -m1 '^cartridge-id	' "$MANIFEST" | cut -f2)"
    [ -n "$expected_fp" ] || die "$MANIFEST has no cartridge-id"
    expected_body="$(grep -v '^#' "$MANIFEST" | grep -v '^cartridge-id	' | LC_ALL=C sort)"
    actual_body="$(collect | LC_ALL=C sort)"
    actual_fp="$(printf '%s\n' "$actual_body" | fingerprint)"

    if [ "$expected_fp" = "$actual_fp" ]; then
      echo "MATCH   cartridge-id $actual_fp"
      exit 0
    fi

    echo "DRIFT   expected $expected_fp"
    echo "        actual   $actual_fp"
    echo
    # Report every differing key, both sides, so the drift is legible.
    diff <(printf '%s\n' "$expected_body") <(printf '%s\n' "$actual_body") \
      | grep -E '^[<>]' \
      | sed -e 's/^< /  manifest: /' -e 's/^> /  device:   /'
    exit 1
    ;;

  show)
    [ -r "$MANIFEST" ] || die "no manifest at $MANIFEST"
    grep -m1 '^cartridge-id	' "$MANIFEST" | cut -f2
    ;;

  *)
    sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
