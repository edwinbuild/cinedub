"""Optional pinned English audio classifier and speech-presence guard; no text sentiment."""

import hashlib
import importlib.util
import json
from pathlib import Path

from ..local_process import run_inference

MODEL_ID = "onnx-community/wav2vec2-base-superb-er-ONNX"
MODEL_REVISION = "e2191e9e8b692c19c7d96e2a1d789ab1df5b7259"
MODEL_NAME = f"{MODEL_ID}@{MODEL_REVISION}"
VAD_ID = "onnx-community/silero-vad"
VAD_REVISION = "e71cae966052b992a7eca6b17738916ce0eca4ec"
MODEL_FILES = {
    "ser/model.onnx": (
        378495202,
        "158cff05806c3e99a949414da4fa199051534dc1ef0fcaf361d6244571f54f7d",
    ),
    "ser/config.json": (2494, "949cefff2a0214d29c70097e98451f2d448c9f53677ff9aa92df336ad7dd98dd"),
    "ser/preprocessor_config.json": (
        215,
        "99272fe8ccfab114b68b478681ea47ee3a1ce62bb788cb92dd6e4f69fb1f1da2",
    ),
    "vad/model.onnx": (2243022, "a4a068cd6cf1ea8355b84327595838ca748ec29a25bc91fc82e6c299ccdc5808"),
}
LABELS = ("neutral", "happy", "angry", "sad")
PROFILE = {
    "version": "english-ser-v1",
    "sample_rate": 16000,
    "min_window_ms": 700,
    "max_window_ms": 20000,
    "speech_threshold": 0.5,
    "min_speech_ms": 300,
    "min_speech_fraction": 0.2,
    "suggestion_score": 0.6,
    "suggestion_margin": 0.15,
}


def read_manifest(directory, *, verify=False):
    directory = Path(directory)
    manifest = json.loads((directory / "cinedub-manifest.json").read_text(encoding="utf-8"))
    expected = {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "vad_id": VAD_ID,
        "vad_revision": VAD_REVISION,
        "sha256": {name: value[1] for name, value in MODEL_FILES.items()},
    }
    if not isinstance(manifest, dict) or any(
        manifest.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("Speech-emotion installation does not match the pinned profile")
    for name, (size, wanted) in MODEL_FILES.items():
        path = directory / name
        if not path.is_file() or path.stat().st_size != size:
            raise ValueError("Speech-emotion model installation is incomplete")
        if verify:
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != wanted:
                    raise ValueError("Speech-emotion model bytes changed; reinstall explicitly")
    return manifest


def availability(directory):
    if any(importlib.util.find_spec(name) is None for name in ("numpy", "onnxruntime")):
        return False, "Install the optional local-emotion extra"
    try:
        read_manifest(directory)
    except (OSError, ValueError, TypeError):
        return (
            False,
            "Run scripts/setup-local-emotion.py for experimental English speech-emotion hints",
        )
    return (
        True,
        "Experimental English audio-only emotion hints; four classes, human review required",
    )


class LocalEmotionAnalyzer:
    name = "local"

    def __init__(self, directory, threads=4, timeout_seconds=900):
        self.directory, self.threads, self.timeout_seconds = (
            Path(directory).resolve(),
            threads,
            timeout_seconds,
        )

    def analyze(self, audio_path, output_dir, *, windows, duration_ms, language, cancel, progress):
        if language != "en-IN":
            raise ValueError("This emotion profile supports English source speech only")
        read_manifest(self.directory, verify=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        request = output_dir / "emotion-input.json"
        # Deliberately no transcript, translation, character notes or text sentiment.
        request.write_text(
            json.dumps({"windows": windows, "duration_ms": duration_ms, "profile": PROFILE})
        )
        run_inference(
            "cinedub_api.local_emotion_runner",
            [
                "--model-dir",
                str(self.directory),
                "--audio",
                str(audio_path.resolve()),
                "--request",
                str(request.resolve()),
                "--output-dir",
                str(output_dir.resolve()),
                "--threads",
                str(self.threads),
            ],
            output_dir,
            threads=self.threads,
            timeout_seconds=self.timeout_seconds,
            cancel=cancel,
            progress=progress,
        )
        read_manifest(self.directory, verify=True)
        return json.loads((output_dir / "emotion-result.json").read_text(encoding="utf-8"))
