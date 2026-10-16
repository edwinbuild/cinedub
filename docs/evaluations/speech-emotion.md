# Local speech emotion execution evaluation

## Scope

The optional local classifier supplies review-only English source-performance hints. This record covers execution, bounded resources, negative controls, review persistence and a small diagnostic of label agreement. It does not establish cinematic quality.

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

## Human-performed speech diagnostic (2026-10-16)

The opt-in `PYTHONPATH=apps/api .venv/bin/python scripts/evaluate-emotion-benchmark.py` downloads 24 English recordings from [CREMA-D](https://github.com/CheyneyComputerScience/CREMA-D/tree/1658cd342dff90010aa843eaeebd53610a08b1dc). The database declares ODbL 1.0 and its contents DbCL 1.0; attribution is Cao et al. (2014), DOI 10.1109/TAFFC.2014.2336244. The maintainers request registration; the script does not submit personal information. These terms are not voice-cloning consent or a commercial/legal clearance assessment.

Selection uses single-label **audio-only crowd majority votes**, not filename/intended emotion: four clips per neutral, happy, angry, sad, fearful and disgusted class, ranked by SHA256 of fixed seed `cinedub-ser-diagnostic-v1` plus filename. Tied votes are excluded before inference. The summary Git blob is pinned and every recording is verified against its pinned LFS SHA256/size. No demographic files are downloaded. Recordings, mappings, attribution and detailed results remain in a private temporary directory outside the repository; do not commit them. Inference sees anonymous windows and audio only. No training, threshold adjustment or paid API call occurs.

| Measurement | Observed | Meaning |
| --- | --- | --- |
| Supported-label raw argmax agreement | 6/16 (37.5%) | Unscored clips count as incorrect; not calibrated accuracy for cinema |
| Supported-label suggestion coverage | 14/16 (87.5%) | Two clips were withheld |
| Agreement among supported-label suggestions | 6/14 (42.9%) | Most suggested labels did not match crowd votes |
| Four-class macro F1, withholding counted as missed labels | 0.300 | Unsupported classes excluded from this four-class metric |
| Unsupported-label false suggestions | 7/8 (87.5%) | Fearful/disgusted clips usually received an inappropriate four-class suggestion |
| Native time / peak child RSS | 6.030 s / 755.8 MiB | Four threads; excludes downloads, conversion, checksum and parent overhead |

Across all clips: 21 suggestions, two ambiguous results and one no-speech result; 23 classifier calls. Supported classes showed strong angry-label bias: all four happy and three neutral clips were suggested as angry. This tiny, non-speaker-disjoint, acted dataset sample is a diagnostic, not a representative natural-film benchmark, confidence calibration, Malayalam validation or psychological inference. The existing model may also have unknown training overlap with public data. It **fails promotion to automatic performance controls**; leave it optional and review-only. A larger independently scored, speaker-disjoint evaluation and a replacement-model comparison are required before promotion. Do not tune thresholds against these same 24 clips and call it independent acceptance.

The editor now exposes these weak results beside the analysis action, not only in documentation. New immutable reports retain the diagnostic warning and the installed-model capability description carries it. Historical report bytes are unchanged. Listening and explicit human review remain required; corrections are still independent of translation, timing and voice controls. The real-model supervised browser workflow passed warning visibility, evidence download, correction/conflict handling and reload persistence; the 390-pixel screenshot was inspected without horizontal overflow. All 21 focused emotion/benchmark backend tests, strict types, ESLint, Ruff/format and generated-contract checks passed. No representative-film or listening-quality acceptance is implied.

## Replacement candidate diagnostic (2026-10-16)

An isolated diagnostic now evaluates a pinned eight-label INT8 candidate without changing application routing, contracts or installed production weights. [The packaging card](https://huggingface.co/smkrv/speech-emotion-classification-onnx/tree/5e6da6730a4add4cb8f4997b902df89c7d38c4e9) declares Apache-2.0 and attributes the upstream model and ONNX conversion. The graph is `fp32/onnx/model_quantized.onnx`, 95,389,059 bytes, SHA256 `3217e95e4b28d53913fbe94cd9650b520f8e7ecf2bd643b9e45fc5b8b93b8aab`; configuration, preprocessing and attribution files have pinned Git blob checksums. The folder name is not a claim that this graph is FP32.

[The upstream model](https://huggingface.co/prithivMLmods/Speech-Emotion-Classification) points to SSI training data. [SSI includes CREMA-D](https://huggingface.co/datasets/stapesai/ssi-speech-emotion-recognition), so **these clips are not an independent held-out test for this candidate**. Dataset-card licence declarations do not resolve component-dataset restrictions, actor rights or commercial model clearance. No SSI recordings, demographic fields or model-specific remote Python code are downloaded. This candidate is a research diagnostic only, not an application provider or approved commercial replacement.

Reproduce after the original benchmark, supplying its private directory:

```bash
PYTHONPATH=apps/api .venv/bin/python scripts/evaluate-emotion-candidate.py --dataset-directory /tmp/cinedub-crema-d-EXAMPLE
# Later, reuse the verified downloaded files; outputs go to a new private directory:
PYTHONPATH=apps/api .venv/bin/python scripts/evaluate-emotion-candidate.py --dataset-directory /tmp/cinedub-crema-d-EXAMPLE --model-directory /tmp/cinedub-emotion-candidate-EXAMPLE
```

The first invocation explicitly downloads the pinned candidate into private temporary storage. Later invocations can reuse it without downloading weights again. Selection is checked against the pinned crowd-label CSV; original hashes and normalized samples must match the baseline scene windows. The report records baseline manifest/scene hashes. The anonymous child request omits gold labels, transcripts, actor identifiers and filenames. Native execution is offline, sequential CPU, four threads, 10 GiB address-space cap and a 900-second parent deadline. The same installed Silero model and speech thresholds are used. Unlike the current model, the candidate's pinned preprocessor requires per-window mean/variance normalization (`do_normalize=true`, epsilon `1e-7`). Original inputs remain untouched.

| Diagnostic measurement | Current four-label graph | Eight-label INT8 candidate |
| --- | --- | --- |
| Classifier graph size (decimal MB) | 378.5 | 95.4 |
| Suggestions matching crowd labels on the 16 shared-class clips | 6/14 suggestions | 6/14 suggestions |
| Label coverage | Neutral/happy/angry/sad | Adds calm/disgusted/fearful/surprised; calm/surprised not tested here |
| Native time in this one run | 6.030 s | 4.740 s |
| Peak child RSS | 755.8 MiB | 368.0 MiB |
| Promotion decision | Remain optional/review-only | Do not replace the current model: no shared-class improvement, training overlap and unresolved independent acceptance |

The final candidate run produced 13/24 correct raw argmax labels and 11/20 matching suggestions (55%) across the six crowd-labelled classes. Five of its eight fearful/disgusted clips received matching suggestions; these are now supported classes, so the earlier four-class out-of-class metric is not comparable. These counts must not be presented as generalization accuracy. Resource measurements exclude downloads, parent preparation and most provenance checks; VAD/classifier lifetimes also differ, so this is not a controlled speed benchmark.

The first exploratory run did not reproduce the baseline's sub-millisecond zero padding and gave 12/24 raw matches and 11/21 matching suggestions. The final script requires identical padded baseline audio and gave the numbers above. This sensitivity reinforces the need for fixed preprocessing and a larger independent evaluation; no thresholds were tuned. Eighteen focused candidate/baseline diagnostic tests and Ruff/format passed; two actual candidate runs completed. No application/browser behavior changed in this milestone.

Other options screened: [DistilHuBERT SER](https://huggingface.co/adolon-ai/distilhubert-ser) is small but outputs arousal/valence trained from CREMA-D categorical centroids, not interchangeable categorical emotion evidence; [emotion2vec+](https://huggingface.co/emotion2vec/emotion2vec_plus_base) offers broader labels but adopts a custom model licence rather than the software licence. Neither was downloaded or promoted. Independent natural-performance data and reviewed licensing remain prerequisites for a replacement.

## Remaining acceptance gates

The disclosure milestone's production build also passed outside the restricted sandbox. The initial sandbox build could not parse its TypeScript subprocess output; the identical host build succeeded. The preceding broader backend run remains incomplete (124 passed before interruption); the disclosure milestone ran the 21 focused tests and browser workflow, not a new full-suite run.

Use authorized natural performances and independent human labels to measure four-class accuracy, class balance, ambiguity/abstention, speech false positives and errors on unseen delivery. Include out-of-class emotions and background contamination. Keep test material outside Git and document its rights. Do not infer actors' psychological states, evaluate Malayalam with this English profile, or connect hints to automatic synthesis controls before separate quality and consent review.
