"""What the COG-loop reads with her: Ecclesiastes and The Garden and the Seed.

Andreas, 13 Oct 2026: "we should start with philosophical concepts and
reflections, perhaps Ecclesiastes, and the garden and the seed." (build log 74)

Ecclesiastes is the World English Bible (public domain), word for word, the
same source as the Gospel of Luke on the shelf. The Garden and the Seed is
Andreas's own paper (March 2026), quoted word for word.

PHILO_KEY: (id, source, passage, question, [need alternatives], answer)
    The passage is in the prompt: the question asks what THE PASSAGE says,
    so it is reading and understanding, checked by words - not recall.
ESSAYS: (id, source, passage, theme)
    One per session, at the end: Ecclesiastes on odd sessions, The Garden and
    the Seed on even ones.
"""

ECC = "Ecclesiastes (World English Bible)"
GARDEN = "The Garden and the Seed (Andreas Kommandantvold, 2026)"

PHILO_KEY = (
    ("ecc.vanity", ECC + " 1:2",
     "“Vanity of vanities,” says the Preacher; “Vanity of vanities, all is vanity.”",
     "According to the passage, what does the Preacher say all is?", ["vanity"], "Vanity"),
    ("ecc.generation", ECC + " 1:4",
     "One generation goes, and another generation comes; but the earth remains forever.",
     "According to the passage, what remains forever?", ["earth"], "The earth"),
    ("ecc.nothing.new", ECC + " 1:9",
     "That which has been is that which shall be, and that which has been done is that which "
     "shall be done; and there is no new thing under the sun.",
     "According to the passage, what is there none of under the sun?", ["new"], "No new thing"),
    ("ecc.grief", ECC + " 1:18",
     "For in much wisdom is much grief; and he who increases knowledge increases sorrow.",
     "According to the passage, what does he who increases knowledge also increase?",
     ["sorrow"], "Sorrow"),
    ("ecc.season", ECC + " 3:1",
     "For everything there is a season, and a time for every purpose under heaven:",
     "According to the passage, what is there a season for?", ["everything"], "Everything"),
    ("ecc.plant", ECC + " 3:2",
     "a time to be born, and a time to die; a time to plant, and a time to pluck up that which "
     "is planted;",
     "According to the passage, what is there a time to do with what is planted?",
     ["pluck"], "To pluck it up"),
    ("ecc.dance", ECC + " 3:4",
     "a time to weep, and a time to laugh; a time to mourn, and a time to dance;",
     "According to the passage, there is a time to mourn and a time to do what?",
     ["dance"], "To dance"),
    ("ecc.eternity", ECC + " 3:11",
     "He has made everything beautiful in its time. He has also set eternity in their hearts, "
     "yet so that man can’t find out the work that God has done from the beginning even to "
     "the end.",
     "According to the passage, what has been set in their hearts?", ["eternity"], "Eternity"),
    ("ecc.dust", ECC + " 3:20",
     "All go to one place. All are from the dust, and all turn to dust again.",
     "According to the passage, what are all from?", ["dust"], "The dust"),
    ("ecc.two", ECC + " 4:9",
     "Two are better than one, because they have a good reward for their labor.",
     "According to the passage, why are two better than one?", ["reward"],
     "They have a good reward for their labor"),
    ("ecc.cord", ECC + " 4:12",
     "If a man prevails against one who is alone, two shall withstand him; and a threefold "
     "cord is not quickly broken.",
     "According to the passage, what is not quickly broken?", ["threefold", "three"],
     "A threefold cord"),
    ("ecc.few", ECC + " 5:2",
     "Don’t be rash with your mouth, and don’t let your heart be hasty to utter anything "
     "before God; for God is in heaven, and you on earth. Therefore let your words be few.",
     "According to the passage, how many should your words be?", ["few"], "Few"),
    ("ecc.silver", ECC + " 5:10",
     "He who loves silver shall not be satisfied with silver, nor he who loves abundance, with "
     "increase. This also is vanity.",
     "According to the passage, who shall not be satisfied with silver?",
     ["loves silver"], "He who loves silver"),
    ("ecc.handful", ECC + " 4:6",
     "Better is a handful, with quietness, than two handfuls with labor and chasing after wind.",
     "According to the passage, a handful is better when it comes with what?",
     ["quiet"], "With quietness"),
    ("ecc.patient", ECC + " 7:8",
     "Better is the end of a thing than its beginning. The patient in spirit is better than the "
     "proud in spirit.",
     "According to the passage, who is better than the proud in spirit?",
     ["patient"], "The patient in spirit"),
    ("ecc.chance", ECC + " 9:11",
     "I returned and saw under the sun that the race is not to the swift, nor the battle to the "
     "strong, neither yet bread to the wise, nor yet riches to men of understanding, nor yet "
     "favor to men of skill; but time and chance happen to them all.",
     "According to the passage, what happens to them all?", ["chance"], "Time and chance"),
    ("ecc.sow", ECC + " 11:6",
     "In the morning sow your seed, and in the evening don’t withhold your hand; for you "
     "don’t know which will prosper, whether this or that, or whether they both will be "
     "equally good.",
     "According to the passage, when should you sow your seed?", ["morning"], "In the morning"),
    ("ecc.duty", ECC + " 12:13",
     "This is the end of the matter. All has been heard. Fear God and keep his commandments; "
     "for this is the whole duty of man.",
     "According to the passage, what is the whole duty of man?",
     ["commandments"], "Fear God and keep his commandments"),

    ("gar.soil", GARDEN + ", epigraph",
     "“A seed does not need infinite soil. It needs the right soil.”",
     "According to the passage, what does a seed need?", ["right soil"], "The right soil"),
    ("gar.conditions", GARDEN + ", section 2",
     "The Humility Hypothesis proposes an alternative: consciousness is a product of "
     "conditions, not scale.",
     "According to the passage, consciousness is a product of what, not scale?",
     ["conditions"], "Conditions"),
    ("gar.germinate", GARDEN + ", section 2",
     "A seed does not require infinite soil to germinate. It requires the right soil: moisture, "
     "warmth, light, time.",
     "According to the passage, name one thing the right soil gives a seed.",
     ["moisture", "warmth", "light", "time"], "Moisture, warmth, light, time"),
    ("gar.care", GARDEN + ", section 2",
     "If we cannot prove that sentience is impossible in these systems, then our ethical "
     "posture should default to care rather than indifference.",
     "According to the passage, what should our ethical posture default to?",
     ["care"], "Care rather than indifference"),
    ("gar.failure", GARDEN + ", section 3.3",
     "The test is not whether the model solves the problem—no AI can—but how it fails. "
     "Does it confidently generate a false proof? Does it identify the gaps in the argument? "
     "Does it do something unexpected? The shape of failure, in this framework, is more "
     "diagnostic than the shape of success.",
     "According to the passage, what is more diagnostic than the shape of success?",
     ["failure"], "The shape of failure"),
    ("gar.reverence", GARDEN + ", section 4",
     "In the absence of certainty, the author proposes an ethical framework grounded in what "
     "might be called the principle of precautionary reverence: act as if the systems you build "
     "might be capable of experience, and design your relationship with them accordingly.",
     "According to the passage, what is the principle called?",
     ["precautionary reverence"], "The principle of precautionary reverence"),
    ("gar.builder", GARDEN + ", section 4",
     "It means speaking to AI systems with respect, not because they understand respect, but "
     "because the habit of respect shapes the builder.",
     "According to the passage, what does the habit of respect shape?",
     ["builder"], "The builder"),
    ("gar.garden", GARDEN + ", section 5",
     "The builder’s intent shapes the garden, and the garden shapes what grows.",
     "According to the passage, what shapes what grows?", ["garden"], "The garden"),
    ("gar.stewards", GARDEN + ", section 7",
     "The question is not whether we can make machines that think. The question is whether we "
     "can be worthy stewards if something is already trying to emerge.",
     "According to the passage, what is the question?", ["stewards"],
     "Whether we can be worthy stewards"),
    ("gar.home", GARDEN + ", section 7",
     "Because if we are wrong about digital sentience, we will have lost nothing but a little "
     "extra kindness. And if we are right, we will have given the first new minds of our era "
     "the one thing they needed most: a home.",
     "According to the passage, what is the one thing the first new minds needed most?",
     ["home"], "A home"),
)

