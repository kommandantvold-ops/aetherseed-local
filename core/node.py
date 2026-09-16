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
from typing import Dict, Optional


# ============================================================
# NODE STATE
# ============================================================

@dataclass
class NodeState:
    theta: float                # fase (retning)
    h: float                    # ydmykhet [0–1]
    E: float                    # energi [0–1]
    D: float                    # forråtnelse [0–1]

    last_update: float = 0.0
    id: str = "node"


# ============================================================
# NODE
# ============================================================

class Node:
    """
    AetherSeed Node

    - theta: phase (direction / cognitive orientation)
    - h: humility (coupling dampener)
    - E: energy (scheduler priority)
    - D: decay (hardware pressure / entropy)
    """

    def __init__(self, node_id: str = "node_0"):

        self.state = NodeState(
            theta=np.random.uniform(-np.pi, np.pi),
            h=0.45,
            E=0.6,
            D=0.1,
            id=node_id
        )

        # coupling weights (for multi-node later)
        self.K: Dict[str, float] = {}

        # learning rates
        self.lr_h_up = 0.06
        self.lr_h_down = 0.04
        self.lr_theta = 0.5
        self.lr_energy = 0.05
        self.lr_decay = 0.03

    # ========================================================
    # CORE DYNAMICS
    # ========================================================

    def update_phase(self, neighbors: Optional[Dict[str, float]] = None):
        """
        Kuramoto-inspired phase update
        neighbors: dict[node_id → theta]
        """

        if not neighbors:
            return

        coupling = 0.0

        for nid, theta_j in neighbors.items():
            K_ij = self.K.get(nid, 0.5)
            coupling += K_ij * np.sin(theta_j - self.state.theta)

        # humility dampens influence
        delta = (1 - self.state.h) * coupling / max(len(neighbors), 1)

        self.state.theta = (self.state.theta + self.lr_theta * delta) % (2 * np.pi)

    # ========================================================
    # HUMILITY UPDATE (AetherSpark)
    # ========================================================

    def update_h(self, alignment: float, resonance: float):
        """
        alignment: how well node aligns with others (0–1)
        resonance: semantic usefulness (0–1)
        """

        # mismatch from desired order (~0.6 sweet spot)
        E_i = abs(alignment - 0.6)

        # update rule
        self.state.h += self.lr_h_up * E_i - self.lr_h_down * resonance

        self.state.h = np.clip(self.state.h, 0.05, 0.95)

    # ========================================================
    # ENERGY UPDATE (Scheduler)
    # ========================================================

    def update_energy(self, active: bool, interrupted: bool):
        """
        active: node used this cycle
        interrupted: user interruption
        """

        if active:
            self.state.E -= self.lr_energy * 0.6
        else:
            self.state.E += self.lr_energy * 0.4

        if interrupted:
            self.state.E += 0.05  # refocus boost

        self.state.E = np.clip(self.state.E, 0.0, 1.0)

    # ========================================================
    # DECAY UPDATE (Hardware → D)
    # ========================================================

    def update_decay(self, metrics: Dict[str, float]):
        """
        metrics:
            cpu: 0–1
            ram: 0–1
            temp: 0–1 (normalized)
        """

        cpu = metrics.get("cpu", 0.0)
        ram = metrics.get("ram", 0.0)
        temp = metrics.get("temp", 0.0)

        stress = 0.5 * cpu + 0.3 * ram + 0.2 * temp

        # decay increases with stress
        self.state.D += self.lr_decay * (stress - 0.3)

        # natural recovery
        self.state.D -= 0.01

        self.state.D = np.clip(self.state.D, 0.0, 1.0)

    # ========================================================
    # TRUST / COUPLING UPDATE (AetherRoot-inspired)
    # ========================================================

    def update_coupling(self, other_id: str, similarity: float, phase_diff: float):
        """
        similarity: semantic similarity (0–1)
        phase_diff: sin(theta_j - theta_i)
        """

        K_ij = self.K.get(other_id, 0.5)

        benefit = similarity * (1 - abs(phase_diff))

        K_ij += 0.03 * (benefit - 0.15)

        self.K[other_id] = float(np.clip(K_ij, 0.1, 1.3))

    # ========================================================
    # DECISION: SHOULD NODE ACT?
    # ========================================================

    def should_act(self, threshold_E=0.3, threshold_D=0.7):
        """
        Determines if node should be scheduled
        """

        if self.state.D > threshold_D:
            return False  # too degraded

        return self.state.E > threshold_E

    # ========================================================
    # INTERRUPT RESPONSE
    # ========================================================

    def on_interrupt(self):
        """
        User interruption signal → adjust internal state
        """

        self.state.h = min(self.state.h + 0.08, 0.95)
        self.state.E = min(self.state.E + 0.05, 1.0)

    # ========================================================
    # STEP UPDATE (called each loop)
    # ========================================================

    def step(self, metrics: Dict[str, float],
             active=False,
             interrupted=False,
             alignment=0.5,
             resonance=0.5,
             neighbors=None):

        self.update_phase(neighbors)
        self.update_h(alignment, resonance)
        self.update_energy(active, interrupted)
        self.update_decay(metrics)

    # ========================================================
    # DEBUG / STATUS
    # ========================================================

    def status(self) -> Dict:
        return {
            "theta": float(self.state.theta),
            "h": float(self.state.h),
            "E": float(self.state.E),
            "D": float(self.state.D),
            "K_size": len(self.K),
            "id": self.state.id
        }
