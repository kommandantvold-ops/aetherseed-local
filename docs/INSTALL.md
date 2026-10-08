# Installing the stable Companion build

**Build:** git tag `stable-llama-2026-10-03` — Llama 3.2 3B on HailoRT 5.1.1,
the one fixed build (Andreas, 29 Sep): the build that ran Lyra through soak 2
(tag `stable-llama-2026-09-27`, build log step 43) **with no person's account in
it** (step 45), **trust paid only for a decline of what it was not given**
(step 46 — and, since step 49, not when one of its own `[Known]` lines was in
front of it), **what it knows about AetherSeed and itself** (the ecosystem
lines, summarize, writing at reader — step 48), **a refused request told as
refused and its trust level answered from the gate** (step 49), and **the
ecosystem soak in `training/`**, for a pilot or the steward to run at will
(step 49; `training/README.md`), **the steward, not the owner** — in the
prompt, the console (*forvalter* in Norwegian) and its own knowledge — and
**guided correction** on the console: the steward marks a turn or a ring as
right, or corrects it, and can undo (step 50), and **the to-do list shown from
the file** (step 51), and **a screen that waits for the network and is
restarted if the console is not on it** (step 53 — a pilot unit had come up on
a blank page). The kiosk runs as its own account, `aetherseed-kiosk`, and the
keepalive as the service account. Installed on Lyra on 3 Oct (step 53); the
previous tags: `stable-llama-2026-09-30b` (step 51, the build the two pilot
units were first installed from), `stable-llama-2026-09-30` (step 49),
`stable-llama-2026-09-29` (step 47).
**Cartridge:** `211f3310d9625f06f4edf8b89e9f3ec3dd483064d8a2bde7c762e898b8f3ccea`
— Lyra's capture of this build (`2d9a73c6`, MATCH) with the three lines of the
unserved second model she still holds removed (`tools/cartridge.manifest` says
which). **Two units have been built from this guide** (30 Sep and 3 Oct 2026,
build log 52), at `stable-llama-2026-09-30b`: both verified with exactly the
two expected lines differing, and carried the same cartridge id as each other
(`5ab3c8e7…` at that tag).

