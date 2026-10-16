import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from .workspace_lock import child_lease_environment, child_process_options


class MediaError(RuntimeError):
    pass


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return name[:180] or "upload.bin"


def probe_media(path: Path) -> dict:
    command = [
        "ffprobe",
        "-protocol_whitelist",
        "file,pipe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            **child_process_options(),
        )
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


def file_digest(path) -> str:
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def run_ffmpeg_capture(arguments, timeout=300, *, cancel=None, loglevel="error"):
    local_arguments = []
    for argument in arguments:
        if argument == "-i":
            local_arguments.extend(["-protocol_whitelist", "file,pipe"])
        local_arguments.append(argument)
    command = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", loglevel, "-y", *local_arguments]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}
    }
    environment.update(child_lease_environment())
    try:
        if cancel is None:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
                env=environment,
                **child_process_options(),
            ).stderr
        cancel()
        with tempfile.TemporaryFile(mode="w+") as log:
            child = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=log,
                start_new_session=True,
                env=environment,
                **child_process_options(),
            )
            started = time.monotonic()
            try:
                while child.poll() is None:
                    cancel()
                    if time.monotonic() - started > timeout:
                        raise TimeoutError("Media processing deadline exceeded")
                    time.sleep(0.1)
                cancel()
                log.seek(max(0, log.tell() - 65536))
                report = log.read()
                if child.returncode:
                    raise MediaError(report.strip()[-1200:] or "FFmpeg operation failed")
                return report
            finally:
                if child.poll() is None:
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        child.wait(timeout=5)
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip()[-1200:] or "FFmpeg operation failed"
        raise MediaError(message) from exc
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise MediaError("FFmpeg is unavailable or the operation timed out") from exc


def run_ffmpeg(arguments: list[str], timeout: int = 300, *, cancel=None) -> None:
    run_ffmpeg_capture(arguments, timeout, cancel=cancel)


def extract_audio(source: Path, destination: Path) -> None:
    info = probe_media(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            canonical_audio_filter(info, 48000),
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )


def audio_offset_ms(info):
    stream = next(item for item in info["streams"] if item.get("codec_type") == "audio")
    start = float(stream.get("start_time") or 0)
    origin = float(info.get("format", {}).get("start_time") or 0)
    return round((start - origin) * 1000)


def canonical_audio_filter(info, sample_rate):
    """Map decoded first audio stream onto the container timeline, including track offset."""
    offset_samples = round(audio_offset_ms(info) * sample_rate / 1000)
    filters = [f"aresample={sample_rate}", "asetpts=PTS-STARTPTS"]
    if offset_samples < 0:
        filters.extend([f"atrim=start_sample={-offset_samples}", "asetpts=PTS-STARTPTS"])
    elif offset_samples > 0:
        filters.append(f"adelay={offset_samples}S:all=1")
    frames = round(info["duration_ms"] * sample_rate / 1000)
    filters.extend([f"apad=whole_len={frames}", f"atrim=end_sample={frames}"])
    return ",".join(filters)


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
