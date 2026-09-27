"""The one model this build serves.

Step 44 (the Qwen trial, Andreas 27 Sep 2026). Until now the served model was
named in six places — the proxy, the console's page, the reading-soak tool,
the keepalive, the warm-up unit and the unit's own description of itself — and
a build that changed one of them and not the others would answer with one
model while holding another resident, or describe itself as a model it does
not run. It is named here; everything in the application reads it from here,
and test_served_model.py fails when a unit file or tool disagrees.

A cartridge serves one model. Changing this line is changing the cartridge.

On the qwen-trial branch (27 Sep): Qwen2.5-1.5B-Instruct, fetched by hash in
step 42b, prompt ceiling 2592 measured in 42c. The stable build, tag
stable-llama-2026-09-27, serves llama3.2:3b.
"""

SERVED_MODEL = "qwen2.5-instruct:1.5b"
