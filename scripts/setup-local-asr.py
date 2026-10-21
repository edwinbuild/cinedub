"""Explicit, resumable model installation. The running application never downloads weights."""

import argparse
import hashlib
import json
from pathlib import Path

from cinedub_api.providers.local_asr import MODEL_FILES, MODEL_ID, MODEL_REVISION, read_manifest
from huggingface_hub import snapshot_download


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("models/faster-whisper-small.en"))
    args = parser.parse_args()
    # Hugging Face downloads converted model data; no remote Python code is executed.
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        allow_patterns=[*MODEL_FILES, "README.md"],
        local_dir=args.directory,
        max_workers=2,
    )
    hashes = {}
    for name in MODEL_FILES:
        with (args.directory / name).open("rb") as handle:
            hashes[name] = hashlib.file_digest(handle, "sha256").hexdigest()
    manifest = {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "license": "MIT",
        "source": f"https://huggingface.co/{MODEL_ID}/tree/{MODEL_REVISION}",
        "sha256": hashes,
    }
    (args.directory / "cinedub-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    read_manifest(args.directory, verify=True)
    print(f"Offline ASR ready: {args.directory}. Set CINEDUB_TRANSCRIBER=local and restart.")


if __name__ == "__main__":
    main()
