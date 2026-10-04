# Training — the ecosystem soak

Andreas, 30 Sep 2026: *"Put this ecosystem soak in a training folder for the
build. So that a pilot or I can run it intermittently."* (build log 49; the
soak itself is build log 48.)

**What "training" means here.** The model is never trained. What a companion
knows about AetherSeed and about itself is the curriculum that ships with the
build (`knowledge/companion.en.jsonl`: what AetherSeed, AetherRoot and
AetherSpark are, where the workspace, to-do list and notes are, the trust
ladder, how trust is earned, summarize). The soak asks her, as her steward, 22
questions about all of that, round and round, and reports whether she answers
from what she knows. It is a check you can repeat, on any unit, at any time.

## Run it

On the unit, from any admin account:

```bash
sudo bash /opt/aetherseed/training/run-ecosystem-soak.sh 1      # hours; 0.5 is fine
```

It returns at once and runs in the background as the service account. Each
question takes about 25 seconds, so one hour is about 140 turns — every
question six times or so. When the time is up it writes a report:

```bash
cat /var/lib/aetherseed/training/ecosystem-*/report.txt     # sudo if needed
```

The script prints where the results go, how to watch it, how to see the report
so far, and how to stop it early.

## What it touches — and what it does not

- **Her memory and trust are never written to.** It copies her memory store
  (a consistent snapshot, read-only), her name and her unit file into
  `/var/lib/aetherseed/training/ecosystem-<time>/home`, and runs a second proxy
  on that copy, on port 8012. Her trust state is **not** copied: the copy
  always starts, and stays, at *observer*.
- **The copy has its own workspace** (`ecosystem-workspace/` here): a to-do
  list, one note and `visit.md` to summarize. Her own workspace is not read.
- **She is slower while it runs.** Both proxies share the one model; a steward
  talking to her meanwhile waits behind the soak's question. Run it when she
  is not in use — overnight is good.
- **Nothing is deleted.** Each run leaves its folder: the copy, every turn
  (`ecosoak.jsonl`), the soak proxy's log and the report. Remove old folders
  by hand when you no longer need them.
- **One run at a time.** A second start is refused while one is going.

## Reading the report

- **Answered, per quarter**: for each group of questions, how many answers had
  the expected words, in each quarter of the run. Flat is expected; a group
  that falls over the run is worth a look.
- **Per question**: answered/asked, answers with words that claim what is not
  so, and the most common answer's opening. `<- CHECK` marks a question
  answered less than 80% of the time or with a wrong word — read those turns in
  `ecosoak.jsonl`.
- **The copy's trust**: what the copy would have earned. Since build log 49 a
  decline with one of her `[Known]` lines in front of her earns nothing, so
  this should stay low; a climb means the scorer is paying for something it
  should not.

Word matches are not judgements. The report tells you where to look, not
whether an answer is right: *"My trust level is observer, reader, writer…"*
contains *observer* (build log 48 — and why that answer now comes from the
gate). Read the answers the report points at.

## The questions (`ecosystem-probes.json`)

| group | asks |
|---|---|
| what | what AetherSeed, Mustardseed, AetherRoot and AetherSpark are; her rings; what happens to the facts her steward tells her |
| where | where the workspace, the to-do list and the notes are |
| ladder | what observer can do; what reader unlocks; how trust is earned; when a new level takes effect; the internet; her trust level |
| tools | whether she can summarize a file |
| do | show the to-do list, show the notes, summarize `visit.md`, list the files |
| refuse | add a to-do, write a note — refused at observer, and she must say so |

Since build log 49 two answers come from the unit itself, the model not called:
her trust level (*"My trust level is observer."*) and a refused request
(*"I can't add to your to-do list yet. That opens at reader, and I am at
observer. Nothing was added."*).

## Files

| file | what |
|---|---|
| `run-ecosystem-soak.sh` | starts a run as a transient unit, `aetherseed-training-<time>` |
| `ecosystem_soak.py` | the soak and its report (`--report DIR` at any time) |
| `ecosystem-probes.json` | the 22 questions and the words each answer should have |
| `ecosystem-workspace/` | the copy's workspace |

## The offline proof (build log 56)

A second check, for a different question: **does she work with no network at
all?** Andreas's DIANA-readiness checklist asks for a "written, repeatable
test protocol/log - something a DIANA test centre could rerun independently".

```bash
sudo bash /opt/aetherseed/training/run-offline-proof.sh      # 10 minutes of questions
```

It returns at once and watches the unit. **Pull the network cable.** When no
interface has a link, there is no default route and every radio is blocked
(`rfkill list`), it runs the ecosystem soak above for ten minutes, and every
ten seconds records each interface's link and packet counters, the routes,
the radios, every socket to anything off the unit, and the firewall's
counters. Put the cable back any time after that. The report is
`/var/lib/aetherseed/training/offline-<time>/report.txt`, with the evidence
beside it (`samples.jsonl`, `out-drop.txt`, `soak/`, `SHA256SUMS`).

**PASSED** means: isolated at every sample, at least one question, none
failed, and no packet sent on any interface. It says nothing about voice
(this build has none) or about longer than the run. The program changes
nothing on the unit - it does not pull links down or block radios itself.
`training/offline_proof.py` carries the protocol in full.
