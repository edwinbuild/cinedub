"""Measured media levels; silence/non-finite readings remain explicit, never invented."""

import json
import math
import re

from .media import MediaError, run_ffmpeg_capture


def loudness_pass(path, input_options=(), *, target_lufs=-27, true_peak_dbfs=-2, cancel=None):
    try:
        report = run_ffmpeg_capture(
            [
                *input_options,
                "-i",
                str(path),
                "-af",
                f"loudnorm=I={target_lufs}:TP={true_peak_dbfs}:LRA=50:print_format=json",
                "-f",
                "null",
                "-",
            ],
            timeout=60,
            cancel=cancel,
            loglevel="info",
        )
        return parse_loudness_report(report)
    except (ValueError, IndexError, KeyError) as exc:
        raise MediaError("Could not measure audio loudness") from exc


def parse_loudness_report(report):
    return json.loads(re.findall(r"\{[^{}]+\}", report)[-1])


def measure_loudness(path, input_options=(), *, cancel=None):
    raw = loudness_pass(path, input_options, cancel=cancel)
    output = {}
    for key, field in [
        ("input_i", "integrated_lufs"),
        ("input_tp", "true_peak_dbfs"),
        ("input_lra", "loudness_range_lu"),
    ]:
        value = float(raw[key])
        output[field] = value if math.isfinite(value) else None
    return output
