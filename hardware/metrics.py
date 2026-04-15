"""
Hardware Metrics — Pi5 Health → Decay Signal
==============================================
Reads system metrics and converts to the D (decay) parameter.
"""

import re
import subprocess


def get_cpu_temp() -> float:
    """Get CPU temperature in Celsius."""
    try:
        temp = open("/sys/class/thermal/thermal_zone0/temp").read().strip()
        return int(temp) / 1000.0
    except Exception:
        return 0.0


def get_memory_usage() -> dict:
    """Get memory usage in MB."""
    try:
        with open("/proc/meminfo") as f:
            meminfo = f.read()
        total = int(re.search(r"MemTotal:\s+(\d+)", meminfo).group(1)) // 1024
        available = int(re.search(r"MemAvailable:\s+(\d+)", meminfo).group(1)) // 1024
        return {"total_mb": total, "available_mb": available, "used_mb": total - available,
                "percent": (total - available) * 100 // total}
    except Exception:
        return {"total_mb": 0, "available_mb": 0, "used_mb": 0, "percent": 0}


def get_disk_usage() -> dict:
    """Get disk usage."""
    try:
        result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        parts = result.stdout.strip().split("\n")[-1].split()
        return {"total": parts[1], "used": parts[2], "available": parts[3], "percent": parts[4]}
    except Exception:
        return {}


def get_uptime_seconds() -> float:
    """Get system uptime in seconds."""
    try:
        return float(open("/proc/uptime").read().split()[0])
    except Exception:
        return 0.0


def compute_decay() -> float:
    """Compute the D (decay) parameter from hardware metrics.
    
    D = 0.0 means healthy
    D = 1.0 means critical
    
    Factors:
    - CPU temp > 70°C starts contributing
    - RAM > 80% starts contributing
    - Both scale linearly to their critical thresholds
    """
    d = 0.0

    # Temperature contribution (70-85°C → 0-0.5)
    temp = get_cpu_temp()
    if temp > 70:
        d += min((temp - 70) / 30, 0.5)

    # Memory contribution (80-95% → 0-0.5)
    mem = get_memory_usage()
    if mem["percent"] > 80:
        d += min((mem["percent"] - 80) / 30, 0.5)

    return min(d, 1.0)


def get_full_report() -> str:
    """Get full hardware report as string."""
    temp = get_cpu_temp()
    mem = get_memory_usage()
    disk = get_disk_usage()
    uptime = get_uptime_seconds()
    decay = compute_decay()

    hours = int(uptime) // 3600
    mins = (int(uptime) % 3600) // 60

    lines = [
        f"🌡️  CPU: {temp:.1f}°C",
        f"💾 RAM: {mem['used_mb']}MB / {mem['total_mb']}MB ({mem['percent']}%)",
        f"💿 Disk: {disk.get('used', '?')} / {disk.get('total', '?')} ({disk.get('percent', '?')})",
        f"⏱️  Uptime: {hours}h {mins}m",
        f"📉 Decay: {decay:.3f}",
    ]
    return "\n".join(lines)
