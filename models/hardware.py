"""Hardware diagnostics, preflight benchmarks, and tailored GPU configuration guidance."""

import os
import platform
import subprocess
import time
from typing import Any, Dict, List, Optional
import psutil
import requests

from config.loader import load_settings_config


def detect_gpu_info() -> Dict[str, Any]:
    """Detect GPU hardware, identifying dedicated vs shared-memory integrated GPUs."""
    system_os = platform.system()
    gpu_names: List[str] = []
    is_dedicated = False
    is_integrated = False
    is_amd = False

    if system_os == "Windows":
        try:
            # Query WMI for video controller description and adapter RAM
            cmd = "Get-CimInstance Win32_VideoController | Select-Object -Property Name, AdapterRAM"
            output = subprocess.check_output(["powershell", "-NoProfile", "-Command", cmd], text=True, timeout=5)
            lines = output.splitlines()
            for line in lines:
                clean = line.strip()
                if clean and not clean.startswith("Name") and not clean.startswith("----"):
                    gpu_names.append(clean)
                    lower = clean.lower()
                    if "amd" in lower or "radeon" in lower:
                        is_amd = True
                    # Check for dedicated vs integrated indicators
                    if any(x in lower for x in ["rx 6600", "rx 6700", "rtx", "geforce", "discrete"]):
                        is_dedicated = True
                    elif any(x in lower for x in ["860m", "780m", "680m", "vega", "graphics", "integrated"]):
                        is_integrated = True
        except Exception:
            pass

    # If neither flag was explicitly found by keyword, fallback heuristics based on RAM and detected names
    if not is_dedicated and not is_integrated:
        if any("radeon" in g.lower() for g in gpu_names):
            is_amd = True
            is_integrated = True

    return {
        "gpus": gpu_names,
        "is_amd": is_amd,
        "is_dedicated": is_dedicated,
        "is_integrated": is_integrated,
    }


def check_ollama_status(base_url: str = "http://localhost:11434") -> Dict[str, Any]:
    """Query Ollama server status and loaded models in VRAM via /api/ps endpoint."""
    result: Dict[str, Any] = {
        "reachable": False,
        "loaded_models": [],
        "vram_percentage": 0.0,
    }

    try:
        resp = requests.get(f"{base_url}/api/ps", timeout=3)
        if resp.status_code == 200:
            result["reachable"] = True
            data = resp.json()
            models = data.get("models", [])
            result["loaded_models"] = models
            if models:
                first = models[0]
                size_total = first.get("size", 1)
                size_vram = first.get("size_vram", 0)
                if size_total > 0:
                    result["vram_percentage"] = round((size_vram / size_total) * 100.0, 1)
    except Exception:
        pass

    return result


def benchmark_tokens_per_second(
    base_url: str = "http://localhost:11434",
    model: str = "qwen2.5:7b",
    test_prompt: str = "Count from 1 to 5.",
) -> Optional[float]:
    """Run a short test generation against Ollama to measure tokens per second."""
    payload = {
        "model": model,
        "prompt": test_prompt,
        "stream": False,
        "options": {"num_predict": 10},
    }
    start_time = time.perf_counter()
    try:
        resp = requests.post(f"{base_url}/api/generate", json=payload, timeout=10)
        elapsed = time.perf_counter() - start_time
        if resp.status_code == 200:
            data = resp.json()
            eval_count = data.get("eval_count", 0)
            if eval_count and elapsed > 0:
                return round(eval_count / elapsed, 1)
            # Estimate if eval_count omitted
            tokens_est = len(data.get("response", "").split())
            if tokens_est and elapsed > 0:
                return round(tokens_est / elapsed, 1)
    except Exception:
        pass
    return None


def run_hardware_preflight(
    ollama_url: str = "http://localhost:11434",
    model_name: str = "qwen2.5:7b",
) -> Dict[str, Any]:
    """Execute complete hardware check, classifying machine type and returning actionable advice."""
    mem = psutil.virtual_memory()
    total_ram_gb = round(mem.total / (1024**3), 1)
    free_ram_gb = round(mem.available / (1024**3), 1)

    gpu_info = detect_gpu_info()
    ollama_info = check_ollama_status(ollama_url)
    tps = benchmark_tokens_per_second(ollama_url, model=model_name)

    # Determine Machine Architecture
    if gpu_info["is_dedicated"]:
        machine_type = "Dedicated GPU Desktop (e.g. AMD RX 6600 8GB)"
    elif gpu_info["is_integrated"]:
        machine_type = "Shared-Memory Laptop (e.g. AMD Ryzen AI 7 350 / Radeon 860M)"
    else:
        machine_type = "Standard PC / CPU Mode"

    # Evaluation & Verdict Logic
    verdict = "Good"
    suggestion = "Your machine is ready for full Jury and Quick study modes."
    low_ram_warning = False

    # Check shared memory constraint
    if gpu_info["is_integrated"] and free_ram_gb < 6.0:
        low_ram_warning = True
        verdict = "Slow (use quick mode only)"
        suggestion = "Low free shared RAM detected. Use Quick Mode and keep context length to 2048."

    # Speed-based judgment
    if tps is not None:
        if tps < 8.0:
            verdict = "Slow (use quick mode only)"
            suggestion = "Generation speed is under 8 tokens/sec. Use Quick Mode or switch to a smaller 3B model."
        elif tps < 3.0:
            verdict = "Not recommended"
            suggestion = "Very slow generation. Consider switching to Colab or remote cloud for complex jury mode."
    elif not ollama_info["reachable"]:
        verdict = "Slow (use quick mode only)"
        suggestion = "Ollama is not currently running. Start Ollama to enable local AI answering."

    # Target machines AMD Vulkan advice
    vulkan_tip = (
        "Tip: On Windows, AMD cards (both RX 6600 and Radeon 860M) run fastest with Ollama's "
        "Vulkan backend. Set OLLAMA_VULKAN=1 in your environment. Do not attempt to use the NPU. "
        "See README.md Section 4 for complete setup details."
    )

    return {
        "verdict": verdict,
        "suggestion": suggestion,
        "machine_type": machine_type,
        "total_ram_gb": total_ram_gb,
        "free_ram_gb": free_ram_gb,
        "low_ram_warning": low_ram_warning,
        "gpus_detected": gpu_info["gpus"],
        "is_amd": gpu_info["is_amd"],
        "ollama_reachable": ollama_info["reachable"],
        "vram_percentage": ollama_info["vram_percentage"],
        "tokens_per_second": tps,
        "vulkan_tip": vulkan_tip,
        "recommended_mode": "quick" if "Slow" in verdict or "Not" in verdict else "jury",
    }