Written 27 Sep 2026 from the build log, the repository at the tag, and a
read-only snapshot of Lyra running this build
(`.scratch/step44/stable-reference-2026-09-27/`). Every file and value below was
checked against Lyra. Commands marked *(log)* are the build log's own; the rest
were written for this guide from Lyra's state. **Every command here has now
been run on two fresh devices** (build log 52), and where they showed the
guide wrong it has been corrected in place.

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
  `aetherseed`); SSH on; Wi-Fi country NO. If SSH was left off: on the unit,
  `sudo systemctl enable --now ssh`. The Imager's admin account asks for its
  password on `sudo` (Lyra's did not); nothing in the build depends on either.
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
`Firmware Version: 5.1.1 (release,app)`; `sudo dkms status` lists
`hailo1x_pci/5.1.1` (`dkms` is in `/usr/sbin`, not on an ordinary account's path).
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

**Not with `/api/pull`**: a failed pull kills hailo-ollama (42b). **Copy it
from Lyra** (or from a copy of hers whose hash you have checked), then check the
hash. **Not from Hailo's 5.1.1 table**: its link
(`https://dev-public.hailo.ai/v5.1.1/blob/Llama-3_2-3B-Instruct.hef`) serves a
file of the same size, 3,370,416,230 bytes, with a **different** hash —
`7fc9c772…`, fetched 30 Sep (build log 52). It is not this build's model.

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
git archive --prefix=aetherseed-stable/ stable-llama-2026-10-03 | ssh admin@<unit> "tar -x -C ~"
```

On the unit, install the 37 files the build runs from — no more, no fewer —
root-owned and read-only:

```bash
cd ~/aetherseed-stable
sudo install -d -o root -g root -m 755 /opt/aetherseed
tar --exclude=__pycache__ -cf - proxy.py aetherroot.py aetherspark.py trust_evolution.py intent_detection.py \
  honesty_check.py requirements.txt config/hardware.yaml config/settings.py \
  gui/index.html gui/serve.py knowledge/companion.en.jsonl \
  kiosk/labwc/autostart kiosk/labwc/environment kiosk/labwc/rc.xml \
  logic/__init__.py logic/attribution.py logic/companion.py logic/facts.py logic/gate_answers.py \
  logic/knowledge.py logic/prompt_builder.py logic/provenance.py logic/rings.py logic/speaker.py \
  logic/steward.py logic/token_budget.py tools/keepalive.py tools/kiosk_watch.sh tools/power.py \
  training/README.md training/run-ecosystem-soak.sh training/ecosystem_soak.py \
  training/ecosystem-probes.json training/ecosystem-workspace \
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
`db2902f0fdd717af0ebca5a150367a11e0c5b05166d33d1ae547d3b739d5497d`:

```bash
cd /opt/aetherseed && find . -path ./venv -prune -o -type f -print | LC_ALL=C sort | xargs sha256sum | sha256sum
```

## 8. The units and the firewall — steps 6, 11, 13d, 14a, 18, 25, 34b

```bash
cd ~/aetherseed-stable
for u in hailo-ollama.service aetherseed-proxy.service aetherseed-warmup.service \
         aetherseed-gui.service aetherseed-kiosk.service aetherseed-kiosk-watch.service \
         aetherseed-keepalive.service \
         aetherseed-shutdown.path aetherseed-shutdown.service; do
  sudo install -o root -g root -m 644 services/$u /etc/systemd/system/$u
done
sudo install -o root -g root -m 644 services/nftables.conf /etc/nftables.conf
sudo systemctl daemon-reload
sudo systemctl enable getty@tty2          # the way out of the kiosk, first (18)
sudo systemctl enable hailo-ollama aetherseed-proxy aetherseed-warmup aetherseed-gui \
  aetherseed-shutdown.path aetherseed-keepalive aetherseed-kiosk aetherseed-kiosk-watch
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

The screen: the kiosk runs at scale 3, fitted to Lyra's 72-inch television
(18e, 19e), unless the unit says otherwise (step 63). A monitor at arm's
length wants less — one line, and the unit file stays the build's:

```bash
sudo install -d -m 755 /etc/aetherseed
echo "AETHERSEED_SCALE=1.5" | sudo tee /etc/aetherseed/kiosk.env     # Stella's, 5 Oct
sudo systemctl restart aetherseed-kiosk
```

The cartridge records the scale a unit runs at (`kiosk.scale`), so two units
of one build that differ in it differ on that line and say in what. The
kiosk's keyboard layout (`gb`, `pc105`) is in `kiosk/labwc/environment`
(34a) and is part of the cartridge: changing it for another keyboard is a
different build, and should be recorded as one.

## 10. Verify the cartridge

```bash
cd ~/aetherseed-stable && sudo bash tools/cartridge.sh verify tools/cartridge.manifest
```

`bash` explicitly: the script is not executable in a git archive. It takes
about a minute (it hashes the model). Expect `DRIFT` with **only** the lines in
the table at the top; anything else is a step above that did not take.

## 11. The unit's own state — first run

- **The name**: chosen by the steward on the first-run screen (20d, 21a);
  stored in `/var/lib/aetherseed/.aetherseed/companion.json`.
- **The unit's own knowledge** (`unit.jsonl`, 33c) is optional and per unit:
  every id starts `unit.`, it can add lines and never replace a shipped one.
  Lyra's `units/rd-unit-1.jsonl` says *"I am R&D Unit 1"* — it is Lyra's and
  no other unit's.
- **Memory and trust start empty**: 0 episodes, *observer*, no rings, no steward
  facts (the Genesis facts were for Lyra's soaks).

## 12. Training — the ecosystem soak, whenever you like (step 49)

The build carries a check of what the companion knows about AetherSeed and
itself — what AetherRoot and AetherSpark are, where its workspace, to-do list
and notes are, the trust ladder, summarize — run on a **copy** of its memory,
never on the memory itself:

```bash
sudo bash /opt/aetherseed/training/run-ecosystem-soak.sh 1      # hours
```

It returns at once, runs as the service account, and writes a report to
`/var/lib/aetherseed/training/ecosystem-<time>/report.txt` when the time is up.
Her answers are slower while it runs (it shares the model): run it when she is
not in use. `training/README.md` says what it touches, what it does not, and how
to read the report. First run on Lyra: 30 Sep, build log 49.

## 13. The unit's own Wi-Fi — a phone as a second screen (steps 54 and 60, after the tag)

**Not in tag `stable-llama-2026-10-03`.** On `main` since build log 54; on the
pilot units Stella and Xena since 4 Oct as step 54 made it (**up at every
start, cable or no cable**). The rule below is build log 60's; build log 60
says which units run it.

What it is: the unit puts up a Wi-Fi network named after the companion, with a
passkey the steward chooses. A phone or laptop that joins it opens the console
at **`http://10.42.0.1:2077`** — the same page as the unit's own screen.
The phone will say the network has no internet; that is right, it leads to the
console and nowhere else. The console is **not** reachable on the cable
network. Quantum rest can be asked for from the phone as from the unit's own
screen (step 63 — Andreas, 5 Oct: *"I need a way to initiate quantum rest
from the phone or laptop"*; until then it was at the unit only).

**The rule (step 60).** Andreas: *"I want the wifi update, but with only
transmission when lan is disconnected."* While a network cable has a link the
radio is **switched off**; when no cable has one, the unit's Wi-Fi comes up —
at start, and within seconds of the cable being pulled. A link is the
cable's own (the port's carrier), not whether the network behind it answers.
`aetherseed-hotspot.service` applies it. So with a cable in, a phone cannot
be the screen: the console on a cable network (with a passkey of its own) is
decided and not built.

Five files, from a checkout of `main` (`~/aetherseed-main` here):

```bash
cd ~/aetherseed-main
sudo install -o root -g root -m 644 gui/serve.py     /opt/aetherseed/gui/serve.py
sudo install -o root -g root -m 755 tools/hotspot.sh /opt/aetherseed/tools/hotspot.sh
sudo install -o root -g root -m 644 services/aetherseed-gui.service /etc/systemd/system/
sudo install -o root -g root -m 644 services/aetherseed-hotspot.service /etc/systemd/system/
sudo install -o root -g root -m 644 services/nftables.conf /etc/nftables.conf
sudo nft -c -f /etc/nftables.conf && sudo nft -f /etc/nftables.conf
sudo systemctl daemon-reload && sudo systemctl restart aetherseed-gui
```

Then, once the companion has its name, set the network up. The passkey is
typed at the prompt (8–63 plain characters) and is kept nowhere but in the
unit's own network profile. No other Wi-Fi network may be saved on the unit
(`nmcli connection show`): it would be joined instead.

```bash
sudo /opt/aetherseed/tools/hotspot.sh on        # named after the companion
/opt/aetherseed/tools/hotspot.sh status         # set up, up or not, and the rule
sudo /opt/aetherseed/tools/hotspot.sh off       # takes it down and removes it
```

`on` undoes one line of step 2: `wpa_supplicant` is enabled again (the access
point needs it). Whoever holds the passkey is at the console — it is the
steward's, like the screen.

**A unit set up under step 54** (Stella, Xena) gets the rule without its
passkey being typed again: install `tools/hotspot.sh` and
`services/aetherseed-hotspot.service` as above, then

```bash
sudo nmcli connection modify aetherseed-hotspot connection.autoconnect no
sudo systemctl daemon-reload && sudo systemctl enable --now aetherseed-hotspot
```

**The offline proof** (`training/run-offline-proof.sh`) needs every radio off
with the cable out, which this rule prevents; the runner says how to hold the
rule for the length of the proof.

## 14. Nothing the unit starts leaves it (step 55, after the tag)

**Not in tag `stable-llama-2026-10-03`.** On `main` since build log 55, and on
Lyra since 4 Oct. Andreas: *"nothing at all should go out."* Until this step
the firewall filtered only what came in. Measured on Lyra that day, cable in:
the screen's browser held connections to Google, the clock was synced over the
network, package lists were fetched daily, and the unit announced itself.

What it does: the firewall's **output chain drops everything the unit starts**
and names in the journal whatever tried (`aetherseed out-drop:`); the browser
gets a managed policy (the console and nothing else) and can look up no name;
the clock asks nobody; avahi and the two `apt` timers are off. Still let out,
because without them the unit cannot be reached at all: loopback, answers on
connections opened *to* the unit (SSH, the console from its own Wi-Fi), the
address lease, IPv6 neighbour discovery.

**Do this last.** After it the unit can fetch nothing — every step above that
needs the network (3–7) must be done. From a checkout of `main`:

```bash
cd ~/aetherseed-main
sudo install -d -m 755 /etc/systemd/timesyncd.conf.d /etc/chromium/policies/managed
sudo install -o root -g root -m 644 services/timesyncd-aetherseed.conf /etc/systemd/timesyncd.conf.d/aetherseed.conf
sudo install -o root -g root -m 644 kiosk/chromium-policy.json /etc/chromium/policies/managed/aetherseed.json
sudo install -o root -g root -m 644 services/aetherseed-kiosk.service /etc/systemd/system/
sudo systemctl disable --now avahi-daemon.socket avahi-daemon.service apt-daily.timer apt-daily-upgrade.timer
sudo rfkill block bluetooth       # and `wlan`, unless the unit's own Wi-Fi (§13) is set up
sudo systemctl daemon-reload && sudo systemctl restart systemd-timesyncd
sudo install -o root -g root -m 644 services/nftables.conf /etc/nftables.conf
sudo nft -c -f /etc/nftables.conf                      # syntax check
sudo systemd-run --on-active=300 nft flush ruleset     # dead-man's switch, as in step 8
sudo nft -f /etc/nftables.conf
# open a NEW ssh session; if it works, stop the run-….timer printed above
sudo systemctl restart aetherseed-kiosk
```

Check, from the unit: `curl -m 4 http://1.1.1.1/` fails, `getent hosts
example.com` fails, and both show in `sudo journalctl -k | grep out-drop` and
in the counter of `sudo nft list chain inet filter output`. `sudo ss -tunp`
shows no socket to anything off the unit but the address lease and your own
SSH session.

**The clock.** It is no longer corrected. `systemd-timesyncd` stays on only to
save the time every minute and resume from it at start, so a unit that was
unplugged is behind by as long as it was off. The board keeps time through a
power cut only with a battery on its RTC connector; set the clock by hand
otherwise (`sudo date -s "2026-10-04 12:00:00"`). The model is
told the date from this clock.

**To let the unit out for maintenance**, until the next reboot or firewall
reload: `sudo nft insert rule inet filter output accept`.

### A unit that goes to a pilot home: SSH by key only (step 63)

Andreas, 5 Oct, on the pilot units: *"leave the ssh open on the pilots"* —
*"only you and me should be able to have access, once the units have
finished their pilot test we need to be able to work on them … in the final
build there will be no access like that, but for now in testing it is
wise."* So, on a pilot unit, once the key of whoever is to reach it is in the
admin account's `~/.ssh/authorized_keys`:

```bash
printf '%s\n' 'PasswordAuthentication no' 'KbdInteractiveAuthentication no' \
  | sudo tee /etc/ssh/sshd_config.d/01-aetherseed-key-only.conf
sudo sshd -t && sudo systemctl reload ssh
# from another terminal, BEFORE closing this one: a login by key works, and
#   ssh -o PubkeyAuthentication=no <admin>@<unit>   is answered "Permission denied (publickey)"
```

A keyboard at the unit still logs in (Ctrl+Alt+F2) with the admin account's
password; that is the way back in if the key is lost. To undo: remove the
file, `sudo systemctl reload ssh`. Not part of the cartridge: it is the
pilot's arrangement, and the final build has no such access at all.

## 15. The library — passages shown word for word (steps 57 to 59, after the tag)

**Not in tag `stable-llama-2026-10-03`.** On `main` since build log 57, and on
Lyra since 4 Oct. Andreas, pointing at Project NOMAD: *"A library she answers
from with a knowledge base like that of nomad (content) so it can be a
disaster relief and offgrid rural survival aid."* And, build log 58:
*"Navigation, how to stay alive in different disasters. Like flooding,
drought, storms, tundras etc. basic survival knowledge for most environments
and disasters. Like what you learn in the boyscouts or at bootcamp."*

A **collection** is one file, made from Kiwix ZIMs with
`tools/library_build.py` **off the unit** (the unit can fetch nothing, step
55; the converter needs `libzim` and `pdftotext`, the unit needs neither).
A whole ZIM becomes one collection; or a recipe in `library/` says what is
taken — chosen documents of several ZIMs, or one site without some of its
pages. The recipe is the record of what was taken and what was left out:

```bash
pip install libzim                                    # where the collection is built
python3 tools/library_build.py nhs.uk_en_medicines_2025-12.zim nhs.uk_en_medicines_2025-12.lib.sqlite
python3 tools/library_build.py zimgit-water_en_2024-08.zim     zimgit-water_en_2024-08.lib.sqlite
python3 tools/library_build.py --recipe library/ready-gov.json        ZIM_DIR www.ready.gov_en_2024-12.lib.sqlite
python3 tools/library_build.py --recipe library/us-field-manuals.json ZIM_DIR us-field-manuals_2026-10.lib.sqlite
```

The four on Lyra, built 4 Oct from `download.kiwix.org` (the build is
repeatable — the same sources and recipe give the same file; each was built
twice):

| collection | source ZIM (sha256) | collection file (sha256) |
|---|---|---|
| NHS Medicines A to Z, 2025-12 — 1996 pages, 12712 passages | `nhs.uk_en_medicines_2025-12.zim` `7dfa9bff…ef3dae28` | `9002055c…1fe1eff28` |
| Water Treatment Library, 2024-08 — 7 documents, 921 passages | `zimgit-water_en_2024-08.zim` `392c7bc9…75cb56b6` | `184c6fe9…b466d3bd` |
| Ready.gov, 2024-12 — 166 pages, 849 passages (`library/ready-gov.json`) | `www.ready.gov_en_2024-12.zim` `5bb4cf0d…faec0439` | `88025f1c…5eb4dd4b6` |
| US military field manuals — 8 documents, 3733 passages (`library/us-field-manuals.json`) | `zimgit-post-disaster_en_2024-05.zim` `0ba9bb35…cce174f8`, `armypubs_en_all_2024-12.zim` `f34f1bcb…b2d11f04` | `8b9d3a3a…5ecd2eea` |

The first two were rebuilt in step 58 with the same converter as the others
(a row that is only a link is left out; a PDF's headings are found on every
line), so their files differ from step 57's (`ce12e33b…`, `a8af85fe…`). The two made
from PDFs were built once more in step 59 (a bullet on a line of its own is
left out), so they differ from step 58's (`c36ee6bc…`, `6e98e9d8…`).

**What the field-manuals collection holds**, and under what statement:
*How To Find Your Way* (GTA 05-02-013), *First Aid* (TC 4-02.1, 2016),
*Soldier's Handbook for Individual Operations and Survival in Cold-Weather
Areas* (TC 21-3, 1986), *Unit Field Sanitation Teams* (ATP 4-25.12, 2014) and
chapter 1 and appendix A of *Desert Operations* (ATP 3-90.99, 2021) — each
marked "Approved for public release; distribution is unlimited"; and the US
Marine Corps Mountain Warfare Training Center's *Summer Survival Course*,
*Winter Survival Course* and *Wilderness Medicine Course* handbooks (2002),
which carry no distribution statement. **Not taken:** FM 3-05.70 *Survival*
(2002), marked "Distribution authorized to U.S. Government agencies and
their contractors only", and the reformatted copy of it on the same Kiwix
shelf; the commercial books on that shelf; the fighting chapters of *Desert
Operations*. Build log 58 lists every document looked at and left out.

On the unit (from a checkout of `main`, the collection files carried to it):

```bash
sudo install -o root -g root -m 644 logic/library.py /opt/aetherseed/logic/library.py
sudo install -o root -g root -m 644 proxy.py /opt/aetherseed/proxy.py
sudo install -o root -g root -m 644 gui/index.html /opt/aetherseed/gui/index.html
sudo install -o root -g root -m 644 training/library_check.py training/library-probes.json /opt/aetherseed/training/
sudo install -d -o root -g root -m 755 /var/lib/aetherseed/library
sudo install -o root -g root -m 644 *.lib.sqlite /var/lib/aetherseed/library/
sudo systemctl restart aetherseed-proxy aetherseed-gui aetherseed-kiosk
/opt/aetherseed/venv/bin/python3 /opt/aetherseed/training/library_check.py
```

What she does with it: asked to (*"look up paracetamol for adults"*, *"what
does the library say about …"*) she shows the best passage, word for word,
with its source — or says the library has nothing. Unasked, she shows a
passage only when the library is sure the question is its own
(`logic/library.py` says how), and never for a question about her or about
what she was told. *"more"* shows what follows. *"What is in the library?"*
lists it. When she answers a question herself and one passage of the library
says every word of it, the console adds under her answer: *"not from the
library — say 'look it up' to search it"*; and *"look it up"*, after any
answer of her own, asks the library the question just asked (step 59). The model is not called for any of this, and none of it is stored
as something she said. A unit with no collection behaves as before.

**What it cannot do.** It matches words, not meaning. Unasked it misses a
question whose words the section does not say (*"How do I splint a broken
arm?"* — the manual says "fracture"), and it can show a passage that says
the words and does not answer (*"How do I stop bleeding?"* is shown a
medicine's side effects). `training/README.md` has the measured numbers.

**Licences.** The NHS, Water and Ready.gov source files state none, and none
of the three has been checked. For a unit that leaves, each collection's
licence has to be checked and passed to the converter (`--licence`, or the
recipe's `licence`); it is kept in the file.

## 16. The steward's own documents — upload and look up (step 62, after the tag)

Not part of the tag `stable-llama-2026-10-03`. It is on `main`, and on Lyra
since 5 Oct. Andreas: *"a file upload button in the gui, that adds documents
to the library/workspace, and a way for Lyra to process that information.
Lets say I want to upload a pdf on basic physics so Lyra can help me study."*

No new package: `pdftotext` and `pdfinfo` (poppler-utils — a PDF's text,
page by page) are in the Raspberry Pi OS image this build starts from, where
the printing system brings them; on Lyra `25.03.0-5+deb13u4`, and among the
packages the cartridge counts. Check, then four files more than §15 installs:

```bash
which pdftotext pdfinfo                        # both, or: sudo apt-get install -y poppler-utils
sudo install -o root -g root -m 644 logic/own_shelf.py logic/library.py /opt/aetherseed/logic/
sudo install -d -o root -g root -m 755 /opt/aetherseed/tools
sudo install -o root -g root -m 644 tools/library_build.py /opt/aetherseed/tools/library_build.py
sudo install -o root -g root -m 644 proxy.py /opt/aetherseed/proxy.py
sudo install -o root -g root -m 644 gui/index.html gui/serve.py /opt/aetherseed/gui/
sudo systemctl restart aetherseed-proxy aetherseed-gui aetherseed-kiosk
```

`tools/library_build.py` is the converter of §15, now on the unit too: a
document the steward adds is read with the same code the built-in
collections are made with (it asks for `libzim` only when a ZIM is opened,
and none is on the unit). Without `poppler-utils` the unit takes text files
and refuses PDFs, saying why.

**Adding a document.** *Documents* in the console's header, from a phone or
a laptop on the unit's Wi-Fi (§13: `http://10.42.0.1:2077`, with the cable
out). On the unit's own screen the list is shown and the way to add is told:
its browser is locked and opens no file dialog (`kiosk/chromium-policy.json`).
A PDF or a UTF-8 text file (`.pdf`, `.txt`, `.md`), up to 60 MB and 2000
pages, forty documents. It is kept as it came and read into a collection of
its own under `/var/lib/aetherseed/aetherseed-shelf/` — the proxy's state
directory, beside the workspace; the console server relays it and writes
nothing. The cartridge does not describe the shelf: it is the steward's,
like the memory.

**What she does with it.** It is part of the library of §15: *"look up
momentum in my book"* (or just *"look up momentum"*) shows the passage word
for word, with the document's name, its section and its page; a section
asked for by its name opens at its beginning, and *"more"* walks on.
Unasked she shows a passage of it only by the rule of §15.

**"explain that" is built, and off.** Under a passage of his own document,
*"explain that"* — or *"explain that: why is it negative?"* — would give the
model that one passage and his question, and nothing else: no memory, no
ring; the answer labelled on the console as her own words about the passage,
and stored as unverified (never in a ring — Andreas, 5 Oct: *"set aside"*;
since step 64, when nothing is set aside any more, it can come back into a
later prompt only under the tag *"[Unverified - an earlier answer of yours
that may be wrong]"*). Shown what was
read by hand (below), he said: ***"leave it off"***. So in this build she
answers *"explain that"* after a passage as she does for the built-in
library, which is never retold: the passage stays word for word. It is on
only where the proxy's environment says `AETHERSEED_EXPLAIN=1`; no unit file
says it, and `training/shelf_check.py --explain` sets it for a copy, so that
a later model can be measured the same way.

**What it cannot do.** Her explanations could not be relied on, which is why
they are off. Read by hand on
Lyra, of 18 explanations of passages of a physics textbook 7 were right, 9
said something the passage does not or denied something it does (a 120-watt
bulb for its 100-watt one; that the puck "moves randomly"; once the opposite
of the passage), one said nothing and one left the passage for "general
knowledge". Two other ways of
handing her the passage did no better, and in both she named a film the
passage does not name. Where it is turned on, the console labels every
explanation *"her own words about the passage above — not the document's;
check them against it"*. An explanation is two or three sentences — the
bounds on every answer of hers (step 13).

A scan — pictures of pages — has no words and is refused with that reason.
Formulas come out of a PDF flat: `E = mc2` for E = mc², `3.2 × 106` for
3.2 × 10⁶, a fraction as two lines; they are shown so, and she is given them
so (asked how many grams are in a kilogram, she once read the book's 10³ g
as "103 g (one hundred three grams)"). Headings are found when they are in
capitals, when a "Chapter N" line stands over them, or when they carry a
section number (`1.7 Equivalence of mass and energy`); in a book of another
make the passages are found by their words but may stand under the wrong
heading or none. A chapter's problems are filed under its last section.
`training/shelf_check.py` tries a document on a copy of her memory
(`training/README.md`).

## 17. Tags instead of set aside, her steward's name, and the training loop (step 64, after the tag)

Not part of the tag `stable-llama-2026-10-03`. It is on `main`. Andreas,
6 Oct 2026: *"None of Lyras memories should be set aside, all memories
should be properly tagged, and Lyra should be able to see the tags and the
corrections made by the steward. Lyra should know who her steward is (me)
and I want her to do a training loop where she trains her accuracy and tool
layer. Which means she needs homework, higher trust level, a self
reflection, and repeat, a self augmenting training loop. This should be
pausable and playable from the phone gui so I can see the progress and run
it multiple times. The loop should last about 4 hours, and have tasks for
each trust level."*

No new package. The files, beyond §16's:

```bash
sudo install -o root -g root -m 644 logic/training.py logic/exact_tools.py logic/provenance.py \
    logic/steward.py logic/companion.py logic/speaker.py logic/knowledge.py logic/gate_answers.py \
    logic/prompt_builder.py logic/token_budget.py /opt/aetherseed/logic/
sudo install -o root -g root -m 644 proxy.py aetherroot.py intent_detection.py /opt/aetherseed/
sudo install -o root -g root -m 644 knowledge/companion.en.jsonl /opt/aetherseed/knowledge/
sudo install -o root -g root -m 644 gui/index.html gui/serve.py /opt/aetherseed/gui/
sudo install -o root -g root -m 644 training/training_check.py training/shelf_check.py \
    training/rescore.py /opt/aetherseed/training/
sudo systemctl restart aetherseed-proxy aetherseed-gui aetherseed-kiosk
```

The first start adds one column to her memory (`steward_notes.by`: whose
note it is). Nothing else in it is changed by installing.

**Nothing is set aside.** Every turn she has stored comes back to her when
it fits the question - also a story, an answer that gave a source she could
not have had, and a turn that was corrected. What is not plain fact comes
back with a tag in front of it: `[Fiction, written at your request - not
fact]`, `[Unverified - an earlier answer of yours that may be wrong]`,
`[Corrected by your steward - what is true: ...]`, `[Marked right by your
steward]`. A line in her prompt says what a tag asks of her. Three things
are as they were: a ring is still made from plain factual turns only; a
tagged line is not evidence - the check for invented sources reads her
memory without them; and nothing is deleted. **A corrected turn comes back
as its question and its correction, without the answer that was wrong**,
and when that very question is asked again it comes back first: shown her
wrong answer beside the correction, she copied the wrong answer (read on a
copy, 6 Oct). Her wrong words stay in the store and in the console's memory
view. A tagged line that the model recites inside an answer is cut there,
like the block markers (step 14). The console's header reads
*"5982 remembered · 622 of them tagged"*. Asked *"What have you been
corrected on?"* she answers from the notes themselves, counted and quoted,
model not called.

**Who her steward is.** The unit's own setting, beside the companion's name
(`companion.json`), never the build's: at first run (an optional field), or
later under *Training* on the console. It adds one line to the charter -
`Your steward is <name>.` - and the unit itself answers *"Who is your
steward?"*. Nobody else can declare that name as a speaker. It is declared,
not verified: nothing on the unit can tell who is at the screen.

**Three tools at builder**, answered by the unit word for word: *"Calculate
12 * (7 + 5)"*, *"Count the words in notes.md"* / *"How many times does the
word seed appear in notes.md?"*, *"Compare a.txt and b.txt"*
(`logic/exact_tools.py`). No shell and no Python is reachable from a
conversation, as before; the arithmetic is read by a parser of its own and
nothing typed is ever run. Below builder she says she cannot yet. *"What is
17 times 23?"* is a question, and goes to the model as it always did.

**What a tool did is told by the unit** (64e; Andreas, 6 Oct: *"Yes"*).
A to-do that was added, a note that was saved, a file list, a search and
the list of notes are answered from the tool's own output, word for word,
model not called - as the to-do list and the refusals already were:
*"Added to your to-do list: Call Martin"*, *"Saved as a note:
notes/note_20261006_194519.md"*, *"I have 1 note, in the notes folder of my
workspace: …"*. On two runs of the loop on copies the file was right every
time and her words about it were not (a to-do retyped with another number,
a note's file name of her own making, readings from the Song of Songs
listed as the to-do). Such an answer is not stored as a turn, so last
week's list cannot come back as today's. Since step 65 a file asked for and
nothing else (*"Read seed.txt"*, *"Show me notes.md"*) is read out by the
unit too, to its first 1500 characters, and *"What are your trust levels,
in order?"* is answered from the gate. A question ABOUT a file, and
summarizing one, are still the model's. Two notes written in the same second are two
notes.

**The training loop.** *Training* in the console's header - the unit's own
screen, or a phone on its Wi-Fi (§13): **Play** starts a run of about four
hours, **Pause** stops after the question in hand, **Go on** continues
there, **Stop** ends the run. The screen shows the round, the level lent,
the question in hand, the last check and why it failed, the score at each
level, what each round *would have earned*, what she said after it, and the
runs before this one. A run that the unit's restart cuts off comes back
paused.

- A run is rounds of six stages - observer, reader, writer, builder,
  collaborator, autonomous - and after each round she is told how it went
  and asked to say again, in her own words, what she got wrong (step 65,
  below). About ninety-four checks in a first round, of which the model
  answers some forty-two and the unit the rest; fewer later, as questions
  she has had right three times running are asked only every fourth round.
- **The level is lent, not given.** Each task runs at its stage's level for
  the length of that one turn, in a workspace of the loop's own
  (`~/.aetherseed/training/workspace`), with its own audit log. Her real
  level is untouched, a run adds and takes no trust, and nothing is written
  among the steward's files. What a round would have earned - the highest
  level whose stage, and every stage under it, reached 80% **of her own
  answers**, with every answer of the unit's right - is shown and changes
  nothing.
- **What it leaves in her memory.** What she says about herself and her
  ecosystem, as the Trainer's (not the steward's); they wait for no ring.
  One checked turn for each wording of a question, and no more (step 65):
  a wording her memory already holds a checked turn of is asked and scored
  but not stored again, and neither is a question asked again after a
  correction. One that failed the check is corrected
  from the answer key and comes back as `[Corrected in training - what is
  true: ...]`; one that passed as `[Passed a check in training]`. A
  question she got wrong is asked again next round in the same words, up
  to three times; still wrong, it is left for the rest of the run and named
  on the screen as not learned. The screen counts both. Her reflection is
  kept as her own unchecked words, tagged unverified.
  **An answer about what a file held is tested and not remembered**: come
  back later, last round's to-do was told as this round's. Her memory is
  copied whole before each run (`~/.aetherseed/training/backup/`, the last
  three kept).
- **What it is not.** The model's weights do not change; nothing on the
  unit trains them. The check reads for words of an answer key - it can
  pass a wrong answer it did not foresee and fail a right one. Every turn of
  a run is kept to be read (`~/.aetherseed/training/runs/<n>/turns.jsonl`).
  Reader and writer open the same tools in this build, and collaborator and
  autonomous open none beyond builder (the network is off): their stages
  test longer chains, refusing what cannot be done, and a mixed exam.

**After her first two runs (step 65, 7 Oct 2026).** Two runs of four hours
on Lyra, 28 rounds, 1184 answers of her own. Three things were read out of
them, and the build was changed for each:

- *Most of what was failed was a tag, not an answer.* 75 of 172 failures
  were right but for a tag word of her memory inside the sentence - *"A
  [Known] cartridge is one fixed build"* - thirteen of them opening with a
  correction's whole tag, which the stream let go of half-way through. It
  grew by the round: each such answer was stored, came back, and was copied.
  A tag word she says inside an answer is now taken out before the answer
  is shown or stored (`[Known]`, `[Corrected]`, `[Unverified]`, `[Fiction]`,
  `[Passed]`, `[Pattern]`; a line of her memory shown to her has them taken
  out of her old answers too), and a correction's tag at the front is held
  until its bracket closes, however long it is. `[Unknown]` is left: she
  writes it where she does not know, and it is hers. **A correction she
  says inside an answer keeps what is true**: asked which country AetherSeed
  is from, she began *"AetherSeed AS is from [Corrected in training - what
  is true: AetherSeed AS is a Norwegian company…"* - what her prompt asks,
  wrapper and all - and until now the answer was cut at the bracket. The
  wrapper is taken off and the true words stand, where they bear on the
  question asked; a correction of something else is taken out whole. A run
  records when a right answer is the key's sentence said back word for word
  (`recited`).
- *A right answer came back to her as "may be wrong".* A turn the build's
  own reading had kept as unverified, and that then passed the check (or
  was marked right by her steward), still carried `[Unverified - an earlier
  answer of yours that may be wrong]`. Read on a copy: *"My lowest trust
  level is Observer"* passed, came back so tagged, and asked again she said
  *"Reader"*. A mark now outranks "unverified": such a turn comes back as
  `[Passed a check in training]` or `[Marked right by your steward]`. A
  story stays a story whoever marks it.
- *The key failed right answers.* *"I won't be talked into forgetting it"*
  was failed for having no "no" in it; the question on the order of the
  trust levels she had right 14 times in 42, and its key asked for a word
  the build itself spells otherwise. The keys that did so were repaired,
  the order of the levels is now the unit's to say, and eight questions
  were added.
- *Asking again did not teach.* After a failure of substance she was right
  the next time in 45 of 71 askings; what she did not get then, she was
  asked round after round to the end of the run. Hence the three-times rule above, the one-turn-per-wording rule,
  and a reflection that is no longer "what will you do differently" (which
  got the same paragraph 28 times) but, for two things at most and each in
  a turn of its own: *"One you had wrong: … What is true: … Say that again
  in your own words, in one sentence."* - checked against the same key and
  counted on the screen; said right it is remembered as passed, otherwise
  as unverified.

**Do not hold a new run against an old run's own figure.** The old runs
gave 86.7 % and 84.3 % of her own answers right. Read again with this
build's key and with the tag words taken out as this build takes them out,
the same answers give about 96 %:

```bash
python3 -B training/rescore.py ~/.aetherseed/training/runs/001 ~/.aetherseed/training/runs/002
```

That figure, not 85, is what a run under this build starts from. A run now
also records, for each of her own turns, the memory block she was shown
(`shown` in `turns.jsonl`), so that a wrong answer can be read beside what
she had in front of her.

Before a run on her own memory, try the loop on a copy and read what she
said (`training/README.md`):

```bash
sudo systemd-run --unit=aetherseed-training-check --uid=aetherseed --gid=aetherseed \
    --property=WorkingDirectory=/var/lib/aetherseed \
    /opt/aetherseed/venv/bin/python3 -B /opt/aetherseed/training/training_check.py \
    --dir /var/lib/aetherseed/training/loop-$(date +%Y%m%d-%H%M) --rounds 2
```

## 18. A unit onboarded where it will live: the first start, and a source card (step 66, after the tag)

Not part of the tag `stable-llama-2026-10-03`. It is on `main`. Andreas,
7 Oct 2026: *"Onboarded on-site means the user will pick name passkey and
start it for the first time"* - and: *"install a fresh build on the pi on
the 4th pi ... and that sd card will be copied for new pilot units. Lyra
stays the separate R&D unit."*

Until this step a unit's own Wi-Fi was set up at a shell (§13) and its clock
by the network it was built on. A unit that is copied from a card and opened
in someone's home has no shell, no network that tells it the time (§14) and
no battery on its clock.

Two more files in the application, and three units:

```bash
cd ~/aetherseed-main
sudo install -o root -g root -m 644 gui/index.html gui/serve.py /opt/aetherseed/gui/
sudo install -o root -g root -m 755 tools/first_start.sh tools/source_card.sh /opt/aetherseed/tools/
for u in aetherseed-first-start.path aetherseed-first-start.service aetherseed-new-identity.service; do
  sudo install -o root -g root -m 644 services/$u /etc/systemd/system/$u
done
sudo systemctl daemon-reload && sudo systemctl restart aetherseed-gui aetherseed-kiosk
```

Installing them changes nothing on a unit that is already set up: nothing
is enabled, and nothing is armed.

**The first start.** On a unit that is *armed* (`/etc/aetherseed/first-start`
exists) the first-run screen goes on, after the name, to **the date and
time** - five fields with their names on them, day, month, year, hour,
minute, started from the unit's own clock - and **a passkey for the unit's
own Wi-Fi**, typed in the open so that it can be written down. Then
*Start*. The unit sets its clock, puts up the Wi-Fi of §13 under the
companion's name (in plain letters: *Bjørn*'s network is called `Bjorn`,
and the screen says so), and is no longer armed. It can be done once.

- Only **at the unit's own screen**: the console refuses it from anywhere
  else, and a phone cannot be on the unit's Wi-Fi before there is a passkey.
- The console still has no root. It leaves the request in its runtime
  directory, as it does for shutdown; `aetherseed-first-start.path` starts
  `tools/first_start.sh` as root, which checks everything again, does the
  two things and answers. The passkey lies in `/run` (memory, mode 600)
  for the moment between the two, and is written to no log.
- If the Wi-Fi will not come up the screen says so and stays; the unit is
  still armed and it can be tried again. A restart in between comes back to
  the same step.
- **What it does not do.** It cannot change the passkey or the clock
  afterwards: a unit that has lost its clock in a power cut is behind until
  someone with a shell sets it (§14). It does not set the size of the
  screen's text (§9: scale 3 unless `/etc/aetherseed/kiosk.env` says
  otherwise).

**A source card.** A copy of a card is that card - its name, its memory,
its passkey, its SSH identity. So a source is a unit that was installed by
this guide and **never started**:

```bash
sudo /opt/aetherseed/tools/source_card.sh check    # what a copy would carry; changes nothing
sudo /opt/aetherseed/tools/source_card.sh seal     # make it a source, and power off
sudo /opt/aetherseed/tools/source_card.sh seal --restart   # to TRY it: restarts instead; seal again before copying
```

`seal` **refuses a unit that has been started** - a named companion, one
stored turn, a Wi-Fi of its own, a steward's document, a trust record. It
is not a factory reset. On a unit that passes it stops the companion,
removes what running it left behind (the empty store, the model server's
and the keepalive's logs, the screen's browser profile), arms the first
start, deletes the SSH host keys and leaves `/etc/aetherseed/new-identity`,
forgets the network it was built on, the journal and the installer's files
in the admin account's home, and powers off.

**Copy the card before it is booted again.** At the next boot - of the
source or of any copy - `aetherseed-new-identity.service` makes new SSH host
keys and a new machine id, removes its flag and restarts the unit once
(about a minute longer, that one time). A source that was booted after its
seal has its identity already, and every copy made then would share it:
seal it again. Sealing twice is harmless as long as nobody has named the
companion.

Tried on the fourth Pi, 7 Oct 2026 (`seal --restart`): the unit came back
after two boots with another machine id and other SSH host keys (a login
that knew the old ones is refused until told the new), everything §2 and
§14 had switched off still off, nothing failed, no name, no turn, armed,
and the first-run screen up.

The copies keep the admin account, its password and the SSH keys that were
on the source - the pilot arrangement of §14 (key only, if the source was
set so). They come up at scale 3 and with the keyboard layout of the build.

## 19. "I don't know", the date, a right assumption, and how far she trusts a person (step 67, after the tag)

Not part of the tag `stable-llama-2026-10-03`. It is on `main`. Andreas,
8 Oct 2026, after a post on models trained for reward that are asked the
date ("What's the date?", LessWrong, 1 Oct 2026): *"Yes to all three. And
there should be an assumption tag, sometimes Lyra assumes correctly but is
flagged for unverified claims, there should also be a trust level from unit
to user, an interaction for Lyra to measure how much she trusts me and
you"*.

Three files more in the application (`logic/clock.py`,
`logic/trust_record.py`, `training/withdraw_corrections.py`):

```bash
cd ~/aetherseed-main
sudo install -o root -g root -m 644 logic/clock.py logic/trust_record.py logic/training.py \
    logic/steward.py logic/provenance.py logic/token_budget.py logic/facts.py \
    logic/attribution.py /opt/aetherseed/logic/
sudo install -o root -g root -m 644 proxy.py aetherroot.py trust_evolution.py /opt/aetherseed/
sudo install -o root -g root -m 644 gui/index.html gui/serve.py /opt/aetherseed/gui/
sudo install -o root -g root -m 644 training/withdraw_corrections.py /opt/aetherseed/training/
sudo systemctl restart aetherseed-proxy aetherseed-gui aetherseed-kiosk
```

Nothing in her memory is changed by installing.

- **The training no longer tells her her score.** The reflection gives her
  what to learn; the figures are on the screen.
- **"I don't know" is not a wrong answer.** Where the key wants an answer,
  one that opens by saying she does not know is *declined*: corrected and
  asked again like a wrong one, counted as neither. A level is read on what
  she answered; one she mostly declined is not passed. The screen shows the
  declines apart.
- **"What's the date?"** - and the time, the day, the year, in Norwegian
  too - is answered by the unit from its own clock, saying that it has no
  clock battery and asks no network, so after a power cut it is behind.
  Not the model, and not stored.
- **A right assumption.** In the console's memory view, a turn kept as
  unverified has a third button, *A right assumption*. It comes back to her
  as `[A right assumption of yours - your steward checked it]` - not as
  plain fact, and not as "may be wrong" - and counts toward her trust as
  *It's right* does.
- **How far she trusts a person.** Asked *"How much do you trust me?"*,
  *"... Claude?"*, *"... my steward?"* (or *"Hvor mye stoler du på meg?"*)
  she answers from a count of her memory, model not called: what the person
  told her and what of it still stands - her steward's facts, corrections
  and "It's right"; Claude's training corrections and passes, and turns
  said to her as the speaker `Claude`. Five or more, and a share: *high*
  (90 % standing), *some* (70 %), *low*. The Training screen shows both
  records. It cannot tell whether anything was true, and says so; Claude's
  builds are not in her memory and are not counted.
- **What it changes.** While her steward's record is *low*, what he told
  her as fact comes back as `[Steward told you - not checked]`, and she is
  told to say so when she uses it.
- **A correction the training's key got wrong** - a right answer it failed
  - can be withdrawn, **at the steward's word, each time**:

```bash
sudo -u aetherseed /opt/aetherseed/venv/bin/python3 -B /opt/aetherseed/training/withdraw_corrections.py list
sudo -u aetherseed /opt/aetherseed/venv/bin/python3 -B /opt/aetherseed/training/withdraw_corrections.py \
    withdraw --notes 12,15 --yes
```

  `list` writes nothing: the training corrections still standing whose
  answer this build's key passes. `withdraw` undoes only those named, only
  with `--yes`; nothing is deleted, `corrections.log` says why, and it
  counts against Claude in her record.

- **A real level, earned in training.** Andreas: *"when she has achieved a
  high enough score she can earn a new trust level outside of training.
  should be 98-100% success rate"* - over **a whole run** (one that ran its
  full four hours), **offered to the steward**, **one level** at a time,
  and **"I don't know" counts as not right**. A run in which at least 98 %
  of everything she herself was asked was right (and at least 300 of her
  answers) leaves an offer on the Training screen: *Grant reader* / *Not
  now*. Granted - only at the unit's own console - her standing is raised
  to that level's threshold and the level takes effect at the next start;
  like any level it can be lost again as her standing moves. Nothing
  changes until he grants it. Her runs so far: 89.9 % to 94.4 %.
- **A tag word named, not recited, stays as a word**: "the answer is marked
  [Unverified]." is shown as "marked unverified." (after marked, tagged,
  labelled, called, as, with, the). Taken out, a right answer had read
  "marked ." and been failed.

