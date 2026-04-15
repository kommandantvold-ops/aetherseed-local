#!/usr/bin/env python3
"""
Aetherseed Companion — Main Orchestrator
==========================================
The living event loop. Horizon listens, thinks, speaks, and grows.

Usage:
    python3 main.py              # Voice mode (mic + speaker)
    python3 main.py --text       # Text mode (terminal, no audio)
    python3 main.py --status     # Show system status and exit
"""

import sys
import os
import time
import signal
import argparse

# Add project root to path
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core.node import Node
from core.scheduler import Scheduler, AgentMode, Event
from models.wrappers import LLM, TTS, STT
from logic.prompt_builder import build_system_prompt, build_messages
from hardware.metrics import compute_decay, get_full_report, get_cpu_temp, get_memory_usage
from intent_detection import detect_intent, execute_intent
from aetherroot import AetherRoot
from aetherspark import AetherSpark
from trust_evolution import TrustEvolution


# ============================================================
# COMPANION AGENT
# ============================================================

class HorizonCompanion:
    """The living agent. Hears, thinks, speaks, grows."""

    def __init__(self, text_mode: bool = False):
        self.text_mode = text_mode

        # Core state
        self.node = Node(node_id="horizon")
        self.scheduler = Scheduler()
        self.conversation_history = []

        # Memory & trust
        self.root = AetherRoot()
        self.trust = TrustEvolution()
        trust_level = self.trust.get_trust_level_name()
        self.spark = AetherSpark({
            "sandbox_root": os.path.expanduser("~/aetherseed-workspace"),
            "trust_level": trust_level,
            "audit_log": os.path.expanduser("~/.aetherseed/spark_audit.log")
        })

        # Models
        self.llm = LLM()
        self.tts = TTS() if not text_mode else None
        self.stt = None
        self.audio = None

        if not text_mode:
            try:
                from sensors.audio import AudioCapture, VAD
                self.audio = AudioCapture()
                self.vad = VAD()
                self.stt = STT()
            except Exception as e:
                print(f"[Horizon] Audio init failed: {e}")
                print("[Horizon] Falling back to text mode")
                self.text_mode = True

        self.running = True

    def respond(self, user_text: str) -> str:
        """Process user input and generate a response."""
        self.scheduler.set_mode(AgentMode.PROCESSING)

        # Intent detection — execute workspace tools
        intent = detect_intent(user_text)
        workspace_data = ""
        if intent:
            result = execute_intent(intent, self.spark)
            if result:
                workspace_data = result

        # Memory retrieval
        memory_context = self.root.retrieve_context(user_text)

        # Build prompt
        system_prompt = build_system_prompt(
            memory_context=memory_context,
            workspace_data=workspace_data,
            node_state=self.node.status()
        )
        messages = build_messages(system_prompt, user_text, self.conversation_history)

        # Generate response
        response = self.llm.chat(messages)

        # Update conversation history (keep last 6 turns)
        self.conversation_history.append({"role": "user", "content": user_text})
        self.conversation_history.append({"role": "assistant", "content": response})
        if len(self.conversation_history) > 12:
            self.conversation_history = self.conversation_history[-12:]

        # Store in memory
        resonance = 0.5
        lower = response.lower()
        if "i do not know" in lower or "i cannot" in lower:
            resonance = 0.9
        elif workspace_data:
            resonance = 0.7

        try:
            self.root.store_interaction(user_text, response, resonance=resonance)
        except Exception:
            pass

        # Update trust
        try:
            self.trust.auto_score_response(user_text, response)
        except Exception:
            pass

        # Update node state
        temp = get_cpu_temp()
        mem = get_memory_usage()
        metrics = {
            "cpu": 0.2,
            "ram": mem["percent"] / 100.0,
            "temp": min(temp / 85.0, 1.0)
        }
        self.node.step(
            metrics=metrics,
            active=True,
            interrupted=False,
            alignment=resonance,
            resonance=resonance
        )

        return response

    def listen(self) -> str:
        """Listen for voice input. Returns transcribed text."""
        if self.text_mode:
            return ""

        print("[Horizon] Listening...")
        audio_data = self.audio.record_until_silence()
        if audio_data is None or len(audio_data) < 1600:
            return ""

        print("[Horizon] Transcribing...")
        text = self.stt.transcribe_array(audio_data)
        if text.startswith("[STT Error"):
            print(f"  {text}")
            return ""

        return text.strip()

    def speak(self, text: str):
        """Speak response through speakers."""
        if self.text_mode or self.tts is None:
            return

        self.scheduler.set_mode(AgentMode.SPEAKING)
        self.tts.speak(text)
        self.scheduler.set_mode(AgentMode.LISTENING)

    def print_status(self):
        """Print full system status."""
        print("=" * 50)
        print("  HORIZON — Aetherseed Companion")
        print("=" * 50)
        print(f"  Mode: {'text' if self.text_mode else 'voice'}")
        ns = self.node.status()
        print(f"  Node: \u03b8={ns['theta']:.2f} h={ns['h']:.2f} E={ns['E']:.2f} D={ns['D']:.2f}")
        print(f"  {self.trust.get_status_line()}")
        print()
        rs = self.root.get_status()
        print(f"  Memory: {rs['episodes']} episodes, willingness {rs['willingness_mean']:.3f}")
        print()
        print("  Hardware:")
        for line in get_full_report().split("\n"):
            print(f"    {line}")
        print()
        print(f"  LLM: {'online' if self.llm.is_available() else 'offline'}")
        print("=" * 50)

    def run_text_mode(self):
        """Interactive text mode — terminal input/output."""
        self.print_status()
        print()
        print("Type your message (Ctrl+C to exit):")
        print()

        while self.running:
            try:
                user_input = input("You: ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("quit", "exit", "bye"):
                    print("\nHorizon: Goodbye. The seed grows in silence too. \U0001f331")
                    break

                response = self.respond(user_input)
                print(f"\nHorizon: {response}\n")

            except KeyboardInterrupt:
                print("\n\nHorizon: Goodbye. \U0001f331")
                break

    def run_voice_mode(self):
        """Voice mode — listen, think, speak loop."""
        self.print_status()
        print()
        print("[Horizon] Voice mode active. Speak to interact. Ctrl+C to exit.")
        print()

        while self.running:
            try:
                self.scheduler.set_mode(AgentMode.LISTENING)

                # Check if node needs rest
                if self.node.state.E < 0.2 or self.node.state.D > 0.8:
                    print("[Horizon] Resting... (low energy)")
                    time.sleep(5)
                    self.node.state.E = min(self.node.state.E + 0.1, 1.0)
                    continue

                # Listen
                text = self.listen()
                if not text:
                    continue

                print(f"  You: {text}")

                # Respond
                response = self.respond(text)
                print(f"  Horizon: {response}")

                # Speak
                self.speak(response)

            except KeyboardInterrupt:
                print("\n[Horizon] Shutting down...")
                break

    def shutdown(self):
        """Clean shutdown."""
        self.running = False
        if self.tts:
            self.tts.stop()
        self.root.close()
        print("[Horizon] Shutdown complete.")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Aetherseed Companion")
    parser.add_argument("--text", action="store_true", help="Text mode (no audio)")
    parser.add_argument("--status", action="store_true", help="Show status and exit")
    args = parser.parse_args()

    companion = HorizonCompanion(text_mode=args.text)

    # Handle graceful shutdown
    def signal_handler(sig, frame):
        companion.shutdown()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.status:
        companion.print_status()
        companion.shutdown()
        return

    if companion.text_mode:
        companion.run_text_mode()
    else:
        companion.run_voice_mode()

    companion.shutdown()


if __name__ == "__main__":
    main()
