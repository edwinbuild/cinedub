"""Float mixing, measured normalization and full-resolution stereo review media."""

import math
from fractions import Fraction

from .media import MediaError, probe_media, run_ffmpeg, run_ffmpeg_capture
from .media_quality import loudness_pass, measure_loudness, parse_loudness_report

THREADS = ["-threads", "4", "-filter_threads", "2", "-filter_complex_threads", "2"]


def render_float_sum(tracks, duration_ms, output, cancel):
    arguments = [*THREADS, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    filters = []
    for index, track in enumerate(tracks, 1):
        arguments.extend(["-i", str(track["path"])])
        gain = 0 if track.get("muted") else 10 ** (track.get("gain_db", 0) / 20)
        filters.append(
            f"[{index}:a]aresample=48000,aformat=sample_fmts=flt:channel_layouts=stereo,"
            f"asetpts=PTS-STARTPTS,volume={gain:.12f},"
            f"adelay={track.get('start_ms', 0) * 48}S:all=1[a{index}]"
        )
    labels = "[0:a]" + "".join(f"[a{index}]" for index in range(1, len(tracks) + 1))
    filters.append(
        f"{labels}amix=inputs={len(tracks) + 1}:duration=first:normalize=0,"
        f"atrim=end_sample={duration_ms * 48}[out]"
    )
    run_ffmpeg(
        [
            *arguments,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_f32le",
            str(output),
        ],
        cancel=cancel,
    )


def render_mix_sum(lines, background, settings, duration_ms, directory, cancel):
    # Keep input descriptors and filter graph size bounded for long dialogue timelines.
    groups = []
    for index in range(0, len(lines), 32):
        path = directory / f"dialogue-group-{index // 32}.wav"
        render_float_sum(lines[index : index + 32], duration_ms, path, cancel)
        groups.append({"path": path})
    while len(groups) > 30:
        previous = groups
        groups = []
        for index in range(0, len(previous), 30):
            path = directory / f"submix-{len(previous)}-{index}.wav"
            render_float_sum(previous[index : index + 30], duration_ms, path, cancel)
            groups.append({"path": path})
    tracks = [{**track, "gain_db": settings["dialogue_gain_db"]} for track in groups]
    tracks += [
        {
            "path": background[name],
            "gain_db": settings[f"{name}_gain_db"],
            "muted": settings[f"{name}_muted"],
        }
        for name in ("music", "effects")
    ]
    raw = directory / "unnormalized-float-mix.wav"
    render_float_sum(tracks, duration_ms, raw, cancel)
    return raw


def normalize_mix(raw, destination, duration_ms, settings, cancel):
    target, peak = settings["target_lufs"], settings["true_peak_dbfs"]
    measured = loudness_pass(raw, target_lufs=target, true_peak_dbfs=peak, cancel=cancel)
    values = {
        name: float(measured[name])
        for name in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    }
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("Mix is silent or cannot be measured reliably; inspect takes and stems")
    normalization = (
        f"loudnorm=I={target}:TP={peak}:LRA=50:linear=true:"
        f"measured_I={values['input_i']}:measured_TP={values['input_tp']}:"
        f"measured_LRA={values['input_lra']}:measured_thresh={values['input_thresh']}:"
        f"offset={values['target_offset']}:print_format=json,aresample=48000,"
        f"apad=whole_len={duration_ms * 48},atrim=end_sample={duration_ms * 48}"
    )
    report = run_ffmpeg_capture(
        [
            *THREADS,
            "-i",
            str(raw),
            "-af",
            normalization,
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s24le",
            str(destination),
        ],
        cancel=cancel,
        loglevel="info",
    )
    applied = parse_loudness_report(report)
    if applied["normalization_type"] != "linear" and not settings["allow_dynamic_normalization"]:
        raise ValueError(
            "Peak/loudness targets require dynamics processing. Lower the loudness target "
            "or explicitly allow dynamic normalization after listening review"
        )
    return {"first_pass": measured, "second_pass": applied}


def verify_audio(path, duration_ms, settings, cancel, *, codec, encoded=False):
    info = probe_media(path)
    audio = [stream for stream in info["streams"] if stream.get("codec_type") == "audio"]
    if len(audio) != 1:
        raise ValueError("Export must contain exactly one audio track")
    stream = audio[0]
    if abs(float(stream.get("start_time") or 0) * 1000) > (50 if encoded else 1):
        raise ValueError("Export audio starts outside its timeline synchronization tolerance")
    if (
        stream["codec_name"] != codec
        or int(stream["sample_rate"]) != 48000
        or stream["channels"] != 2
    ):
        raise ValueError("Export audio codec/rate/channel contract failed")
    stream_duration = float(stream.get("duration") or info["format"]["duration"])
    tolerance = 50 if encoded else 1
    if abs(stream_duration * 1000 - duration_ms) > tolerance:
        raise ValueError("Export audio duration does not match the source timeline")
    sample_count = None
    if not encoded:
        sample_count = round(int(stream["duration_ts"]) * Fraction(stream["time_base"]) * 48000)
        if sample_count != duration_ms * 48:
            raise ValueError("Export PCM sample count does not match the source timeline")
    levels = measure_loudness(path, cancel=cancel)
    if levels["integrated_lufs"] is None or levels["true_peak_dbfs"] is None:
        raise ValueError("Export loudness/peak could not be verified")
    if abs(levels["integrated_lufs"] - settings["target_lufs"]) > 1:
        raise ValueError("Export loudness missed target by more than 1 LU; adjust the mix")
    # Lossy AAC can overshoot its PCM input: separate, explicit delivery tolerance.
    peak_limit = settings["true_peak_dbfs"] + (1 if encoded else 0.2)
    if levels["true_peak_dbfs"] > peak_limit:
        raise ValueError("Export true peak exceeded its delivery limit")
    # Decode every frame, failing on corrupt packets rather than only trusting ffprobe.
    run_ffmpeg(["-xerror", "-i", str(path), "-map", "0:a:0", "-f", "null", "-"], cancel=cancel)
    return {
        "codec": codec,
        "sample_rate": 48000,
        "channels": 2,
        "sample_count": sample_count,
        "duration_ms": round(stream_duration * 1000),
        **levels,
        "true_peak_limit_dbfs": peak_limit,
        "loudness_tolerance_lu": 1,
        "decode_verified": True,
    }


def mux_source_video(source, master, output, duration_ms, cancel):
    info = probe_media(source)
    video = next(
        (stream for stream in info["streams"] if stream.get("codec_type") == "video"), None
    )
    if not video:
        return None
    if video.get("color_transfer") in {"smpte2084", "arib-std-b67"}:
        raise ValueError(
            "This stereo SDR review profile cannot convert HDR safely; "
            "use an HDR mastering workflow"
        )
    copy = video["codec_name"] == "h264" and video.get("pix_fmt") == "yuv420p"
    arguments = [
        *THREADS,
        "-copyts",
        "-start_at_zero",
        "-i",
        str(source),
        "-i",
        str(master),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map_metadata",
        "-1",
        "-c:v",
        "copy" if copy else "libx264",
    ]
    if not copy:
        arguments += [
            "-preset",
            "fast",
            "-crf",
            "18",
            "-vf",
            "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-pix_fmt",
            "yuv420p",
        ]
        arguments += ["-fps_mode", "passthrough"]
    arguments += [
        "-threads",
        "4",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-t",
        str(duration_ms / 1000),
        "-movflags",
        "+faststart",
        str(output),
    ]
    run_ffmpeg(arguments, cancel=cancel)
    exported = probe_media(output)
    streams = exported["streams"]
    output_video = next(stream for stream in streams if stream.get("codec_type") == "video")
    if len(streams) != 2 or output_video["codec_name"] != "h264":
        raise MediaError("Export video/stream contract failed")
    if output_video["width"] not in {
        video["width"],
        video["width"] + video["width"] % 2,
    } or output_video["height"] not in {video["height"], video["height"] + video["height"] % 2}:
        raise MediaError("Export unexpectedly changed video resolution")
    if abs(exported["duration_ms"] - duration_ms) > 100:
        raise MediaError("Export video duration is outside its 100 ms container tolerance")
    expected_start = float(video.get("start_time") or 0) - float(
        info["format"].get("start_time") or 0
    )
    try:
        rate = float(Fraction(video.get("avg_frame_rate") or "0/1"))
    except (ValueError, ZeroDivisionError):
        rate = 0
    frame_seconds = 1 / rate if rate > 0 else 0.1
    if abs(float(output_video.get("start_time") or 0) - expected_start) > max(frame_seconds, 0.001):
        raise MediaError("Export video start timestamp changed relative to its source timeline")
    run_ffmpeg(["-xerror", "-i", str(output), "-map", "0:v:0", "-f", "null", "-"], cancel=cancel)
    return {
        "codec": "h264",
        "source_video_copied": copy,
        "width": output_video["width"],
        "height": output_video["height"],
        "duration_ms": exported["duration_ms"],
        "start_time_seconds": float(output_video.get("start_time") or 0),
        "start_timestamp_tolerance_ms": round(max(frame_seconds, 0.001) * 1000, 3),
        "decode_verified": True,
        "profile": "SDR stereo review; not DCP, HDR or surround mastering",
    }
