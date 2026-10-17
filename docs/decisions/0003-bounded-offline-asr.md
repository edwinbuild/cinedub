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

## Human-performed transcript diagnostic (2026-10-17)

`scripts/evaluate-local-asr.py` runs the existing production adapter on the fixed 24-clip CREMA-D scene already used for [emotion diagnostics](../evaluations/speech-emotion.md). To prepare only the licensed data without installing/running emotion models:

```bash
PYTHONPATH=apps/api .venv/bin/python scripts/evaluate-emotion-benchmark.py --prepare-only
PYTHONPATH=apps/api .venv/bin/python scripts/evaluate-local-asr.py --dataset-directory /tmp/cinedub-crema-d-EXAMPLE
```

Use the actual private directory printed by preparation. Metadata preparation requires public network access; native ASR runs offline with already installed weights. No paid API, model download, actor enrollment or training occurs. Dataset recordings, the copied input scene, reference/hypothesis, exact case mappings, source documentation and detailed reports stay in private temporary directories outside Git. Only aggregate evidence and tooling are committed.

The pinned [CREMA-D README](https://github.com/CheyneyComputerScience/CREMA-D/blob/1658cd342dff90010aa843eaeebd53610a08b1dc/README.md) supplies the documented sentence-code map. Its Git blob SHA1 is `394e5758ef79b060a53fc5d083a017b552598d84`; the selection CSV and original recordings retain the existing pinned checks. The dataset declares ODbL/DbCL terms and requests registration; attribution is retained, no personal information is submitted, and these declarations are not actor-cloning consent or commercial clearance. No demographic files are accessed.

Reference sentences are derived from the fixed filenames and never passed as prompts/model inputs. The original recording hashes and normalized windows must match the baseline scene, which is copied into a new private directory and checked after inference. Model installation is verified before/after; reports retain model identity/manifest, scene/selection hashes, runtime package versions, runner source hash and native resource metadata. Word-error counts use minimum-edit alignment after Unicode casefolding, apostrophe removal and word tokenization. Numbers and expanded contractions are not equated; this is an explicit literal convention, not the Whisper benchmark normalizer. Insertions may yield WER over 100%, and a missing denominator is never labelled zero-error accuracy.

| Measurement | First run | Snapshot-bound repeat |
| --- | --- | --- |
| Input | Same 24 clips / 68.773 s | Same scene checksum |
| Reference / recognized words | 133 / 129 | 133 / 124 |
| Substitutions / deletions / insertions | 6 / 8 / 4 | 5 / 10 / 1 |
| Diagnostic word error rate | 18/133 = 13.53% | 16/133 = 12.03% |
| Native CPU inference time | 33.620 s | 27.200 s |
| Peak child RSS | 1153.3 MiB | 1152.2 MiB |
| Adapter wall time | 36.840 s | 29.799 s |

Both runs used the same model revision/scene hash, CPU int8 and four threads. Installed faster-whisper was 1.2.1 and CTranslate2 4.8.3. Its inspected `WhisperModel.transcribe` implementation permits the default fallback temperatures `[0.0, 0.2, 0.4, 0.6, 0.8, 1.0]`; the current native report does not expose which temperature was used per segment. Sampling fallback may contribute to variation, but the exact cause was not established. Neither run is selected as a stable guarantee or advertised as “accuracy.” Future work must freeze/version decoding choices and record actual fallback decisions before claiming repeatability.

This is a stitched acted-English diagnostic with 250 ms gaps, a selection originally balanced by crowd emotion labels and repeated standard sentences—not a random sample of natural movie dialogue. The reference utterances have not been human-listening verified; filename/script text can differ from what an actor actually said. Whisper training overlap is unknown. There is no measured speaker identification, noise/separation robustness, word-timing accuracy, translation quality or Malayalam acceptance. The result supports continued manual correction/review, not completed cinema quality.

All 41 focused scoring/audio/ASR-adapter/emotion-dataset/candidate checks passed, including the final CLI report/snapshot flow with mocked inference, and two real native ASR runs completed. Prepare-only/default dataset modes are covered by synthetic unit fixtures with mocked downloads/inference, not a new live preparation run. Ruff/format and diff checks passed. No application behavior, API contract, database schema or browser UI changed; no new full-suite/build/browser claim is made for this diagnostic-only milestone.
