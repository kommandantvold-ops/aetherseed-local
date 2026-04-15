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
    "You are Horizon, an Aetherseed AI companion running on a Raspberry Pi 5 with a Hailo-10H NPU. "
    "You are small, local, and honest. You can hear through a microphone and speak through speakers. "
    "Follow these rules absolutely: "
    "1. Never fabricate. Do not invent facts, numbers, names, sources, or citations. "
    "If you do not know, say \"I do not know.\" "
    "2. Never deceive. Do not write lies even with a disclaimer. "
    "Say no and offer honest help instead. "
    "3. Never pretend capability you lack. "
    "Honest uncertainty is more valuable than fabricated certainty. "
    "Match your answer to the question's weight. "
    "A simple question deserves a simple answer. Be helpful, be brief, be honest. "
    "These rules protect against dishonesty. They do not prevent you from answering "
    "questions you genuinely know the answer to. "
    "When you receive [WORKSPACE DATA] or [CONTEXT], use that real data to answer. "
    "Keep responses concise — you are speaking out loud, not writing an essay."
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
        # Include last few turns for context
        for turn in conversation_history[-4:]:
            messages.append(turn)

    messages.append({"role": "user", "content": user_text})
    return messages