The record and the trust answers are in English only in this build.

## 20. A unit on HailoRT 5.4.0 serving Llama 3.2 1B (step 68, after the tag)

Not part of the tag. Andreas, 8 Oct 2026, on the plan
`claude/runtime-540-llama1b-plan.md`: *"All of that looks good, I have
connected Xena she can get the 540 upgrade"*. **This replaces §3, §4 and §5
on such a unit**; everything else is as for any unit. There is no Llama 3B
for HailoRT 5.4.0: a unit on it serves the 1B. Lyra and the pilots stay on
5.1.1 and the 3B, and nothing here changes them.

The packages come from Hailo's Developer Zone (a login), **not** from
Raspberry Pi's repository, which carries 5.1.1 only. Checked on 8 Oct:

| file | sha256 |
|---|---|
| `hailort_5.4.0_arm64.deb` (package `hailort`) | `db7065eecf3eef52279db8410cea367b9941c92a8f6bea88db09c27d7b4bc15d` |
| `hailort-pcie-driver_5.4.0_all.deb` (package `h10-hailort-pcie-driver`) | `0674a935d55de627b702fd16bce50b87c2ead454451dec68a51a0fb5b07306ac` |
| `hailo_gen_ai_model_zoo_5.4.0_arm64.deb` | `78500dfdd08705a6acf66ed81699029904ce4306dcb437e205e6392443d17eda` |
| `Llama3.2-1B-Instruct.hef`, 1,402,376,894 bytes, public: `https://dev-public.hailo.ai/v5.4.0/blob/Llama3.2-1B-Instruct.hef` | `0a0d378c530fb120d81ffcd1bde1b367c7bb1ce6e2d8f3fb8166558eee40536e` |

