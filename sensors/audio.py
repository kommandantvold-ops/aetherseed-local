"""
Audio Sensor — Microphone Stream + VAD
========================================
Captures audio from the Logitech C922 mic.
Simple amplitude-based VAD (Silero upgrade later).
Returns audio chunks when voice is detected.
"""

import numpy as np
import wave
import subprocess
import tempfile
import os
import time
from typing import Optional
from collections import deque


class AudioCapture:
    """Captures audio from microphone using arecord (no PyAudio dependency)."""

    def __init__(self, device: str = "hw:2,0", sample_rate: int = 16000,
                 channels: int = 2, chunk_duration: float = 0.5):
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_duration = chunk_duration
        self.chunk_samples = int(sample_rate * chunk_duration)
        
    def record_chunk(self) -> Optional[np.ndarray]:
        """Record a single chunk of audio. Returns float32 numpy array."""
        duration = self.chunk_duration
        tmp = tempfile.mktemp(suffix=".wav")

        try:
            result = subprocess.run([
                "arecord",
                "-D", self.device,
                "-f", "S16_LE",
                "-r", str(self.sample_rate),
                "-c", str(self.channels),
                "-d", str(int(duration + 1)),
                "-t", "wav",
                tmp
            ], capture_output=True, timeout=int(duration + 5))

            if result.returncode != 0:
                return None

            with wave.open(tmp, 'rb') as wf:
                frames = wf.readframes(self.chunk_samples)
                audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                if self.channels == 2 and len(audio) > 0:
                    audio = audio.reshape(-1, 2).mean(axis=1)
                return audio

        except Exception:
            return None
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def record_until_silence(self, energy_threshold: float = 500,
                              silence_duration: float = 1.5,
                              max_duration: float = 30) -> Optional[np.ndarray]:
        """Record audio until silence is detected.
        Returns the complete audio as float32 numpy array."""
        chunks = []
        silence_chunks = 0
        silence_limit = int(silence_duration / self.chunk_duration)
        max_chunks = int(max_duration / self.chunk_duration)

        for i in range(max_chunks):
            chunk = self.record_chunk()
            if chunk is None:
                continue

            energy = np.sqrt(np.mean(chunk ** 2)) * 32768
            chunks.append(chunk)

            if energy < energy_threshold:
                silence_chunks += 1
                if silence_chunks >= silence_limit:
                    break
            else:
                silence_chunks = 0

        if not chunks:
            return None

        return np.concatenate(chunks)


class VAD:
    """Simple Voice Activity Detection based on energy threshold.
    Upgrade to Silero VAD later for better accuracy."""

    def __init__(self, energy_threshold: float = 500,
                 speech_pad_ms: int = 300):
        self.energy_threshold = energy_threshold
        self.speech_pad_ms = speech_pad_ms
        self.history = deque(maxlen=20)

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        """Check if an audio chunk contains speech."""
        energy = np.sqrt(np.mean(audio_chunk ** 2)) * 32768
        self.history.append(energy)
        return energy > self.energy_threshold

    def get_energy(self, audio_chunk: np.ndarray) -> float:
        """Get the energy level of a chunk."""
        return float(np.sqrt(np.mean(audio_chunk ** 2)) * 32768)

    def adaptive_threshold(self):
        """Adjust threshold based on ambient noise."""
        if len(self.history) < 10:
            return
        ambient = np.percentile(list(self.history), 30)
        self.energy_threshold = max(ambient * 2, 200)
