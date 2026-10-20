# AetherSeed Companion

A small, local AI companion that runs entirely on your own hardware.
It answers from what it has stored, says "I don't know" when it does not, and
earns more access only by demonstrating that it can be trusted with it.

- **Local.** The language model runs on the device. Nothing leaves it.
- **Memory you can read.** Conversations, facts and notes live in one SQLite
  database on the device, with tamper-evident logs (`tools/verify_chain.py`).
- **Trust is earned.** Four levels — observer, writer, builder, autonomous —
  decide which tools it may use. It starts at observer.
- **A steward and guests.** The steward owns the device and its memory.
  Anyone else on the network is a guest and cannot read or change the steward's
  data.

## Requirements

| | |
|---|---|
| Board | Raspberry Pi 5 (16 GB recommended) |
| Accelerator | Hailo-10H (for example the Raspberry Pi AI HAT+ 2) |
| OS | Raspberry Pi OS 64-bit (Debian Trixie) |
| Runtime | HailoRT 5.4.0 and `hailo-ollama`, from Hailo |
| Model | `qwen3:1.7b` (Hailo-10H build) |
| Python | 3.11 or newer, with `venv` |

The Hailo runtime, driver and model come from Hailo and are not part of this
repository. See [`docs/INSTALL.md`](docs/INSTALL.md).

## Install

```bash
git clone https://github.com/kommandantvold-ops/aetherseed-local.git
cd aetherseed-local
sudo ./install.sh
```

`install.sh` checks the prerequisites, creates the service accounts, installs
the application to `/opt/aetherseed`, sets up its Python environment and
installs and starts the services. It can be run again safely. Details and
options are in [`docs/INSTALL.md`](docs/INSTALL.md).

Then open `http://127.0.0.1:2077` on the device (or add `--lan` to the
install to reach it from your network) and follow the first-start page.

## Tests

```bash
python3 -m unittest discover -p "test_*.py"
```

The tests need no Hailo hardware.

## Layout

| Path | Contents |
|---|---|
| `proxy.py` | The companion's server: memory, trust, safety gate, model calls |
| `aetherroot.py`, `aetherspark.py` | Memory store and safety gate |
| `logic/` | Trust levels, workspace, forgetting, logs, training |
| `gui/` | The web console and the manual |
| `services/` | systemd units, udev rules |
| `tools/` | Maintenance tools |
| `training/` | Optional training loop (see its README) |
| `knowledge/` | What the companion knows about itself |

## License

See [`LICENSE`](LICENSE).
