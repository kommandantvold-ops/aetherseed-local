"""Working memory: the last exchange of this conversation goes with the next
turn.

the steward, after a unit's first days on Qwen3 (finding 2 of): she
asks for context instead of finding it. Measured: on a unit, 12 of 73 short
follow-ups within five minutes of the turn before were answered by asking what
he meant ("Do you disagree?" - "I don't have a context for what you're
disagreeing about"); on copies of a unit, "And what day is that happening?"
did not find "... on Saturday" said two turns earlier, at either memory budget.

Why: the console sends each turn ALONE, and the only way a past turn reached
her was AetherRoot's long-term retrieval, which ranks by rare words in common.
A follow-up shares none with what it refers to. Every agent of the market map
read sends the recent turns of the conversation as real
user/assistant messages - OpenClaw, Hermes Agent, nanobot, NanoClaw, ZeroClaw,
PicoClaw, Moltis - and only then adds long-term memory. This is that, at the
size of this unit:

  - at most MAX_EXCHANGES (3) exchanges, each within WINDOW_S of the next turn;
  - the same speaker only: the steward's conversation is not shown to a guest -
    and, since, the same conversation: every guest is "Guest",
    so the console names each phone's conversation and the key is both
    (proxy._conversation_key). Conversations on two screens run side by side:
    a turn on one does not end the other;
  - kept in this process only, never written: a restart forgets it, and the
    long-term memory is where a turn is remembered;
  - timed by time.monotonic, so that a clock set back or forward cannot make an old exchange new;
  - the assistant's side as it was SHOWN, cut at REPLY_MAX characters.

What it is not: a summary, a compaction, or anything the model writes. The
budget guard (logic/token_budget.enforce_budget) drops these before anything
else when a prompt does not fit, oldest first, a question and its answer
together.
"""
import threading
import time

WINDOW_S = 600           # ten minutes between the last exchange and this turn
# Three, not two. Tried on copies of a unit, the
# four turns of 77d: with two, "And what day is that happening?" lost "...on
# Saturday" behind an unrelated turn in between (a library passage), and she
# answered "the 10th day". With three, the turn it refers to is in front of
# her. Three exchanges cost about 150-450 tokens of a 1536-token prompt, and
# the budget guard drops the oldest first.
MAX_EXCHANGES = 3
REPLY_MAX = 400          # characters of a reply carried (a passage can be long)
USER_MAX = 400


class WorkingMemory:
    def __init__(self, window_s: float = WINDOW_S, max_exchanges: int = MAX_EXCHANGES,
                 clock=time.monotonic):
        self.window_s = window_s
        self.max_exchanges = max_exchanges
        self.clock = clock
        self._lock = threading.Lock()
        self._turns = []             # (at, speaker, user, reply), oldest first

    def add(self, speaker: str, user: str, reply: str):
        """One exchange as it happened: what was said, what was shown."""
        user = " ".join((user or "").split())
        reply = (reply or "").strip()
        if not user or not reply:
            return
        if len(user) > USER_MAX:
            user = user[:USER_MAX].rsplit(" ", 1)[0] + " ..."
        if len(reply) > REPLY_MAX:
            reply = reply[:REPLY_MAX].rsplit(" ", 1)[0] + " ..."
        with self._lock:
            self._turns.append((self.clock(), speaker, user, reply))
            # room for a few conversations side by side
            del self._turns[:-max(self.max_exchanges * 8, 16)]

    def recent(self, speaker: str) -> list:
        """[(user, reply), ...], oldest first: the last exchanges of `speaker`
        (a speaker, or a speaker's conversation) that run up to now without a
        gap longer than the window. Another conversation's turns in between
        are passed over: until they ended this one, which was
        right for one screen and wrong for a phone beside it."""
        now = self.clock()
        out = []
        with self._lock:
            edge = now
            for at, who, user, reply in reversed(self._turns):
                if who != speaker:
                    continue
                if edge - at > self.window_s:
                    break
                out.append((user, reply))
                edge = at
                if len(out) >= self.max_exchanges:
                    break
        out.reverse()
        return out

    def forget(self, matcher):
        """Drop every exchange whose words `matcher(user + " " + reply)` says
        hold what was told to be forgotten (logic/forget.py)."""
        with self._lock:
            self._turns = [t for t in self._turns if not matcher(t[2] + " " + t[3])]

    def forget_last(self, speaker):
        """Drop the last exchange of `speaker`."""
        with self._lock:
            for i in range(len(self._turns) - 1, -1, -1):
                if self._turns[i][1] == speaker:
                    del self._turns[i]
                    return

    def clear(self):
        with self._lock:
            self._turns.clear()


def as_messages(exchanges) -> list:
    """The exchanges as the chat messages they were."""
    msgs = []
    for user, reply in exchanges:
        msgs.append({"role": "user", "content": user})
        msgs.append({"role": "assistant", "content": reply})
    return msgs