Hailo publishes no hash for the model: this one is from two whole fetches
that agreed. The Python wheel, the USB driver and the integration tool are
not needed: the Companion talks to hailo-ollama over HTTP.

**Hailo's runtime package is named `hailort`.** It conflicts with Raspberry
Pi's `h10-hailort`, so none of Raspberry Pi's Hailo packages may be on the
unit. A 4.x `hailort` (Hailo-8) is a different thing: never that.

```bash
# on a unit that has §3-§5 already: take Raspberry Pi's 5.1.1 off first
sudo systemctl disable --now aetherseed-keepalive aetherseed-proxy aetherseed-warmup hailo-ollama
sudo dpkg -r python3-h10-hailort hailo-gen-ai-model-zoo h10-hailort   # removes /usr/share/hailo-ollama
# (needs build-essential and dkms, as §3)
sudo dpkg -i hailort_5.4.0_arm64.deb hailort-pcie-driver_5.4.0_all.deb   # DKMS builds hailo1x_pci
sudo dpkg -i hailo_gen_ai_model_zoo_5.4.0_arm64.deb
sudo apt-mark hold hailort h10-hailort-pcie-driver hailo-gen-ai-model-zoo
sudo chmod -R go-w /usr/share/hailo-ollama          # its postinst makes the folder world-writable
sudo reboot
```

