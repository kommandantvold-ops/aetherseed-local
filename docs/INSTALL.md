# Installing the stable Companion build

**Build:** git tag `stable-llama-2026-09-28` — Llama 3.2 3B on HailoRT 5.1.1:
the build that ran Lyra through soak 2 (tag `stable-llama-2026-09-27`, build log
step 43) **with no person's account in it** (step 45). The kiosk runs as its own
account, `aetherseed-kiosk`, and the keepalive as the service account.
**Cartridge:** `db06b3b8cb00541b2541cd4c37b70f01a9b6bca34079631c6a47f4fe16edb6bd`
— **derived, not captured**: Lyra's captured `235a29d0` with the lines this
build changes replaced (`tools/cartridge.manifest` says which). The first unit
built from this guide captures the real one.

Written 27 Sep 2026 from the build log, the repository at the tag, and a
read-only snapshot of Lyra running this build
(`.scratch/step44/stable-reference-2026-09-27/`). Every file and value below was
checked against Lyra. **No new device has been built from this guide yet** —
the first one is the test (build log, open item 14). Commands marked *(log)*
are the build log's own; the rest were written for this guide, from Lyra's
state, and have not been run on a fresh device.

`docs/SETUP.md` and the README's quick start describe an earlier device
(`hailo-h10-all`, hailo-ollama built from source, a Qwen3 model pulled over
the API, `pip --break-system-packages`, Open WebUI). **Do not follow them for
this build.**

---

## What "the same build" means here

At the end, `tools/cartridge.sh verify` compares the unit with Lyra's manifest,
line by line. On a new unit expect these lines, and only these, to differ:

| line | why | what to do |
|---|---|---|
| `packages.count`, `packages.digest` (and `kernel.release`) | the base image or apt state differs from Lyra's | flash the same image; never `apt upgrade` (step 1) |
| `firmware.version` | a different bootloader/firmware; Lyra's bootloader is the 8 Dec 2025 release, firmware `2226a853` | leave the EEPROM alone, or accept the line |

**Any other difference is an install mistake.** Lyra's own package set is
1650 packages with 9 held (the kernel); its image came up as Debian 13.7 with
kernel `6.18.50+rpt-rpi-2712` and 1645 packages before anything was installed.

## You need

- Raspberry Pi 5 (Lyra: Model B Rev 1.1, 16 GB) with the AI HAT+ 2 (Hailo-10H),
  boot media, **Ethernet** (step 2 switches Wi-Fi off), a screen for the kiosk.
- An admin account of your choosing on the unit. **Nothing in the build depends
  on its name**; the examples call it `admin`.
- The repository at the tag, from the PC (`C:\aetherseed-local`).
- The model and its tokenizer, **copied from Lyra** (simplest) or downloaded,
  and checked by hash either way:
  - `sha256_1129f5f8384e4e45c5890104dc4ec1aee77e800ce1484ddc3aa942399aada425` —
    3,370,416,230 bytes, in `/usr/share/hailo-ollama/models/blob/`
  - `tokenizer.json`, sha256 `6b9e4e7fb171f92fd137b777cc2714bf87d11576700a1dcd7a399e7bbe39537b`,
    in `/var/lib/aetherseed/`

## 1. Flash and first boot

- Raspberry Pi Imager: **Raspberry Pi OS (64-bit) with desktop, Trixie** — the
  kiosk uses the image's own labwc and Chromium (Lyra: labwc 0.20.1-1+rpt1,
  chromium 152.0.7977.82-1~deb13u1+rpt2).
- In the Imager's settings: an admin user (any name — the build runs as its
  own two accounts, created in step 6); a **hostname of its own** (Lyra is
  `aetherseed`); SSH on; Wi-Fi country NO.
- First boot, then check: `uname -r` should print `6.18.50+rpt-rpi-2712`. If it
  does not, the kernel and package lines will differ — decide before going on.
- **Never run `apt upgrade` or `full-upgrade`.** `apt-get update` only reads
  package lists and is fine.

## 2. An appliance, and PCIe Gen 3 — build log step 2

*(log)*

