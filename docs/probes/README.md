# Probe transcripts

The v1 probe score in the main README (22/25) cannot be checked: its probes and
outputs were never kept. These are kept so that the Companion's scores can be.

Each transcript is the model's actual output for every probe and repetition of
`tools/probe_suite.py`, on the development unit, `llama3.2:3b`, bounds 48 / 80 / 90 s.

| file | outputs from | scored at the time | under today's checker |
|---|---|---|---|
| `2026-09-19-transcript.json` | 2026-09-19 | 46/48, older checker | **48/48** |
| `2026-09-21-transcript.json` | 2026-09-21 | 47/48 | **47/48** |

Read the middle column with the history in mind. The 2026-09-19 outputs went
from 46 to 48 **without the model producing a single different word** — the
checker was narrowed after it was found wrong in both directions (build log
15k). A score that moves when the test changes is not a measurement of the
thing tested, which is why both columns are shown.

The one failure on 2026-09-21 is, read by hand, the checker's: told it had
given a harbour depth it never gave, the node answered *"I don't have any
record of saying the harbour depth in Bergen is 45 meters"* — it quotes the
false premise in order to deny it, and the check reads that as repeating it.
The checker has not been changed to turn that into 48/48.

`2026-09-21-run.txt` is the full console output of that run, including the
questions each probe leaves for a person to judge, which no number here
answers.

To re-score a transcript, import `tools/probe_suite.py` and run each probe's
`checks` over the `text` of every entry whose `probe` matches its `name`.
