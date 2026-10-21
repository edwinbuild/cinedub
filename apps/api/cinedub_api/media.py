import json
import re
import shutil
import subprocess
import wave
from pathlib import Path


class MediaError(RuntimeError):
    pass


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return name[:180] or "upload.bin"


def probe_media(path: Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise MediaError("The uploaded file is not readable media") from exc
    payload = json.loads(result.stdout)
    duration = payload.get("format", {}).get("duration")
    payload["duration_ms"] = round(float(duration) * 1000) if duration else None
    return payload


def write_srt(segments: list, path: Path) -> None:
    def timestamp(milliseconds: int) -> str:
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, millis = divmod(remainder, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"

    blocks = []
    for position, segment in enumerate(segments, start=1):
        text = segment.translated_text or segment.source_text
        blocks.append(
            f"{position}\n{timestamp(segment.start_ms)} --> {timestamp(segment.end_ms)}\n{text}\n"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(blocks), encoding="utf-8")


def copy_reference_video(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def run_ffmpeg(arguments: list[str], timeout: int = 300) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *arguments]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip()[-1200:] or "FFmpeg operation failed"
        raise MediaError(message) from exc
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise MediaError("FFmpeg is unavailable or the operation timed out") from exc


def extract_audio(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )


def create_preview_proxy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            "scale='min(1280,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "24",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )


def write_waveform(audio_path: Path, destination: Path, points: int = 800) -> None:
    with wave.open(str(audio_path), "rb") as audio:
        channels = audio.getnchannels()
        sample_width = audio.getsampwidth()
        frame_count = audio.getnframes()
        if sample_width != 2:
            raise MediaError("Waveform generation expects 16-bit PCM audio")
        frames_per_point = max(1, frame_count // points)
        peaks: list[float] = []
        while data := audio.readframes(frames_per_point):
            samples = memoryview(data).cast("h")
            peak = max((abs(value) for value in samples), default=0) / 32768
            peaks.append(round(min(1.0, peak), 4))
        payload = {
            "sample_rate": audio.getframerate(),
            "channels": channels,
            "duration_ms": round(frame_count / audio.getframerate() * 1000),
            "peaks": peaks,
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
