# ADR 0003: Bounded, optional offline English transcription

Status: accepted implementation profile, 2026-10-14. This advances the agreed local-model roadmap while live Sarvam credentials are deferred; it does not replace the Sarvam translation/voice decision.

## Decision

Use faster-whisper with Systran/faster-whisper-small.en at revision `d1d751a5f8271d482d14ca55d9e2deeebbae577f`. Install it explicitly through the optional `local-asr` extra and a setup script; keep converted model data/checksums in ignored `models/`. Runtime inference is offline and never requests remote model code.

Start with CPU int8, four threads, a single durable worker and a maximum two-minute input. Each inference lives in its own subprocess with a 10 GiB virtual-memory cap, cancellation and deadline. Release model memory when the subprocess exits. No GPU libraries, driver replacement or fine-tuning are required. The laptop has an RTX 3070 Ti Laptop GPU with 8 GiB VRAM; a detected driver is not evidence of GPU inference compatibility.

Job admission freezes model revision, directory, checksum manifest, thread count and deadline. The worker verifies checksums and rejects changes after scheduling. Local work is free of API billing and safely retryable after worker recovery. Model revision, device, precision, latency, peak RSS, raw word estimates and missing-diarization warnings are retained as provenance.

## Tradeoffs

- This English-only model is an inexpensive transcription alternative, not a speaker diarizer, Malayalam recognizer, forced aligner, emotion model or voice generator.
- Lines begin with unassigned speakers. Editors create speakers and assign lines explicitly rather than receiving invented speaker identities.
- Correcting speakers or English before translation must not prevent filling an empty Malayalam field. Existing human translations remain protected; asynchronous results still use version checks.
- Per-job model loading adds latency but bounds retained memory and allows cancellation of native inference.
- The canonical 16 kHz mono PCM ingest output is read directly. Arbitrary-container decoding in the model library is not part of this boundary.
- A model switch uses the transcriber adapter/routing boundary. Expanding this profile to another model, language, GPU or diarizer requires its own resource and quality evaluation.

## Evidence and remaining gates

One original 14.8-second eSpeak-generated two-voice scene produced the expected transcript in 4.484 seconds, with 623.5 MiB peak process RSS on CPU. A separate real browser/API/worker workflow recognized original speech and persisted manual speaker assignment. Neither proves natural acting, background-noise robustness or speaker separation. Evaluate licensed natural scenes before making accuracy or production-readiness claims.
