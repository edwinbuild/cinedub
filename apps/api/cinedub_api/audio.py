"""Bounded speech fitting and dialogue-only preview rendering with FFmpeg."""

from pathlib import Path

from .media import probe_media, run_ffmpeg


def combine_audio(parts: list[Path], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    arguments = []
    for part in parts:
        arguments.extend(["-i", str(part)])
    if len(parts) > 1:
        labels = "".join(f"[{index}:a]" for index in range(len(parts)))
        arguments.extend(
            ["-filter_complex", f"{labels}concat=n={len(parts)}:v=0:a=1[out]", "-map", "[out]"]
        )
    arguments.extend(["-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(output)])
    run_ffmpeg(arguments)


def fit_dialogue(raw: Path, output: Path, target_ms: int, max_speedup: float) -> dict:
    metadata = probe_media(raw)
    duration = metadata.get("duration_ms")
    if not duration or target_ms <= 0:
        raise ValueError("Candidate audio has no usable duration")
    required_speedup = duration / target_ms
    if required_speedup > max_speedup:
        return {
            "fit_status": "too_long",
            "raw_duration_ms": duration,
            "target_duration_ms": target_ms,
            "required_speedup": required_speedup,
            "warning": "Shorten the translation or expand its timing; safe speed-up limit exceeded",
        }
    speed = max(1.0, required_speedup)
    frames = target_ms * 48  # 48 kHz, exact integer samples for millisecond boundaries.
    filters = (
        f"atempo={speed:.8f},aresample=48000,apad=whole_len={frames},atrim=end_sample={frames}"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(raw),
            "-af",
            filters,
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
    )
    return {
        "fit_status": "ready",
        "raw_duration_ms": duration,
        "target_duration_ms": target_ms,
        "required_speedup": speed,
        "sample_rate": 48000,
        "channels": 2,
    }


def render_dialogue_mix(lines: list[dict], duration_ms: int, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    arguments = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    filters = []
    for index, line in enumerate(lines, start=1):
        arguments.extend(["-i", str(line["path"])])
        filters.append(f"[{index}:a]adelay={line['start_ms']}:all=1[a{index}]")
    labels = "[0:a]" + "".join(f"[a{index}]" for index in range(1, len(lines) + 1))
    filters.append(
        f"{labels}amix=inputs={len(lines) + 1}:duration=first:normalize=0,"
        f"alimiter=limit=0.95:level=0:latency=1,"
        f"atrim=end_sample={duration_ms * 48}[out]"
    )
    arguments.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
    )
    run_ffmpeg(arguments)


def mux_dialogue_preview(proxy: Path, dialogue: Path, output: Path, duration_ms: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(proxy),
            "-i",
            str(dialogue),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            str(duration_ms / 1000),
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
