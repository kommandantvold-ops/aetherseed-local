"""Build log 57: the library - a passage word for word, or nothing.

Andreas, 4 Oct 2026: "A library she answers from with a knowledge base like
that of nomad (content) so it can be a disaster relief and offgrid rural
survival aid." Passages shown word for word, not retold: "Yes! Perfect!"

The collections here are made in the test, with the converter's own schema;
the real ones are measured by training/library_check.py.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))
import library_build as lb  # noqa: E402
from logic import library as L  # noqa: E402

DOSE = ("Adults can take two 500mg tablets, 4 times in 24 hours. You must wait at least "
        "4 hours between doses. The maximum is eight 500mg tablets in 24 hours.")
ALCOHOL = "Do not drink alcohol while you're taking metronidazole, including the 2 days after."
BLEACH = ("Purifying by adding liquid chlorine bleach. Add the amount of bleach according to "
          "the table below.\n1 gallon\n1/4 teaspoon\n5 gallons\n1 teaspoon")


def make(path, kind, title, date, docs):
    """docs: [(doc title, author, [(heading, place, text), ...]), ...]"""
    db = sqlite3.connect(path)
    db.executescript(lb.SCHEMA)
    n = 0
    for dtitle, author, passages in docs:
        cur = db.execute("INSERT INTO docs(title, author, locator) VALUES (?,?,?)",
                         (dtitle, author, dtitle))
        for seq, (heading, place, text) in enumerate(passages, 1):
            lb.add(db, cur.lastrowid, seq, dtitle, heading, place, text)
            n += 1
    meta = {"format": "1", "id": os.path.basename(path).split(".")[0], "title": title,
            "description": "made for a test", "date": date, "kind": kind,
            "licence": "not stated in the source file", "docs": str(len(docs)),
            "passages": str(n)}
    db.executemany("INSERT INTO meta VALUES (?,?)", sorted(meta.items()))
    db.commit()
    db.close()


def filler(n, word):
    """Pages about nothing in particular, so that the words that matter are rare."""
    return [("About another %s" % word, "",
             [("Key facts", "", "This %s page says to keep it in a cool dry place "
               "and to ask a pharmacist when unsure." % word)]) for _ in range(n)]


class Lib(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="library-")
        make(os.path.join(cls.dir, "medicines.lib.sqlite"), "site", "Medicines A to Z", "2025-12-14", [
            ("How and when to take paracetamol for adults", "", [
                ("How and when to take paracetamol for adults", "", "Paracetamol is available as tablets."),
                ("Dosage and strength", "", "The usual dose for adults is either 500mg or 1g."),
                ("Important", "", DOSE),
                ("If you forget to take it", "", "Take it as soon as you remember.")]),
            ("Common questions about metronidazole", "", [
                ("How does metronidazole work?", "", "Metronidazole is an antibiotic."),
                ("Can I drink alcohol while taking metronidazole?", "", ALCOHOL),
                ("Will it affect my driving?", "", "It is safe to drive unless metronidazole "
                 "makes you dizzy. Do not drink and drive.")]),
            ("How and when to take ibuprofen and codeine", "", [
                ("If you take too much", "", "Do not take more than the recommended dose of "
                 "ibuprofen and codeine.")]),
            ("How and when to take ibuprofen for adults", "", [
                ("If you take too much", "", "Taking too much ibuprofen by mouth can be dangerous.")]),
            ("Side effects of melatonin", "", [
                ("Strange dreams or night sweats", "", "Talk to your doctor if the night sweats go on.")]),
        ] + filler(300, "medicine"))
        make(os.path.join(cls.dir, "water.lib.sqlite"), "documents", "Water Treatment Library",
             "2024-08-29", [
            ("Purifying Water During an Emergency", "Washington State Dept of Health", [
                ("", "page 1", "Storing water safely. Store one gallon of water per person per day."),
                ("", "page 2", BLEACH),
                ("", "page 2", "Caution: Bleach will not kill some disease-causing organisms.")]),
            ("Water Treatment", "Various", [
                ("", "page %d" % i, "Clean water matters in every household and school, lesson %d." % i)
                for i in range(1, 40)]),
        ])
        cls.lib = L.Library(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)


class TheWordsOfAQuestion(unittest.TestCase):

    def test_the_words_that_carry_it(self):
        self.assertEqual(L.terms("How much paracetamol can an adult take?"), ["paracetamol", "adult"])
        self.assertEqual(L.terms("What is giardia?"), ["giardia"])
        self.assertEqual(L.terms("Good night"), ["night"])
        self.assertEqual(L.terms("hello"), [])

    def test_every_word_chooses_the_passage(self):
        self.assertEqual(L.all_words("How long does ibuprofen take to work?"),
                         ["long", "ibuprofen", "take", "work"])

    def test_asked_to_look_it_up(self):
        for text, q in (("look up paracetamol for adults", "paracetamol for adults"),
                        ("Look up boiling water.", "boiling water"),
                        ("what does the library say about ibuprofen and pregnancy?", "ibuprofen and pregnancy"),
                        ("search the library for bleach", "bleach"),
                        ("library: giardia", "giardia"),
                        ("Please look up snake bite in the library", "snake bite")):
            with self.subTest(text=text):
                self.assertEqual(L.lookup_query(text), q)
        for text in ("How much paracetamol can an adult take?", "look up", "I looked up at the sky",
                     "What is the library?", ""):
            with self.subTest(text=text):
                self.assertIsNone(L.lookup_query(text))

    def test_asked_what_it_holds(self):
        self.assertTrue(L.asks_contents("What is in the library?"))
        self.assertTrue(L.asks_contents("what does your library hold"))
        self.assertFalse(L.asks_contents("What is a library?"))


class UnaskedOnlyWhenSure(Lib):

    def test_a_dose_from_the_page_that_is_about_it(self):
        hit = self.lib.find("What is the maximum dose of paracetamol in 24 hours?")
        self.assertEqual(hit["title"], "How and when to take paracetamol for adults")
        self.assertEqual(hit["text"], DOSE)                      # word for word

    def test_the_heading_that_says_it_wins_over_the_page_top(self):
        hit = self.lib.find("Is it safe to drink alcohol with metronidazole?")
        self.assertEqual(hit["heading"], "Can I drink alcohol while taking metronidazole?")
        self.assertEqual(hit["text"], ALCOHOL)

    def test_another_medicine_in_the_title_is_another_medicine(self):
        hit = self.lib.find("What if I take too much ibuprofen?")
        self.assertEqual(hit["title"], "How and when to take ibuprofen for adults")

    def test_a_shelf_of_documents_by_title_and_nearness(self):
        hit = self.lib.find("How much bleach do I add to a gallon of water?")
        self.assertEqual(hit["collection_id"], "water")
        self.assertEqual(hit["text"], BLEACH)
        self.assertEqual(hit["place"], "page 2")

    def test_what_it_leaves_alone(self):
        for q in ("Good night",                                   # one common word in a heading
                  "What happened in the beginning?",
                  "What are your rings?", "Where is your workspace?",        # about her
                  "What have I told you about paracetamol?",                 # what she was told
                  "I took a paracetamol this morning",                       # told, not asked
                  "How do I tie a bowline?", "What is the capital of France?",
                  "How much paracetamol can a horse take?",                  # a word it lacks
                  "hello", ""):
            with self.subTest(q=q):
                self.assertIsNone(self.lib.find(q))

    def test_no_library_no_answer(self):
        empty = tempfile.mkdtemp(prefix="nolib-")
        try:
            lib = L.Library(empty)
            self.assertFalse(lib)
            self.assertIsNone(lib.find("What is the maximum dose of paracetamol?"))
            self.assertEqual(L.nothing("x", lib.holds()), "I have no library on this unit.")
        finally:
            shutil.rmtree(empty, ignore_errors=True)


class AskedTheBestThereIs(Lib):

    def test_the_best_passage(self):
        hit = self.lib.look_up("paracetamol for adults")
        self.assertEqual(hit["title"], "How and when to take paracetamol for adults")

    def test_between_collections_the_one_that_says_more_about_it(self):
        self.assertEqual(self.lib.look_up("bleach")["collection_id"], "water")

    def test_nothing_is_said_as_nothing(self):
        self.assertIsNone(self.lib.look_up("how to tie a bowline"))
        self.assertIsNone(self.lib.look_up("snake bite"))
        text = L.nothing("snake bite", self.lib.holds())
        self.assertIn("The library has nothing I can show for that.", text)
        self.assertIn("Medicines A to Z (2025-12)", text)
        self.assertIn("Water Treatment Library (2024-08)", text)

    def test_what_follows(self):
        hit = self.lib.look_up("bleach gallon")
        nxt = self.lib.after(hit)
        self.assertIn("Caution: Bleach will not kill", nxt["text"])
        self.assertIsNone(self.lib.after(nxt))


class OnTheScreen(Lib):

    def test_the_passage_whole_and_its_source(self):
        hit = self.lib.find("How much bleach do I add to a gallon of water?")
        text = L.shown(hit)
        self.assertTrue(text.startswith("From the library, word for word:\n\n"))
        self.assertIn(BLEACH, text)                              # every character of it
        self.assertIn('Source: Water Treatment Library (2024-08) - "Purifying Water During an '
                      'Emergency" - Washington State Dept of Health - page 2', text)
        self.assertIn('Say "more" for what follows it.', text)

    def test_a_site_passage_names_its_heading(self):
        text = L.shown(self.lib.find("Is it safe to drink alcohol with metronidazole?"))
        self.assertIn('Source: Medicines A to Z (2025-12) - "Common questions about metronidazole" '
                      '- Can I drink alcohol while taking metronidazole?', text)

    def test_a_long_passage_says_that_it_goes_on(self):
        hit = dict(self.lib.look_up("bleach gallon"), text="A sentence. " * 200)
        text = L.shown(hit)
        self.assertIn("[the passage goes on]", text)
        self.assertLess(len(text), L.SHOWN_MAX + 400)

    def test_what_it_holds(self):
        text = L.contents(self.lib)
        self.assertIn("Medicines A to Z (2025-12)", text)
        self.assertIn("2 documents, 42 passages", text)
        self.assertIn("305 documents", text)


class TheConverter(unittest.TestCase):

    def test_a_page_under_its_own_headings(self):
        page = """<html><head><title>Common questions about X - NHS</title>
        <script>var a = 'not this';</script></head><body>
        <nav><a href="/">Home</a> Menu not this</nav>
        <main><h1>Common questions about X</h1><p>First <b>words</b>.</p>
        <details><summary><span> How does X work? </span></summary>
        <div><p>It works &amp; it helps.</p><ul><li>one</li><li>two</li></ul></div></details>
        <h2>Dose</h2><table><tr><th>Age</th><th>Dose</th></tr><tr><td>Adult</td><td>500mg</td></tr></table>
        </main><footer>Not this either</footer></body></html>"""
        title, sections = lb.page_sections(page)
        self.assertEqual(title, "Common questions about X - NHS")
        self.assertEqual(sections, [
            ("Common questions about X", ["First words."]),
            ("How does X work?", ["It works & it helps.", "- one", "- two"]),
            ("Dose", ["Age | Dose", "Adult | 500mg"])])

    def test_passages_keep_paragraphs_whole(self):
        paras = ["a" * 400, "b" * 400, "c" * 400, "d" * 50]
        out = lb.passages_from(paras, limit=900, least=200)
        self.assertEqual(out, ["a" * 400 + "\n" + "b" * 400, "c" * 400 + "\n" + "d" * 50])
        long = ("One sentence here. " * 80).strip()
        cut = lb.passages_from([long], limit=900)
        self.assertTrue(all(len(c) <= 900 for c in cut))
        self.assertEqual(" ".join(cut).replace("  ", " "), long)   # nothing lost, nothing added

    def test_a_pdf_page_becomes_paragraphs(self):
        text = ("Purifying by boiling\nIf your tap water is unsafe, boil-\ning is the best "
                "method to kill\norganisms.\n\n12\n\nBring the water to a rolling boil for at "
                "least\none full minute.\n")
        self.assertEqual(lb.page_paragraphs(text), [
            "Purifying by boiling If your tap water is unsafe, boiling is the best method to "
            "kill organisms.",
            "Bring the water to a rolling boil for at least one full minute."])

    def test_the_unit_needs_nothing_but_sqlite(self):
        with open(os.path.join(HERE, "logic", "library.py"), encoding="utf-8") as f:
            code = f.read()
        self.assertNotIn("libzim", code.split('"""', 2)[2])
        self.assertNotIn("pdftotext", code.split('"""', 2)[2])
        self.assertIn("mode=ro", code)                           # opened read-only


