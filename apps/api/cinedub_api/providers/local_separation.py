"""Pinned MRX cinematic separator, optional/offline and subprocess-bounded."""

import hashlib
import importlib.util
import json
from pathlib import Path

from ..local_process import run_inference

MODEL_ID = "audiojs/mrx"
MODEL_REVISION = "dedc823a0bea2ed085d19e8b7f32589d35169ee8"
MODEL_FILE = "mrx.int8.onnx"
MODEL_SHA256 = "d876c92d224f5d8cd2207d528b23369da895a6de71fb24132416fcb16f9f8424"
MODEL_NAME = f"{MODEL_ID}@{MODEL_REVISION}"


def read_manifest(directory: Path, *, verify=False):
    manifest = json.loads((directory / "cinedub-manifest.json").read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("model_id") != MODEL_ID
        or manifest.get("revision") != MODEL_REVISION
        or manifest.get("sha256") != MODEL_SHA256
    ):
        raise ValueError("Separator model does not match the pinned supported conversion")
    path = directory / MODEL_FILE
    if not path.is_file() or path.stat().st_size != 31_287_081:
        raise ValueError("Separator installation is incomplete")
    if verify:
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != MODEL_SHA256:
                raise ValueError(
                    "Separator model checksum changed; rerun setup-local-separation.py"
                )
    return manifest


def availability(directory: Path):
    if importlib.util.find_spec("onnxruntime") is None or importlib.util.find_spec("numpy") is None:
        return False, "Install local-separation extra and run scripts/setup-local-separation.py"
    try:
        read_manifest(directory)
    except (OSError, ValueError, TypeError):
        return False, "Pinned separator model is not ready; run scripts/setup-local-separation.py"
    return True, "MRX cinematic dialogue/music/effects · CPU · review required"


class LocalSeparator:
    name = "local"

    def __init__(self, directory, threads=4, timeout_seconds=900):
        self.directory = Path(directory).resolve()
        self.threads = threads
        self.timeout_seconds = timeout_seconds

    def separate(self, audio_path, output_dir, *, duration_ms, gain_db, cancel, progress):
        read_manifest(self.directory, verify=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        run_inference(
            "cinedub_api.local_separation_runner",
            [
                "--model-dir",
                str(self.directory),
                "--audio",
                str(audio_path.resolve()),
                "--output-dir",
                str(output_dir.resolve()),
                "--duration-ms",
                str(duration_ms),
                "--gain-db",
                str(gain_db),
                "--threads",
                str(self.threads),
            ],
            output_dir,
            threads=self.threads,
            timeout_seconds=self.timeout_seconds,
            cancel=cancel,
            progress=progress,
        )
        payload = json.loads((output_dir / "separation-result.json").read_text())
        if payload.get("model") != MODEL_NAME:
            raise ValueError("Separator returned mismatched provenance")
        return payload
