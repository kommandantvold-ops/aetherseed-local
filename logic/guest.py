"""What a guest reaches, and what she says when a guest asks for the rest.

whether a guest's question should be able to
bring back what the steward told her: "A guest should not."

 made every phone that has not signed in a guest (gui/serve.py) and
kept the console's panels and the working memory from it. This is the rest,
in the proxy, for a turn whose speaker is GUEST:

  - her long-term memory: the guest's own turns and the build's curriculum
    ([Known]); no steward turns, no rings, no steward facts
    (aetherroot.retrieve_context, only_speaker);
  - the library: the built-in collections only, never the steward's own
    documents; and "more" and "look it up" follow what THAT guest was shown,
    not the steward's last passage;
  - answered by the unit, model not called, instead of from the steward's
    data: her record (flagged prompts, the steward's words among them), how
    far she trusts someone, her corrections, and the workspace - the to-do
    list, notes and files are the steward's. The exact tools (a sum, a
    count, a comparison) touch nothing of his and stay.

Every one of these is said plainly rather than refused silently, so a guest
knows it was asked for something that is not theirs to read.
"""

TEXTS = {
    "record": {
        "en": "My record is for my steward to read.",
        "nb": "Loggen min er for forvalteren min å lese.",
    },
    "trust": {
        "en": "How far I trust someone is between me and my steward.",
        "nb": "Hvor mye jeg stoler på noen, er mellom meg og forvalteren min.",
    },
    "corrections": {
        "en": "What my steward has corrected in my memory is for my steward to read.",
        "nb": "Det forvalteren min har rettet i minnet mitt, er for forvalteren å lese.",
    },
    "forget": {
        "en": "Only my steward can tell me to forget something.",
        "nb": "Bare forvalteren min kan be meg glemme noe.",
    },
    "workspace": {
        "en": "My steward's to-do list, notes and files are not opened for a guest.",
        "nb": "Forvalterens gjøremålsliste, notater og filer åpnes ikke for en gjest.",
    },
}


def guest_text(kind: str, language: str = "en") -> str:
    texts = TEXTS[kind]
    return texts.get(language) or texts["en"]
