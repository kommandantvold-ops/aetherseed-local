"""Rings, the memory counter, and what consolidation is allowed to read.

Step 32 (code review mk.2, 25 Sep 2026). Three findings, each pinned here:

  F1  consolidation summarised 'unverified' and 'fiction' turns into [Pattern]
      lines that a factual request then retrieved - provenance laundering.
  F2  a ring is 20 episodes, not 50: the trigger fires at 50 waiting, takes 20.
  F3  the console's count was table rows; it now says remembered / set aside.

Every test runs in a throwaway root dir. Nothing here touches a unit's memory.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aetherroot
from aetherroot import AetherRoot
from logic import provenance


def _turns(root, n, mode="factual", start=1, word="ordinary"):
    for i in range(start, start + n):
        root.store_interaction(f"{word}{i} alpha beta gamma", "answer", 0.5, mode=mode)


class _Root(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.root = AetherRoot(self.dir)

    def tearDown(self):
        self.root.store.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def rings(self):
        return self.root.get_status()["rings"]


class TestConsolidationReadsFactualOnly(_Root):
    """F1."""

    def test_unverified_words_never_reach_a_factual_prompt(self):
        # The step-32 repro: 13 set-aside turns, then enough factual ones to
        # close the first ring. Before the fix the [Pattern] line carried
        # 'secretword3' into this factual prompt.
        _turns(self.root, 13, mode="unverified", word="secretword")
        _turns(self.root, 50, start=14)
        # Counted from the table, not get_status(), so this test fails on the
        # defect itself when run against the pre-fix code, not on a missing key.
        closed = self.root.store.conn.execute(
            "SELECT COUNT(*) FROM growth WHERE event_type = 'consolidation'").fetchone()[0]
        self.assertGreaterEqual(closed, 1)
        ctx = self.root.retrieve_context("tell me about secretword3 and alpha",
                                         request_mode="factual")
        self.assertNotIn("secretword", ctx)

    def test_fiction_words_never_reach_a_factual_prompt(self):
        _turns(self.root, 13, mode="fiction", word="dragonword")
        _turns(self.root, 50, start=14)
        for sem in self.root.store.get_all_semantic():
            self.assertNotIn("dragonword", sem["content"])

    def test_a_ring_takes_only_factual_episodes(self):
        _turns(self.root, 30, mode="unverified", word="secretword")
        _turns(self.root, 50, start=31)
        (sem,) = self.root.store.get_all_semantic()
        src = [int(i) for i in str(sem["source_ids"]).split(",")]
        modes = {e["id"]: e["mode"] for e in self.root.store.get_all_episodes()}
        self.assertEqual({"factual"}, {modes[i] for i in src})

    def test_non_factual_turns_do_not_close_a_ring(self):
        _turns(self.root, 60, mode="unverified", word="secretword")
        _turns(self.root, 20, mode="fiction", word="dragonword", start=61)
        self.assertEqual(0, self.rings()["count"])
        self.assertEqual([], self.root.store.get_all_semantic())

    def test_skipped_episodes_are_left_unconsolidated(self):
        # Decision 25 Sep: skipped, not marked. The record keeps them as they were.
        _turns(self.root, 5, mode="unverified", word="secretword")
        _turns(self.root, 50, start=6)
        rows = self.root.store.conn.execute(
            "SELECT consolidated FROM episodes WHERE mode = 'unverified'").fetchall()
        self.assertEqual({0}, {r[0] for r in rows})

    def test_mode_constants_match_provenance(self):
        self.assertEqual((provenance.FACTUAL,), aetherroot.CONSOLIDATES)
        self.assertEqual((provenance.FACTUAL, provenance.FICTION), aetherroot.REMEMBERED)
        self.assertEqual((provenance.UNVERIFIED,), aetherroot.SET_ASIDE)


class TestRings(_Root):
    """F2 and 4c."""

    def test_rings_close_at_50_then_every_20(self):
        closed = []
        for i in range(1, 131):
            _turns(self.root, 1, start=i)
            if self.rings()["count"] > len(closed):
                closed.append(i)
        self.assertEqual([50, 70, 90, 110, 130], closed)

    def test_progress_is_n_of_50_before_the_first_ring(self):
        _turns(self.root, 22)
        r = self.rings()
        self.assertEqual((0, 22, 50, None), (r["count"], r["into"], r["of"], r["last_at"]))

    def test_progress_is_n_of_20_after_it(self):
        _turns(self.root, 50)
        r = self.rings()
        self.assertEqual((1, 0, 20), (r["count"], r["into"], r["of"]))
        self.assertIsNotNone(r["last_at"])
        _turns(self.root, 7, start=51)
        self.assertEqual((1, 7, 20), (self.rings()["count"], self.rings()["into"], self.rings()["of"]))

    def test_set_aside_turns_do_not_advance_the_ring(self):
        _turns(self.root, 10)
        _turns(self.root, 10, mode="unverified", word="secretword", start=11)
        self.assertEqual(10, self.rings()["into"])

    def test_a_config_without_the_batch_key_still_works(self):
        # Lyra's config.json was written before consolidation_batch existed and
        # is loaded as-is, without defaults merged in.
        self.root.store.close()
        cfg = Path(self.dir) / "config.json"
        data = json.loads(cfg.read_text())
        del data["consolidation_batch"]
        cfg.write_text(json.dumps(data))
        self.root = AetherRoot(self.dir)
        _turns(self.root, 57)
        r = self.rings()
        self.assertEqual((1, 7, 20), (r["count"], r["into"], r["of"]))


class TestCounter(_Root):
    """F3 / 4b."""

    def test_remembered_and_set_aside(self):
        _turns(self.root, 13)
        _turns(self.root, 20, mode="unverified", word="secretword", start=14)
        s = self.root.get_status()
        self.assertEqual((33, 13, 20), (s["episodes"], s["remembered"], s["set_aside"]))

    def test_fiction_counts_as_remembered(self):
        _turns(self.root, 3)
        _turns(self.root, 2, mode="fiction", word="dragonword", start=4)
        s = self.root.get_status()
        self.assertEqual((5, 0), (s["remembered"], s["set_aside"]))



class TestWhatARingKeeps(_Root):
    """Step 37 (Andreas: "both, labelled"). Until then a ring kept ten words
    from the first five of each message, stopwords in, order random:
    "Conversation patterns about: to, claude, so, matter, one, okay, ..." """

    def test_the_chosen_part_is_made_only_of_what_was_said(self):
        from logic.rings import tokens
        for i in range(1, 51):
            self.root.store_interaction(
                "Claude here. " + ("The heron stood in the river." if i % 2
                                   else "A boat crossed the fjord."), "Yes.", 0.5)
        (sem,) = self.root.store.get_all_semantic()
        said = set()
        for e in self.root.store.get_all_episodes():
            said.update(tokens(e["user_msg"]))
        self.assertTrue(sem["content"].startswith("themes: "), sem["content"])
        themes = sem["content"].split("themes: ", 1)[1].split(" · ")[0].split(", ")
        self.assertTrue(themes and set(themes) <= said, themes)
        self.assertNotIn("claude", themes, "a word said in every turn is no theme")
        self.assertRegex(sem["content"], r" · e\.g\. User: “Claude here\. (The heron|A boat)")
        self.assertEqual(sem["ring_no"], 1)

    def test_themes_rank_what_is_distinctive(self):
        from logic.rings import themes
        ring = ["the heron and the river", "a heron by the river", "heron at dawn"]
        doc_freq = {"heron": 3, "river": 2, "dawn": 1, "boat": 40}
        self.assertEqual(themes(ring, doc_freq, 50)[:2], ["heron", "river"])
        self.assertNotIn("the", themes(ring, doc_freq, 50))
        self.assertEqual(themes(["boat boat"], {"boat": 50}, 50), [],
                         "a word in every turn of the store scores nothing")

    def test_the_representative_is_the_turn_nearest_the_centre(self):
        from logic.rings import representative
        self.assertEqual(representative([[1, 0], [0.9, 0.1], [0, 1]]), 1)
        self.assertIsNone(representative([]))

    def test_her_sentence_is_one_sentence_with_no_tags(self):
        from logic.rings import clean_own_words, OWN_WORDS_MAX
        self.assertEqual(clean_own_words('"[Ring] These turns were verses about love. And more."'),
                         "These turns were verses about love.")
        self.assertEqual(clean_own_words("A [marker] inside"), "")
        self.assertLessEqual(len(clean_own_words("word " * 100)), OWN_WORDS_MAX + 1)
        self.assertEqual(clean_own_words(""), "")

    def test_the_line_shows_her_words_only_under_their_label(self):
        from logic.rings import ring_line, OWN_WORDS_LABEL
        self.assertEqual(ring_line(3, "themes: a, b"), "[Ring] 3 · themes: a, b")
        self.assertEqual(ring_line(3, "themes: a, b", "About a and b."),
                         "[Ring] 3 · themes: a, b · %s About a and b." % OWN_WORDS_LABEL)

    def test_a_ring_waits_for_its_words_at_most_three_times(self):
        _turns(self.root, 50)
        (sem,) = self.root.store.get_all_semantic()
        for _ in range(3):
            self.assertEqual(len(self.root.store.rings_needing_own_words(3)), 1)
            self.root.store.set_own_words(sem["id"], "", "model failed")
        self.assertEqual(self.root.store.rings_needing_own_words(3), [])

if __name__ == "__main__":
    unittest.main()
