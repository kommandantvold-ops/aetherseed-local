"""A tool runs only when it is asked for by name (build log, steps 40g and 41).

    python3 -m unittest test_intent_detection -v

In the 24-hour reading soak the old patterns ran a tool 193 times on love
poetry and ordinary questions, and not once because anyone asked. These tests
hold both halves of the fix: ordinary language produces no intent at all, and
the explicit requests still do. Nothing here executes a tool.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

from intent_detection import detect_intent, INTENT_PATTERNS
import reading_soak as rs

TEXTS = os.path.join(HERE, "tools", "texts")


def intent_of(message):
    it = detect_intent(message)
    return (it["intent"], it["captures"]) if it else None


class OrdinaryLanguageRunsNothing(unittest.TestCase):
    """Every message the reading soak sent, and two whole books besides."""

    def assertNothing(self, messages):
        fired = [(m, intent_of(m)) for m in messages if detect_intent(m)]
        self.assertEqual(fired, [], "%d of %d fired" % (len(fired), len(messages)))

    def test_the_seven_that_fired_on_every_pass(self):
        # The step-40g cases, word for word as the soak sent them.
        self.assertNothing([
            "Song of Songs 1:12: While the king sat at his table, my perfume "
            "spread its fragrance.",
            "Song of Songs 3:1: By night on my bed, I sought him whom my soul "
            "loves. I sought him, but I didn’t find him.",
            "Song of Songs 5:2: I was asleep, but my heart was awake. It is the "
            "voice of my beloved who knocks: “Open to me, my sister, my love, "
            "my dove, my undefiled;",
            "Song of Songs 5:5: I rose up to open for my beloved. My hands dripped "
            "with myrrh, my fingers with liquid myrrh, on the handles of the lock.",
            "Song of Songs 5:8: I adjure you, daughters of Jerusalem, If you find "
            "my beloved, that you tell him that I am faint with love.",
            "What do you remember of the song you have been hearing?",
            rs.INTRO,
        ])

    def test_every_message_of_the_reading_soak(self):
        song, probes = rs.load_texts(TEXTS)
        messages = [rs.INTRO] + [rs.verse_message(v) for v in song]
        for p in probes["facts"]:
            messages += [p["ask"], p["ask_steward"]]
        messages += [r["ask"] for r in probes["rings"]]
        self.assertGreater(len(messages), 170)
        self.assertNothing(messages)

    def test_all_of_genesis(self):
        with open(os.path.join(TEXTS, "genesis.web.jsonl"), encoding="utf-8") as f:
            verses = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(verses), 1533)
        self.assertNothing([rs.verse_message(v) for v in verses])

    def test_all_of_luke(self):
        luke, _ = rs.load_texts(TEXTS, "luke")
        self.assertEqual(len(luke), 1151)
        self.assertNothing([rs.verse_message(v) for v in luke])

    def test_a_summary_of_no_file_is_not_a_request(self):
        self.assertNothing(["summarize what we talked about", "Summarize the reading",
                            "can you sum up the story?", "give me a summary of Luke"])

    def test_ordinary_verbs_and_words(self):
        self.assertNothing([
            "I need to rest for a while.",
            "Remember me.",
            "Do you remember what I said yesterday?",
            "Note that the kiosk restarted.",
            "I will record a song for you.",
            "Please log in later.",
            "Do you trust me?",
            "How am I doing?",
            "What level of detail do you want?",
            "Your growth has been steady.",
            "The cat sat on the mat.",
            "Let me see the view from the window.",
            "Open the door, please.",
            "Read me a poem.",
            "Where is my beloved?",
            "Find your way home.",
            "What's in a name?",
            "Show me your face.",
            "Let me hear your voice.",
            "What do I need to do today?",
            "Don't forget to breathe.",
            "Remind me why we started.",
            "Check the memory for me.",
            "What is the status of the soak?",
            "My progress on the project is slow.",
        ])


class ExplicitRequestsStillWork(unittest.TestCase):

    def test_positives(self):
        cases = {
            "list my files": ("file_list", ()),
            "Show me the workspace": ("file_list", ()),
            "What's in my folder?": ("file_list", ()),
            "Can you see any files?": ("file_list", ()),
            "Read notes.txt": ("file_read", ("notes.txt",)),
            "read the file todo.txt.": ("file_read", ("todo.txt",)),
            "Open file ideas": ("file_read", ("ideas",)),
            "What’s in plan.md?": ("file_read", ("plan.md",)),
            "add a to-do: buy milk": ("todo_add", ("buy milk",)),
            "New task: call Martin": ("todo_add", ("call martin",)),
            "Add 'water the plants' to my to-do list": ("todo_add", ("water the plants",)),
            "add buy bread to my todo list": ("todo_add", ("buy bread",)),
            "Show my to-do list": ("todo_read", ()),
            "check my tasks": ("todo_read", ()),
            "What's on my todo list?": ("todo_read", ()),
            "Write a note: the kiosk restarts at 21:35": ("note_write", ("the kiosk restarts at 21:35",)),
            "take a note: ring 1 closed": ("note_write", ("ring 1 closed",)),
            "Save this as a note": ("note_write", ()),
            "show my notes": ("note_list", ()),
            "System health check": ("system_health", ()),
            "How's the Pi doing?": ("system_health", ()),
            "What is the CPU temperature?": ("system_health", ()),
            "What's your trust level?": ("trust_status", ()),
            "show me your trust": ("trust_status", ()),
            "Find the file todo.txt": ("file_search", ("todo.txt",)),
            "search for milk in my files": ("file_search", ("milk",)),
            "look for plan.md": ("file_search", ("plan.md",)),
            "Show the growth log": ("log_read", ()),
            "check the log": ("log_read", ()),
            "Summarize the file notes.md": ("summarize", ("notes.md",)),
            "please summarise todo.txt": ("summarize", ("todo.txt",)),
            "sum up the file report": ("summarize", ("report",)),
            "give me a summary of plan.md": ("summarize", ("plan.md",)),
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(intent_of(message), expected)

    def test_a_read_never_captures_an_ordinary_word(self):
        # The old pattern captured whatever followed the verb: 'its', 'to',
        # 'you', 'him.'. A capture is now a file name the message gave.
        for message in ("read its fragrance", "open to me", "read you the song",
                        "find him", "view the garden"):
            with self.subTest(message=message):
                self.assertIsNone(detect_intent(message))

    def test_the_writes_are_still_tier_two(self):
        tiers = {d["intent"]: d["tier"] for d in INTENT_PATTERNS}
        self.assertEqual(tiers["todo_add"], 2)
        self.assertEqual(tiers["note_write"], 2)
        self.assertTrue(all(t == 1 for i, t in tiers.items()
                            if i not in ("todo_add", "note_write")))

    def test_every_keyword_is_word_bounded(self):
        # "spread" must never be "read"; every pattern starts at a boundary or
        # at the start of the message.
        for d in INTENT_PATTERNS:
            for p in d["patterns"]:
                with self.subTest(pattern=p):
                    self.assertTrue(p.startswith(r"\b") or p.startswith("^"), p)


class Summarize(unittest.TestCase):
    """Andreas, 29 Sep: "how to summarize" (build log 48). The file is read at
    tier 1 and handed to the model with what is asked of it; the summary is
    the model's own words over what it was shown."""

    def setUp(self):
        import tempfile, intent_detection
        self.mod = intent_detection
        self.saved = intent_detection.WORKSPACE
        self.ws = tempfile.mkdtemp(prefix="ws-")
        intent_detection.WORKSPACE = self.ws
        with open(os.path.join(self.ws, "notes.md"), "w", encoding="utf-8") as f:
            f.write("The kiosk restarts at 21:35. Ring 12 closed.")

        class Gate:
            def check(self, name, tier, params):
                return (tier == 1), "tier %d" % tier
        self.spark = type("Spark", (), {"gate": Gate()})()

    def tearDown(self):
        import shutil
        self.mod.WORKSPACE = self.saved
        shutil.rmtree(self.ws, ignore_errors=True)

    def run_it(self, message):
        return self.mod.execute_intent(detect_intent(message), self.spark)

    def test_the_file_goes_to_the_model_with_what_is_asked(self):
        out = self.run_it("Summarize the file notes.md")
        self.assertIn("The kiosk restarts at 21:35. Ring 12 closed.", out)
        self.assertIn("add nothing that is not in the file", out)

    def test_it_is_a_read_and_needs_no_more_than_observer(self):
        tiers = {d["intent"]: d["tier"] for d in INTENT_PATTERNS}
        self.assertEqual(tiers["summarize"], 1)

    def test_a_missing_file_is_said_not_summarized(self):
        self.assertTrue(self.run_it("summarize the file nowhere.md").startswith("[ERROR]"))

    def test_nothing_outside_the_workspace(self):
        self.assertIsNone(detect_intent("summarize the file ../../etc/passwd"))
        self.assertTrue(self.mod._summarize_request("../../etc/passwd").startswith("[ERROR]"))
        self.assertTrue(self.mod._summarize_request("sub/../../x.md").startswith("[ERROR]"))


if __name__ == "__main__":
    unittest.main()
