# Words used in this project

| Word | Meaning |
|---|---|
| Companion | The whole device: the model, its memory and the rules around them. |
| Steward | The person who owns the device. Signs in with their own passkey. |
| Guest | Anyone else who talks to it. A guest's turns are not stored and a guest never reaches the steward's memory. |
| Brake | A steward switch that stops the companion from answering or learning until released. |
| Trust level | observer, writer, builder or autonomous. Decides which tools and workspace folders it may use. It starts at observer and is raised by demonstrated behaviour. |
| Gate (AetherSpark) | The code that checks each tool call against the trust level. Nothing in it asks a person; a person's approval is recorded in the approvals queue. |
| Approvals queue | Requests the companion cannot do alone, waiting for the steward to approve or decline. |
| AetherRoot | The memory store (SQLite): episodes, rings, facts and steward notes. |
| Episode | One stored turn of conversation. |
| Ring | A consolidated summary of a group of episodes. |
| Fact | A statement the steward told the companion, kept with its source. |
| Served answer | An answer the device gives from its own records without calling the model. |
| Restatement | At the end of a training round, the companion says a lesson again; it is kept only if it passes the answer key. |
| Chained log | A log where each line includes a hash of the one before, so changes are detectable (`tools/verify_chain.py`). |

## State on the device

| Path | Contents |
|---|---|
| `/opt/aetherseed` | Application (read-only to the service) |
| `/var/lib/aetherseed` | Memory database, logs, training and workspace data (the service's `HOME`) |
| `/etc/aetherseed/model.env` | The served model |
| `/etc/aetherseed/steward.key` | Hash of the steward's passkey, never the passkey |
