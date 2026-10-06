#!/usr/bin/env python3
"""A document of the steward's, tried on a copy: read in, looked up, explained.

    sudo -u aetherseed /opt/aetherseed/venv/bin/python3 /opt/aetherseed/training/shelf_check.py \\
        --dir /var/lib/aetherseed/training/shelf-<time> --document book.pdf --asks asks.json

Her memory is copied (training/ecosystem_soak.py does the same) and a second
proxy runs on the copy, with a shelf of its own: the document is put on THAT
shelf, and every "explain that" - which is stored, as unverified - is stored
in the copy. Nothing of hers is written. The built-in library is the unit's
own, read-only, so what is shown is what she would show.

--asks is a list of {"look": "momentum", "ask": "why is it conserved?"}: for
each, "look up <look> in my book". With --explain, "explain that" follows
(with ": <ask>" when one is given): explaining is OFF in the build (Andreas,
5 Oct 2026: "leave it off"), and --explain turns it on for the copy's proxy
only, so that a later model can be measured the same way. --plain is a list of plain questions, asked as they are, to
see which of them the document now answers unasked. Every turn goes to
turns.jsonl and, to be read by a person, to report.txt: the passage as it
was shown, and under it her words about it. Build log 62.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ecosystem_soak as eco  # noqa: E402


def upload(base, path, name=None):
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(
        base + "/aetherseed/upload", data=data, method="POST",
        headers={"Content-Type": "application/octet-stream",
                 "X-Filename": urllib.parse.quote(name or os.path.basename(path))})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def wait_until_read(base, doc_id, seconds=900):
    t0 = time.time()
    while time.time() - t0 < seconds:
        for d in eco.get(base, "/aetherseed/shelf")["documents"]:
            if d["id"] == doc_id and d["state"] != "reading":
                return d, round(time.time() - t0, 1)
        time.sleep(1)
    raise SystemExit("the document was not read in %d s" % seconds)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="where the copy, the turns and the report go")
    ap.add_argument("--copy-from", default="/var/lib/aetherseed/.aetherseed",
                    help="her state directory (.aetherseed), read and never written")
    ap.add_argument("--document", required=True)
    ap.add_argument("--name", help="the file name to give it (default: its own)")
    ap.add_argument("--asks", help='JSON: [{"look": ..., "ask": ...}, ...]')
    ap.add_argument("--plain", help="JSON: [question, ...], asked as they are")
    ap.add_argument("--explain", action="store_true",
                    help='turn "explain that" on for the copy, and ask it after each passage')
    ap.add_argument("--port", type=int, default=8013)
    a = ap.parse_args(argv)

    asks = json.load(open(a.asks, encoding="utf-8")) if a.asks else []
    plain = json.load(open(a.plain, encoding="utf-8")) if a.plain else []
    os.makedirs(a.dir, exist_ok=True)
    home = os.path.join(a.dir, "home")
    episodes = eco.copy_home(a.copy_from, home)
    if a.explain:
        os.environ["AETHERSEED_EXPLAIN"] = "1"      # the copy's proxy only: it inherits this
    else:
        os.environ.pop("AETHERSEED_EXPLAIN", None)
    proc, base = eco.start_proxy(home, a.port, os.path.join(a.dir, "proxy.log"))
    turns, lines = os.path.join(a.dir, "turns.jsonl"), []

    def write(e):
        e.setdefault("at", eco.now())
        with open(turns, "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def say(text=""):
        lines.append(text)
        print(text, flush=True)

    try:
        before = eco.get(base, "/aetherseed/status")
        say("copy of %d episodes; build %s; explaining %s" % (
            episodes, eco.build_id(),
            "ON for this copy" if eco.get(base, "/aetherseed/shelf").get("explains") else "off"))
        status, d = upload(base, a.document, a.name)
        if status != 202:
            say("REFUSED (%s): %s" % (status, d.get("error")))
            write({"kind": "upload", "status": status, "answer": d})
            return 1
        doc, secs = wait_until_read(base, d["document"]["id"])
        write({"kind": "upload", "status": status, "document": doc, "read_secs": secs})
        say('"%s": %s in %.0f s - %s pages, %s passages%s'
            % (doc["title"], doc["state"], secs, doc.get("pages"), doc.get("passages"),
               " (%s)" % doc["note"] if doc.get("note") else ""))
        if doc["state"] != "ready":
            return 1
        r = eco.chat(base, "What is in the library?")
        say("\n" + r["reply"])
        for n, item in enumerate(asks, 1):
            look = "look up %s in my book" % item["look"]
            shown = eco.chat(base, look)
            write({"kind": "look", "n": n, "sent": look, "reply": shown["reply"],
                   "meta": shown["meta"], "secs": shown["secs"], "status": shown["status"]})
            say("\n" + "=" * 78 + "\n[%d] YOU: %s   (%s, %.1f s)\n" % (
                n, look, shown["meta"].get("mode"), shown["secs"]))
            say(shown["reply"])
            if not a.explain or shown["meta"].get("mode") != "library" \
                    or "Source:" not in shown["reply"]:
                continue
            explain = "explain that" + (": " + item["ask"] if item.get("ask") else "")
            told = eco.chat(base, explain)
            write({"kind": "explain", "n": n, "sent": explain, "reply": told["reply"],
                   "meta": told["meta"], "secs": told["secs"], "status": told["status"],
                   "failures": eco.failure(told)})
            say("\n[%d] YOU: %s   (%.1f s; explains=%s; flagged sources=%s)\n"
                % (n, explain, told["secs"], bool(told["meta"].get("explains")),
                   told["meta"].get("unbacked_sources")))
            say("HER WORDS: " + (told["reply"] or "(nothing)"))
        if plain:
            say("\n" + "=" * 78 + "\nPLAIN QUESTIONS - shown unasked, or hers?\n")
        for q in plain:
            r = eco.chat(base, q)
            mode = r["meta"].get("mode")
            write({"kind": "plain", "sent": q, "reply": r["reply"], "meta": r["meta"],
                   "secs": r["secs"], "status": r["status"]})
            first = r["reply"].replace("\n", " ")[:150]
            say("%-8s %-44s %s" % ("SHOWN" if mode == "library" else "hers", q, first))
        after = eco.get(base, "/aetherseed/status")
        write({"kind": "status", "before": before, "after": after})
        say("\nthe copy: %s -> %s episodes; remembered %s -> %s; tagged %s -> %s"
            % (before.get("episodes"), after.get("episodes"), before.get("remembered"),
               after.get("remembered"), before.get("tagged"), after.get("tagged")))
    finally:
        proc.terminate()
        try:
            proc.wait(20)
        except Exception:
            proc.kill()
        with open(os.path.join(a.dir, "report.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
