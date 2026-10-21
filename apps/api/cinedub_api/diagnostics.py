import shutil
import subprocess
from pathlib import Path


def _memory_gib() -> tuple[float | None, float | None]:
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", maxsplit=1)
            values[key] = int(value.strip().split()[0])
        scale = 1024 * 1024
        return round(values["MemTotal"] / scale, 1), round(values["MemAvailable"] / scale, 1)
    except (OSError, KeyError, ValueError):
        return None, None


def _gpu_name() -> str | None:
    roots = sorted(Path("/proc/driver/nvidia/gpus").glob("*/information"))
    for path in roots:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("Model:"):
                    return line.split(":", maxsplit=1)[1].strip()
        except OSError:
            continue
    return None


def hardware_diagnostics(storage_root: Path) -> dict:
    gpu_name = _gpu_name()
    cuda_ready = False
    gpu_error = None
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        cuda_ready = result.returncode == 0
        if not cuda_ready:
            gpu_error = (result.stderr or result.stdout).strip()[:300] or "nvidia-smi failed"
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        gpu_error = type(exc).__name__
    total_memory, available_memory = _memory_gib()
    disk = shutil.disk_usage(storage_root)
    return {
        "gpu_detected": gpu_name is not None,
        "gpu_name": gpu_name,
        "cuda_ready": cuda_ready,
        "gpu_error": gpu_error,
        "memory_total_gib": total_memory,
        "memory_available_gib": available_memory,
        "storage_free_gib": round(disk.free / (1024**3), 1),
        "ffmpeg_ready": shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None,
    }
