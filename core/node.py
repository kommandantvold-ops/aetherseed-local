"""
Core Node — θ, h, E, D model
==============================
Each Aetherseed agent is a node with four state variables:

θ (theta) — phase angle, alignment with the garden (0 to 2π)
h (humility) — regulator, scales response confidence (0 to 1)
E (energy) — available compute/attention budget (0 to 1)  
D (decay) — hardware degradation signal (0 to 1, 0=healthy)

These update every tick based on interaction quality,
hardware metrics, and trust evolution.
"""

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class NodeState:
    """The living state of an Aetherseed node."""
    theta: float = 0.0          # Phase alignment (radians)
    humility: float = 0.7       # High humility = cautious, honest
    energy: float = 1.0         # Full energy at start
    decay: float = 0.0          # No decay at start
    
    # Derived
    resonance: float = 0.0      # Kuramoto order parameter (computed)
    alive: bool = True
    last_update: str = ""
    ticks: int = 0

    def update(self, interaction_quality: float = 0.5, hw_decay: float = 0.0):
        """Update node state after an interaction.
        
        interaction_quality: 0-1 (how good was the last interaction)
        hw_decay: 0-1 (hardware stress level)
        """
        # Theta drifts toward alignment based on interaction quality
        # Good interactions pull theta toward 0 (aligned), bad ones scatter
        alignment_pull = 0.1 * (interaction_quality - 0.5)
        self.theta = (self.theta + alignment_pull) % (2 * np.pi)
        
        # Humility adjusts slowly
        # High quality interactions slightly reduce humility (more confident)
        # Low quality increases it (more cautious)
        h_drift = 0.02 * (0.5 - interaction_quality)
        self.humility = np.clip(self.humility + h_drift, 0.1, 0.95)
        
        # Energy depletes with use, recovers slowly during idle
        self.energy = np.clip(self.energy - 0.01 + 0.005, 0.0, 1.0)
        
        # Decay tracks hardware stress
        self.decay = np.clip(hw_decay, 0.0, 1.0)
        
        # Compute resonance (simplified Kuramoto for single node)
        # r = cos(theta) * (1 - decay) * energy
        self.resonance = float(np.cos(self.theta) * (1 - self.decay) * self.energy)
        
        self.last_update = datetime.now(timezone.utc).isoformat()
        self.ticks += 1

    def effective_confidence(self) -> float:
        """How confident should the agent be in its responses?
        Scaled by humility, energy, and decay."""
        return (1 - self.humility) * self.energy * (1 - self.decay)

    def should_rest(self) -> bool:
        """Should the node enter low-power mode?"""
        return self.energy < 0.2 or self.decay > 0.8

    def to_dict(self) -> dict:
        return {
            "theta": round(self.theta, 4),
            "humility": round(self.humility, 4),
            "energy": round(self.energy, 4),
            "decay": round(self.decay, 4),
            "resonance": round(self.resonance, 4),
            "confidence": round(self.effective_confidence(), 4),
            "alive": self.alive,
            "ticks": self.ticks,
            "last_update": self.last_update,
        }

    def status_line(self) -> str:
        return (
            f"θ={self.theta:.2f} h={self.humility:.2f} "
            f"E={self.energy:.2f} D={self.decay:.2f} "
            f"r={self.resonance:.2f} conf={self.effective_confidence():.2f}"
        )
