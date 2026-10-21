"""Describe source/take differences without an invented quality or emotion-match score."""

import math


def active_span(performance, start_ms, end_ms):
    times = [
        frame["time_ms"]
        for frame in performance["frames"]
        if frame["rms_dbfs"] is not None
        and frame["rms_dbfs"] >= performance["activity_threshold_dbfs"]
    ]
    if not times:
        return 0, 0
    first, last = max(start_ms, min(times)), min(end_ms, max(times) + 20)
    internal = sum(
        max(0, min(last, pause["end_ms"]) - max(first, pause["start_ms"]))
        for pause in performance["pauses"]
    )
    return last - first, internal


def compare_performance(source, target, *, start_ms, end_ms, fitted_padding_ms):
    source_span, source_pauses = active_span(source, start_ms, end_ms)
    target_span, target_pauses = active_span(target, start_ms, end_ms)
    source_pitch, target_pitch = source["pitch_median_hz"], target["pitch_median_hz"]
    rms_delta = (
        target["rms_dbfs"] - source["rms_dbfs"]
        if source["rms_dbfs"] is not None and target["rms_dbfs"] is not None
        else None
    )
    return {
        "rms_delta_db": round(rms_delta, 2) if rms_delta is not None else None,
        "pitch_shift_semitones": round(12 * math.log2(target_pitch / source_pitch), 2)
        if source_pitch and target_pitch
        else None,
        "source_active_span_ms": source_span,
        "target_active_span_ms": target_span,
        "source_internal_pause_ms": source_pauses,
        "target_internal_pause_ms": target_pauses,
        "active_span_delta_ms": target_span - source_span,
        "fitted_padding_ms": fitted_padding_ms,
    }