```bash
sudo cp /boot/firmware/config.txt /boot/firmware/config.txt.bak-$(date +%Y%m%d-%H%M%S)
sudo systemctl set-default multi-user.target
sudo systemctl disable lightdm
for u in bluetooth udisks2 upower accounts-daemon rpcbind nfs-blkmap wpa_supplicant; do
  sudo systemctl disable --now $u
done
sudo systemctl disable NetworkManager-wait-online.service
echo 'dtparam=pciex1_gen=3' | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

`wpa_supplicant` is Wi-Fi: on a unit without Ethernet, leave it out of the
loop (its state is not in the cartridge). After the reboot, `lspci -vv` shows
`LnkSta: Speed 8GT/s`; `Width x1 (downgraded)` is normal.

## 3. The Hailo runtime — steps 3, 8d, 8a

```bash
sudo apt-get update                       # lists only
sudo apt-get install -y h10-hailort h10-hailort-pcie-driver python3-h10-hailort   # (log)
sudo apt-get install -y dkms                                  # the driver under DKMS (8d)
sudo apt-get install --reinstall -y h10-hailort-pcie-driver   # builds it for DKMS
sudo reboot
```

Check: `hailortcli fw-control identify` shows `HAILO10H` and
`Firmware Version: 5.1.1 (release,app)`; `dkms status` lists `hailo1x_pci/5.1.1`.
Versions must read h10-hailort 5.1.1, h10-hailort-pcie-driver 5.1.1,
python3-h10-hailort 5.1.1-1, dkms 3.2.2-1~deb13u1.

Hold the kernel — the cartridge decision; nothing may move it (8a):

```bash
sudo apt-mark hold linux-headers-6.18.50+rpt-common-rpi linux-headers-6.18.50+rpt-rpi-2712 \
  linux-headers-6.18.50+rpt-rpi-v8 linux-headers-rpi-2712 linux-headers-rpi-v8 \
  linux-image-6.18.50+rpt-rpi-2712 linux-image-6.18.50+rpt-rpi-v8 linux-image-rpi-2712 linux-image-rpi-v8
```

## 4. hailo-ollama — step 4

The GenAI model zoo package, a standalone `.deb`, pinned by hash (4):

```bash
cd /tmp
curl -fLO https://dev-public.hailo.ai/2025_12/Hailo10/hailo_gen_ai_model_zoo_5.1.1_arm64.deb
echo "17d5b476320b72ec199032e7a7b87ba72cb51311d56a9f0604213b7a9056deb9  hailo_gen_ai_model_zoo_5.1.1_arm64.deb" | sha256sum -c
sudo apt-get install -y ./hailo_gen_ai_model_zoo_5.1.1_arm64.deb
```

Bind it to loopback (4, finding 1). The file must be exactly these bytes, **no
newline at the end** — its hash is in the cartridge:

```bash
printf '{\n    "server": {\n        "host": "127.0.0.1",\n        "port": 8000\n    },\n    "library": {\n        "host": "dev-public.hailo.ai",\n        "port": 443\n    },\n    "main_poll_time_ms": 200\n}' \
  | sudo tee /etc/xdg/hailo-ollama/hailo-ollama.json > /dev/null
sha256sum /etc/xdg/hailo-ollama/hailo-ollama.json   # b350ac9ecb75e2376293c281c3f71636f683e84ba6cc55524c54a4f34f3b952b
```

## 5. The model — steps 5, 42b

**Not with `/api/pull`**: a failed pull kills hailo-ollama (42b). Copy it from
Lyra, or download it from Hailo's 5.1.1 table
(`https://dev-public.hailo.ai/v5.1.1/blob/Llama-3_2-3B-Instruct.hef` — the
table's link; we have not fetched it ourselves), then check the hash:

```bash
B=/usr/share/hailo-ollama/models/blob
H=1129f5f8384e4e45c5890104dc4ec1aee77e800ce1484ddc3aa942399aada425
scp andreas@aetherseed.local:$B/sha256_$H /tmp/      # from Lyra (her account is andreas), ~3.4 GB
echo "$H  /tmp/sha256_$H" | sha256sum -c
sudo install -d -o root -g root -m 755 $B
sudo install -o root -g root -m 644 /tmp/sha256_$H $B/sha256_$H
```

Root-owned and read-only to everyone else: hailo-ollama reads the model and
never writes it. (On Lyra the directory belongs to her operator account, a
leftover of fetching models by hand; the cartridge does not hash ownership.)

