"""Download a pinned MIT-licensed MRX data graph, not remote Python code."""

import argparse
import json
from pathlib import Path

from cinedub_api.providers.local_separation import (
    MODEL_FILE,
    MODEL_ID,
    MODEL_REVISION,
    MODEL_SHA256,
    read_manifest,
)
from huggingface_hub import snapshot_download


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("models/mrx"))
    args = parser.parse_args()
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=args.directory,
        allow_patterns=[MODEL_FILE, "LICENSE", "README.md"],
        max_workers=2,
    )
    (args.directory / "cinedub-manifest.json").write_text(
        json.dumps(
            {
                "model_id": MODEL_ID,
                "revision": MODEL_REVISION,
                "sha256": MODEL_SHA256,
                "license": "MIT",
                "upstream": "merlresearch/cocktail-fork-separation",
                "upstream_revision": "19b3de827ebc4bfb014570cf92dd32b4ee3b6921",
                "conversion": "audiojs; int8 stored weights, float32 computation",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    read_manifest(args.directory, verify=True)
    print(f"Offline cinematic separator ready: {args.directory}")


if __name__ == "__main__":
    main()
