"""Explicitly install the pinned English ONNX CTC data graph (no remote Python execution)."""

import argparse
import json
from pathlib import Path

from cinedub_api.providers.local_alignment import (
    MODEL_HASHES,
    MODEL_ID,
    MODEL_REVISION,
    read_manifest,
)
from huggingface_hub import snapshot_download


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("models/wav2vec2-english"))
    args = parser.parse_args()
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=args.directory,
        allow_patterns=[*MODEL_HASHES, "README.md"],
        max_workers=2,
    )
    (args.directory / "cinedub-manifest.json").write_text(
        json.dumps(
            {
                "model_id": MODEL_ID,
                "revision": MODEL_REVISION,
                "sha256": MODEL_HASHES,
                "upstream": "facebook/wav2vec2-base-960h",
                "upstream_license": "Apache-2.0",
                "license_evidence": "https://huggingface.co/facebook/wav2vec2-base-960h",
                "conversion": "onnx-community; conversion card names upstream; no separate license",
                "purpose": "English source-word alignment; not Malayalam or speech emotion",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    read_manifest(args.directory, verify=True)
    print(f"Offline English alignment ready: {args.directory}")


if __name__ == "__main__":
    main()
