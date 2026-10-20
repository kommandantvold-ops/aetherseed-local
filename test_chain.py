"""Records that show whether they were changed.

    python3 -m unittest test_chain -v

logic/chain.py, the writers that use it, and tools/verify_chain.py. Every
test works in a throwaway directory.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

from logic import chain  # noqa: E402
import verify_chain  # noqa: E402


def lines(path):
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def rewrite(path, new_lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")


class _Dir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="chain-")
        self.log = os.path.join(self.dir, "corrections.log")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, n, start=0):
        with contextlib.redirect_stdout(io.StringIO()):
            return [chain.append(self.log, {"action": "note", "n": i}) for i in range(start, start + n)]


class TheChain(_Dir):

    def test_a_new_record_holds_from_its_first_line(self):
        hashes = self.write(3)
        r = chain.verify(self.log)
        self.assertEqual((r["ok"], r["lines"], r["chained"], r["started"], r["anchors"]),
                         (True, 3, 3, 1, 1))
        self.assertEqual(r["head"], hashes[-1])
        first = json.loads(lines(self.log)[0])
        self.assertEqual(first["prev"], chain.ZERO)
        self.assertEqual(json.loads(lines(self.log)[1])["prev"], hashes[0])

    def test_a_line_keeps_what_the_writer_gave_it(self):
        self.write(1)
        e = json.loads(lines(self.log)[0])
        self.assertEqual((e["action"], e["n"]), ("note", 0))

    def test_the_old_lines_are_fixed_as_they_stood_not_rewritten(self):
        old = ['{"action": "set_mode", "id": 1}', '{"action": "set_mode", "id": 2}']
        rewrite(self.log, old)
        with open(self.log, "rb") as f:
            before = f.read()
        self.write(2)
        self.assertEqual(lines(self.log)[:2], old)
        first = json.loads(lines(self.log)[2])
        self.assertEqual(first["prev"], hashlib.sha256(before).hexdigest())
        r = chain.verify(self.log)
        self.assertEqual((r["ok"], r["started"], r["chained"]), (True, 3, 2))

    def test_an_old_line_changed_afterwards_shows(self):
        rewrite(self.log, ['{"action": "set_mode", "id": 1}'])
        self.write(2)
        ls = lines(self.log)
        ls[0] = '{"action": "set_mode", "id": 9}'
        rewrite(self.log, ls)
        r = chain.verify(self.log)
        self.assertEqual((r["ok"], r["first_bad"]), (False, 2))
        self.assertIn("what stands before it", r["why"])

    def test_a_chained_line_changed_shows_at_that_line(self):
        self.write(4)
        ls = lines(self.log)
        e = json.loads(ls[1])
        e["n"] = 99
        ls[1] = json.dumps(e)
        rewrite(self.log, ls)
        r = chain.verify(self.log)
        self.assertEqual((r["ok"], r["first_bad"]), (False, 2))
        self.assertIn("hash does not match", r["why"])

    def test_a_line_removed_shows_at_the_next(self):
        self.write(4)
        ls = lines(self.log)
        del ls[1]
        rewrite(self.log, ls)
        r = chain.verify(self.log)
        self.assertEqual((r["ok"], r["first_bad"]), (False, 2))
        self.assertIn("changed, removed or put in", r["why"])

    def test_a_line_put_in_shows(self):
        self.write(3)
        ls = lines(self.log)
        ls.insert(2, ls[0])
        rewrite(self.log, ls)
        r = chain.verify(self.log)
        self.assertEqual((r["ok"], r["first_bad"]), (False, 3))

    def test_a_torn_line_is_closed_and_fixed_by_the_next(self):
        self.write(2)
        with open(self.log, "ab") as f:
            f.write(b'{"action": "note", "n": ')          # a cut mid-write
        self.write(2, start=2)
        r = chain.verify(self.log)
        self.assertEqual((r["ok"], r["chained"], r["outside"], r["anchors"]), (True, 4, [3], 2))
        ls = lines(self.log)
        ls[2] = '{"action": "nothing", "n": '
        rewrite(self.log, ls)
        r = chain.verify(self.log)
        self.assertEqual((r["ok"], r["first_bad"]), (False, 4))

    def test_a_line_from_a_writer_outside_the_chain_is_fixed_by_the_next(self):
        self.write(2)
        with open(self.log, "a", encoding="utf-8") as f:
            f.write('{"action": "old tool"}\n')
        self.write(1, start=2)
        r = chain.verify(self.log)
        self.assertEqual((r["ok"], r["outside"]), (True, [3]))
        ls = lines(self.log)
        ls[2] = '{"action": "someone else"}'
        rewrite(self.log, ls)
        self.assertEqual(chain.verify(self.log)["first_bad"], 4)

    def test_threads_never_interleave(self):
        def w(k):
            with contextlib.redirect_stdout(io.StringIO()):
                for i in range(25):
                    chain.append(self.log, {"thread": k, "i": i})
        ts = [threading.Thread(target=w, args=(k,)) for k in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        r = chain.verify(self.log)
        self.assertEqual((r["ok"], r["chained"], r["outside"]), (True, 200, []))

    def test_announce_prints_the_head(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            h = chain.append(self.log, {"a": 1}, announce="corrections.log")
        self.assertEqual(out.getvalue().strip(), "[chain] corrections.log %s" % h[:16])

    def test_a_missing_file_has_nothing_to_hold(self):
        r = chain.verify(os.path.join(self.dir, "none.log"))
        self.assertEqual((r["ok"], r["lines"], r["started"]), (True, 0, None))


class TheTool(_Dir):

    def run_tool(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify_chain.main(["--dir", self.dir] + list(args))
        return code, out.getvalue()

    def test_it_says_what_holds(self):
        self.write(3)
        code, out = self.run_tool()
        self.assertEqual(code, 0)
        self.assertIn("corrections.log", out)
        self.assertIn("chained from line 1 (3)", out)
        self.assertTrue(out.strip().endswith("holds"))

    def test_it_names_the_first_broken_line(self):
        self.write(3)
        ls = lines(self.log)
        ls[2] = ls[2].replace('"n": 2', '"n": 7')
        rewrite(self.log, ls)
        code, out = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("BROKEN at line 3", out)

    def test_a_record_rewritten_whole_is_caught_by_the_journal(self):
        # Every hash recomputed after an edit: the chain alone cannot see it.
        # The heads the journal saw before the rewrite are no longer there.
        seen = self.write(3)
        ls = lines(self.log)
        os.remove(self.log)
        for raw in ls:
            e = json.loads(raw)
            if e["n"] == 1:
                e["n"] = 5
            e.pop("prev"), e.pop("hash")
            with contextlib.redirect_stdout(io.StringIO()):
                chain.append(self.log, e)
        self.assertTrue(chain.verify(self.log)["ok"])
        saved = verify_chain.journal_heads
        verify_chain.journal_heads = lambda *a, **k: {"corrections.log": [h[:16] for h in seen]}
        try:
            code, out = self.run_tool("--journal")
        finally:
            verify_chain.journal_heads = saved
        self.assertEqual(code, 1)
        self.assertIn("2 are NOT in the file", out)

    def test_json(self):
        self.write(1)
        code, out = self.run_tool("--json")
        d = json.loads(out)
        self.assertTrue(d["corrections.log"]["ok"])
        self.assertNotIn("heads", d["corrections.log"])


class TheWriters(unittest.TestCase):
    """Every writer of the four records writes a chained line."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="writers-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_correction_from_the_console(self):
        from logic import steward
        log = os.path.join(self.dir, "corrections.log")
        with contextlib.redirect_stdout(io.StringIO()):
            steward._log(log, {"action": "support", "target": "turn", "id": 3})
            steward._log(log, {"action": "undo", "note": 1})
        r = chain.verify(log)
        self.assertEqual((r["ok"], r["chained"]), (True, 2))
        self.assertEqual(json.loads(lines(log)[0])["by"], "steward (console)")

    def test_the_steward_facts_tool(self):
        import steward_facts
        log = os.path.join(self.dir, "corrections.log")
        with contextlib.redirect_stdout(io.StringIO()):
            steward_facts.log_line(log, {"action": "add_fact", "fact": 1})
        self.assertEqual(chain.verify(log)["chained"], 1)

    def test_the_correct_memory_tool(self):
        import correct_memory
        log = os.path.join(self.dir, "corrections.log")
        with contextlib.redirect_stdout(io.StringIO()):
            correct_memory.log_line(log, {"action": "set_mode", "episode": 4,
                                          "mode_before": "factual"})
        r = chain.verify(log)
        self.assertEqual((r["ok"], r["chained"]), (True, 1))
        # and the tool still reads its own log back
        self.assertEqual(correct_memory.previous_modes(log, [4]), {4: "factual"})

    def test_trust_events_every_one_and_every_grant(self):
        from trust_evolution import TrustEvolution
        state = os.path.join(self.dir, "trust_state.json")
        t = TrustEvolution(state)
        with contextlib.redirect_stdout(io.StringIO()):
            t.record_event("honest_refusal", "Declined: how far is Mars")
            t.grant_level("reader", "earned in training")
            t.reset()
        log = os.path.join(self.dir, "trust_events.log")
        r = chain.verify(log)
        self.assertEqual((r["ok"], r["chained"]), (True, 3))
        types = [json.loads(l)["type"] for l in lines(log)]
        self.assertEqual(types, ["honest_refusal", "steward_grant", "reset"])

    def test_a_ring_and_a_wipe(self):
        import aetherroot
        rootdir = os.path.join(self.dir, "aetherroot")
        os.makedirs(rootdir)
        cfg = dict(aetherroot.DEFAULT_CONFIG, consolidation_threshold=10, consolidation_batch=5)
        with open(os.path.join(rootdir, "config.json"), "w") as f:
            json.dump(cfg, f)
        with contextlib.redirect_stdout(io.StringIO()):
            root = aetherroot.AetherRoot(rootdir)
            try:
                for i in range(12):
                    root.store_interaction("Question %d about the river" % i, "Answer %d." % i)
                root.reset("episodes_only")
            finally:
                root.close()
        log = os.path.join(rootdir, "growth.log")
        r = chain.verify(log)
        self.assertTrue(r["ok"])
        events = [json.loads(l)["event"] for l in lines(log)]
        self.assertIn("ring", events)
        self.assertEqual(events[-1], "memory_wiped")
        self.assertEqual(json.loads(lines(log)[-1])["held_before"]["episodes"], 12)


if __name__ == "__main__":
    unittest.main()
