"""Pinned experimental Malayalam CTC conversion; no automatic timing application."""

import hashlib
import importlib.util
import json
from pathlib import Path

MODEL_ID = "trysem/wav2vec2-malayalam-onnx-int8"
MODEL_REVISION = "f16ea0d2a80812d38205d335c1f4806543dccad0"
MODEL_NAME = f"{MODEL_ID}@{MODEL_REVISION}"
MODEL_FILE = "model_quantized.onnx"
MODEL_HASHES = {
    MODEL_FILE: "40a80cff1d5750939ca8f657587ed05b826d75466df9f83f7344154b9e61f12a",
    "config.json": "d879422b8940e1add96535009078d4854d982e04bcc6d13bc4462c82b22c4912",
    "vocab.json": "924b80a58255782eb0d1478f3bd29f4743327a4b1fe99aea36ddda960a6f5135",
    "preprocessor_config.json": "ffc72f475cd79680d5d659fbaefc691cdbcee5c9703a15faf708a5e91452a8d8",
}


def read_manifest(directory: Path, *, verify=False):
    manifest = json.loads((directory / "cinedub-manifest.json").read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("model_id") != MODEL_ID
        or manifest.get("revision") != MODEL_REVISION
        or manifest.get("sha256") != MODEL_HASHES
    ):
        raise ValueError("Target alignment model does not match the pinned conversion")
    for name, expected in MODEL_HASHES.items():
        path = directory / name
        if not path.is_file() or not 0 < path.stat().st_size <= 400_000_000:
            raise ValueError("Target alignment installation is incomplete")
        if name == MODEL_FILE and path.stat().st_size != 356_698_513:
            raise ValueError("Target alignment installation is incomplete")
        if verify:
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != expected:
                    raise ValueError(
                        "Target alignment checksum changed; reinstall the pinned model"
                    )
    return manifest


def availability(directory):
    if importlib.util.find_spec("numpy") is None or importlib.util.find_spec("onnxruntime") is None:
        return False, "Install local-alignment extra and run scripts/setup-target-alignment.py"
    try:
        read_manifest(directory)
    except (OSError, ValueError, TypeError):
        return (
            False,
            "Run scripts/setup-target-alignment.py to install the experimental Malayalam model",
        )
    return True, "Experimental Malayalam word suggestions · CPU · natural-speech quality unverified"
