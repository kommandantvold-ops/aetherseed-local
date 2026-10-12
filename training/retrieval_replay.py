#!/usr/bin/env python3
"""Which memories would she be shown? Replayed on a COPY of her memory, model
not called (build log 70).

    sudo -u aetherseed /opt/aetherseed/venv/bin/python3 -B \\
        /opt/aetherseed/training/retrieval_replay.py --copy-from /var/lib/aetherseed/.aetherseed

Andreas, 10 Oct 2026, on memories crowding a file question: *"might need a
better resonance tag, or a different approach?"* Retrieval ranks a turn by
0.5 x similarity + 0.35 x resonance + 0.15 x recency, where resonance is how
clean that answer was when it was stored - nothing about what it is about.
This replays every question of the training key against her memory under
the current rule and under alternatives, and counts, of the turns shown,
how many are about the same question (by the question's own wording family)
and how many are other training questions.

Writes nothing to her memory: the store is copied (sqlite backup) into a
temporary directory, read there, and the copy deleted.
"""
import argparse
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np  # noqa: E402
import aetherroot as A  # noqa: E402
from logic import training  # noqa: E402


def rules():
    return {
        "now": lambda sim, res, rec: 0.5 * sim + 0.35 * res + 0.15 * rec,
        # relevance first: resonance and recency only scale what is relevant
        "scaled": lambda sim, res, rec: sim * (0.65 + 0.35 * res) + 0.05 * rec,
        # resonance counts only above a similarity floor
        "floor": lambda sim, res, rec: (0.5 * sim + 0.35 * res + 0.15 * rec) if sim >= 0.5
                 else 0.5 * sim,
        "similarity": lambda sim, res, rec: sim,
    }


