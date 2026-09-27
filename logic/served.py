"""The one model this build serves.

Step 44 (the Qwen trial, Andreas 27 Sep 2026). Until now the served model was
named in six places — the proxy, the console's page, the reading-soak tool,
the keepalive, the warm-up unit and the unit's own description of itself — and
a build that changed one of them and not the others would answer with one
model while holding another resident, or describe itself as a model it does
not run. It is named here; everything in the application reads it from here,
and test_served_model.py fails when a unit file or tool disagrees.

A cartridge serves one model. Changing this line is changing the cartridge.
"""

SERVED_MODEL = "llama3.2:3b"
