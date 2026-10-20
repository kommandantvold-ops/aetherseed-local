"""The founders route and the unit's own knowledge file.

A founders question about AetherSeed is answered by the unit from its shipped
line, word for word, as the contact address is: a small model cannot reliably
copy a proper noun it has seen once. A unit's own facts live in a per-unit file,
not in the shared curriculum.
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


class TheFoundersRoute(unittest.TestCase):
    ASKING = [
        "tell me about the founders?",
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
        "My name is Sam and I am the AetherWeaver",
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

    def test_the_served_line_names_no_person_and_stands_alone(self):
        text = load_knowledge(ROOT / "knowledge" / "companion.en.jsonl").by_id(FOUNDERS_ENTRY)
        self.assertIn("three people", text)
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



    def test_a_unit_line_cannot_replace_a_shipped_one(self):
        k = self._load(self._unit([
            {"id": "as.founders", "text": "The founders are somebody else."},
            {"id": "unit.ok", "text": "A unit line."},
        ]))
        self.assertIn("three people", k.by_id("as.founders"))
        self.assertEqual("A unit line.", k.by_id("unit.ok"))
        self.assertEqual(1, len(k.errors))

    def test_no_unit_file_is_fine(self):
        k = self._load(Path(self.tmp) / "absent.jsonl")
        self.assertIsNotNone(k)
        self.assertFalse(any(e["id"].startswith("unit.") for e in k.entries))

    def test_a_named_path_never_picks_up_the_unit_file(self):
        unit = self._unit([{"id": "unit.ok", "text": "A unit line."}])
        with mock.patch.dict(os.environ, {"AETHERSEED_UNIT_KNOWLEDGE": str(unit)}):
            k = load_knowledge(ROOT / "knowledge" / "companion.en.jsonl")
        self.assertFalse(any(e["id"].startswith("unit.") for e in k.entries))



if __name__ == "__main__":
    unittest.main()
