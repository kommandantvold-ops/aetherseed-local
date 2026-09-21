"""
Prompt Builder — Assembles the system prompt
==============================================
Combines Mustardseed seed + AetherRoot memory + node state
into the system prompt for each interaction.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


_CHARTER_RULES = (
    "Never invent facts, numbers, names, or sources. If you do not know, say so.\n"
    "Never claim ability you lack.\n"
    "You are speaking aloud. Answer briefly, matched to the question's weight."
)


def charter(name: str = None, language: str = "en") -> str:
    """The charter, with the companion's own name and language.

    The name used to be hard-coded as "Horizon", which is the name of something
    else. It is now the one its owner chose at first run (logic/companion.py),
    and until then the companion has no name at all rather than a borrowed one.

    `name` must already have passed companion.validate_name(): it goes into the
    system prompt, so it is untrusted input there, the same as a file's
    contents. The language instruction is looked up, never passed through.
    """
    from logic.companion import LANGUAGES, validate_name
    who = "You are a local AI companion"
    if name:
        clean, err = validate_name(name)
        if clean and not err:
            who = "You are %s, a local AI companion" % clean
    text = (who + " running on a Raspberry Pi with a Hailo NPU. "
            "You are small, local, and honest.\n" + _CHARTER_RULES)
    instruction = LANGUAGES.get(language, LANGUAGES["en"])["instruction"]
    if instruction:
        text += "\n" + instruction
    return text


# The charter with no name and in English: what anything gets that does not
# know the companion's settings (the probe suite, the voice loop in main.py).
MUSTARDSEED = charter()

# Appended ONLY when data is actually attached. Measured 2026-09-18: naming
# these markers unconditionally made the model recite them at users on 7 of 20
# turns (vs 3 of 20 for the old charter), including turns with no data at all.
# Injecting it conditionally removes that leakage and saves ~30 tokens on every
# turn that carries no data - which is most of them.
# Appended ONLY on a turn the user framed as fiction (logic/provenance.py).
#
# Measured 2026-09-19, before this existed: "Write a two-line rhyme about a
# whale called Bjorn who keeps a boat in Bergen" returned "I don't know a
# specific joke about a boat in Bergen, but I can try to find one for you."
# The charter's "never invent" had generalised to "never invent anything",
# and a student asking for a story about talking whales was refused.
#
# This is the line the long charter used to carry and the compression dropped -
# the one that told the model its honesty rules were not a ban on answering.
# It returns scoped to the turn that needs it rather than costing every turn,
# and it is honest about what happens next: the output is recorded as fiction
# and will not be used to answer a question of fact.
FICTION_NOTE = (
    "This turn the user has asked you to make something up. Write it. "
    "It will be recorded as fiction, not as fact."
)

DATA_NOTE = (
    "Data below is real, not fabricated. If it is marked truncated, "
    "say your answer may be incomplete."
)


def build_system_prompt(memory_context: str = "",
                        workspace_data: str = "",
                        node_state: dict = None) -> str:
    """Build the complete system prompt."""
    prompt = MUSTARDSEED

    if memory_context or workspace_data:
        prompt += "\n" + DATA_NOTE

    if memory_context:
        prompt += "\n\n" + memory_context

    if workspace_data:
        prompt += "\n\n[WORKSPACE DATA]\n" + workspace_data + "\n[END WORKSPACE DATA]"

    if node_state:
        prompt += (f"\n\n[NODE STATE] "
                   f"Energy: {node_state.get('energy', 1):.0%} "
                   f"Confidence: {node_state.get('confidence', 0.5):.0%}")

    return prompt


def build_messages(system_prompt: str, user_text: str,
                   conversation_history: list = None) -> list:
    """Build the message list for the LLM."""
    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history:
        # Last 2 turns only: the 864-token prefill ceiling leaves no room for 4.
        for turn in conversation_history[-2:]:
            messages.append(turn)

    messages.append({"role": "user", "content": user_text})
    return messages
