"""Versioned stock catalog and application-owned candidate signatures."""

import hashlib
import json
import math

from .schemas import VoiceChoice


def stock_variation(value) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.01 <= value <= 1
    ):
        raise ValueError("Stock generation variation must be a finite number from 0.01 to 1")
    return float(value)


# Bulbul v3 catalog checked against Sarvam's official REST documentation on 2026-10-14.
# Pinning the model prevents accidentally sending v3 names to v4 persona models.
SARVAM_V3_VOICES = (
    "shubh",
    "aditya",
    "ritu",
    "priya",
    "neha",
    "rahul",
    "pooja",
    "rohan",
    "simran",
    "kavya",
    "amit",
    "dev",
    "ishita",
    "shreya",
    "ratan",
    "varun",
    "manan",
    "sumit",
    "roopa",
    "kabir",
    "aayan",
    "ashutosh",
    "advait",
    "anand",
    "tanya",
    "tarun",
    "sunny",
    "mani",
    "gokul",
    "vijay",
    "shruti",
    "suhani",
    "mohit",
    "kavitha",
    "rehan",
    "soham",
    "rupali",
)


def stock_catalog(provider: str) -> list[VoiceChoice]:
    names = SARVAM_V3_VOICES if provider == "sarvam" else ("speaker-a", "speaker-b")
    return [
        VoiceChoice(
            id=name,
            display_name=name.title(),
            provider=provider,
            model="bulbul:v3" if provider == "sarvam" else "deterministic-fixture-v1",
            language="ml-IN",
        )
        for name in names
    ]


def candidate_signature(line: dict, voice: dict) -> str:
    material = {
        field: line[field]
        for field in ("source_text", "translated_text", "start_ms", "end_ms", "speaker_id")
    }
    material["voice"] = voice
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
