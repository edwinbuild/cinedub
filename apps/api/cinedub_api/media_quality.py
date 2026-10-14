"""Measured media levels; silence/non-finite readings remain explicit, never invented."""

import json
import math
import re
import subprocess

from .media import MediaError


def measure_loudness(path, input_options=()):
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                *input_options,
                "-i",
                str(path),
                "-af",
                "loudnorm=I=-27:TP=-2:LRA=7:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        raw = json.loads(re.findall(r"\{[^{}]+\}", result.stderr)[-1])
    except (subprocess.SubprocessError, FileNotFoundError, ValueError, IndexError) as exc:
        raise MediaError("Could not measure audio loudness") from exc
    output = {}
    for key, field in [
        ("input_i", "integrated_lufs"),
        ("input_tp", "true_peak_dbfs"),
        ("input_lra", "loudness_range_lu"),
    ]:
        value = float(raw[key])
        output[field] = value if math.isfinite(value) else None
    return output
