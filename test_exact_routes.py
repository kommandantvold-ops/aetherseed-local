"""The founders route and the unit's own knowledge file.

Step 33 (25 Sep 2026). Episode #22: with the curriculum live and spelling
"Vamsti", the model answered "Andreas Vamasti Kommandantvold", and repeated it
the next night (#23). The founders line is now served from the build like the
contact address (step 28). Episode #29: the node told its owner it was "not a
part of R&D Unit 1" - a fact true of one unit only, so it lives in a per-unit
file, not the shared curriculum.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logic import knowledge
from logic.knowledge import (exact_entry_for, is_founders_question, load_knowledge,
                             CONTACT_ENTRY, FOUNDERS_ENTRY)

ROOT = Path(__file__).resolve().parent
UNIT_FILE = ROOT / "units" / "rd-unit-1.jsonl"


class TheFoundersRoute(unittest.TestCase):
    ASKING = [
        "tell me about the founders?",              # episode #22, verbatim
        "Who founded AetherSeed?",
        "who founded aetherseed",
        "who are your founders",
        "Who are the founders?",
        "Tell me about the founders of AetherSeed",
        "Name the founders",
        "Who founded the company?",
        "who are the co-founders of aetherseed?",
    ]

    NOT_ASKING = [
        "who founded Microsoft?",
        "tell me about the founders of Rome",
        "The founders of Rome were twins.",
        "I am one of the founders",
        "Andreas Vamsti (not Vamasti) Kommandantvold is me. I am the AetherWeave",
        "who made you",
        "what is aetherseed",
        "How do I contact AetherSeed?",
        "can you help me contact my landlord",
        "",
    ]

    def test_asking(self):
        missed = [q for q in self.ASKING if not is_founders_question(q)]
        self.assertEqual([], missed)

    def test_not_asking(self):
        caught = [q for q in self.NOT_ASKING if is_founders_question(q)]
        self.assertEqual([], caught)

    def test_routes_in_order(self):
        self.assertEqual(CONTACT_ENTRY, exact_entry_for("How do I contact AetherSeed?"))
        self.assertEqual(FOUNDERS_ENTRY, exact_entry_for("tell me about the founders?"))
        self.assertIsNone(exact_entry_for("who founded Microsoft?"))

    def test_the_served_line_spells_the_names_right_and_stands_alone(self):
        text = load_knowledge(ROOT / "knowledge" / "companion.en.jsonl").by_id(FOUNDERS_ENTRY)
        self.assertIn("Andreas Vamsti Kommandantvold", text)
        self.assertNotIn("Vamasti", text)
        self.assertIn("Martin Lervik Nilsen", text)
        self.assertIn("Christian Theodor Wisnes", text)
        # Served on its own, "Its founders..." would have no antecedent.
        self.assertTrue(text.startswith("AetherSeed's founders"))


class TheUnitFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _unit(self, lines):
        p = Path(self.tmp) / "unit.jsonl"
        p.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")
        return p

    def _load(self, unit_path):
        with mock.patch.dict(os.environ, {"AETHERSEED_UNIT_KNOWLEDGE": str(unit_path)}):
            os.environ.pop("AETHERSEED_KNOWLEDGE", None)
            return load_knowledge()

    def test_lyras_file_loads_and_answers_episode_29(self):
        k = self._load(UNIT_FILE)
        self.assertEqual([], k.errors)
        q = ("I would like to talk about the future of AetherSeed, you are Lyra "
             "R&D Unit 1 and will shape the future of all Companions, just like "
             "Horizon has helped shape you")
        self.assertTrue(any("R&D Unit 1" in l for l in k.lines_for(q)))

    def test_it_stays_quiet_off_topic(self):
        k = self._load(UNIT_FILE)
        self.assertEqual([], k.lines_for("what is the capital of France"))
        self.assertEqual([], k.lines_for("help me write to my landlord"))

    def test_a_unit_line_cannot_replace_a_shipped_one(self):
        k = self._load(self._unit([
            {"id": "as.founders", "text": "The founders are somebody else."},
            {"id": "unit.ok", "text": "A unit line."},
        ]))
        self.assertIn("Vamsti", k.by_id("as.founders"))
        self.assertEqual("A unit line.", k.by_id("unit.ok"))
        self.assertEqual(1, len(k.errors))

    def test_no_unit_file_is_fine(self):
        k = self._load(Path(self.tmp) / "absent.jsonl")
        self.assertIsNotNone(k)
        self.assertFalse(any(e["id"].startswith("unit.") for e in k.entries))

    def test_a_named_path_never_picks_up_the_unit_file(self):
        with mock.patch.dict(os.environ, {"AETHERSEED_UNIT_KNOWLEDGE": str(UNIT_FILE)}):
            k = load_knowledge(ROOT / "knowledge" / "companion.en.jsonl")
        self.assertFalse(any(e["id"].startswith("unit.") for e in k.entries))

    def test_the_unit_file_is_not_in_the_shared_curriculum(self):
        shipped = (ROOT / "knowledge" / "companion.en.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("R&D Unit", shipped)


if __name__ == "__main__":
    unittest.main()
