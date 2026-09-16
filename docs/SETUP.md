# Aetherseed Setup Guide

**From bare metal to a living AI agent on Raspberry Pi 5 + Hailo-10H**

---

## Hardware Requirements

- Raspberry Pi 5 (16GB RAM)
- Raspberry Pi AI HAT+ 2 (Hailo-10H, 40 TOPS, 8GB LPDDR4)
- MicroSD card (64GB+) or NVMe SSD
- USB-C power supply (27W / 5.1V 5A)
- Ethernet cable (recommended for setup)

## Phase 1: OS Installation

1. Flash **Raspberry Pi OS (64-bit, Trixie)** using Raspberry Pi Imager
2. Set hostname to `horizon`, create user, enable SSH
3. Boot and SSH in:

```bash
ssh your-user@horizon.local
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

## Phase 2: Enable PCIe Gen 3

```bash
echo "dtparam=pciex1_gen=3" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

Verify:

```bash
hailortcli fw-control identify
# Should show: Device Architecture: HAILO10H
```

## Phase 3: Install Hailo Software

```bash
sudo apt install hailo-h10-all
sudo reboot
```

Verify:

```bash
dpkg -l | grep hailo
hailortcli fw-control identify
```

## Phase 4: Build hailo-ollama

```bash
sudo apt install libssl-dev cmake gcc g++ -y

git clone https://github.com/hailo-ai/hailo_model_zoo_genai.git
cd hailo_model_zoo_genai
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j4
sudo cmake --install build
```

### Required Patch: JSON Escape Fix

hailo-ollama's JSON parser doesn't escape control characters (newlines, tabs) in prompts,
which breaks Open WebUI integration. Apply this patch before building:

Edit `src/library/controller/llm_generation_callback.hpp`, find the `escape_json_quotes` function,
and replace it with:

```cpp
inline std::string escape_json_quotes(const std::string &text)
{
    std::string result;
    result.reserve(text.size() + 16);
    for (char c : text) {
        switch (c) {
            case '"':  result += "\\\""; break;
            case '\\': result += "\\\\"; break;
            case '\n': result += "\\n"; break;
            case '\r': result += "\\r"; break;
            case '\t': result += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned char>(c));
                    result += buf;
                } else {
                    result += c;
                }
                break;
        }
    }
    return result;
}
```

Then rebuild and reinstall.

## Phase 5: Pull the Model

```bash
hailo-ollama &
sleep 5

# Pull Qwen3-1.7B
curl --no-buffer --silent http://localhost:8000/api/pull \
  -H 'Content-Type: application/json' \
  -d '{"model": "qwen3:1.7b", "stream": true}'

# Verify
curl --silent http://localhost:8000/api/tags | python3 -m json.tool
```

## Phase 6: Install Aetherseed

```bash
pkill hailo-ollama

git clone https://github.com/kommandantvold-ops/aetherseed-local.git
cd aetherseed-local

# Create workspace
mkdir -p ~/aetherseed-workspace/notes
mkdir -p ~/aetherseed-workspace/logs

# Install numpy (only external dependency)
pip install numpy --break-system-packages
```

## Phase 7: Install Open WebUI

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in

sudo docker run -d --net=host \
  -e OLLAMA_BASE_URL=http://127.0.0.1:8001 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

Note: WebUI points to port **8001** (the Aetherseed proxy), not 8000 (hailo-ollama directly).

Clear the system prompt in WebUI settings — the proxy injects Mustardseed automatically.

## Phase 8: Install Systemd Services

```bash
sudo cp services/hailo-ollama.service /etc/systemd/system/
sudo cp services/aetherseed-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hailo-ollama
sudo systemctl enable aetherseed-proxy
sudo systemctl start hailo-ollama
sleep 5
sudo systemctl start aetherseed-proxy
```

## Phase 9: Verify

```bash
# Check services
sudo systemctl status hailo-ollama
sudo systemctl status aetherseed-proxy

# Test the chain
curl --silent http://localhost:8001/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model": "manifests:qwen3", "messages": [{"role": "user", "content": "Hello"}]}'

# Check trust status
python3 trust_evolution.py status

# Check memory
python3 aetherroot.py status

# Open WebUI
# Navigate to http://horizon.local:8080
```

## Phase 10: VLM and Whisper (Optional)

