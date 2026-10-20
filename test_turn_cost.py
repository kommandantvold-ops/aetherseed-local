"""What a stored turn costs: fewer rewrites, and less read.

    python3 -m unittest test_turn_cost -v
"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aetherroot  # noqa: E402


class TheStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cost-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = aetherroot.MemoryStore(os.path.join(self.tmp, "m.db"))
        e = np.ones(64, dtype=np.float32)
        for i in range(6):
            self.store.store_episode("s", "q%d" % i, "a", e, speaker="Guest" if i % 2 else "")

    def test_embeddings_can_be_left_unread(self):
        eps = self.store.get_all_episodes(embeddings=False)
        self.assertEqual(len(eps), 6)
        self.assertTrue(all(e["embedding"] is None for e in eps))
        self.assertTrue(all(e["embedding"] is not None for e in self.store.get_all_episodes()))

    def test_one_speakers_turns_are_chosen_in_the_query(self):
        guest = self.store.get_all_episodes(speaker="Guest")
        self.assertEqual({e["speaker"] for e in guest}, {"Guest"})
        self.assertEqual(len(guest), 3)
        steward = self.store.get_all_episodes(speaker="")
        self.assertEqual(len(steward), 3)


class TheStateFiles(unittest.TestCase):

    def test_written_every_few_turns_and_at_close(self):
        home = tempfile.mkdtemp(prefix="cost-home-")
        self.addCleanup(shutil.rmtree, home, True)
        root = aetherroot.AetherRoot(home)
        path = os.path.join(home, "embedder_state.json")
        for i in range(aetherroot.SAVE_EVERY - 1):
            root.store_interaction("question %d" % i, "answer")
        before = os.stat(path).st_mtime_ns if os.path.exists(path) else None
        root.store_interaction("the tenth", "answer")
        self.assertTrue(os.path.exists(path))
        after = os.stat(path).st_mtime_ns
        self.assertNotEqual(before, after)
        root.store_interaction("an eleventh", "answer")
        mid = os.stat(path).st_mtime_ns
        self.assertEqual(mid, after, "not rewritten on every turn")
        root.close()
        self.assertNotEqual(os.stat(path).st_mtime_ns, mid, "written at a clean shutdown")


if __name__ == "__main__":
    unittest.main()