def words_report(wording, mems, eps, top, now_rule):
    """Word-based retrieval (build log 72; the review of 10 Oct, Root #2/#3):
    a turn is scored by the words of the question it shares, weighted by how
    rare each is in her memory - the steward's facts are found this way
    already (logic/facts.py: log(1 + n/d)). Swept over a threshold T: a turn
    is shown only if the words it shares carry at least T of the question's
    weight. Two orders among those: by the word score, and by the rule the
    unit uses now (similarity, resonance, recency) with the word score in
    place of similarity."""
    import math
    import time
    from logic.knowledge import _STOP, _tokens

    def content(text):
        return [t for t in dict.fromkeys(_tokens(text)) if t not in _STOP and len(t) > 1]

    for field, label in (("user_msg", "her questions"), ("both", "questions and answers")):
        sets = []
        for ep in eps:
            text = ep.get("user_msg") or ""
            if field == "both":
                text += " " + (ep.get("ai_msg") or "")
            sets.append(frozenset(content(text)))
        n = len(sets) or 1
        df, inv = {}, {}
        for i, ws in enumerate(sets):
            for w in ws:
                df[w] = df.get(w, 0) + 1
                inv.setdefault(w, []).append(i)

        def idf(w):
            return math.log(1 + n / df.get(w, 0.5))
        thresholds = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
        orders = ("words", "now")
        out = {(t, o): {"same": 0, "other_training": 0, "other": 0, "shown": 0, "q": 0, "none": 0}
               for t in thresholds for o in orders}
        spent = 0.0
        for key, tid in wording.items():
            t0 = time.perf_counter()
            qw = content(key)
            denom = sum(idf(w) for w in qw) or 1.0
            score = {}
            for w in qw:
                for i in inv.get(w, ()):
                    score[i] = score.get(i, 0.0) + idf(w)
            spent += time.perf_counter() - t0
            for t in thresholds:
                passing = [(sc / denom, i) for i, sc in score.items() if sc / denom >= t]
                for o in orders:
                    if o == "words":
                        ranked = sorted(passing, reverse=True)
                    else:
                        ranked = sorted(((now_rule(w, mems[i]["res"], mems[i]["rec"]), i)
                                         for w, i in passing), reverse=True)
                    seen, picked = set(), []
                    for _, i in ranked:
                        k = mems[i]["key"]
                        if k and k in seen:
                            continue
                        seen.add(k)
                        picked.append(i)
                        if len(picked) >= top:
                            break
                    r = out[(t, o)]
                    r["q"] += 1
                    r["none"] += not picked
                    for i in picked:
                        m = mems[i]
                        r["shown"] += 1
                        if m["task"] == tid:
                            r["same"] += 1
                        elif m["trainer"] and m["task"]:
                            r["other_training"] += 1
                        else:
                            r["other"] += 1
        print()
        print("words of %s: %d turns, %d words; %.1f ms a question to score them all"
              % (label, n, len(df), 1000 * spent / max(1, len(wording))))
        print("%-22s %8s %15s %16s %8s %10s" % ("T, order", "shown/q", "about it (q's)",
                                              "other training", "other", "none shown"))
        for (t, o), r in out.items():
            print("%-22s %8.2f %9d (%3.0f%%) %10d %8d %10d" % (
                "T %.1f, by %s" % (t, o), r["shown"] / r["q"], r["same"], 100 * r["same"] / r["q"],
                r["other_training"], r["other"], r["none"]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy-from", default="/var/lib/aetherseed/.aetherseed")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--words", action="store_true",
                    help="also rank by the words of each turn (build log 72): the threshold sweep")
    a = ap.parse_args(argv)
    tmp = tempfile.mkdtemp(prefix="replay-")
    try:
        src = sqlite3.connect("file:%s?mode=ro" % os.path.join(a.copy_from, "aetherroot", "memory.db"),
                              uri=True)
        dst_path = os.path.join(tmp, "memory.db")
        dst = sqlite3.connect(dst_path)
        src.backup(dst)
        src.close()
        dst.close()
        store = A.MemoryStore(dst_path)
        import json
        cfg = dict(A.DEFAULT_CONFIG)
        try:
            with open(os.path.join(a.copy_from, "aetherroot", "config.json")) as f:
                cfg.update(json.load(f))
        except (OSError, ValueError):
            pass
        emb = A.TFIDFEmbedder(dim=cfg["embedding_dim"])
        from pathlib import Path
        emb.load_state(Path(a.copy_from) / "aetherroot" / "embedder_state.json")
        print("weights on the unit:", cfg.get("retrieval_weights"))
        episodes = store.get_all_episodes()
        # every wording of the key -> its task id; and her turns' questions -> task id
        settings = {}
        wording = {}
        for level in training.LADDER:
            for r in range(1, 9):
                fixed, pool = training.stage_tasks(level, r, settings)
                for t in fixed + pool:
                    for said in t["say"]:
                        wording[A._question_key(said)] = t["id"]
        mems = []
        for ep in episodes:
            if ep.get("embedding") is None:
                continue
            mems.append({"emb": ep["embedding"], "res": ep.get("resonance", 0.5),
                         "rec": A.recency_score(ep.get("timestamp", "")),
                         "task": wording.get(A._question_key(ep.get("user_msg") or "")),
                         "trainer": (ep.get("speaker") or "") == "Trainer"})
        # as the unit does: at most one turn per question wording
        for m, ep in zip(mems, [e for e in episodes if e.get("embedding") is not None]):
            m["key"] = A._question_key(ep.get("user_msg") or "")
        variants = [("now", rules()["now"], 0.0), ("scaled", rules()["scaled"], 0.0)]
        for floor in (0.3, 0.4, 0.5):
            variants.append(("now, floor %.1f" % floor, rules()["now"], floor))
            variants.append(("scaled, floor %.1f" % floor, rules()["scaled"], floor))
        out = {name: {"same": 0, "other_training": 0, "other": 0, "shown": 0, "q": 0} for name, _, _ in variants}
        for key, tid in wording.items():
            q = emb.embed(key)
            sims = [A.cosine_similarity(q, m["emb"]) for m in mems]
            for name, f, floor in variants:
                ranked = sorted(((f(s, m["res"], m["rec"]), i) for i, (s, m) in enumerate(zip(sims, mems))
                                 if s >= floor), reverse=True)
                seen, picked = set(), []
                for _, i in ranked:
                    k = mems[i]["key"]
                    if k and k in seen:
                        continue
                    seen.add(k)
                    picked.append(i)
                    if len(picked) >= a.top:
                        break
                o = out[name]
                o["q"] += 1
                for i in picked:
                    m = mems[i]
                    o["shown"] += 1
                    if m["task"] == tid:
                        o["same"] += 1
                    elif m["trainer"] and m["task"]:
                        o["other_training"] += 1
                    else:
                        o["other"] += 1
        print("%d turns in the copy, %d training wordings, up to %d shown, one per question" % (
            len(mems), len(wording), a.top))
        print("%-20s %8s %15s %16s %8s" % ("rule", "shown/q", "about it (q's)", "other training", "other"))
        for name, o in out.items():
            print("%-20s %8.2f %9d (%3.0f%%) %10d %8d" % (name, o["shown"] / o["q"], o["same"],
                  100 * o["same"] / o["q"], o["other_training"], o["other"]))
        if a.words:
            words_report(wording, mems, [e for e in episodes if e.get("embedding") is not None],
                         a.top, rules()["now"])
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