```bash
cd ~
git clone https://github.com/hailo-ai/hailo-apps.git
cd hailo-apps
sudo ./install.sh --no-tappas-required
source setup_env.sh

# Test VLM
python3 -m hailo_apps.python.gen_ai_apps.simple_vlm_chat.simple_vlm_chat

# Test Whisper
python3 -m hailo_apps.python.gen_ai_apps.simple_whisper_chat.simple_whisper_chat
```

Note: VLM and Whisper require exclusive access to the Hailo device. Stop hailo-ollama first,
or start hailo-ollama with `HAILO_OLLAMA_VDEVICE_GROUP_ID=SHARED`.

## Service Architecture

```
Open WebUI (8080) → Aetherseed Proxy (8001) → hailo-ollama (8000) → Hailo-10H NPU

Proxy injects:
  ├── Mustardseed seed (alignment)
  ├── AetherRoot memory (context from past conversations)
  └── Intent detection (workspace tools, system health, trust status)
```

## Troubleshooting

**hailo-ollama won't start:** Check `hailortcli fw-control identify`. If no device found, reseat PCIe cable and verify PCIe Gen 3 is enabled.

**WebUI shows 500 errors:** Check if both hailo-ollama and aetherseed-proxy are running: `sudo systemctl status hailo-ollama aetherseed-proxy`

**Model not found:** Run `curl --silent http://localhost:8000/hailo/v1/list` to see available models. The model name is `manifests:qwen3`.

**VLM fails with status 6:** The Hailo device is in use by hailo-ollama. Stop it first: `sudo systemctl stop hailo-ollama`

---

## Phase 11: The v2 agent layer (voice mode)

Phases 1-10 bring up the **proxy stack** — Open WebUI to `proxy.py` to
hailo-ollama. That path is complete and needs nothing below. `main.py` is the
separate voice/agent entry point and has two extra requirements.

**Dependencies.** The v2 layer adds PyYAML on top of numpy:

```bash
pip install -r requirements.txt --break-system-packages
```

**The `models/` package is not in this repository.** It is listed in
`.gitignore`, so a fresh clone does not contain it and `main.py` will fail at
import with `ModuleNotFoundError: No module named 'models'`. Everything else in
the tree imports cleanly without it — only voice mode is affected.

`main.py` needs `models/wrappers.py` to export three classes:

| Class | Methods used by `main.py` | Backed by |
|-------|---------------------------|-----------|
| `LLM` | `.chat(messages)` , `.is_available()` | hailo-ollama at `LLM_ENDPOINT` (`config/settings.py`) |
| `TTS` | `.speak(text)` , `.stop()` | the bundled `piper/` binaries |
| `STT` | `.transcribe_array(audio_data)` | Whisper on the Hailo (`STT_HEF` in `config/hardware.yaml`) |

Copy your existing `models/` directory into the clone, or write the three
wrappers against that contract.

**Verify the split:**

```bash
# proxy stack — should print nothing and exit 0
python3 -c "import proxy, aetherroot, aetherspark, trust_evolution, intent_detection, honesty_check"

# v2 layer minus voice — should also be silent
python3 -c "import core.node, core.scheduler, hardware.metrics, logic.prompt_builder, sensors.audio, config.settings"

# voice mode — fails until models/ is present
python3 -c "import main"
```

---

## Phase 12: Honesty scoring

`honesty_check.py` scores responses by provenance: a citation, DOI, URL,
percentage or measurement is trusted only if it appears in what the node read
that turn. It replaces the keyword matching in `auto_score_response()`.

It ships **inert**. The flags at the top of `trust_evolution.py`:

| Flag | Default | Effect |
|------|---------|--------|
| `AUTO_TASK_CREDIT` | `False` | was `True` in effect — credited +3 for any reply over ten characters |
| `PROVENANCE_REPORT_ONLY` | `True` | log would-be penalties without moving standing |
| `PROVENANCE_STRICT` | `False` | `True` also flags unsourced figures, not just citations |
| `ENFORCE_MODULE_GATING` | `False` | require curriculum modules before a tier promotion |

Run in report-only mode first and read the observations before enforcing:

```bash
python3 test_trust_scoring.py          # 14 unit tests
python3 -c "import json,os; print(json.load(open(os.path.expanduser('~/.aetherseed/trust_state.json'))).get('observations', []))"
```

`test_proxy_integration.py` drives four turns through the real proxy against a
stubbed hailo-ollama, if you want the end-to-end check without the NPU. Stop
the `hailo-ollama` unit first — it needs port 8000.
