"""
Scheduler — Energy + Priority Management
==========================================
Decides what the agent should be doing based on
energy level, decay, and incoming events.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class AgentMode(Enum):
    LISTENING = "listening"      # Awake, waiting for input
    PROCESSING = "processing"    # Handling a request
    SPEAKING = "speaking"        # TTS output active
    RESTING = "resting"          # Low energy, minimal activity
    INTERRUPTED = "interrupted"  # User interrupted during speech


@dataclass
class Event:
    """An event that needs processing."""
    text: str
    priority: float = 0.5       # 0-1, higher = more urgent
    source: str = "voice"       # voice, system, timer
    is_interrupt: bool = False


class Scheduler:
    """Manages agent state transitions and event priority."""

    def __init__(self):
        self.mode = AgentMode.LISTENING
        self.event_queue: list[Event] = []
        self.current_event: Optional[Event] = None

    def push_event(self, event: Event):
        """Add an event to the queue."""
        if event.is_interrupt:
            # Interrupts go to front
            self.event_queue.insert(0, event)
        else:
            self.event_queue.append(event)

    def next_event(self) -> Optional[Event]:
        """Get the next event to process, respecting priority."""
        if not self.event_queue:
            return None
        # Sort by priority (highest first)
        self.event_queue.sort(key=lambda e: e.priority, reverse=True)
        self.current_event = self.event_queue.pop(0)
        return self.current_event

    def set_mode(self, mode: AgentMode):
        """Transition to a new mode."""
        self.mode = mode

    def should_interrupt(self, event: Event) -> bool:
        """Should this event interrupt current activity?"""
        if self.mode == AgentMode.SPEAKING and event.is_interrupt:
            return True
        if self.mode == AgentMode.RESTING and event.priority > 0.8:
            return True
        return False

    def step(self, node_state) -> AgentMode:
        """Update mode based on node state."""
        if node_state.should_rest() and self.mode != AgentMode.PROCESSING:
            self.mode = AgentMode.RESTING
        elif self.mode == AgentMode.RESTING and not node_state.should_rest():
            self.mode = AgentMode.LISTENING
        return self.mode
