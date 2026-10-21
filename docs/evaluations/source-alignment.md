# Source alignment verification

The optional English CTC aligner is connected to durable jobs and the review editor. Verification on 2026-10-15 covers synthetic integration and resource use, not manually annotated film-word accuracy or Malayalam performance preservation.

## Reproduce

Install the optional dependencies/model using the README, then run:

```bash
.venv/bin/pytest -q tests/api/test_alignment.py
CINEDUB_E2E_ALIGNMENT=1 CINEDUB_E2E_TRANSCRIBER=local npm run test:e2e -- tests/e2e/alignment.spec.ts
PYTHONPATH=apps/api .venv/bin/python scripts/evaluate-local-alignment.py --duration-seconds 120
```

The evaluator generates original eSpeak NG speech in 15-second slots, each with one second of leading silence. It retains inputs, output words/curves and measured resource data under ignored `data/evaluation/`. It contains no actor recordings or paid requests.

## Observed model comparison

| Graph | Controlled 120-second scene | Mean first-phrase acoustic score | First-phrase greedy text error ratio | Child peak RSS | Inference time |
| --- | --- | --- | --- | --- | --- |
| Quantized ONNX, 95 MB | 88 suggested words; all 8 phrases flagged | 0.0160 | 0.9661 | 752.7 MiB | 9.974 s |
| Float32 ONNX, 378 MB | 88 suggested words; all 8 phrases flagged | 0.6002 | 0.2969 | 1026.7 MiB | 10.077 s |

Both placed the first word near 1.02 seconds, but timing placement alone does not establish correctness: forced paths can place words that were not spoken. The quantized graph primarily decoded E characters. Float32 recovered recognizable speech but scored short words poorly on this synthetic voice; the hard fixture remains review-only. Host/resource numbers are single runs, not maximum guarantees or a physical 24 GB host certification.

A separate 15-second slot containing “Hello world. This is a simple test.” produced seven suggested words, mean score 0.6722, greedy error ratio 0.1481, 828.0 MiB child peak RSS and 2.244 seconds inference. It exercised the provisional application gate; it does not calibrate that gate. The browser test uses this simpler original phrase for acceptance and a deliberately different script to verify rejection, without weakening thresholds.

## Workflow checks

The complete backend suite passed 78 tests. All eight browser workflows passed across the standard fixture, local ASR/alignment/separation, and fixture-speech retained-background export configurations. An earlier mixed run incorrectly sent tone fixtures through real ASR; the proper separate configurations passed. Ruff, ESLint, generated contracts and strict TypeScript checks passed. These automated checks do not replace listening review.

- Source-word audition uses the existing canonical scene player.
- Explicit timing application persists across reload and works at a 390 px viewport without horizontal overflow.
- Edited/approved timing requires replacement permission and listening confirmation; text stays intact, selected takes are cleared, and normal edit history is retained.
- Audio/report checksum changes, late transcript edits and changed approved stems prevent application/publication of current evidence.
- CTC tests cover repeated letters, blank transitions, unfittable transcripts and unsupported characters.
- Signal tests measure a known 200 Hz tone, RMS/peak levels, silence and low-energy intervals; they assert no emotion output.
- Native child cancellation/deadline and safe local-job restart are tested separately from model accuracy.

## Remaining acceptance

Use authorized/licensed natural English dialogue with independently timed words, including accents, overlap, music and whispers. Measure median/p95 boundary error, omissions, counterfactual rejection and review effort; calibrate score thresholds on separate clips. Evaluate Malayalam candidate alignment with a licensed, provenance-checked model and language reviewer. Compare source and target acoustic delivery without treating pitch/energy as emotion. None of these gates is closed by synthetic browser tests.
