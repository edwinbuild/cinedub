"""Local synthetic Malayalam speech probe; not a natural-speech or language-expert score."""

import argparse
import hashlib
import json
import os
import resource
import subprocess
import tempfile
import time
import wave
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "4"


def evaluate(model_dir, text):
    resource.setrlimit(resource.RLIMIT_AS, (10 * 1024**3, 10 * 1024**3))
    import numpy as np
    import onnxruntime as ort
    from cinedub_api.alignment_dsp import force_align, malayalam_tokens

    root = Path("data/evaluation")
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="malayalam-alignment-", dir=root))
    original, prepared = directory / "speech.wav", directory / "speech-16k.wav"
    subprocess.run(
        ["espeak-ng", "-v", "ml", "-s", "135", "-w", str(original), text],
        check=True,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(original),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-af",
            "adelay=500:all=1,apad=pad_dur=0.5",
            "-c:a",
            "pcm_s16le",
            str(prepared),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with wave.open(str(prepared)) as handle:
        samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(
            np.float32
        )
    if len(samples) > 16000 * 20:
        raise ValueError("Synthetic probe exceeds a 20-second window")
    samples /= 32768
    samples = (samples - samples.mean()) / np.sqrt(samples.var() + 1e-7)
    path = model_dir / "model_quantized.onnx"
    with path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != (
            "40a80cff1d5750939ca8f657587ed05b826d75466df9f83f7344154b9e61f12a"
        ):
            raise ValueError("Malayalam probe graph checksum does not match the pinned conversion")
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = 4, 1
    ort.disable_telemetry_events()
    started = time.monotonic()
    model = ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    feed = {"input_values": samples[None]}
    if any(item.name == "attention_mask" for item in model.get_inputs()):
        feed["attention_mask"] = np.ones((1, len(samples)), dtype=np.int64)
    logits = model.run(None, feed)[0][0]
    vocab = json.loads((model_dir / "vocab.json").read_text())
    normalized, tokens = malayalam_tokens(text, vocab)
    alignment = force_align(
        logits, tokens, normalized, vocab, offset_ms=0, duration_ms=len(samples) // 16
    )
    summary = {
        "text": text,
        "fixture": "Original synthetic eSpeak NG Malayalam, not human speech",
        "duration_ms": len(samples) // 16,
        "alignment": alignment,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "inputs": [(item.name, item.shape, item.type) for item in model.get_inputs()],
        "output_shape": logits.shape,
    }
    (directory / "evaluation.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Local evidence: {directory}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=Path("models/wav2vec2-malayalam"))
    parser.add_argument("--text", default="നമസ്കാരം. ഇത് ഒരു ചെറിയ പരീക്ഷണം ആണ്.")
    args = parser.parse_args()
    evaluate(args.model_dir, args.text)
