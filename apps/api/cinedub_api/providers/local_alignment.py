"""Optional pinned English CTC aligner. No download or remote model code at runtime."""

import hashlib
import importlib.util
import json
from pathlib import Path

from ..local_process import run_inference

MODEL_ID = "onnx-community/wav2vec2-base-960h-ONNX"
MODEL_REVISION = "729c1a6730fb549c20a1c73a3d3f96f11020225e"
MODEL_NAME = f"{MODEL_ID}@{MODEL_REVISION}"
MODEL_FILE = "onnx/model.onnx"
MODEL_HASHES = {
    MODEL_FILE: "00b7cc69516c1ab63c429e63a2b543e4d42bb77441ec5b98ee935de175b00de1",
    "config.json": "15c7cf6378153bdcb33fce27780ab9aae37fd154fbb674cacc3347992055d323",
    "preprocessor_config.json": "8cdfd65ff4115423185a1512bdae100e2e0cd744f5b322417429944aaafd0827",
    "vocab.json": "4178db26b3c7570f6a47f14ac6a1c7b32950b8c2800fb097287e53776934f1c5",
}


def read_manifest(directory: Path, *, verify=False):
    manifest = json.loads((directory / "cinedub-manifest.json").read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("model_id") != MODEL_ID
        or manifest.get("revision") != MODEL_REVISION
        or manifest.get("sha256") != MODEL_HASHES
    ):
        raise ValueError("Alignment model does not match the pinned supported conversion")
    for name, expected in MODEL_HASHES.items():
        path = directory / name
        size = 377_911_891 if name == MODEL_FILE else None
        if not path.is_file() or not 0 < path.stat().st_size <= 400_000_000:
            raise ValueError("Alignment installation is incomplete")
        if size and path.stat().st_size != size:
            raise ValueError("Alignment installation is incomplete")
        if verify:
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != expected:
                    raise ValueError(
                        "Alignment model checksum changed; rerun setup-local-alignment.py"
                    )
    return manifest


def availability(directory: Path):
    if importlib.util.find_spec("onnxruntime") is None or importlib.util.find_spec("numpy") is None:
        return False, "Install local-alignment extra and run scripts/setup-local-alignment.py"
    try:
        read_manifest(directory)
    except (OSError, ValueError, TypeError):
        return False, "Pinned alignment model is not ready; run scripts/setup-local-alignment.py"
    return True, "English source-word CTC alignment + acoustic measurements · CPU · review required"


class LocalAligner:
    name = "local"

    def __init__(self, directory, threads=4, timeout_seconds=600):
        self.directory = Path(directory).resolve()
        self.threads = threads
        self.timeout_seconds = timeout_seconds

    def align(self, audio_path, output_dir, *, lines, duration_ms, language, cancel, progress):
        if language != "en-IN":
            raise ValueError("This installed aligner supports English source audio only")
        read_manifest(self.directory, verify=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        request = output_dir / "alignment-input.json"
        request.write_text(json.dumps({"lines": lines, "duration_ms": duration_ms}))
        run_inference(
            "cinedub_api.local_alignment_runner",
            [
                "--model-dir",
                str(self.directory),
                "--audio",
                str(audio_path.resolve()),
                "--output-dir",
                str(output_dir.resolve()),
                "--request",
                str(request.resolve()),
                "--threads",
                str(self.threads),
            ],
            output_dir,
            threads=self.threads,
            timeout_seconds=self.timeout_seconds,
            cancel=cancel,
            progress=progress,
        )
        payload = json.loads((output_dir / "alignment-result.json").read_text())
        if payload.get("model") != MODEL_NAME:
            raise ValueError("Alignment returned mismatched model provenance")
        return payload
