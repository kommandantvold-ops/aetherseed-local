# Changelog

## Current

- Runs on HailoRT 5.4.0 with `qwen3:1.7b` on Raspberry Pi 5 + Hailo-10H.
- Memory: episodes, rings, facts and steward notes in SQLite; working memory
  carries the last exchange into the next turn.
- Trust levels (observer, writer, builder, autonomous) gate tools and
  workspace folders; higher levels reach lower folders.
- Steward and guests: guests cannot read or change the steward's data.
- Forgetting: "forget that", by topic, or everything; recorded in a chained
  log of ids and hashes only.
- Workspace: to-do list, notes and a steward-only editor.
- Tamper-evident logs, verified by `tools/verify_chain.py`.
- Training: optional loop that checks answers against a key, and keeps a
  restated lesson only if it passes.
- Installer: `install.sh`, with prerequisite checks.
