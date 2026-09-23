"""
power.py — what this unit can and cannot say about its own energy use.
======================================================================

WHAT IS MEASURABLE HERE, MEASURED 2026-09-23
--------------------------------------------
The Pi 5's PMIC exposes per-rail current and voltage through
`vcgencmd pmic_read_adc`. Twelve rails report both, so their product summed is
a real power figure for the board:

    idle                    2.00 W
    four CPU spinners       5.31 W      (VDD_CORE 0.49 -> 3.80 W, 1.5 -> 2.4 GHz)
    back to idle            1.99 W

WHAT IS NOT MEASURABLE, AND WHY THIS FILE SAYS SO OUT LOUD
----------------------------------------------------------
**The NPU is not on any sensed rail.** A 31-second generation on the Hailo-10H
moved the board total by -0.015 W - noise, and in the wrong direction:

    idle (20 s, 48 samples)         mean 2.042 W   min 1.861   max 2.851
    generating (30.9 s, 73 samples) mean 2.027 W   min 1.860   max 2.921

The CPU-spinner run above is the control: the instrument sees a 3.3 W swing
when there is one, so the flat NPU reading is a real absence, not a blind
instrument. The accelerator draws from the 5 V input, and `EXT5V` is one of the
two rails with a voltage sense and no current sense.

**`hailortcli measure-power` does not work on this board.** It fails
`HAILO_OPEN_FILE_FAILURE(13)` as root, and still fails with hailo-ollama
stopped and the device free - so it is not a permission and not a busy device.
HailoRT 5.1.1 on this HAILO10H exposes no power sensor.

So: the number this module reports is **the sum of the twelve PMIC-sensed
rails**. It is not wall power, it does not include the accelerator, and it does
not include conversion losses in the supply. Total system power still needs an
inline meter between the supply and the unit - which is what step 14f said when
it struck "2.5 watts" out of the README, and it is still true.

What it is good for: a 24-hour series of it says whether the board's own draw
and temperature drift, which is the degradation question. Pure stdlib; one
`vcgencmd` call per sample, about 10 ms.
"""

from __future__ import annotations

import re
import subprocess

__all__ = ["read", "rails", "COVERS"]

COVERS = ("sum of 12 PMIC-sensed rails; excludes the Hailo NPU (not on a "
          "sensed rail) and supply losses; not wall power")

_RX = re.compile(r"\s*(\S+)\s+(current|volt)\(\d+\)=([0-9.]+)[AV]")


def _vcgencmd(*args) -> str:
    try:
        return subprocess.run(("vcgencmd",) + args, capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def rails() -> dict:
    """Every rail that reports BOTH a current and a voltage, in watts.

    A rail with only one of the two is skipped rather than guessed at: EXT5V
    reports volts and no amps, and pretending otherwise would invent the one
    number this whole module exists to say it cannot measure.
    """
    out = _vcgencmd("pmic_read_adc")
    amps, volts = {}, {}
    for line in out.splitlines():
        m = _RX.match(line)
        if not m:
            continue
        name, kind, value = m.group(1), m.group(2), float(m.group(3))
        (amps if kind == "current" else volts)[name[:-2]] = value
    return {k: round(amps[k] * volts[k], 4) for k in amps if k in volts}


def read(per_rail: bool = False) -> dict:
    """One sample: board watts, temperature, throttling, CPU clock."""
    r = rails()
    temp = _vcgencmd("measure_temp").replace("temp=", "").replace("'C", "")
    clock = _vcgencmd("measure_clock", "arm")
    out = {
        "board_w": round(sum(r.values()), 3) if r else None,
        "rails_n": len(r),
        "temp_c": float(temp) if temp else None,
        "throttled": _vcgencmd("get_throttled").replace("throttled=", "") or None,
        "arm_mhz": int(clock.split("=")[1]) // 1000000 if "=" in clock else None,
    }
    if per_rail:
        out["rails"] = r
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(read(per_rail=True), indent=2))
    print(COVERS)
