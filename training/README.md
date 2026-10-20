# Training (optional)

The model itself is never trained. "Training" here means a loop of exercises
that checks what the companion knows about the AetherSeed framework and lets
it reflect on feedback. It is optional and uses its own files; it does not
change the trust level.

## The COG loop

```bash
sudo bash /opt/aetherseed/training/run-cog-loop.sh [SESSIONS]
```

Starts in the background and returns at once. Each session:

1. **Attempt** — every item twice, once with relevant lines from memory in the
   prompt and once without (the control).
2. **Check** — the companion is shown its answer and asked to check it.
3. **Say back** — on a few items it is asked what it answered and why.
4. **Essay** — a short essay on a passage of the framework texts in
   `training/texts/`.

Between sessions a reviewer writes `reviews/NNN.txt` for an essay, then:

```bash
python3 training/cog_loop.py --reflect DIR NNN
```

shows the companion the essay and the review and stores its short reflection
in memory. That is the only thing the loop writes to memory.

Results are kept per model under `/var/lib/aetherseed/cog/<model>/`: every
prompt and reply word for word in `sessions/`, essays in `essays/`.

## Safety

- Sessions only read memory.
- A session will not start while the steward's brake is set or another run is
  on, and checks again before every model call.
- Prompts are counted with the model's tokenizer and kept under its measured
  limit.

## Files

| File | Purpose |
|---|---|
| `run-cog-loop.sh` | Starts the loop as a transient service |
| `cog_loop.py` | The loop and `--reflect` |
| `cog_texts.py` | The passages and questions |
| `texts/` | The framework texts |
