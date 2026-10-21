"""Explicitly install pinned audio-only emotion/VAD graphs; no remote model code."""

import argparse
import json
from pathlib import Path

from cinedub_api.providers.local_emotion import (
    MODEL_FILES,
    MODEL_ID,
    MODEL_REVISION,
    VAD_ID,
    VAD_REVISION,
    read_manifest,
)


def main():
    from huggingface_hub import hf_hub_download

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("models/speech-emotion"))
    args = parser.parse_args()
    try:
        read_manifest(args.directory, verify=True)
    except (OSError, ValueError, TypeError):
        pass
    else:
        print(f"Already verified optional speech-emotion/VAD models: {args.directory}")
        return
    for kind, repository, revision in [
        ("ser", MODEL_ID, MODEL_REVISION),
        ("vad", VAD_ID, VAD_REVISION),
    ]:
        directory = args.directory / kind
        for filename in [
            "onnx/model.onnx",
            *(
                ["config.json", "preprocessor_config.json", "README.md"]
                if kind == "ser"
                else ["LICENSE"]
            ),
        ]:
            downloaded = Path(
                hf_hub_download(
                    repository, filename, revision=revision, local_dir=directory, token=False
                )
            )
            if filename.startswith("onnx/"):
                downloaded.replace(directory / "model.onnx")
    (args.directory / "cinedub-manifest.json").write_text(
        json.dumps(
            {
                "model_id": MODEL_ID,
                "revision": MODEL_REVISION,
                "vad_id": VAD_ID,
                "vad_revision": VAD_REVISION,
                "sha256": {name: value[1] for name, value in MODEL_FILES.items()},
                "emotion_license": "Apache-2.0 declared by upstream and conversion cards",
                "upstream": "superb/wav2vec2-base-superb-er",
                "vad_license": "MIT",
                "purpose": "English speech-performance hints; not psychological diagnosis",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    read_manifest(args.directory, verify=True)
    print(f"Verified optional speech-emotion/VAD models: {args.directory}")


if __name__ == "__main__":
    main()