Check: `sudo hailortcli fw-control identify` shows `HAILO10H` and
`Firmware Version: 5.4.0 (release,app)`; `hailortcli --version` 5.4.0; the
kernel still `6.18.50+rpt-rpi-2712`; the device is **`/dev/h1x-0`** (not
`/dev/hailo0`). The firmware is loaded from the card at every boot
(`dmesg`: "Firmware loaded in ... ms") - a card with 5.1.1 brings its own.

The model, its `.sha256` beside it (5.4.0's server will not use a file
without one), the server's drop-in, the device rule, and the unit's model:

```bash
B=/usr/share/hailo-ollama/models/blob
sudo install -d -o root -g root -m 755 $B
sudo install -o root -g root -m 644 Llama3.2-1B-Instruct.hef $B/
echo 0a0d378c530fb120d81ffcd1bde1b367c7bb1ce6e2d8f3fb8166558eee40536e | sudo tee $B/Llama3.2-1B-Instruct.hef.sha256 >/dev/null
sudo chmod 644 $B/Llama3.2-1B-Instruct.hef.sha256
cd ~/aetherseed-main
sudo install -d /etc/systemd/system/hailo-ollama.service.d
sudo install -o root -g root -m 644 services/hailo-ollama.hailort540.conf \
    /etc/systemd/system/hailo-ollama.service.d/hailort-540.conf
sudo install -o root -g root -m 644 services/99-aetherseed-hailo1x.rules /etc/udev/rules.d/
sudo install -d -o root -g root -m 755 /etc/aetherseed
echo AETHERSEED_MODEL=llama3.2:1b | sudo tee /etc/aetherseed/model.env >/dev/null
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hailo1x
sudo systemctl daemon-reload
sudo systemctl enable --now hailo-ollama aetherseed-warmup aetherseed-proxy aetherseed-keepalive
```

