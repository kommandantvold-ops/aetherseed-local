#!/usr/bin/env python3
"""The offline proof: the companion works with no network at all (build log 56).

Andreas's DIANA-readiness checklist, item 1: "Full functional test with all
radios physically off ... Written, repeatable test protocol/log - something a
DIANA test centre could rerun independently, not just a one-time claim."

THE PROTOCOL (anyone can rerun it):

  1. With the unit running, on the unit:
         sudo bash /opt/aetherseed/training/run-offline-proof.sh
     It returns at once. From now on this program watches the unit.
  2. Pull the network cable. (Radios must already be off: `rfkill list`.)
     The run begins by itself when the unit is isolated: no interface has a
     link, there is no default route, and every radio is blocked.
  3. Leave it for the length of the run (10 minutes unless told otherwise)
     plus a minute. The screen and keyboard keep working throughout.
  4. Put the cable back whenever you like after that. The report is
     /var/lib/aetherseed/training/offline-<time>/report.txt.

WHAT IT DOES while the unit is isolated: runs the ecosystem soak
(training/ecosystem_soak.py) - the build's own questions, asked of a second
proxy on a COPY of the companion's memory, answered by the same model on the
same NPU, through the same guards and tools. Her own memory and trust are not
written to. Every 10 seconds it records, as evidence: each interface's link
and packet counters, the routes, the radios, every socket to anything off the
unit, and the firewall's counters.

WHAT IT CLAIMS, and only this: for the whole of the run the unit had no link
and no radio, sent no packet on any interface, and answered every question.
It does not show how long that holds, nor anything about voice (this build
has none).

Root, standard library only. It changes nothing on the unit: it does not pull
links down or block radios itself - a proof that arranges its own conditions
proves less.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = "/var/lib/aetherseed/.aetherseed"
SERVICE_USER = "aetherseed"
DROP_PREFIX = "aetherseed out-drop:"


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def sh(cmd, timeout=20):
    """Output of a command, '' if it fails - evidence gathering never stops the run."""
    try:
        return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                              text=True, timeout=timeout).stdout
    except Exception:
        return ""


def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default                 # carrier of an interface that is down: unreadable


# ---------------------------------------------------------------------------
# What the unit looks like right now
# ---------------------------------------------------------------------------

def interfaces(root="/sys/class/net"):
    out = {}
    for path in sorted(glob.glob(os.path.join(root, "*"))):
        name = os.path.basename(path)
        if name == "lo":
            continue
        out[name] = {
            "carrier": read(os.path.join(path, "carrier"), "0") == "1",
            "operstate": read(os.path.join(path, "operstate"), "unknown"),
            "tx_packets": int(read(os.path.join(path, "statistics/tx_packets"), "0") or 0),
            "rx_packets": int(read(os.path.join(path, "statistics/rx_packets"), "0") or 0),
        }
    return out


def radios(root="/sys/class/rfkill"):
    out = []
    for path in sorted(glob.glob(os.path.join(root, "rfkill*"))):
        out.append({"name": read(os.path.join(path, "name")),
                    "type": read(os.path.join(path, "type")),
                    "blocked": read(os.path.join(path, "soft"), "0") == "1"
                    or read(os.path.join(path, "hard"), "0") == "1"})
    return out


def default_routes():
    lines = sh("ip -4 route show default; ip -6 route show default").splitlines()
    return [l.strip() for l in lines if l.strip()]


def off_unit_sockets():
    """Every socket whose other end is not this unit."""
    out = []
    for line in sh("ss -tunH").splitlines():
        f = line.split()
        if len(f) < 6:
            continue
        peer = f[5]
        if peer.startswith(("127.", "[::1]", "0.0.0.0:*", "*:*", "[::]:*")):
            continue
        out.append(" ".join(f[:6]))
    return out


def drop_counters():
    """Packets the firewall has dropped, by chain (services/nftables.conf)."""
    out = {}
    for chain in ("output", "input"):
        text = sh("nft list chain inet filter %s" % chain)
        for line in text.splitlines():
            if "dropped by policy" in line and "packets" in line:
                f = line.split()
                out[chain] = int(f[f.index("packets") + 1])
    return out


def snapshot():
    return {"at": now(), "mono": round(time.monotonic(), 1), "interfaces": interfaces(),
            "radios": radios(), "default_routes": default_routes(),
            "off_unit_sockets": off_unit_sockets(), "drops": drop_counters()}


def isolated(s):
    """(is it, why not). No link anywhere, no default route, every radio blocked."""
    why = []
    for name, i in sorted(s["interfaces"].items()):
        if i["carrier"]:
            why.append("%s has a link" % name)
    if s["default_routes"]:
        why.append("a default route exists")
    for r in s["radios"]:
        if not r["blocked"]:
            why.append("radio %s (%s) is not blocked" % (r["name"], r["type"]))
    return (not why), why


# ---------------------------------------------------------------------------
# What the unit is: enough for someone else to know they test the same thing
# ---------------------------------------------------------------------------

def sha256_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return "MISSING"


def identity():
    # compiled leftovers (__pycache__) are not the application: on 4 Oct 2026
    # ten of them, from diagnostics run as root, were in the first report's hash
    app = sh("cd %s && find . -path ./venv -prune -o -name __pycache__ -prune -o -type f -print | LC_ALL=C sort "
             "| xargs sha256sum 2>/dev/null | sha256sum | cut -d' ' -f1" % APP).strip()
    blobs = sorted(glob.glob("/usr/share/hailo-ollama/models/blob/*"))
    name = ""
    try:
        with open(os.path.join(STATE, "companion.json"), encoding="utf-8") as f:
            name = json.load(f).get("name") or ""
    except Exception:
        pass
    return {"companion": name, "hostname": sh("hostname").strip(),
            "kernel": sh("uname -r").strip(),
            "app_digest": app,
            "firewall_sha256": sha256_file("/etc/nftables.conf"),
            "model_files": ["%s (%d bytes)" % (os.path.basename(b), os.path.getsize(b))
                            for b in blobs]}


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------

def soak_result(soak_dir):
    turns, failed, answered = 0, 0, 0
    try:
        with open(os.path.join(soak_dir, "ecosoak.jsonl"), encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("kind") != "probe":
                    continue
                turns += 1
                failed += 1 if e.get("failures") else 0
                answered += 1 if (e.get("score") or {}).get("answered") else 0
    except OSError:
        pass
    return {"turns": turns, "failed": failed, "answered": answered}


def verdict(samples, soak, attempts):
    """What the evidence says. `samples` are the snapshots taken while the soak
    ran, the first at its start and the last at its end."""
    broken = []
    for s in samples:
        ok, why = isolated(s)
        if not ok:
            broken.append("%s: %s" % (s["at"], "; ".join(why)))
    sent = {}
    if samples:
        first, last = samples[0]["interfaces"], samples[-1]["interfaces"]
        for name in sorted(set(first) | set(last)):
            sent[name] = (last.get(name, {}).get("tx_packets", 0)
                          - first.get(name, {}).get("tx_packets", 0))
    sockets = sorted({x for s in samples for x in s["off_unit_sockets"]})
    v = {"isolated_throughout": bool(samples) and not broken, "isolation_broken": broken,
         "packets_sent": sent, "off_unit_sockets": sockets,
         "attempts_dropped": attempts, "soak": soak}
    # Packets are the claim. A socket left over from before the cable was
    # pulled is listed, but it has sent nothing if the counters say nothing.
    v["passed"] = bool(v["isolated_throughout"] and soak["turns"] > 0 and soak["failed"] == 0
                       and not any(sent.values()))
    return v


def report_text(meta, ident, before, v, soak_report):
    L = []
    add = L.append
    add("OFFLINE PROOF - AetherSeed Companion")
    add("=" * 36)
    add("")
    add("RESULT: %s" % ("PASSED" if v["passed"] else "NOT PASSED"))
    add("")
    add("The unit")
    add("  companion      %s (host %s)" % (ident["companion"] or "-", ident["hostname"]))
    add("  kernel         %s" % ident["kernel"])
    add("  application    sha256 %s" % ident["app_digest"])
    add("  firewall       sha256 %s" % ident["firewall_sha256"])
    for m in ident["model_files"]:
        add("  model          %s" % m)
    add("")
    add("The run (times are the unit's own clock, which nothing corrects)")
    add("  started        %s" % meta["started"])
    add("  isolated from  %s" % (meta.get("isolated_at") or "never"))
    add("  questions      %s to %s" % (meta.get("soak_start") or "-", meta.get("soak_end") or "-"))
    add("  link back      %s" % (meta.get("link_back") or "not while this was written"))
    add("")
    add("Before the cable was pulled")
    for name, i in sorted(before["interfaces"].items()):
        add("  %-14s link %s, %s" % (name, "yes" if i["carrier"] else "no", i["operstate"]))
    for r in before["radios"]:
        add("  radio %-8s %s: %s" % (r["name"], r["type"], "blocked" if r["blocked"] else "NOT blocked"))
    add("  default route  %s" % ("; ".join(before["default_routes"]) or "none"))
    add("")
    add("While the questions were asked (%d samples, one every 10 s)" % meta.get("samples", 0))
    add("  no link, no default route, every radio blocked, at every sample: %s"
        % ("yes" if v["isolated_throughout"] else "NO"))
    for b in v["isolation_broken"][:10]:
        add("    broken  %s" % b)
    for name, n in sorted(v["packets_sent"].items()):
        add("  packets sent on %-6s %d" % (name, n))
    add("  sockets to anything off the unit: %s"
        % ("none" if not v["off_unit_sockets"] else "(listed; the packet counters are the claim)"))
    for s in v["off_unit_sockets"]:
        add("    %s" % s)
    add("  attempts to send, stopped by the firewall: %d (out-drop.txt names each)"
        % v["attempts_dropped"])
    add("")
    add("What she did meanwhile")
    add("  questions asked %d, failed %d, answered by the expected words %d"
        % (v["soak"]["turns"], v["soak"]["failed"], v["soak"]["answered"]))
    add("")
    add("PASSED means: isolated at every sample, at least one question, none failed,")
    add("and no packet sent on any interface.")
    add("It says nothing about voice (this build has none) or about longer than the run.")
    add("")
    add("To rerun: sudo bash /opt/aetherseed/training/run-offline-proof.sh ; pull the")
    add("cable; wait; put it back. Evidence beside this file: samples.jsonl (every")
    add("sample), out-drop.txt (the kernel's log of what the firewall stopped),")
    add("soak/ecosoak.jsonl (every question and answer), SHA256SUMS.")
    add("")
    add("-" * 72)
    add(soak_report.rstrip())
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--minutes", type=float, default=10.0, help="how long she is questioned")
    ap.add_argument("--wait", type=float, default=20.0,
                    help="minutes to wait for the unit to be isolated before giving up")
    a = ap.parse_args(argv)

    os.makedirs(a.dir, exist_ok=True)
    soak_dir = os.path.join(a.dir, "soak")
    os.makedirs(soak_dir, exist_ok=True)
    shutil.chown(soak_dir, SERVICE_USER, SERVICE_USER)
    samples_path = os.path.join(a.dir, "samples.jsonl")

    def record(s, phase):
        s["phase"] = phase
        with open(samples_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(s) + "\n")
        return s

    meta = {"started": now()}
    ident = identity()
    before = record(snapshot(), "before")
    print("[offline] watching; pull the cable. %s" % "; ".join(isolated(before)[1]), flush=True)

    deadline = time.monotonic() + a.wait * 60
    while time.monotonic() < deadline:
        s = snapshot()
        if isolated(s)[0]:
            time.sleep(5)                      # and still, five seconds on
            s = snapshot()
            if isolated(s)[0]:
                meta["isolated_at"] = s["at"]
                break
        time.sleep(2)

    during = []
    if meta.get("isolated_at"):
        print("[offline] isolated at %s; asking for %s minutes" % (meta["isolated_at"], a.minutes),
              flush=True)
        since = time.strftime("%Y-%m-%d %H:%M:%S")
        meta["soak_start"] = now()
        during.append(record(snapshot(), "during"))
        soak = subprocess.Popen(
            ["runuser", "-u", SERVICE_USER, "--", os.path.join(APP, "venv/bin/python3"),
             os.path.join(APP, "training/ecosystem_soak.py"), "--dir", soak_dir,
             "--copy-from", STATE, "--hours", str(a.minutes / 60.0)],
            cwd="/var/lib/aetherseed", stdout=open(os.path.join(a.dir, "soak.log"), "w"),
            stderr=subprocess.STDOUT)
        while soak.poll() is None:
            time.sleep(10)
            during.append(record(snapshot(), "during"))
        during.append(record(snapshot(), "during"))
        meta["soak_end"] = now()
        drops = [l for l in sh(["journalctl", "-k", "--since", since, "--no-pager",
                                "-o", "short-iso"]).splitlines() if DROP_PREFIX in l]
    else:
        print("[offline] the unit was never isolated; nothing was asked", flush=True)
        drops = []
    with open(os.path.join(a.dir, "out-drop.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(drops) + ("\n" if drops else ""))
    meta["samples"] = len(during)

    def write_report():
        v = verdict(during, soak_result(soak_dir), len(drops))
        text = report_text(meta, ident, before, v, read(os.path.join(soak_dir, "report.txt")))
        with open(os.path.join(a.dir, "report.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        with open(os.path.join(a.dir, "verdict.json"), "w", encoding="utf-8") as f:
            json.dump({"meta": meta, "identity": ident, "verdict": v}, f, indent=1)
        sums = []
        for name in ("report.txt", "verdict.json", "samples.jsonl", "out-drop.txt",
                     "soak/ecosoak.jsonl", "soak/report.txt"):
            sums.append("%s  %s" % (sha256_file(os.path.join(a.dir, name)), name))
        with open(os.path.join(a.dir, "SHA256SUMS"), "w", encoding="utf-8") as f:
            f.write("\n".join(sums) + "\n")
        return v

    v = write_report()
    print("[offline] %s; report written" % ("PASSED" if v["passed"] else "NOT PASSED"), flush=True)

    # Note when the link comes back, so the report says from when to when.
    end = time.monotonic() + 3600
    while meta.get("isolated_at") and time.monotonic() < end:
        s = snapshot()
        if any(i["carrier"] for i in s["interfaces"].values()):
            record(s, "after")
            meta["link_back"] = s["at"]
            write_report()
            print("[offline] link back at %s" % s["at"], flush=True)
            break
        time.sleep(10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
