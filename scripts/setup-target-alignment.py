"""Explicitly install pinned Malayalam ONNX data; no remote Python or runtime download."""

import argparse
import json
from pathlib import Path

from cinedub_api.providers.local_target_alignment import (
    MODEL_HASHES,
    MODEL_ID,
    MODEL_REVISION,
    read_manifest,
)
from huggingface_hub import snapshot_download


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("models/wav2vec2-malayalam"))
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
                "upstream": "gvs/wav2vec2-large-xlsr-malayalam",
                "upstream_revision": "b073beb93616a83d26933e1aa98d9299a5f4af23",
                "upstream_license": "Apache-2.0 declared by upstream card",
                "license_evidence": "https://huggingface.co/gvs/wav2vec2-large-xlsr-malayalam",
                "conversion_license": "No separate license declaration in conversion card",
                "purpose": "Experimental Malayalam word suggestions; "
                "not certified alignment or emotion",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    read_manifest(args.directory, verify=True)
    print(f"Experimental offline Malayalam alignment ready: {args.directory}")


if __name__ == "__main__":
    main()