import proxy  # noqa: E402
from test_memory_turn import SCRIPT, _Proxy  # noqa: E402


class AtTheProxy(_Proxy):
    """The library answers before the model is asked - or stands down."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Lib.setUpClass()

    @classmethod
    def tearDownClass(cls):
        Lib.tearDownClass()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.saved = L._LIB
        L._LIB = Lib.lib
        proxy.ProxyHandler._library_last.update(hit=None, at=0.0)

    def tearDown(self):
        L._LIB = self.saved
        super().tearDown()

    def _served(self, text):
        n = len(SCRIPT["requests"])
        status, reply, meta = self.ask(text)
        self.assertEqual(status, 200)
        self.assertEqual(len(SCRIPT["requests"]), n, "the model must not be called")
        self.assertEqual(meta["mode"], "library")
        return reply

    def test_a_passage_word_for_word_and_the_model_is_not_called(self):
        reply = self._served("How much bleach do I add to a gallon of water?")
        self.assertIn(BLEACH, reply)
        self.assertIn("Source: Water Treatment Library (2024-08)", reply)

    def test_it_is_not_remembered(self):
        before = len(proxy.root.store.get_all_episodes())
        self._served("How much bleach do I add to a gallon of water?")
        self.assertEqual(len(proxy.root.store.get_all_episodes()), before)
        self.assertFalse(os.path.exists(proxy.PROVENANCE_LOG))

    def test_asked_and_it_has_nothing_she_says_so(self):
        reply = self._served("look up snake bite")
        self.assertIn("The library has nothing I can show for that.", reply)

    def test_more_walks_on_and_ends(self):
        self._served("look up bleach gallon")
        self.assertIn("Caution: Bleach will not kill", self._served("more"))
        self.assertEqual(self._served("more"), "That is the end of that document.")

    def test_more_with_nothing_before_it_is_hers(self):
        n = len(SCRIPT["requests"])
        self.ask("more")
        self.assertGreater(len(SCRIPT["requests"]), n)

    def test_what_it_holds(self):
        self.assertIn("The library on this unit:", self._served("What is in the library?"))

    def test_a_question_about_her_goes_to_her(self):
        for q in ("What is Mustardseed?", "What are your rings?", "Good night", "hello"):
            with self.subTest(q=q):
                n = len(SCRIPT["requests"])
                _, _, meta = self.ask(q)
                self.assertGreater(len(SCRIPT["requests"]), n, "the model answers these")
                self.assertNotEqual(meta.get("mode"), "library")

    def test_a_story_is_not_looked_up(self):
        n = len(SCRIPT["requests"])
        self.ask("Write a story about how much bleach to add to a gallon of water")
        self.assertGreater(len(SCRIPT["requests"]), n)

    def test_a_unit_without_a_library_is_as_it_was(self):
        L._LIB = L.Library(os.path.join(Lib.dir, "no-such-dir"))
        n = len(SCRIPT["requests"])
        self.ask("How much bleach do I add to a gallon of water?")
        self.assertGreater(len(SCRIPT["requests"]), n)
        self.ask("look up bleach")
        self.assertGreater(len(SCRIPT["requests"]), n + 1)


if __name__ == "__main__":
    unittest.main()
