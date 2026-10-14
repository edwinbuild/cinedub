"""Offline MRX inference over prepared stereo float32 PCM with fixed resource limits."""

import argparse
import json
import resource
import subprocess
import time
from pathlib import Path

from .providers.local_separation import MODEL_FILE, MODEL_NAME, read_manifest


def run(model_dir, audio, output_dir, duration_ms, gain_db, threads):
    read_manifest(model_dir, verify=True)
    resource.setrlimit(resource.RLIMIT_AS, (10 * 1024**3, 10 * 1024**3))
    import numpy as np
    import onnxruntime as ort

    from .separation_dsp import STEMS, separate_channels

    ort.disable_telemetry_events()
    if not 0 < duration_ms <= 120000 or audio.stat().st_size > 44100 * 121 * 2 * 4:
        raise ValueError("Separation input exceeds the two-minute laptop profile")
    samples = np.fromfile(audio, dtype="<f4").reshape(-1, 2)
    if len(samples) < 2 or not np.isfinite(samples).all() or not -60 <= gain_db <= 60:
        raise ValueError("Invalid canonical separation input")
    if abs(len(samples) / 44100 * 1000 - duration_ms) > 2:
        raise ValueError("Canonical separation input duration does not match the source")
    gain = 10 ** (gain_db / 20)
    started = time.monotonic()
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(
        str(model_dir / MODEL_FILE), sess_options=options, providers=["CPUExecutionProvider"]
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    def progress(completed, total):
        path = output_dir / "progress.json"
        temporary = path.with_suffix(".part")
        temporary.write_text(json.dumps({"completed": completed, "total": total}), encoding="utf-8")
        temporary.replace(path)

    stems = separate_channels(samples * gain, session, progress=progress) / gain
    residual = samples - stems.sum(axis=0)

    def rms(data):
        return float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))

    metadata = {
        "model": MODEL_NAME,
        "device": "cpu",
        "threads": threads,
        "storage_precision": "int8 weights",
        "compute_precision": "float32",
        "input_gain_db": gain_db,
        "window_seconds": 20,
        "context_seconds": 2,
        "overlap_crossfade_seconds": 4,
        "channels": 2,
        "input_sample_rate": 44100,
        "output_sample_rate": 48000,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "reconstruction_snr_db": round(
            20 * np.log10(max(rms(samples), 1e-10) / max(rms(residual), 1e-10)), 2
        ),
        "warning": "Estimated stems: review dialogue leakage, missing effects and stereo image. "
        "Reconstruction SNR is not separation quality",
        "stems": {},
    }
    for index, name in enumerate(STEMS):
        path = output_dir / f"{name}.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "f32le",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-i",
                "pipe:0",
                "-af",
                f"aresample=48000,apad=whole_len={duration_ms * 48},"
                f"atrim=end_sample={duration_ms * 48}",
                "-c:a",
                "pcm_f32le",
                str(path),
            ],
            input=stems[index].astype("<f4").tobytes(),
            capture_output=True,
            check=True,
            timeout=60,
        )
        metadata["stems"][name] = {
            "filename": path.name,
            "peak": float(np.max(np.abs(stems[index]))),
            "rms": rms(stems[index]),
        }
    result = output_dir / "separation-result.json"
    temporary = result.with_suffix(".part")
    temporary.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    temporary.replace(result)
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration-ms", type=int, required=True)
    parser.add_argument("--gain-db", type=float, default=0)
    parser.add_argument("--threads", type=int, choices=range(1, 9), default=4)
    args = parser.parse_args()
    run(args.model_dir, args.audio, args.output_dir, args.duration_ms, args.gain_db, args.threads)
