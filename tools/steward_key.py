#!/usr/bin/env python3
"""The passkey the steward signs in with from a phone.

steward sign-in from a phone is "steward name +
passkey", and the passkey is "The Wi-Fi passkey". What is kept is a hash of it
(gui/signin.py), in /etc/aetherseed/steward.key, owned by root and readable by
the unit's own services. Never the passkey itself.

    sudo tools/steward_key.py own            a passkey of the steward's own, asked for
                                             without echo (or one line on standard
                                             input). Not the Wi-Fi passkey: that is
                                             refused. This is the passkey to use.
    sudo tools/steward_key.py wifi           the unit's Wi-Fi passkey, read from its
                                             network profile (tools/hotspot.sh).
                                             Kept for a unit that wants it, and says
                                             what it means; nothing sets it by itself.
    ... | sudo tools/steward_key.py wifi --stdin
                                             the same, the passkey on standard input
         tools/steward_key.py status         set or not, which kind, since when
    sudo tools/steward_key.py off            no steward sign-in from a phone: every
                                             phone is a guest

`wifi` never replaces a passkey of the steward's own unless --replace is given:
a new Wi-Fi passkey (hotspot.sh on) does not undo a choice the steward made.
`own` replaces whatever is there.

Why a passkey of his own is the way: the Wi-Fi passkey is held by everyone who
was given the Wi-Fi, and the steward's name is no secret, so with it a guest
who wants to can sign in as the steward. With one of his own, only he can.
the steward first chose the Wi-Fi passkey he decided
that a unit's first start requires one of his own, separate from the Wi-Fi. hotspot.sh no longer sets this key from the Wi-Fi.
"""
import argparse
import getpass
import grp
import json
import os
import subprocess
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "gui"))
import signin  # noqa: E402

KEY_FILE = os.environ.get("AETHERSEED_STEWARD_KEY", "/etc/aetherseed/steward.key")
GROUP = os.environ.get("AETHERSEED_STEWARD_KEY_GROUP", "aetherseed")
PROFILE = os.environ.get("AETHERSEED_HOTSPOT_PROFILE", "aetherseed-hotspot")
NMCLI = os.environ.get("AETHERSEED_NMCLI", "nmcli")


def die(msg, code=2):
    print("steward-key: " + msg, file=sys.stderr)
    sys.exit(code)


def need_root():
    if os.geteuid() != 0 and "AETHERSEED_STEWARD_KEY" not in os.environ:
        die("run with sudo")


def write_record(rec):
    """Atomically: a new file beside the old one, its mode and owner set
    before a byte of it is written, then moved over."""
    d = os.path.dirname(KEY_FILE) or "."
    os.makedirs(d, mode=0o755, exist_ok=True)
    try:
        gid = grp.getgrnam(GROUP).gr_gid
    except KeyError:
        die("there is no group %r on this unit - the console could not read the key" % GROUP)
    tmp = KEY_FILE + ".new"
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        os.fchmod(fd, 0o640)
        if os.geteuid() == 0:
            os.fchown(fd, 0, gid)
        os.write(fd, (json.dumps(rec, indent=1) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, KEY_FILE)


def read_line_from_stdin():
    line = sys.stdin.readline()
    return line[:-1] if line.endswith("\n") else line


def wifi_passkey():
    """The unit's Wi-Fi passkey, as NetworkManager holds it (root only)."""
    try:
        out = subprocess.run([NMCLI, "-s", "-g", "802-11-wireless-security.psk",
                              "connection", "show", PROFILE],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        die("could not ask NetworkManager: %r" % (e,))
    if out.returncode != 0:
        die("this unit has no Wi-Fi of its own set up (%s) - nothing to read" % PROFILE)
    key = out.stdout[:-1] if out.stdout.endswith("\n") else out.stdout
    # nmcli's terse output may escape ':' and '\' with a backslash. Rather
    # than guess which version did what, a passkey that prints with a
    # backslash is not read this way at all.
    if "\\" in key:
        die("the Wi-Fi passkey has a ':' or '\\' in it, which nmcli escapes; give it on "
            "standard input instead: sudo tools/steward_key.py wifi --stdin")
    return key


def wifi_passkey_or_none():
    """The Wi-Fi passkey if this unit has one of its own and it can be read,
    else None - a unit without a hotspot has nothing for a steward's passkey
    to be confused with."""
    try:
        out = subprocess.run([NMCLI, "-s", "-g", "802-11-wireless-security.psk",
                              "connection", "show", PROFILE],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    key = out.stdout[:-1] if out.stdout.endswith("\n") else out.stdout
    return key or None


def cmd_wifi(a):
    need_root()
    print("steward-key: WARNING - anyone given the Wi-Fi holds this passkey, and the "
          "steward's name is no secret: they can sign in as the steward. "
          "sudo tools/steward_key.py own is the safe choice.", file=sys.stderr)
    old = signin.load_record(KEY_FILE)
    if old and old["source"] == "own" and not a.replace:
        print("steward-key: the steward has a passkey of his own; it is kept "
              "(give --replace to use the Wi-Fi passkey instead)")
        return 0
    key = read_line_from_stdin() if a.stdin else wifi_passkey()
    if not signin.passkey_shape_ok(key):
        die("not a usable passkey (8-63 plain characters)")
    write_record(signin.make_record(key, "wifi"))
    del key
    print("steward-key: set from the unit's Wi-Fi passkey - a phone signs in as the "
          "steward with the steward's name and that passkey")
    return 0


def cmd_own(a):
    need_root()
    if sys.stdin.isatty():
        key = getpass.getpass("A passkey of the steward's own (8-63 plain characters): ")
        again = getpass.getpass("Once more: ")
        if key != again:
            die("the two did not match; nothing was changed")
    else:
        key = read_line_from_stdin()
    if not signin.passkey_shape_ok(key):
        die("not a usable passkey (8-63 plain characters)")
    if key == wifi_passkey_or_none():
        die("that is the Wi-Fi passkey, which everyone given the Wi-Fi holds - "
            "choose a passkey of your own; nothing was changed")
    write_record(signin.make_record(key, "own"))
    del key
    print("steward-key: set to a passkey of the steward's own - the Wi-Fi passkey no "
          "longer signs anyone in as the steward")
    return 0


def cmd_status(a):
    if not os.path.exists(KEY_FILE):
        print("steward-key: not set - every phone is a guest; the unit's own screen is the steward")
        return 0
    rec = signin.load_record(KEY_FILE)
    if rec is None:
        print("steward-key: %s is there but cannot be read as a key - no phone can sign in" % KEY_FILE)
        return 1
    kind = "the unit's Wi-Fi passkey" if rec["source"] == "wifi" else "a passkey of the steward's own"
    print("steward-key: set to %s, since %s" % (kind, rec.get("set_at", "?")))
    if rec["source"] == "wifi":
        print("steward-key: anyone given the Wi-Fi can sign in as the steward with it - "
              "run: sudo tools/steward_key.py own")
    return 0


def cmd_off(a):
    need_root()
    try:
        os.unlink(KEY_FILE)
        print("steward-key: removed - every phone is a guest now")
    except FileNotFoundError:
        print("steward-key: was not set")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wifi")
    w.add_argument("--stdin", action="store_true")
    w.add_argument("--replace", action="store_true")
    sub.add_parser("own")
    sub.add_parser("status")
    sub.add_parser("off")
    a = ap.parse_args(argv)
    return {"wifi": cmd_wifi, "own": cmd_own, "status": cmd_status, "off": cmd_off}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
