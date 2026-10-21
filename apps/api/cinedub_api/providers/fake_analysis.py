"""Deterministic DEMO analysis adapters.

They exercise the real job, review and lineage paths without models. They never measure
audio, infer emotion or adapt language; every output says so explicitly.
"""

import hashlib
import json

from ..dialogue_prompt import request_digest
from ..performance_comparison import compare_performance
from .fake_media import DEMO_MODEL

DEMO_NOTE = "DEMO fixture: not measured"
EMOTION_WARNING = "DEMO: no speech-emotion analysis was performed"
EMOTION_PROFILE = {
    "version": "demo-no-analysis-v1",
    "sample_rate": 16000,
    "min_window_ms": 700,
    "max_window_ms": 20000,
    "speech_threshold": 0.5,
    "min_speech_ms": 300,
    "min_speech_fraction": 0.2,
    "suggestion_score": 1.0,
    "suggestion_margin": 1.0,
}
EMOTION_MANIFEST = {"demo": True, "vad_id": "none", "vad_revision": "demo"}
DIALOGUE_MANIFEST = {"demo": True, "engine_tag": "demo", "engine_commit": "demo"}


def unmeasured_performance(word_count=0, duration_ms=0):
    return {
        "method": "acoustic-dsp-v1",
        "rms_dbfs": None,
        "peak_dbfs": None,
        "pitch_median_hz": None,
        "pitch_p10_hz": None,
        "pitch_p90_hz": None,
        "energy_active_ratio": 0,
        "activity_threshold_dbfs": -50,
        "words_per_minute": round(word_count / (duration_ms / 60_000), 1) if duration_ms else 0,
        "pauses": [],
        "frames": [],
        "warnings": [DEMO_NOTE + "; words per minute is counted from text"],
    }


def spread_words(text, start_ms, end_ms):
    """Evenly spaced placeholder word slots; never acoustic evidence."""
    words = text.split()[: max(1, end_ms - start_ms)]
    if not words or end_ms <= start_ms:
        return []
    step = (end_ms - start_ms) / len(words)
    result = []
    for index, word in enumerate(words):
        start = start_ms + round(index * step)
        end = max(start + 1, start_ms + round((index + 1) * step))
        result.append(
            {"text": word, "start_ms": start, "end_ms": min(end, end_ms), "acoustic_score": 0.0}
        )
    return result


class FakeAligner:
    name = "fake"
    model = DEMO_MODEL

    def align(self, audio_path, output_dir, *, lines, duration_ms, language, cancel, progress):
        cancel()
        evidence = []
        for index, line in enumerate(lines, start=1):
            words = spread_words(line["source_text"], line["start_ms"], line["end_ms"])
            evidence.append(
                {
                    "segment_id": line["id"],
                    "segment_version": line["version"],
                    "source_text": line["source_text"],
                    "original_start_ms": line["start_ms"],
                    "original_end_ms": line["end_ms"],
                    "status": "needs_review",
                    "words": words,
                    "acoustic_score": None,
                    "greedy_text": "",
                    "text_error_ratio": None,
                    "performance": unmeasured_performance(
                        len(words), line["end_ms"] - line["start_ms"]
                    ),
                    "warnings": ["DEMO: evenly spaced placeholder words, not forced alignment"],
                }
            )
            progress(index, len(lines))
        return {"model": self.model, "lines": evidence, "metadata": {"latency_ms": 0, "demo": True}}


class FakeTakeAnalyzer:
    name = "fake"
    model = DEMO_MODEL

    def compare(self, request, output_dir, *, cancel, progress):
        cancel()
        lines = []
        takes = request["takes"]
        for index, take in enumerate(takes, start=1):
            duration = take["end_ms"] - take["start_ms"]
            source = unmeasured_performance(len(take["source_text"].split()), duration)
            target = unmeasured_performance(len(take["translated_text"].split()), duration)
            status = "unalignable" if request["include_target_alignment"] else "not_requested"
            lines.append(
                {
                    "candidate_id": take["candidate_id"],
                    "source_performance": source,
                    "target_performance": target,
                    "target_alignment": {
                        "status": status,
                        "model": DEMO_MODEL if request["include_target_alignment"] else None,
                        "words": [],
                        "warnings": ["DEMO: no target-language alignment was performed"]
                        if request["include_target_alignment"]
                        else [],
                    },
                    "comparison": compare_performance(
                        source,
                        target,
                        start_ms=take["start_ms"],
                        end_ms=take["end_ms"],
                        fitted_padding_ms=take["fitted_padding_ms"],
                    ),
                }
            )
            progress(index, len(takes))
        return {
            "lines": lines,
            "metadata": {
                "model": self.model,
                "target_alignment_model": DEMO_MODEL
                if request["include_target_alignment"]
                else None,
                "device": "none",
                "latency_ms": 0,
                "target_alignment_requested": request["include_target_alignment"],
                "target_inference_count": 0,
                "demo": True,
            },
        }


def concise_variant(text):
    words = text.split()
    kept = words[: max(1, (len(words) * 3 + 3) // 4)]
    return " ".join(kept)


class FakeDialogueAdapter:
    name = "fake"
    model = DEMO_MODEL

    def adapt(self, request, output_dir, *, cancel, progress):
        cancel()
        completed = list(request.get("completed_lines", []))
        for line in request["lines"][len(completed) :]:
            draft = line["data"]["draft_translation"].strip() or line["data"]["source_text"]
            serialized = json.dumps(line, sort_keys=True, ensure_ascii=False)
            completed.append(
                {
                    "segment_id": line["segment_id"],
                    "output": {
                        "faithful": draft,
                        "concise": concise_variant(draft),
                        "notes": "DEMO fixture: rule-based word trim, not a language model",
                    },
                    "prompt_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                    "request_sha256": request_digest(line),
                    "prompt_tokens": max(1, min(3312, len(serialized) // 4)),
                    "latency_ms": 0,
                }
            )
            progress(list(completed))
        return {
            "provider": self.name,
            "model": self.model,
            "prompt_version": request["prompt_version"],
            "parameters": request["parameters"],
            "lines": completed,
            "runtime": {"elapsed_ms": 0, "peak_rss_mib": 0, "threads": 1},
        }


class FakeEmotionAnalyzer:
    name = "fake"
    model = DEMO_MODEL

    def analyze(self, audio_path, output_dir, *, windows, duration_ms, language, cancel, progress):
        cancel()
        lines = []
        for index, window in enumerate(windows, start=1):
            lines.append(
                {
                    "segment_id": window["id"],
                    "start_ms": window["start_ms"],
                    "end_ms": window["end_ms"],
                    "status": "not_analyzed",
                    "suggested_label": None,
                    "scores": [],
                    "score_margin": None,
                    "speech_ms": 0,
                    "speech_fraction": 0,
                    "rms_dbfs": None,
                    "warnings": [EMOTION_WARNING],
                }
            )
            progress(index, len(windows))
        return {
            "provider": self.name,
            "model": self.model,
            "profile": EMOTION_PROFILE,
            "lines": lines,
            "metadata": {
                "elapsed_ms": 0,
                "peak_rss_mib": 0,
                "threads": 1,
                "emotion_inference_count": 0,
                "vad_frame_count": 0,
                "demo": True,
            },
        }