## 6. The service account and the NPU — steps 6, 8e

```bash
sudo useradd --system --home-dir /var/lib/aetherseed --create-home \
  --shell /usr/sbin/nologin --comment "AetherSeed Companion" aetherseed
sudo groupadd --system hailo
sudo usermod -aG hailo aetherseed
printf 'SUBSYSTEM=="hailo_chardev", MODE="0660", GROUP="hailo"\n' \
  | sudo tee /etc/udev/rules.d/99-aetherseed-hailo.rules > /dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hailo_chardev
```

Check: `stat -c '%a %U:%G' /dev/hailo0` prints `660 root:hailo`, and
`sha256sum /etc/udev/rules.d/99-aetherseed-hailo.rules` gives
`9943a61b6fbc5dfb4c9e7aea5ccb1faeacfc4fe5df671462771ab919f06a6949`. **Install
the one line, not the repository's `services/99-aetherseed-hailo.rules`**: that
file carries a comment header, and Lyra's installed rule does not.

The screen's own account (step 45): an ordinary account with no password, no
shell and no sudo — the kiosk runs as this, never as an admin:

```bash
sudo useradd --create-home --shell /usr/sbin/nologin \
  --comment "AetherSeed Companion screen" --groups video,render,input aetherseed-kiosk
```

## 7. The application — steps 11, 42g

Copy the tag to the unit, from the repository on the PC:

```bash
git archive --prefix=aetherseed-stable/ stable-llama-2026-09-28 | ssh admin@<unit> "tar -x -C ~"
```

On the unit, install the 27 files the build runs from — no more, no fewer —
root-owned and read-only:

```bash
cd ~/aetherseed-stable
sudo install -d -o root -g root -m 755 /opt/aetherseed
tar -cf - proxy.py aetherroot.py aetherspark.py trust_evolution.py intent_detection.py \
  honesty_check.py requirements.txt config/hardware.yaml config/settings.py \
  gui/index.html gui/serve.py knowledge/companion.en.jsonl \
  kiosk/labwc/autostart kiosk/labwc/environment kiosk/labwc/rc.xml \
  logic/__init__.py logic/attribution.py logic/companion.py logic/facts.py logic/knowledge.py \
  logic/prompt_builder.py logic/provenance.py logic/rings.py logic/speaker.py logic/token_budget.py \
  tools/keepalive.py tools/power.py \
  | sudo tar -x -C /opt/aetherseed --no-same-owner
sudo chown -R root:root /opt/aetherseed && sudo chmod -R a+rX,go-w /opt/aetherseed
```

The Python environment: a venv that also sees the system's packages (numpy
2.2.4 comes from the system), with `tokenizers` and what it pulled in on Lyra:

```bash
sudo python3 -m venv --system-site-packages /opt/aetherseed/venv
sudo /opt/aetherseed/venv/bin/pip install tokenizers==0.23.2 huggingface_hub==1.32.0 \
  hf-xet==1.6.0 fsspec==2026.7.0 filelock==4.0.0 httpx==0.28.1 httpcore==1.0.9 \
  h11==0.16.0 anyio==4.15.1 click==8.5.0 typing_extensions==4.16.0
```

The tokenizer (copy it from Lyra and check it):

```bash
scp andreas@aetherseed.local:/var/lib/aetherseed/tokenizer.json /tmp/
echo "6b9e4e7fb171f92fd137b777cc2714bf87d11576700a1dcd7a399e7bbe39537b  /tmp/tokenizer.json" | sha256sum -c
sudo install -o aetherseed -g aetherseed -m 644 /tmp/tokenizer.json /var/lib/aetherseed/tokenizer.json
```

Check the application against the cartridge — this must print
`410d15ac3f8988d65b4e8b1d8b1252abf55579c0b4cb4518368541ea5b88ebfe`:

```bash
cd /opt/aetherseed && find . -path ./venv -prune -o -type f -print | LC_ALL=C sort | xargs sha256sum | sha256sum
```

## 8. The units and the firewall — steps 6, 11, 13d, 14a, 18, 25, 34b

