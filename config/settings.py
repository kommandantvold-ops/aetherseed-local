"""
Aetherseed Companion — Global Settings
"""

import os
import yaml
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).parent.parent
CONFIG_DIR = ROOT_DIR / "config"
WORKSPACE_DIR = Path(os.path.expanduser("~/aetherseed-workspace"))
STATE_DIR = Path(os.path.expanduser("~/.aetherseed"))

# Load hardware config
HW_CONFIG_PATH = CONFIG_DIR / "hardware.yaml"
if HW_CONFIG_PATH.exists():
    with open(HW_CONFIG_PATH) as f:
        HW = yaml.safe_load(f)
else:
    HW = {}

# Audio
AUDIO_INPUT_DEVICE = HW.get("audio", {}).get("input_device", "hw:2,0")
AUDIO_OUTPUT_DEVICE = HW.get("audio", {}).get("output_device", "hw:0,0")
SAMPLE_RATE = HW.get("audio", {}).get("sample_rate", 16000)
CHANNELS = HW.get("audio", {}).get("channels", 1)
CHUNK_SIZE = HW.get("audio", {}).get("chunk_size", 1024)

# Camera
CAMERA_DEVICE = HW.get("camera", {}).get("device", "/dev/video0")

# Models
LLM_ENDPOINT = HW.get("models", {}).get("llm", {}).get("endpoint", "http://127.0.0.1:8000")
LLM_MODEL = HW.get("models", {}).get("llm", {}).get("model_name", "manifests:qwen3")
VLM_HEF = HW.get("models", {}).get("vlm", {}).get("hef_path", "")
STT_HEF = HW.get("models", {}).get("stt", {}).get("hef_path", "")

# Thresholds
VAD_ENERGY = HW.get("thresholds", {}).get("vad_energy", 500)
SILENCE_DURATION = HW.get("thresholds", {}).get("silence_duration", 1.5)
MAX_LISTEN_DURATION = HW.get("thresholds", {}).get("max_listen_duration", 30)

# Proxy
PROXY_PORT = 8001
HAILO_PORT = 8000
