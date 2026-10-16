"""Offline English ASR with a pinned, explicitly installed CTranslate2 model.

Inference runs in a disposable process: its model memory is released at the end,
and cancellation/deadlines can stop native inference, not just the Python iterator.
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ..workspace_lock import child_lease_environment, child_process_options

MODEL_ID = "Systran/faster-whisper-small.en"
MODEL_REVISION = "d1d751a5f8271d482d14ca55d9e2deeebbae577f"
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
MODEL_NAME = f"{MODEL_ID}@{MODEL_REVISION}"


def read_manifest(directory: Path, *, verify: bool = False) -> dict:
    manifest = json.loads((directory / "cinedub-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("model_id") != MODEL_ID or manifest.get("revision") != MODEL_REVISION:
        raise ValueError("Local ASR model does not match the pinned supported revision")
    hashes = manifest.get("sha256", {})
    for name in MODEL_FILES:
        path = directory / name
        if not path.is_file() or name not in hashes or not path.stat().st_size:
            raise ValueError("Local ASR installation is incomplete; rerun setup-local-asr.py")
        if path.stat().st_size > 1_000_000_000:
            raise ValueError("Local ASR model exceeds this laptop profile's size limit")
        if verify:
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != hashes[name]:
                    raise ValueError("Local ASR model checksum changed; rerun setup-local-asr.py")
    return manifest


def availability(directory: Path) -> tuple[bool, str]:
    if importlib.util.find_spec("faster_whisper") is None:
        return False, "Install the optional local-asr extra and run scripts/setup-local-asr.py"
    try:
        read_manifest(directory)
    except (OSError, ValueError, TypeError, KeyError):
        return False, "Pinned local ASR model is not ready; run scripts/setup-local-asr.py"
    return True, "Offline English ASR · CPU int8 · manual speaker assignment (no diarization)"


class LocalTranscriber:
    name = "local"

    def __init__(self, directory: Path, threads: int = 4, timeout_seconds: int = 600):
        self.directory = directory.resolve()
        self.threads = threads
        self.timeout_seconds = timeout_seconds

    def transcribe(self, audio_path: Path, output_dir: Path, cancel) -> dict:
        read_manifest(self.directory, verify=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = (output_dir / "local-result.json").resolve()
        # No credentials or arbitrary user model code are passed to the child.
        env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}
        }
        env.update(
            {
                "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "OMP_NUM_THREADS": str(self.threads),
                "OPENBLAS_NUM_THREADS": "1",
            }
        )
        env.update(child_lease_environment())
        command = [
            sys.executable,
            "-m",
            "cinedub_api.local_asr_runner",
            "--model-dir",
            str(self.directory),
            "--audio",
            str(audio_path.resolve()),
            "--output",
            str(output_path),
            "--threads",
            str(self.threads),
        ]
        started = time.monotonic()
        with (output_dir / "inference.log").open("w") as log:
            process = subprocess.Popen(
                command, env=env, stdout=log, stderr=log, **child_process_options()
            )
            try:
                while process.poll() is None:
                    cancel()
                    if time.monotonic() - started > self.timeout_seconds:
                        raise TimeoutError("Local ASR deadline exceeded; inference was stopped")
                    time.sleep(0.25)
                cancel()
                if process.returncode:
                    raise RuntimeError("Local ASR inference failed; see the local inference log")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        if payload.get("local_metadata", {}).get("model") != MODEL_NAME:
            raise ValueError("Local ASR returned mismatched model provenance")
        return payload
