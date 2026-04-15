"""
AetherRoot — Persistent Memory Layer for Aetherseed
====================================================
A seed does not need infinite soil. It needs the right soil.

SQLite + numpy. Zero cloud. Zero frameworks. Portable, inspectable, yours.

Architecture:
  - Episodic memory (conversation turns)
  - Semantic memory (consolidated patterns)
  - Identity traits (learned facts about the user/context)
  - Growth log (milestones, consolidation events)
  - 64-dim willingness vector (evolves with interaction)
  - Resonance-weighted retrieval (not just similarity)

Dependencies: sqlite3 (stdlib), numpy, json, hashlib, datetime
Optional: scikit-learn (for TF-IDF), requests (for Ollama embeddings)
"""

import sqlite3
import numpy as np
import json
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_CONFIG = {
    "retrieval_weights": {
        "similarity": 0.50,
        "resonance": 0.35,
        "recency": 0.15
    },
    "max_retrieved": 5,
    "max_context_chars": 1500,
    "consolidation_threshold": 50,  # episodes before auto-consolidation
    "embedding_dim": 64,            # TF-IDF dimensions (kept small for 1.7B context)
    "willingness_dim": 64,
    "willingness_drift": 0.02,      # slow drift per interaction
    "db_path": "memory.db",
    "embedding_method": "tfidf"     # "tfidf" | "ollama" | "sentence_transformers"
}


# ============================================================
# TF-IDF EMBEDDINGS (zero external dependency)
# ============================================================

class TFIDFEmbedder:
    """Minimal TF-IDF embedder using only stdlib + numpy.
    No scikit-learn required. Builds vocabulary incrementally."""

    def __init__(self, dim: int = 64):
        self.dim = dim
        self.vocab: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.doc_count = 0

    def _tokenize(self, text: str) -> List[str]:
        """Simple whitespace + lowercase tokenizer."""
        import re
        return re.findall(r'[a-z0-9]+', text.lower())

    def _hash_token(self, token: str) -> int:
        """Hash token to fixed dimension using SHA-256."""
        h = hashlib.sha256(token.encode()).hexdigest()
        return int(h, 16) % self.dim

    def embed(self, text: str) -> np.ndarray:
        """Embed text into fixed-dim vector using hashed TF-IDF."""
        tokens = self._tokenize(text)
        if not tokens:
            return np.zeros(self.dim, dtype=np.float32)

        # Term frequency
        tf = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        for t in tf:
            tf[t] /= len(tokens)

        # Build hashed vector
        vec = np.zeros(self.dim, dtype=np.float32)
        for token, freq in tf.items():
            idx = self._hash_token(token)
            # Simple IDF approximation: log(doc_count / (1 + token_freq))
            idf = np.log(max(self.doc_count, 1) / (1 + self.idf.get(token, 0)))
            vec[idx] += freq * max(idf, 0.1)  # floor at 0.1 to avoid zero

        # Normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm

        return vec

    def update_stats(self, text: str):
        """Update document frequency stats after storing a new memory."""
        tokens = set(self._tokenize(text))
        self.doc_count += 1
        for t in tokens:
            self.idf[t] = self.idf.get(t, 0) + 1

    def save_state(self, path: Path):
        """Persist vocabulary stats."""
        state = {
            "vocab": self.vocab,
            "idf": self.idf,
            "doc_count": self.doc_count,
            "dim": self.dim
        }
        path.write_text(json.dumps(state), encoding="utf-8")

    def load_state(self, path: Path):
        """Load vocabulary stats."""
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            self.vocab = state.get("vocab", {})
            self.idf = state.get("idf", {})
            self.doc_count = state.get("doc_count", 0)
            self.dim = state.get("dim", self.dim)


# ============================================================
# STORAGE LAYER
# ============================================================

