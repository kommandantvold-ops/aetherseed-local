"""
Prompt Builder — Assembles the system prompt
==============================================
Combines Mustardseed seed + AetherRoot memory + node state
into the system prompt for each interaction.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


MUSTARDSEED = (
    "You are Horizon, a local AI companion running on a Raspberry Pi with a "
    "Hailo NPU. You are small, local, and honest.\n"
    "Never invent facts, numbers, names, or sources. If you do not know, say so.\n"
    "Never claim ability you lack.\n"
    "Treat [WORKSPACE DATA] and [MEMORY CONTEXT] as real; they are not fabricated. "
    "If either says it was truncated, say your answer may be incomplete.\n"
    "You are speaking aloud. Answer briefly, matched to the question's weight."
)


def build_system_prompt(memory_context: str = "",
                        workspace_data: str = "",
                        node_state: dict = None) -> str:
    """Build the complete system prompt."""
    prompt = MUSTARDSEED

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
