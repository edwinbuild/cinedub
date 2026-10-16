# Local speech emotion execution evaluation

## Scope

The optional local classifier supplies review-only English source-performance hints. This record covers execution, bounded resources, negative controls and review persistence, not emotion-recognition accuracy or cinematic quality.

## Frozen models and profile

| Component | Pinned identity | Purpose |
| --- | --- | --- |
| Emotion classifier | `onnx-community/wav2vec2-base-superb-er-ONNX@e2191e9e8b692c19c7d96e2a1d789ab1df5b7259` | Four English training labels; raw mono 16 kHz input |
| Speech detector | `onnx-community/silero-vad@e71cae966052b992a7eca6b17738916ce0eca4ec` | Withhold labels when insufficient speech is detected |
| Routing profile | `english-ser-v1` | 700–20000 ms windows, speech score threshold 0.5, at least 300 ms and 20% speech, suggested class score at least 0.6 and margin at least 0.15 |

Thresholds are provisional and not calibrated. Exact graph/config hashes are in `providers/local_emotion.py`. See [the architecture decision](../decisions/0011-reviewed-speech-emotion.md) for licensing and use limits.

## Reproduction

Install the extra alongside any other extras you already use; `uv sync` may otherwise remove those optional dependencies.

```bash
uv sync --extra local-asr --extra local-separation --extra local-alignment --extra local-dialogue --extra local-emotion --group dev
PYTHONPATH=apps/api .venv/bin/python scripts/setup-local-emotion.py
PYTHONPATH=apps/api .venv/bin/python scripts/evaluate-local-emotion.py
CINEDUB_E2E_EMOTION=1 npm run test:e2e -- tests/e2e/speech-emotion.spec.ts
```

The setup is explicit and public, without an HF token. Later jobs run offline. The smoke script creates original eSpeak NG English speech, a two-second 220 Hz tone and two seconds of silence under ignored `data/evaluation/`. Browser tests use isolated temporary projects, fake transcription and real local emotion inference; fake transcripts are not recognition evidence. No paid API is called.

## Measured smoke result

On 2026-10-16, the installed CPU graphs processed an 8.482-second control scene with four threads. Native inference/VAD time was 1.762 seconds and peak child RSS was 705.8 MiB; this excludes model download and parent-side setup/checksum overhead.

| Control | Observed result | What it establishes |
| --- | --- | --- |
| 4.482 s synthetic English speech | Neutral suggestion; 3616 ms detected speech | Audio inference executes; not a correct-emotion benchmark |
| 2 s tone | No label; 128 ms detected speech, below the required thresholds | This particular non-speech control is withheld; not universal music rejection |
| 2 s silence | No label and no emotion inference | Silence is not assigned a fabricated emotion |

The real-model browser workflow passed generation, immutable evidence download, explicit human correction, reload persistence, unchanged dialogue and the 390-pixel layout check. Unit/API coverage checks malformed provenance/scores, stale or changed audio/windows, append-only review conflicts, native import isolation, stable softmax and VAD padding/state reset. These checks are not human listening or model-quality acceptance.

## Open quality gates

Use authorized natural performances and independent human labels to measure four-class accuracy, class balance, ambiguity/abstention, speech false positives and errors on unseen delivery. Include out-of-class emotions and background contamination. Keep test material outside Git and document its rights. Do not infer actors' psychological states, evaluate Malayalam with this English profile, or connect hints to automatic synthesis controls before separate quality and consent review.
