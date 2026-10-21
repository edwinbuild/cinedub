"""Disposable offline inference process with deadlines, cancellation and bounded polling."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .workspace_lock import child_lease_environment, child_process_options


def run_inference(module, arguments, output_dir, *, threads, timeout_seconds, cancel, progress):
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}
    }
    env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": str(threads),
        }
    )
    env.update(child_lease_environment())
    progress_path = output_dir / "progress.json"
    progress_path.unlink(missing_ok=True)
    last_progress = None
    started = time.monotonic()
    with (output_dir / "inference.log").open("w") as log:
        child = subprocess.Popen(
            [sys.executable, "-m", module, *arguments],
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
            **child_process_options(),
        )
        try:
            while child.poll() is None:
                cancel()
                if time.monotonic() - started > timeout_seconds:
                    raise TimeoutError("Local model deadline exceeded; inference stopped")
                if progress_path.is_file():
                    value = json.loads(progress_path.read_text())
                    pair = value["completed"], value["total"]
                    if pair != last_progress:
                        progress(*pair)
                        last_progress = pair
                time.sleep(0.25)
            cancel()
            if child.returncode:
                raise RuntimeError("Local model inference failed; inspect its local inference log")
        finally:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass  # Native work can finish between poll and signal.
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=5)
