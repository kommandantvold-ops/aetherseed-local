"""Build logs 57 to 59: the library - a passage word for word, or nothing.

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

    def test_a_word_that_carries_nothing_in_any_form(self):
        # build log 58, from her real traffic: the index reads "thats" as "that"
        self.assertEqual(L.terms("thats great, tell me more"), ["great"])
        self.assertEqual(L.terms("What are the things I needed?"), [])

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

    def test_look_it_up_is_said_after_an_answer(self):
        for t in ("look it up", "Look it up!", "yes, look it up please", "slå det opp"):
            with self.subTest(t=t):
                self.assertTrue(L.says_look_it_up(t))
        for t in ("look up bleach", "look it up in the dictionary for me", "look", "it"):
            with self.subTest(t=t):
                self.assertFalse(L.says_look_it_up(t))
        self.assertIsNone(L.lookup_query("look it up"))          # not "look up <it>"

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

    def test_not_sure_but_one_passage_says_it_all(self):
        # build log 59: the line under her own answer, "not from the library"
        q = "Where is a cool dry place?"
        self.assertIsNone(self.lib.find(q))
        self.assertTrue(self.lib.says_it_all(q))
        for q in ("A cool dry place",                          # not asked
                  "Is your place cool and dry?",                # about her
                  "Is the capital of France dry?",              # no passage says it all
                  "I keep it in a cool dry place"):             # told, not asked
            with self.subTest(q=q):
                self.assertFalse(self.lib.says_it_all(q))

    def test_no_library_no_answer(self):
        empty = tempfile.mkdtemp(prefix="nolib-")
        try:
            lib = L.Library(empty)
            self.assertFalse(lib)
            self.assertIsNone(lib.find("What is the maximum dose of paracetamol?"))
            self.assertEqual(L.nothing("x", lib.holds()), "I have no library on this unit.")
        finally:
            shutil.rmtree(empty, ignore_errors=True)


class DisasterPagesAndManuals(unittest.TestCase):
    """Build log 58: pages named in the plural, and manuals of hundreds of
    pages under their own headings."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="library58-")
        make(os.path.join(cls.dir, "ready.lib.sqlite"), "site", "Ready", "2024-12-03", [
            ("Hurricanes", "", [
                ("Hurricanes", "", "Hurricanes are dangerous and can cause major damage."),
                ("Prepare for Hurricanes", "", "Know your evacuation zone. Prepare a kit."),
                ("Stay Safe During a Hurricane", "", "Stay away from windows.")]),
            ("Earthquakes", "", [
                ("Earthquakes", "", "An earthquake is a sudden shaking of the ground."),
                ("Stay Safe During", "", "Drop, cover and hold on during an earthquake.")]),
            ("Games", "", [("Games", "", "These games test what children know. Play them at school.")]),
            ("Recovering from Disaster", "", [
                ("If you have insurance, contact your insurance agent to file a claim.", "",
                 "Take photos and make a list of the damage before you clean up.")]),
            ("How and when to use fusidic acid", "", [
                ("Important: Fire warning", "", "The cream can build up on clothes and bedding "
                 "and make them more likely to catch fire.")]),
        ] + filler(120, "disaster"))
        cold = [("", "page %d" % i, "Keep moving and keep dry on the march, lesson %d. Build "
                 "nothing where the wind can reach it." % i) for i in range(1, 150)]
        cold[20] = ("FROSTBITE", "page 21", "Treat frostbite by warming the part against the body. "
                    "Do not rub it.")
        cold[40] = ("SNOW CAVE", "page 41", "Dig into a drift at least eight feet deep. Keep the "
                    "entrance lower than the sleeping bench.")
        cold[60] = ("LOCATING THE NORTH STAR", "page 61", "Follow the two pointer stars of the "
                    "Big Dipper.")
        cold[80] = ("SPRING POLE", "page 81", "A bent sapling lifts the snare when it is tripped.")
        cold[100] = ("FIRES: Building the Fire", "page 101", "Lay tinder, then kindling, then fuel.")
        cold[110] = ("3-6. BUILDING ARCTIC TENTS", "page 111", "Pitch the tent with its door away "
                     "from the wind, in the shelter of the trees, and bank snow on the skirt.")
        cold[120] = ("COOKING OF MEATS", "page 121", "Store jerky wrapped in dry clothes or cloth.")
        make(os.path.join(cls.dir, "manuals.lib.sqlite"), "documents", "Field manuals", "2026-10-04", [
            ("Soldier's Handbook for Operations in Cold-Weather Areas (1986)", "US Army", cold)])
        cls.lib = L.Library(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_a_word_is_the_word_the_index_keeps(self):
        for a, b in (("hurricanes", "hurricane"), ("earthquakes", "earthquake"),
                     ("floods", "flood"), ("preparing", "prepare"), ("FILES", "file")):
            self.assertEqual(L.stem(a), L.stem(b))

    def test_a_page_named_in_the_plural(self):
        hit = self.lib.find("How do I prepare for a hurricane?")
        self.assertEqual((hit["title"], hit["heading"]), ("Hurricanes", "Prepare for Hurricanes"))
        hit = self.lib.find("What should I do during an earthquake?")
        self.assertEqual((hit["title"], hit["heading"]), ("Earthquakes", "Stay Safe During"))

    def test_a_heading_the_question_says(self):
        # nothing under "SNOW CAVE" says "build"; the manual does
        hit = self.lib.find("How do I build a snow cave?")
        self.assertEqual((hit["heading"], hit["place"]), ("SNOW CAVE", "page 41"))

    def test_a_rare_word_over_a_section(self):
        hit = self.lib.find("How do I treat frostbite?")
        self.assertEqual(hit["heading"], "FROSTBITE")
        self.assertTrue(hit["text"].startswith("Treat frostbite by warming"))

    def test_a_lesser_heading_is_a_heading_of_its_own(self):
        hit = self.lib.find("How do I build a fire?")
        # two words of "Building the Fire", against one of a medicine's "Fire warning"
        self.assertEqual((hit["heading"], hit["place"]), ("FIRES: Building the Fire", "page 101"))

    def test_a_word_among_several_in_a_heading_is_not_its_subject(self):
        # "3-6. BUILDING ARCTIC TENTS" says "build", and its text "snow" and "shelter"
        self.assertIsNone(self.lib.find("How do I build a snow shelter?"))

    def test_a_handbook_is_not_about_its_title_on_every_page(self):
        # "store" and "clothes" stand together on page 121 of a cold-weather handbook
        self.assertIsNone(self.lib.find("How do I store my cold-weather clothes?"))

    def test_what_it_leaves_alone(self):
        for q in ("What is the weather like?",       # a word of a long title is not its subject
                  "list my files",                   # a word in a heading that is a sentence
                  "Let's play a game",               # a proposal to her, not a question
                  "thats great, tell me more",       # "thats" is "that"; "FROSTBITE" is not "great"
                  "Where is the north pole?",        # two headings, one word each
                  "How do I treat a burn?"):         # a word it lacks
            with self.subTest(q=q):
                self.assertIsNone(self.lib.find(q))


class AskedTheBestThereIs(Lib):

    def test_the_best_passage(self):
        hit = self.lib.look_up("paracetamol for adults")
        self.assertEqual(hit["title"], "How and when to take paracetamol for adults")

    def test_between_collections_the_one_that_says_more_about_it(self):
        self.assertEqual(self.lib.look_up("bleach")["collection_id"], "water")

    def test_a_passage_with_something_to_read(self):
        # build log 59: the shortest passage that says the word ranks first -
        # "look up frostbite" was shown one sentence on its third degree
        d = tempfile.mkdtemp(prefix="library-read-")
        try:
            long = ("Determine whether the frostbite is superficial or deep. " * 5).strip()
            make(os.path.join(d, "cold.lib.sqlite"), "documents", "Cold", "2026-10-04", [
                ("Cold injuries", "", [
                    ("THIRD-DEGREE FROSTBITE", "page 1", "Third-degree frostbite is deep."),
                    ("TREATMENT FOR FROSTBITE", "page 2", long),
                    ("TRENCH FOOT", "page 3", "Keep the feet dry and change socks often.")])])
            lib = L.Library(d)
            self.assertEqual(lib.look_up("frostbite")["heading"], "TREATMENT FOR FROSTBITE")
            # with nothing longer to show, the short one is still shown
            self.assertEqual(lib.look_up("trench foot")["heading"], "TRENCH FOOT")
        finally:
            shutil.rmtree(d, ignore_errors=True)

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
            "Purifying by boiling\nIf your tap water is unsafe, boiling is the best method to "
            "kill organisms.",
            "Bring the water to a rolling boil for at least one full minute."])

    def test_the_rows_of_a_list_stay_rows(self):
        # joined into one sentence, "1 gallon" loses its "1/4 teaspoon"
        text = ("The following is a list of the tent group for an infantry squad, which is\n"
                "carried on the sled:\n1 Ten-man tent with liner\n1 Yukon stove\n"
                "2 Five-gallon gasoline cans (one with white gasoline per platoon)\n1 Hatchet\n")
        self.assertEqual(lb.page_paragraphs(text), [
            "The following is a list of the tent group for an infantry squad, which is "
            "carried on the sled:\n1 Ten-man tent with liner\n1 Yukon stove\n"
            "2 Five-gallon gasoline cans (one with white gasoline per platoon)\n1 Hatchet"])

    def test_headings_in_a_pdf(self):
        for line in ("DETERMINING THE DISTANCE", "3-2. TENT GROUP EQUIPMENT", "CHAPTER 3",
                     "Chapter 18", "SNOW TRENCH", "APPENDIX B"):
            with self.subTest(line=line):
                self.assertTrue(lb.heading_line(line))
        for line in ("Figure 19-7. Body Signals", "WSVX.02.04", "TC 21-3", "12",
                     "NOTE: Always check the scale on your map", "You can use your map.",
                     "DO NOT WALK, SWIM OR DRIVE THROUGH FLOOD WATERS.", "Graphic (Bar) Scale Method"):
            with self.subTest(line=line):
                self.assertFalse(lb.heading_line(line))

    def test_a_document_under_its_headings_without_its_running_heads(self):
        pages = [(n, "TC 21-3\n\n%s\n\nBody of page %d, long enough to be worth keeping here.\n\n%d\n"
                  % ("CHAPTER 3\n\nTents and Heating Equipment\n\n3-1. GENERAL" if n == 2 else "", n, n))
                 for n in range(1, 9)]
        out = lb.document_passages(pages)
        self.assertEqual(out[0], ("", "page 1", "Body of page 1, long enough to be worth keeping here."))
        self.assertEqual(out[1], ("3-1. GENERAL", "page 2",
                                  "Body of page 2, long enough to be worth keeping here."))
        self.assertEqual(out[2][0], "3-1. GENERAL")               # the heading carries on
        self.assertFalse(any("TC 21-3" in t for _, _, t in out))  # the running head is gone

    def test_a_row_that_is_only_a_link_is_the_sites_way_around_itself(self):
        # build log 58: "look up flooding" was shown the language menu
        page = """<html lang="en"><head><title>Floods</title></head><body><main><h1>Floods</h1>
        <ul><li><span><a href="fr/floods">Français</a></span></li>
        <li><span><a href="ht/floods">Kreyòl</a></span></li></ul>
        <a href="#during"><p>During a flood</p></a>
        <p>Flooding is common. <a href="more">Read more</a></p>
        <h2><a href="#during">During</a></h2><ul><li>Move to higher ground.</li></ul>
        </main></body></html>"""
        self.assertEqual(lb.page_sections(page)[1], [
            ("Floods", ["Flooding is common. Read more"]),
            ("During", ["- Move to higher ground."])])         # a heading may be a link

    def test_a_handbook_typed_without_blank_lines(self):
        # build log 58: "UNITED STATES MARINE CORPS" headed 532 passages
        text = ("UNITED STATES MARINE CORPS\nMountain Warfare Training Center\nSTUDENT HANDOUT\n"
                "SURVIVAL SHELTERS\nOUTLINE\n"
                "1. REQUIREMENTS. Any shelter must keep out the wind and the wet, whatever it is made of.\n"
                "c. Snow Cave. A snow cave shelters one to sixteen men for long periods of time.\n"
                "(a) Dig down into the snow until the tunnel entrance has been reached.\n"
                "b. Angry outbursts.\n")
        kinds = [(k, t.split("\n")[0][:34]) for k, t in lb.page_blocks(text)]
        self.assertEqual(kinds, [
            ("h", "UNITED STATES MARINE CORPS"), ("p", "Mountain Warfare Training Center"),
            ("h", "STUDENT HANDOUT"), ("h", "SURVIVAL SHELTERS"), ("h", "OUTLINE"),
            ("h", "REQUIREMENTS"), ("p", "1. REQUIREMENTS. Any shelter must "),
            ("m", "Snow Cave"), ("p", "c. Snow Cave. A snow cave shelters")])
        self.assertIn("b. Angry outbursts.", lb.page_blocks(text)[-1][1])   # a row, not a heading

    def test_a_bullet_on_a_line_of_its_own_says_nothing(self):
        text = "The following helps prevent trench foot:\n\uf0b7\n\uf0b7\nChange to dry socks twice daily.\n• Keep the feet dry.\n"
        self.assertEqual(lb.page_paragraphs(text), [
            "The following helps prevent trench foot: Change to dry socks twice daily.\n- Keep the feet dry."])

    def test_a_table_of_contents_answers_nothing(self):
        text = ("CONTENTS\n\nHEAT STROKE .................................... 11-1\n"
                "FROSTBITE ...................................... 12-4\n\nThe body follows here.\n")
        self.assertEqual(lb.page_blocks(text), [("h", "CONTENTS"), ("p", "The body follows here.")])
        self.assertFalse(lb.heading_line("HEAT STROKE ............ 11-1"))

    def test_a_lesson_under_its_own_headings(self):
        head = "UNITED STATES MARINE CORPS\nMountain Warfare Training Center\n"
        foot = "\nWSVX 02.04\n"
        body = {
            1: "STUDENT HANDOUT\nSURVIVAL SHELTERS\nENABLING LEARNING OBJECTIVES\n"
               "(1) Without the aid of references, construct a snow cave, in accordance with the references.\n"
               "OUTLINE\n1. MAN-MADE SHELTERS. Many configurations of man-made shelters may be used.\n"
               "b. Snow Cave. A snow cave is used to shelter one to sixteen men for long periods.\n",
            2: "(a) Dig down into the snow until the desired tunnel entrance has been reached.\n"
               "SNOW CAVE\n"
               "c. Tree-pit Snow Shelter. A tree-pit snow shelter is designed for one to three men.\n",
        }
        pages = [(n, head + body.get(n, "More of the lesson stands on page %d of the handbook.\n" % n) + foot)
                 for n in range(1, 8)]
        out = lb.document_passages(pages, skip_under=["ENABLING LEARNING OBJECTIVE"],
                                   not_headings=["OUTLINE", "STUDENT HANDOUT"])
        headings = [h for h, _, _ in out]
        self.assertEqual(headings[:4], ["MAN-MADE SHELTERS", "MAN-MADE SHELTERS: Snow Cave",
                                        "MAN-MADE SHELTERS: Snow Cave",          # carried to page 2
                                        "MAN-MADE SHELTERS: Tree-pit Snow Shelter"])
        text = "\n".join(t for _, _, t in out)
        self.assertNotIn("MARINE CORPS", text)                    # the running head
        self.assertNotIn("WSVX 02.04", text)                      # the running foot
        self.assertNotIn("Without the aid of references", text)   # the objectives
        self.assertNotIn("SNOW CAVE: Tree-pit", " ".join(headings))   # a caption is not a heading

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
        proxy.ProxyHandler._library_asked.update(q=None, at=0.0)

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

    def test_a_what_if_is_a_question_not_a_story(self):
        reply = self._served("What if I take too much ibuprofen?")
        self.assertIn("Taking too much ibuprofen by mouth can be dangerous.", reply)

    def test_a_shared_word_in_what_she_was_told_does_not_take_it_away(self):
        # on Lyra a verse of Genesis saying "children" sent an aspirin
        # question to the model
        saved = proxy.root._fact_lines
        proxy.root._fact_lines = lambda q, report=None: ["[Steward told you] bleach is under the sink"]
        try:
            self.assertIn(BLEACH, self._served("How much bleach do I add to a gallon of water?"))
        finally:
            proxy.root._fact_lines = saved

    def test_her_own_answer_says_it_is_not_from_the_library(self):
        # build log 59: one passage says every word of the question, the
        # library is not sure - she answers, and the tag says where from
        n = len(SCRIPT["requests"])
        before = len(proxy.root.store.get_all_episodes())
        _, reply, meta = self.ask("Where is a cool dry place?")
        self.assertGreater(len(SCRIPT["requests"]), n, "the model answers")
        self.assertTrue(meta["library_line"])
        self.assertNotIn("library", reply.lower())               # the line is not in her words
        after = proxy.root.store.get_all_episodes()
        self.assertEqual(len(after), before + 1)
        self.assertFalse(any("look it up" in str(e) for e in after))   # nor in her memory
        # ... and "look it up" asks the library the same question
        shown = self._served("look it up")
        self.assertIn("From the library, word for word:", shown)
        self.assertIn("cool dry place", shown)
        # once shown, nothing is waiting: the next "look it up" is hers
        n = len(SCRIPT["requests"])
        self.ask("look it up")
        self.assertGreater(len(SCRIPT["requests"]), n)

    def test_no_line_where_no_passage_says_it(self):
        for q in ("hello", "What is Mustardseed?", "Good night"):
            with self.subTest(q=q):
                _, _, meta = self.ask(q)
                self.assertFalse(meta.get("library_line"))

    def test_look_it_up_with_nothing_asked_finds_nothing_or_is_hers(self):
        n = len(SCRIPT["requests"])
        self.ask("look it up")                                   # nothing waiting: hers
        self.assertGreater(len(SCRIPT["requests"]), n)
        self.ask("hello")                                        # she answers; no passage on it
        self.assertIn("The library has nothing I can show for that.", self._served("look it up"))

    def test_a_unit_without_a_library_is_as_it_was(self):
        L._LIB = L.Library(os.path.join(Lib.dir, "no-such-dir"))
        n = len(SCRIPT["requests"])
        self.ask("How much bleach do I add to a gallon of water?")
        self.assertGreater(len(SCRIPT["requests"]), n)
        self.ask("look up bleach")
        self.assertGreater(len(SCRIPT["requests"]), n + 1)


if __name__ == "__main__":
    unittest.main()
