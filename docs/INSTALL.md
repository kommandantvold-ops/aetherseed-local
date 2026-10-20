# Installing AetherSeed Companion

This installs the companion application on a Raspberry Pi 5 with a Hailo-10H.
The Hailo runtime, driver and model are Hailo's; install them first (below),
then run `install.sh`.

## Prerequisites

1. **Raspberry Pi OS 64-bit (Debian Trixie)**, updated, with SSH or a screen.
   Give the device a hostname and an admin account of your choice.
2. **Hailo-10H recognised by the OS.** After installing the Hailo runtime and
   PCIe driver, `hailortcli fw-control identify` must show `HAILO10H`, and the
   device `/dev/h1x-0` must exist.
3. **HailoRT 5.4.0**, the PCIe driver and the GenAI model-zoo package
   (`hailo-ollama`), from Hailo's Developer Zone. Check `hailortcli --version`
   prints 5.4.0. Do not mix Hailo's `hailort` package with Raspberry Pi's
   `h10-hailort`: they conflict, so remove the latter first.
4. **The model `qwen3:1.7b`** (its `.hef` file and `.sha256`) in hailo-ollama's
   model store, `/usr/share/hailo-ollama/models/blob/`. Use the file from Hailo
   and verify its checksum against the one Hailo publishes or that you recorded
   when you fetched it. Check that `curl -s 127.0.0.1:8000/api/tags` lists it.
5. **The model's tokenizer**, `tokenizer.json` of Qwen3-1.7B, saved as
   `/var/lib/aetherseed/qwen3-1.7b.tokenizer.json` (or beside `install.sh`;
   the installer copies it). The application counts prompt tokens with it
   because the compiled model has a hard prompt limit.
6. `python3` 3.11 or newer with `venv`, and `curl`.

Hold the kernel and Hailo packages (`apt-mark hold`) so an upgrade cannot
break the driver, and do not run `apt full-upgrade` on a working device.

## Install

```bash
git clone https://github.com/kommandantvold-ops/aetherseed-local.git
cd aetherseed-local
sudo ./install.sh --check     # lists what is missing; changes nothing
sudo ./install.sh             # installs and starts
```

Options:

| Option | Effect |
|---|---|
| `--lan` | Serve the console to your network. Default: this device only. |
| `--kiosk` | Also install a full-screen display (needs `labwc` and `chromium`). |

The installer creates the `aetherseed` service account, copies the
application to `/opt/aetherseed` (root-owned, read-only to the service),
builds a Python environment, writes `/etc/aetherseed/model.env`, installs the
systemd units and starts them. Run it again to update after `git pull`; the
memory in `/var/lib/aetherseed` is not touched.

## First start

Open `http://127.0.0.1:2077` (or `http://<device>:2077` with `--lan`). The
first-start page asks for the companion's name and your steward passkey. The
companion starts at the *observer* trust level with an empty memory. The
manual is on its shelf and in the console.

Check the services:

```bash
systemctl --failed
systemctl status hailo-ollama aetherseed-proxy aetherseed-gui
journalctl -u aetherseed-proxy -n 30
```

The first answer after power-on can take about a minute while the model loads.

## Tests

```bash
python3 -m unittest discover -p "test_*.py"
```

They run on any machine with Python and need no Hailo hardware.

## Where things are

| | |
|---|---|
| Application | `/opt/aetherseed` |
| Memory, logs, training | `/var/lib/aetherseed` |
| Model setting | `/etc/aetherseed/model.env` |
| Services | `/etc/systemd/system/aetherseed-*.service`, `hailo-ollama.service` |

Check the integrity of the logs at any time:

```bash
sudo -u aetherseed /opt/aetherseed/venv/bin/python3 /opt/aetherseed/tools/verify_chain.py
```

## Uninstall

```bash
sudo systemctl disable --now aetherseed-proxy aetherseed-gui aetherseed-warmup aetherseed-keepalive hailo-ollama
sudo rm -rf /opt/aetherseed /etc/systemd/system/aetherseed-*.service \
  /etc/systemd/system/hailo-ollama.service* /etc/aetherseed
# memory is kept in /var/lib/aetherseed; delete it only if you want it gone
```
