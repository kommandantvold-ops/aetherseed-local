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
  /etc/udev/rules.d/99-aetherseed-hailo.rules
)

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

  # The charter decides what the node says about itself, so it is part of the
  # cartridge even though it lives in the application, not the OS.
  local pb
  pb="$(dirname "$0")/../logic/prompt_builder.py"
  [ -r "$pb" ] || pb=/opt/aetherseed/logic/prompt_builder.py
  emit file.prompt_builder "$(hash_file "$pb")"

  emit device.node_mode  "$(stat -c '%a %U:%G' /dev/hailo0 2>/dev/null || echo MISSING)"
  emit service.enabled   "$(systemctl is-enabled hailo-ollama 2>/dev/null || echo unknown)"
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