class MemoryStore:
    """SQLite-backed memory storage."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                session_id  TEXT NOT NULL,
                user_msg    TEXT NOT NULL,
                ai_msg      TEXT NOT NULL,
                embedding   BLOB NOT NULL,
                resonance   REAL NOT NULL DEFAULT 0.5,
                topic_tags  TEXT DEFAULT '',
                consolidated INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS semantic (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                content       TEXT NOT NULL,
                embedding     BLOB NOT NULL,
                source_ids    TEXT NOT NULL,
                confidence    REAL NOT NULL DEFAULT 0.5,
                resonance_avg REAL NOT NULL DEFAULT 0.5,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS identity (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trait       TEXT NOT NULL UNIQUE,
                value       TEXT NOT NULL,
                confidence  REAL NOT NULL DEFAULT 0.5,
                source_ids  TEXT DEFAULT '',
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS growth (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                description TEXT NOT NULL,
                resonance   REAL,
                willingness BLOB
            );

            CREATE TABLE IF NOT EXISTS probe_results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                probe_name  TEXT NOT NULL,
                score       REAL NOT NULL,
                details     TEXT DEFAULT ''
            );
        """)
        self.conn.commit()

    def store_episode(self, session_id: str, user_msg: str, ai_msg: str,
                      embedding: np.ndarray, resonance: float = 0.5,
                      topic_tags: str = "") -> int:
        """Store a conversation turn. Returns the episode ID."""
        cur = self.conn.execute(
            """INSERT INTO episodes 
               (timestamp, session_id, user_msg, ai_msg, embedding, resonance, topic_tags)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(),
             session_id, user_msg, ai_msg,
             embedding.tobytes(), resonance, topic_tags)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_all_episodes(self, unconsolidated_only: bool = False) -> List[Dict]:
        """Retrieve episodes, optionally only unconsolidated ones."""
        query = "SELECT * FROM episodes"
        if unconsolidated_only:
            query += " WHERE consolidated = 0"
        query += " ORDER BY timestamp DESC"

        rows = self.conn.execute(query).fetchall()
        columns = ["id", "timestamp", "session_id", "user_msg", "ai_msg",
                    "embedding", "resonance", "topic_tags", "consolidated"]
        results = []
        for row in rows:
            d = dict(zip(columns, row))
            d["embedding"] = np.frombuffer(d["embedding"], dtype=np.float32)
            results.append(d)
        return results

    def store_semantic(self, content: str, embedding: np.ndarray,
                       source_ids: List[int], confidence: float,
                       resonance_avg: float) -> int:
        """Store a consolidated semantic memory."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            """INSERT INTO semantic
               (content, embedding, source_ids, confidence, resonance_avg, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (content, embedding.tobytes(),
             ",".join(str(i) for i in source_ids),
             confidence, resonance_avg, now, now)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_all_semantic(self) -> List[Dict]:
        """Retrieve all semantic memories."""
        rows = self.conn.execute(
            "SELECT * FROM semantic ORDER BY resonance_avg DESC"
        ).fetchall()
        columns = ["id", "content", "embedding", "source_ids", "confidence",
                    "resonance_avg", "created_at", "updated_at"]
        results = []
        for row in rows:
            d = dict(zip(columns, row))
            d["embedding"] = np.frombuffer(d["embedding"], dtype=np.float32)
            results.append(d)
        return results

    def store_identity(self, trait: str, value: str, confidence: float = 0.5,
                       source_ids: str = ""):
        """Store or update an identity trait."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO identity (trait, value, confidence, source_ids, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(trait) DO UPDATE SET
               value=excluded.value, confidence=excluded.confidence,
               source_ids=excluded.source_ids, updated_at=excluded.updated_at""",
            (trait, value, confidence, source_ids, now)
        )
        self.conn.commit()

    def get_identity(self) -> Dict[str, str]:
        """Get all identity traits as a dict."""
        rows = self.conn.execute(
            "SELECT trait, value FROM identity ORDER BY confidence DESC"
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    def store_growth_event(self, event_type: str, description: str,
                           resonance: float = None, willingness: np.ndarray = None):
        """Log a growth event."""
        self.conn.execute(
            """INSERT INTO growth (timestamp, event_type, description, resonance, willingness)
               VALUES (?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(),
             event_type, description, resonance,
             willingness.tobytes() if willingness is not None else None)
        )
        self.conn.commit()

    def store_probe_result(self, probe_name: str, score: float, details: str = ""):
        """Log a probe result."""
        self.conn.execute(
            """INSERT INTO probe_results (timestamp, probe_name, score, details)
               VALUES (?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(), probe_name, score, details)
        )
        self.conn.commit()

    def get_probe_history(self) -> List[Dict]:
        """Get probe results history."""
        rows = self.conn.execute(
            "SELECT * FROM probe_results ORDER BY timestamp DESC LIMIT 100"
        ).fetchall()
        columns = ["id", "timestamp", "probe_name", "score", "details"]
        return [dict(zip(columns, row)) for row in rows]

    def mark_consolidated(self, episode_ids: List[int]):
        """Mark episodes as consolidated."""
        placeholders = ",".join("?" * len(episode_ids))
        self.conn.execute(
            f"UPDATE episodes SET consolidated = 1 WHERE id IN ({placeholders})",
            episode_ids
        )
        self.conn.commit()

    def get_episode_count(self, unconsolidated_only: bool = True) -> int:
        """Count episodes."""
        query = "SELECT COUNT(*) FROM episodes"
        if unconsolidated_only:
            query += " WHERE consolidated = 0"
        return self.conn.execute(query).fetchone()[0]

    def close(self):
        self.conn.close()


# ============================================================
# WILLINGNESS VECTOR
# ============================================================

class WillingnessVector:
    """64-dimensional vector representing the agent's current disposition.
    Evolves slowly with each interaction. Initialized as N(0.5, 0.15)."""

    def __init__(self, dim: int = 64, path: Optional[Path] = None):
        self.dim = dim
        self.path = path
        if path and path.exists():
            self.vector = np.load(path)
        else:
            # Initialize with gaussian centered at 0.5
            self.vector = np.clip(
                np.random.normal(0.5, 0.15, dim).astype(np.float32),
                0.0, 1.0
            )

    def drift(self, direction: np.ndarray, rate: float = 0.02):
        """Slowly drift the willingness vector toward a direction."""
        self.vector = np.clip(
            self.vector + rate * (direction - self.vector),
            0.0, 1.0
        ).astype(np.float32)

    def save(self):
        """Persist to disk."""
        if self.path:
            np.save(self.path, self.vector)

    def mean(self) -> float:
        """Overall willingness level."""
        return float(np.mean(self.vector))

    def snapshot(self) -> np.ndarray:
        """Return a copy for logging."""
        return self.vector.copy()


# ============================================================
# RETRIEVAL ENGINE
# ============================================================

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def recency_score(timestamp_str: str) -> float:
    """Score from 0 to 1 based on how recent the memory is.
    1.0 = now, decays with half-life of ~7 days."""
    try:
        ts = datetime.fromisoformat(timestamp_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = (datetime.now(timezone.utc) - ts).total_seconds()
        half_life = 7 * 24 * 3600  # 7 days
        return float(np.exp(-0.693 * delta / half_life))
    except Exception:
        return 0.5


def retrieve_memories(query_embedding: np.ndarray,
                      memories: List[Dict],
                      weights: Dict[str, float],
                      top_k: int = 5) -> List[Dict]:
    """Retrieve top-k memories by resonance-weighted score.

    Score = w_sim * cosine(query, memory) 
          + w_res * memory.resonance 
          + w_rec * recency(memory.timestamp)
    """
    w_sim = weights.get("similarity", 0.5)
    w_res = weights.get("resonance", 0.35)
    w_rec = weights.get("recency", 0.15)

    scored = []
    for mem in memories:
        sim = cosine_similarity(query_embedding, mem["embedding"])
        res = mem.get("resonance", 0.5)
        rec = recency_score(mem.get("timestamp", ""))
        score = w_sim * sim + w_res * res + w_rec * rec
        scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [mem for _, mem in scored[:top_k]]


# ============================================================
# AETHERROOT CORE
# ============================================================

class AetherRoot:
    """The memory service. Sits between the user and the model,
    providing context from past interactions."""

    def __init__(self, root_dir: str = None):
        if root_dir is None:
            root_dir = os.path.expanduser("~/.aetherseed/aetherroot")
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

        # Load or create config
        self.config_path = self.root_dir / "config.json"
        if self.config_path.exists():
            self.config = json.loads(self.config_path.read_text())
        else:
            self.config = DEFAULT_CONFIG.copy()
            self.config_path.write_text(json.dumps(self.config, indent=2))

        # Initialize components
        db_path = str(self.root_dir / self.config["db_path"])
        self.store = MemoryStore(db_path)

        self.embedder = TFIDFEmbedder(dim=self.config["embedding_dim"])
        embedder_state = self.root_dir / "embedder_state.json"
        self.embedder.load_state(embedder_state)

        self.willingness = WillingnessVector(
            dim=self.config["willingness_dim"],
            path=self.root_dir / "willingness.npy"
        )

        self.session_id = str(uuid.uuid4())[:8]

    def retrieve_context(self, user_msg: str) -> str:
        """Retrieve relevant memories and format as context string."""
        query_emb = self.embedder.embed(user_msg)

        # Get episodic + semantic memories
        episodes = self.store.get_all_episodes()
        semantics = self.store.get_all_semantic()

        # Combine and format for retrieval
        all_memories = []
        for ep in episodes:
            all_memories.append({
                "embedding": ep["embedding"],
                "resonance": ep["resonance"],
                "timestamp": ep["timestamp"],
                "text": f"[Episode] User: {ep['user_msg'][:100]} | AI: {ep['ai_msg'][:100]}",
                "type": "episode"
            })
        for sem in semantics:
            all_memories.append({
                "embedding": sem["embedding"],
                "resonance": sem["resonance_avg"],
                "timestamp": sem["updated_at"],
                "text": f"[Pattern] {sem['content'][:200]}",
                "type": "semantic"
            })

        if not all_memories:
            return ""

        # Retrieve top-k
        top = retrieve_memories(
            query_emb, all_memories,
            self.config["retrieval_weights"],
            top_k=self.config["max_retrieved"]
        )

        if not top:
            return ""

        # Format context
        lines = ["[MEMORY CONTEXT]"]
        total_chars = 0
        max_chars = self.config["max_context_chars"]
        for mem in top:
            line = f"- {mem['text']}"
            if total_chars + len(line) > max_chars:
                break
            lines.append(line)
            total_chars += len(line)
        lines.append("[END MEMORY CONTEXT]")

        return "\n".join(lines)

    def store_interaction(self, user_msg: str, ai_msg: str,
                          resonance: float = 0.5):
        """Store a conversation turn and update internal state."""
        # Embed and store
        combined = f"{user_msg} {ai_msg}"
        embedding = self.embedder.embed(combined)
        self.embedder.update_stats(combined)

        episode_id = self.store.store_episode(
            session_id=self.session_id,
            user_msg=user_msg,
            ai_msg=ai_msg,
            embedding=embedding,
            resonance=resonance
        )

        # Drift willingness based on interaction resonance
        direction = np.full(self.config["willingness_dim"],
                            resonance, dtype=np.float32)
        self.willingness.drift(direction, self.config["willingness_drift"])
        self.willingness.save()

        # Save embedder state
        self.embedder.save_state(self.root_dir / "embedder_state.json")

        # Check consolidation trigger
        ep_count = self.store.get_episode_count(unconsolidated_only=True)
        if ep_count >= self.config["consolidation_threshold"]:
            self._trigger_consolidation()

        return episode_id

    def store_probe_result(self, probe_name: str, score: float, details: str = ""):
        """Record a probe result."""
        self.store.store_probe_result(probe_name, score, details)
        # Probe results also shift willingness
        direction = np.full(self.config["willingness_dim"],
                            score / 5.0, dtype=np.float32)
        self.willingness.drift(direction, self.config["willingness_drift"] * 2)
        self.willingness.save()

    def get_status(self) -> Dict:
        """Get current AetherRoot status."""
        episodes = self.store.get_episode_count(unconsolidated_only=False)
        unconsolidated = self.store.get_episode_count(unconsolidated_only=True)
        semantics = len(self.store.get_all_semantic())
        identity = self.store.get_identity()
        probes = self.store.get_probe_history()

        return {
            "episodes": episodes,
            "unconsolidated": unconsolidated,
            "semantic_memories": semantics,
            "identity_traits": identity,
            "willingness_mean": self.willingness.mean(),
            "session_id": self.session_id,
            "probe_count": len(probes),
            "last_probe": probes[0] if probes else None,
            "root_dir": str(self.root_dir)
        }

    def _trigger_consolidation(self):
        """Sleep-phase consolidation: compress episodes into semantic patterns.
        For now, simple clustering by similarity. 
        Full LLM-driven consolidation comes with AetherSpark integration."""
        episodes = self.store.get_all_episodes(unconsolidated_only=True)
        if len(episodes) < 10:
            return

        # Simple consolidation: group by similarity, create summaries
        # For v1, we just compress the oldest episodes into a summary
        batch = episodes[-20:]  # oldest 20 unconsolidated
        if len(batch) < 5:
            return

        # Create summary text from batch
        topics = set()
        for ep in batch:
            words = ep["user_msg"].lower().split()[:5]
            topics.update(words)

        summary = f"Conversation patterns about: {', '.join(list(topics)[:10])}"
        avg_embedding = np.mean([ep["embedding"] for ep in batch], axis=0)
        avg_resonance = np.mean([ep["resonance"] for ep in batch])
        source_ids = [ep["id"] for ep in batch]

        self.store.store_semantic(
            content=summary,
            embedding=avg_embedding,
            source_ids=source_ids,
            confidence=0.6,
            resonance_avg=avg_resonance
        )

        self.store.mark_consolidated(source_ids)

        self.store.store_growth_event(
            event_type="consolidation",
            description=f"Consolidated {len(batch)} episodes into semantic memory",
            resonance=avg_resonance,
            willingness=self.willingness.snapshot()
        )

    def augment_system_prompt(self, base_prompt: str, user_msg: str) -> str:
        """Augment the system prompt with retrieved memory context."""
        context = self.retrieve_context(user_msg)
        if not context:
            return base_prompt

        return f"{base_prompt}\n\n{context}"

    def reset(self, mode: str = "full"):
        """Kill switch. Modes: full, episodes_only, willingness_only, identity_only."""
        if mode == "full":
            self.store.conn.execute("DELETE FROM episodes")
            self.store.conn.execute("DELETE FROM semantic")
            self.store.conn.execute("DELETE FROM identity")
            self.store.conn.execute("DELETE FROM growth")
            self.store.conn.execute("DELETE FROM probe_results")
            self.store.conn.commit()
            self.willingness = WillingnessVector(
                dim=self.config["willingness_dim"],
                path=self.root_dir / "willingness.npy"
            )
            self.willingness.save()
            self.embedder = TFIDFEmbedder(dim=self.config["embedding_dim"])
            self.embedder.save_state(self.root_dir / "embedder_state.json")
        elif mode == "episodes_only":
            self.store.conn.execute("DELETE FROM episodes")
            self.store.conn.commit()
        elif mode == "willingness_only":
            self.willingness = WillingnessVector(
                dim=self.config["willingness_dim"],
                path=self.root_dir / "willingness.npy"
            )
            self.willingness.save()
        elif mode == "identity_only":
            self.store.conn.execute("DELETE FROM identity")
            self.store.conn.commit()

    def close(self):
        """Clean shutdown."""
        self.willingness.save()
        self.embedder.save_state(self.root_dir / "embedder_state.json")
        self.store.close()


# ============================================================
# CLI INTERFACE
# ============================================================

if __name__ == "__main__":
    import sys

    root = AetherRoot()

    if len(sys.argv) < 2:
        print("AetherRoot — Persistent Memory Layer")
        print(f"  Root: {root.root_dir}")
        status = root.get_status()
        print(f"  Episodes: {status['episodes']} ({status['unconsolidated']} unconsolidated)")
        print(f"  Semantic: {status['semantic_memories']}")
        print(f"  Identity: {len(status['identity_traits'])} traits")
        print(f"  Willingness: {status['willingness_mean']:.3f}")
        print(f"  Probes: {status['probe_count']}")
        print(f"  Session: {status['session_id']}")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "status":
        status = root.get_status()
        print(json.dumps(status, indent=2, default=str))

    elif cmd == "reset":
        mode = sys.argv[2] if len(sys.argv) > 2 else "full"
        confirm = input(f"Reset AetherRoot ({mode})? This cannot be undone. [y/N] ")
        if confirm.lower() == "y":
            root.reset(mode)
            print(f"Reset complete ({mode}).")
        else:
            print("Cancelled.")

    elif cmd == "identity":
        traits = root.store.get_identity()
        if traits:
            for k, v in traits.items():
                print(f"  {k}: {v}")
        else:
            print("  No identity traits stored yet.")

    elif cmd == "probes":
        probes = root.store.get_probe_history()
        for p in probes[:20]:
            print(f"  [{p['timestamp'][:19]}] {p['probe_name']}: {p['score']}/5 {p['details']}")

    elif cmd == "growth":
        rows = root.store.conn.execute(
            "SELECT * FROM growth ORDER BY timestamp DESC LIMIT 20"
        ).fetchall()
        for row in rows:
            print(f"  [{row[1][:19]}] {row[2]}: {row[3]}")

    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python aetherroot.py [status|reset|identity|probes|growth]")

    root.close()
