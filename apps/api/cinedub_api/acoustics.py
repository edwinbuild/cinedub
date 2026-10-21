"""Language-independent signal measurements. Not speaker identity, VAD, intent or emotion."""

import numpy as np

SAMPLE_RATE = 16000
FRAME = 640  # 40 ms, enough for ~70 Hz with a conservative pitch range.
HOP = 320  # 20 ms. Curves remain bounded to at most 6000 frames per two-minute scene.


def dbfs(value):
    return round(float(20 * np.log10(value)), 2) if value > 1e-10 else None


def pitch(frame):
    frame = frame.astype(np.float64) - np.mean(frame)
    power = frame * frame
    if power.sum() < 1e-9:
        return None
    correlation = np.fft.irfft(np.abs(np.fft.rfft(frame, n=2048)) ** 2, n=2048)
    lags = np.arange(32, 229)  # 500..70 Hz; not reliable for all characters/whispers.
    sums = np.r_[0, np.cumsum(power)]
    denominator = np.sqrt(sums[FRAME - lags] * (sums[FRAME] - sums[lags]))
    correlation = correlation[lags] / np.maximum(denominator, 1e-12)
    peaks = (
        np.flatnonzero(
            (correlation[1:-1] > correlation[:-2]) & (correlation[1:-1] >= correlation[2:])
        )
        + 1
    )
    if not len(peaks):
        return None
    strong = peaks[correlation[peaks] >= max(0.7, float(correlation[peaks].max()) * 0.9)]
    if not len(strong):
        return None
    index = int(strong[0])
    a, b, c = correlation[index - 1 : index + 2]
    adjustment = 0.5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c else 0
    return round(float(SAMPLE_RATE / (lags[index] + adjustment)), 1)


def measure_performance(samples, *, offset_ms=0, word_count=0):
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 1 or not 0 < len(samples) <= 120 * SAMPLE_RATE:
        raise ValueError("Acoustic input must be mono 16 kHz within the two-minute limit")
    if not np.isfinite(samples).all():
        raise ValueError("Non-finite acoustic samples")
    frames = []
    for start in range(0, len(samples), HOP):
        raw = samples[start : start + FRAME]
        frames.append((start, raw, dbfs(float(np.sqrt(np.mean(raw * raw))))))
    highest = max((level for _, _, level in frames if level is not None), default=-120)
    threshold = max(-50.0, highest - 35)
    curves, active, pitches = [], [], []
    for start, raw, level in frames:
        is_active = level is not None and level >= threshold
        value = (
            pitch(np.pad(raw, (0, FRAME - len(raw)))) if is_active and len(raw) == FRAME else None
        )
        if value is not None:
            pitches.append(value)
        active.append(is_active)
        curves.append({"time_ms": offset_ms + start // 16, "rms_dbfs": level, "pitch_hz": value})
    pauses, beginning = [], None
    for index, is_active in enumerate([*active, True]):
        time_ms = min(len(samples), index * HOP) // 16 + offset_ms
        if not is_active and beginning is None:
            beginning = time_ms
        if is_active and beginning is not None:
            if time_ms - beginning >= 150:
                pauses.append({"start_ms": beginning, "end_ms": time_ms})
            beginning = None
    return {
        "method": "acoustic-dsp-v1",
        "rms_dbfs": dbfs(float(np.sqrt(np.mean(samples * samples)))),
        "peak_dbfs": dbfs(float(np.max(np.abs(samples)))),
        "pitch_median_hz": round(float(np.median(pitches)), 1) if pitches else None,
        "pitch_p10_hz": round(float(np.percentile(pitches, 10)), 1) if pitches else None,
        "pitch_p90_hz": round(float(np.percentile(pitches, 90)), 1) if pitches else None,
        "energy_active_ratio": round(sum(active) / len(active), 4),
        "activity_threshold_dbfs": round(threshold, 2),
        "words_per_minute": round(word_count * 60 * SAMPLE_RATE / len(samples), 1),
        "pauses": pauses,
        "frames": curves,
        "warnings": [
            "Signal measurements, not emotion, speaker identity or validated speech activity",
            "Pitch can be unreliable with noise, music, overlapping speakers or whispers; "
            "range 70–500 Hz",
            "Level and energy pauses describe this analysis audio, "
            "which may have been gain-normalized",
        ],
    }
