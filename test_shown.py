"""What was in front of her, after the token budget.

    python3 -m unittest test_shown -v

logic/token_budget.enforce_budget drops memory lines from the tail of the
block when a prompt does not fit. Until the checks after the turn read
the block as retrieved, so:
  - the honesty check and the steward check counted a dropped line as backing;
  - the scorer and the answer's tag counted it as shown;
  - the notes explaining a tag stayed in the prompt after their lines went.
No turn on a unit has been trimmed yet; these
tests force it with a counter that weighs each memory line at 100.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from logic import shown  # noqa: E402
from logic.facts import FACT_TAG, FACT_NOTE, FACT_NOTE_UNCHECKED, FACT_TAG_UNCHECKED  # noqa: E402
from logic.provenance import TAG_NOTE, UNVERIFIED_LABEL  # noqa: E402
from logic.prompt_builder import DATA_NOTE  # noqa: E402
from logic.token_budget import enforce_budget as real_enforce_budget  # noqa: E402

FACT = "- %s The rice store holds 40 kg. (Samuel)" % FACT_TAG
UNCHECKED = "- %s The well is 12 m deep. (Martin)" % FACT_TAG_UNCHECKED
KNOWN = "- [Known] At observer I may only read."
TAGGED = "- %s [Episode] User: Is the rice dry? | AI: Mostly." % UNVERIFIED_LABEL
PLAIN = "- [Episode] User: Hello | AI: Hello."


def block(*lines):
    return "\n".join(["[MEMORY CONTEXT]"] + list(lines) + ["[END MEMORY CONTEXT]"]) if lines else ""


def system(memory, notes=(FACT_NOTE, TAG_NOTE, DATA_NOTE), workspace=None):
    s = "You are Aria. Use [MEMORY CONTEXT] as real.\n" + "\n".join(notes)
    if memory:
        s += "\n\n" + memory
    if workspace is not None:
        s += "\n\n[WORKSPACE DATA]\n" + workspace + "\n[END WORKSPACE DATA]"
    return s


def report(kinds, tagged, facts=(), fact_texts=(), rings=(), known=None, trusted=""):
    r = {"line_kinds": list(kinds), "tagged": tagged, "facts": list(facts),
         "fact_sources": ["src%d" % i for i in facts], "fact_texts": list(fact_texts),
         "rings": list(rings), "trusted_context": trusted}
    if known is not None:
        r["known"] = known
    return r


class Settle(unittest.TestCase):

    def test_nothing_trimmed_nothing_changes(self):
        mem = block(KNOWN, FACT, TAGGED)
        trusted = block(KNOWN, FACT)
        rep = report(["known", "fact", "memory"], 1, [7], ["The rice store holds 40 kg."],
                     known=1, trusted=trusted)
        m, t, r = shown.settle(system(mem), mem, trusted, rep)
        self.assertEqual((m, t), (mem, trusted))
        self.assertEqual(r, rep)
        self.assertNotIn("lines_trimmed", r)

    def test_the_tail_goes_and_the_report_follows(self):
        mem = block(KNOWN, FACT, TAGGED)
        trusted = block(KNOWN, FACT)
        rep = report(["known", "fact", "memory"], 1, [7], ["The rice store holds 40 kg."],
                     known=1, trusted=trusted)
        m, t, r = shown.settle(system(block(KNOWN, FACT)), mem, trusted, rep)
        self.assertEqual(m, block(KNOWN, FACT))
        self.assertEqual(t, block(KNOWN, FACT))
        self.assertEqual((r["tagged"], r["facts"], r["known"], r["lines_trimmed"]), (0, [7], 1, 1))

    def test_a_dropped_fact_is_not_backing(self):
        mem = block(KNOWN, FACT, TAGGED)
        trusted = block(KNOWN, FACT)
        rep = report(["known", "fact", "memory"], 1, [7], ["The rice store holds 40 kg."],
                     known=1, trusted=trusted)
        m, t, r = shown.settle(system(block(KNOWN)), mem, trusted, rep)
        self.assertNotIn("40 kg", t)
        self.assertEqual((r["facts"], r["fact_texts"], r["fact_sources"]), ([], [], []))
        self.assertEqual(r["lines_trimmed"], 2)

    def test_an_emptied_block_leaves_nothing_shown(self):
        mem = block(FACT)
        rep = report(["fact"], 0, [7], ["The rice store holds 40 kg."], trusted=mem)
        m, t, r = shown.settle(system(""), mem, mem, rep)
        self.assertEqual((m, t, r["facts"], r["tagged"]), ("", "", [], 0))

    def test_all_lines_tagged_then_some_dropped(self):
        mem = block(TAGGED, TAGGED.replace("dry", "wet"))
        rep = report(["memory", "memory"], 2, trusted="")
        m, t, r = shown.settle(system(block(TAGGED)), mem, "", rep)
        self.assertEqual((t, r["tagged"]), ("", 1))

    def test_a_report_without_kinds_matches_facts_by_their_words(self):
        mem = block(FACT, PLAIN)
        rep = {"facts": [7], "fact_sources": ["Samuel"],
               "fact_texts": ["The rice store holds 40 kg."], "tagged": 0}
        m, t, r = shown.settle(system(block(PLAIN)), mem, mem, rep)
        self.assertEqual(r["facts"], [])
        m, t, r = shown.settle(system(block(FACT)), mem, mem, rep)
        self.assertEqual(r["facts"], [7])

    def test_the_report_passed_in_is_not_changed(self):
        mem = block(FACT, TAGGED)
        rep = report(["fact", "memory"], 1, [7], ["The rice store holds 40 kg."],
                     trusted=block(FACT))
        before = dict(rep)
        shown.settle(system(""), mem, block(FACT), rep)
        self.assertEqual(rep, before)


class DropNotes(unittest.TestCase):

    def test_every_note_stays_while_its_lines_do(self):
        mem = block(FACT, TAGGED)
        s = system(mem)
        self.assertEqual(shown.drop_notes(s, mem, 1), (s, []))

    def test_the_tag_note_goes_with_the_last_tagged_line(self):
        mem = block(FACT)
        out, gone = shown.drop_notes(system(mem), mem, 0)
        self.assertNotIn(TAG_NOTE, out)
        self.assertIn(FACT_NOTE, out)
        self.assertEqual(gone, ["TAG_NOTE"])

    def test_the_fact_note_goes_with_the_last_fact(self):
        mem = block(PLAIN)
        out, gone = shown.drop_notes(system(mem), mem, 0)
        self.assertNotIn(FACT_NOTE, out)
        self.assertIn(DATA_NOTE, out)
        self.assertEqual(sorted(gone), ["FACT_NOTE", "TAG_NOTE"])

    def test_the_unchecked_half_goes_alone_when_only_checked_facts_are_left(self):
        notes = (FACT_NOTE + " " + FACT_NOTE_UNCHECKED, DATA_NOTE)
        mem = block(FACT)
        out, gone = shown.drop_notes(system(mem, notes), mem, 0)
        self.assertIn(FACT_NOTE, out)
        self.assertNotIn(FACT_NOTE_UNCHECKED, out)
        self.assertEqual(gone, ["FACT_NOTE_UNCHECKED"])
        out, gone = shown.drop_notes(system("", notes), "", 0)
        self.assertNotIn(FACT_NOTE, out)
        self.assertNotIn(FACT_NOTE_UNCHECKED, out)

    def test_an_unchecked_fact_keeps_both(self):
        notes = (FACT_NOTE + " " + FACT_NOTE_UNCHECKED, DATA_NOTE)
        mem = block(UNCHECKED)
        s = system(mem, notes)
        self.assertEqual(shown.drop_notes(s, mem, 0), (s, []))

    def test_the_data_note_stays_for_a_file(self):
        out, gone = shown.drop_notes(system("", workspace="- dry the matches"), "", 0)
        self.assertIn(DATA_NOTE, out)
        out, gone = shown.drop_notes(system(""), "", 0)
        self.assertNotIn(DATA_NOTE, out)

    def test_a_note_quoted_inside_a_file_is_never_taken_for_one(self):
        ws = "Notes copied by hand:\n" + TAG_NOTE + "\n" + FACT_NOTE
        mem = block(PLAIN)
        out, gone = shown.drop_notes(system(mem, workspace=ws), mem, 0)
        self.assertEqual(out.count(TAG_NOTE), 1)       # the file's copy
        self.assertEqual(out.count(FACT_NOTE), 1)
        self.assertIn(ws, out)


class _LinesWeigh:
    """A counter for these tests: each memory line weighs 100, the rest 10."""
    def __init__(self, ceiling):
        self.ceiling = ceiling
        self.model = "test"

    def count_messages(self, msgs):
        sys_text = next((m["content"] for m in msgs if m.get("role") == "system"), "")
        return 100 * len(shown.memory_lines(sys_text)) + 10


class TheBudgetLeavesNoEmptyBlock(unittest.TestCase):
    """Popping the last line used to leave "[MEMORY CONTEXT]" over nothing
    whenever that pop was what made the prompt fit."""

    def fit(self, sys_text, ceiling):
        msgs = [{"role": "system", "content": sys_text}, {"role": "user", "content": "Hi"}]
        out, rep = real_enforce_budget(_LinesWeigh(ceiling), msgs)
        return out[0]["content"], rep

    def test_the_last_line_takes_the_block_with_it(self):
        text, rep = self.fit(system(block(PLAIN)), 18)
        self.assertNotIn("\n[MEMORY CONTEXT]", text)
        self.assertNotIn("[END MEMORY CONTEXT]", text)
        self.assertEqual(text, text.rstrip())
        self.assertEqual(rep.memory_entries_dropped, 1)

    def test_a_file_after_it_stays_where_it_was(self):
        text, rep = self.fit(system(block(PLAIN, FACT), workspace="- dry the matches"), 18)
        self.assertIn(DATA_NOTE + "\n\n[WORKSPACE DATA]\n- dry the matches", text)
        self.assertEqual(rep.memory_entries_dropped, 2)

    def test_lines_that_fit_are_left_alone(self):
        sys_text = system(block(PLAIN, FACT))
        text, rep = self.fit(sys_text, 100000)
        self.assertEqual((text, rep.trimmed), (sys_text, False))


try:
    import test_memory_turn as tmt   # the real proxy in front of a scripted model
    from test_memory_turn import _Proxy, _RecordingTrust, SCRIPT
    import proxy
except Exception:                    # pragma: no cover - the proxy test needs the stack
    tmt = None


@unittest.skipIf(tmt is None, "the proxy stack is not importable here")
class AtTheProxy(_Proxy if tmt else unittest.TestCase):

    QUESTION = "What does the rice store hold?"
    REPLY = "My steward told me the rice store holds 40 kg."

    def setUp(self):
        super().setUp()
        self.trust = _RecordingTrust()
        self.saved = (proxy.trust, proxy.enforce_budget, proxy.token_counter)
        proxy.trust = self.trust
        proxy.enforce_budget = real_enforce_budget
        self.ceiling = 100000
        proxy.token_counter = lambda *a, **k: _LinesWeigh(self.ceiling)
        proxy.root.store.add_fact("The rice store holds 40 kg.", "Samuel")
        SCRIPT["chunks"] = [self.REPLY]

    def tearDown(self):
        proxy.trust, proxy.enforce_budget, proxy.token_counter = self.saved
        super().tearDown()

    def told(self):
        import time
        for _ in range(100):
            if self.trust.calls:
                return self.trust.calls[-1]
            time.sleep(0.02)
        self.fail("the scorer was never called")

    def test_shown_the_fact_it_is_backed(self):
        status, text, meta = self.ask(self.QUESTION)
        self.assertEqual(status, 200)
        sent = self.system_sent()
        self.assertIn(FACT_TAG, sent)
        self.assertIn(FACT_NOTE, sent)
        self.assertEqual((meta["facts_used"], meta["steward_backed"], meta["unsourced_figures"]),
                         (1, True, 0))

    def test_a_fact_the_budget_dropped_backs_nothing(self):
        self.ceiling = 50                      # no memory line fits
        status, text, meta = self.ask(self.QUESTION)
        self.assertEqual(status, 200)
        sent = self.system_sent()
        self.assertNotIn(FACT_TAG, sent)
        self.assertNotIn(FACT_NOTE, sent)      # X8: no note without its lines
        self.assertNotIn(DATA_NOTE, sent)
        # X9: not shown, so not backing - neither for the steward check nor
        # for the honesty check, and the scorer is told it was not shown
        self.assertEqual(meta["facts_used"], 0)
        self.assertIs(meta["memory_used"], False)
        self.assertIs(meta["steward_credited"], True)
        self.assertIs(meta["steward_backed"], False)
        self.assertEqual(meta["unsourced_figures"], 1)
        self.assertEqual(meta["mode"], "unverified")
        k = self.told()
        self.assertEqual((k["shown_facts"], k["memory_context"]), (0, ""))

    def test_a_tagged_line_dropped_takes_its_note_and_the_fact_stays(self):
        proxy.root.store_interaction("Is the rice store dry?", "I think it is mostly dry.",
                                     mode="unverified", rings=False)
        status, text, meta = self.ask(self.QUESTION)
        sent = self.system_sent()
        self.assertIn(UNVERIFIED_LABEL, sent)
        self.assertIn(TAG_NOTE, sent)
        self.assertGreaterEqual(meta["tagged_used"], 1)
        n = len(shown.memory_lines(sent))
        SCRIPT["requests"].clear()
        self.ceiling = 100 * (n - 1) + 18      # room for all but the last line
        status, text, meta = self.ask(self.QUESTION)
        sent = self.system_sent()
        self.assertEqual(len(shown.memory_lines(sent)), n - 1)
        self.assertNotIn(UNVERIFIED_LABEL, sent)
        self.assertNotIn(TAG_NOTE, sent)
        self.assertIn(FACT_NOTE, sent)
        self.assertEqual((meta["tagged_used"], meta["facts_used"], meta["steward_backed"]),
                         (0, 1, True))


if __name__ == "__main__":
    unittest.main()