```bash
cd ~/aetherseed-stable
for u in hailo-ollama.service aetherseed-proxy.service aetherseed-warmup.service \
         aetherseed-gui.service aetherseed-kiosk.service aetherseed-keepalive.service \
         aetherseed-shutdown.path aetherseed-shutdown.service; do
  sudo install -o root -g root -m 644 services/$u /etc/systemd/system/$u
done
sudo install -o root -g root -m 644 services/nftables.conf /etc/nftables.conf
sudo systemctl daemon-reload
sudo systemctl enable getty@tty2          # the way out of the kiosk, first (18)
sudo systemctl enable hailo-ollama aetherseed-proxy aetherseed-warmup aetherseed-gui \
  aetherseed-shutdown.path aetherseed-keepalive aetherseed-kiosk
```

The firewall, loaded the way 13d did it — with a dead-man's switch, because a
mistake here locks SSH out *(the two `nft` lines and the enable are the log's;
the rest is written for this guide)*:

```bash
sudo nft -c -f /etc/nftables.conf                      # syntax check
sudo systemd-run --on-active=150 nft flush ruleset     # dead-man's switch (note the unit name it prints)
sudo nft -f /etc/nftables.conf
# now open a NEW ssh session; if it works:
sudo systemctl stop <the run-….timer printed above>    # cancel the switch
sudo systemctl enable nftables
```

## 9. Reboot, and check

```bash
sudo reboot
```

After it: `systemctl --failed` lists nothing; hailo-ollama, the proxy, the
console, the kiosk and the keepalive are active; the screen asks
**"What would you like to call your companion?"** (the first-run screen, 21a).
Lyra's first answer after power-on takes about a minute — the warm-up loading
the model (14a). **Ctrl+Alt+F2** reaches a shell whatever the kiosk does (on an
Apple keyboard, Ctrl+Alt+fn+F2). The keepalive's log is
`/var/lib/aetherseed-keepalive/keepalive.jsonl`.

The screen under its own account was shown on Lyra on 28 Sep (build log
step 45a): this build's kiosk unit, run as `aetherseed-kiosk` on another
console, brought up labwc and Chromium and loaded the console, and its browser
profile was gone when it stopped. If the screen stays black, Ctrl+Alt+F2 and
`journalctl -b -u aetherseed-kiosk`.

The screen: `--force-device-scale-factor=3` in the kiosk unit is fitted to
Lyra's 72-inch television (18e, 19e), and the kiosk's keyboard layout (`gb`,
`pc105`) is in `kiosk/labwc/environment` (34a). Both are part of the
cartridge: changing either for another screen or keyboard is a different
build, and should be recorded as one.

## 10. Verify the cartridge

```bash
cd ~/aetherseed-stable && sudo bash tools/cartridge.sh verify tools/cartridge.manifest
```

`bash` explicitly: the script is not executable in a git archive. It takes
about a minute (it hashes the model). Expect `DRIFT` with **only** the lines in
the table at the top; anything else is a step above that did not take.

## 11. The unit's own state — first run

- **The name**: chosen by the owner on the first-run screen (20d, 21a);
  stored in `/var/lib/aetherseed/.aetherseed/companion.json`.
- **The unit's own knowledge** (`unit.jsonl`, 33c) is optional and per unit:
  every id starts `unit.`, it can add lines and never replace a shipped one.
  Lyra's `units/rd-unit-1.jsonl` says *"I am R&D Unit 1"* — it is Lyra's and
  no other unit's.
- **Memory and trust start empty**: 0 episodes, *observer*, no rings, no owner
  facts (the Genesis facts were for Lyra's soaks).

## Decisions this build carries, not steps

- **The keepalive** (`aetherseed-keepalive`) is an R&D instrument — it holds
  the model resident and logs latency every three minutes. It is enabled in
  this cartridge; a unit without it is a different cartridge (25c).
- **The pilot blockers**, as far as they still stand (build log,
  `claude/pilot-readiness.md`): the kiosk no longer runs as an account with
  sudo (step 45), but the Imager's admin account still has passwordless sudo
  and Ctrl+Alt+F2 offers a login prompt for it; SSH password authentication
  (LAN-only through the firewall); no Chromium lockdown policy.
- **The apt timers run** (they read lists; they do not upgrade a held kernel).
  Whether an appliance should run them is an open decision.