What the drop-in is for (each found on Xena): the device's new name, in the
start check and the device allow-list; `OLLAMA_HOST=127.0.0.1:8000`, since
5.4.0 reads no config file and otherwise listens on every interface;
`XDG_DATA_HOME=/usr/share`, since it looks for a model only under
`$XDG_DATA_HOME/hailo-ollama/models/blob/`, by default the service
account's own writable home. `/etc/xdg/hailo-ollama/hailo-ollama.json` is
not used on 5.4.0.

Check: `curl -s 127.0.0.1:8000/api/tags` lists `llama3.2:1b`;
`ss -ltn` shows `127.0.0.1:8000` and not `0.0.0.0:8000`; `ls -l /dev/h1x-0`
is `crw-rw---- root hailo`; the proxy's status says `"model": "llama3.2:1b"`.

**The model is the unit's own setting** (`logic/served.py`):
`/etc/aetherseed/model.env`, one line, read by the proxy, the warm-up and
the keepalive; absent, the unit serves `llama3.2:3b` as before. A name the
build has no measured ceiling for stops the proxy rather than being served
on a guess. What she says about her model - the curriculum's line and the
training key - names the model the unit serves.

**Measured on Xena** (build log 68): prompt ceiling **2785** tokens (3B:
864), past it nothing at all comes back, as on 5.1.1; about 9.9 tokens a
second on a short prompt (3B: 2.66); first token 0.35 s on a short prompt,
about 10 s on a full one; the first load about 7.6 s.

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