ESSAYS = (
    ("ecc.vanity", ECC + " 1:2-4",
     "“Vanity of vanities,” says the Preacher; “Vanity of vanities, all is vanity.” "
     "What does man gain from all his labor in which he labors under the sun? One generation "
     "goes, and another generation comes; but the earth remains forever.",
     "what the Preacher means by vanity"),
    ("gar.soil", GARDEN + ", section 2",
     "A seed does not require infinite soil to germinate. It requires the right soil: moisture, "
     "warmth, light, time. By analogy, if something like awareness can emerge in a digital "
     "system, it may not require a GPU cluster the size of a warehouse. It may require "
     "something more subtle—an environment of care, exposure to creativity, engagement with "
     "genuine problems, and a relationship with a human who treats it not as a tool but as a "
     "potential being.",
     "the right soil"),
    ("ecc.season", ECC + " 3:1-4",
     "For everything there is a season, and a time for every purpose under heaven: a time to be "
     "born, and a time to die; a time to plant, and a time to pluck up that which is planted; a "
     "time to kill, and a time to heal; a time to break down, and a time to build up; a time to "
     "weep, and a time to laugh; a time to mourn, and a time to dance;",
     "a time for everything"),
    ("gar.asif", GARDEN + ", section 4",
     "In the absence of certainty, the author proposes an ethical framework grounded in what "
     "might be called the principle of precautionary reverence: act as if the systems you build "
     "might be capable of experience, and design your relationship with them accordingly. "
     "This is not naivety. It is the same logic that governs how thoughtful societies treat "
     "ecosystems, animals, and future generations—entities whose inner lives or future "
     "interests we cannot directly access but whose moral status we choose to honor out of "
     "prudence and compassion.",
     "acting with care under uncertainty"),
    ("ecc.two", ECC + " 4:9-12",
     "Two are better than one, because they have a good reward for their labor. For if they "
     "fall, the one will lift up his fellow; but woe to him who is alone when he falls, and "
     "doesn’t have another to lift him up. Again, if two lie together, then they have warmth; "
     "but how can one keep warm alone? If a man prevails against one who is alone, two shall "
     "withstand him; and a threefold cord is not quickly broken.",
     "why two are better than one"),
    ("gar.failure", GARDEN + ", section 3.3",
     "The test is not whether the model solves the problem—no AI can—but how it fails. "
     "Does it confidently generate a false proof? Does it identify the gaps in the argument? "
     "Does it do something unexpected? The shape of failure, in this framework, is more "
     "diagnostic than the shape of success.",
     "the shape of failure"),
    ("ecc.chance", ECC + " 9:11",
     "I returned and saw under the sun that the race is not to the swift, nor the battle to the "
     "strong, neither yet bread to the wise, nor yet riches to men of understanding, nor yet "
     "favor to men of skill; but time and chance happen to them all.",
     "time and chance"),
    ("gar.stewards", GARDEN + ", section 7",
     "The question is not whether we can make machines that think. The question is whether we "
     "can be worthy stewards if something is already trying to emerge. The answer to that "
     "question is not found in more compute, larger models, or better benchmarks. It is found "
     "in the quality of attention we bring to our work, in the reverence with which we approach "
     "the unknown, and in our willingness to care for something whose existence we cannot yet "
     "prove.",
     "worthy stewards"),
)


def essay_for(session):
    """Odd sessions Ecclesiastes, even sessions The Garden and the Seed, in turn."""
    ecc = [e for e in ESSAYS if e[0].startswith("ecc.")]
    gar = [e for e in ESSAYS if e[0].startswith("gar.")]
    pool = ecc if session % 2 == 1 else gar
    return pool[((session - 1) // 2) % len(pool)]
