# Take performance verification

Source/take measurements and experimental Malayalam word suggestions are connected to durable jobs and the editor. Evidence on 2026-10-15 covers contracts, measured signals, consent protections and original synthetic speech. It does not establish natural Malayalam alignment accuracy, actor fidelity or emotion preservation.

## Reproduce

```bash
.venv/bin/pytest -q tests/api/test_take_analysis.py
PYTHONPATH=apps/api .venv/bin/python scripts/setup-target-alignment.py
PYTHONPATH=apps/api .venv/bin/python scripts/evaluate-malayalam-alignment.py
test_state=$(mktemp -d /tmp/cinedub-e2e-XXXXXX)
CINEDUB_E2E_PERFORMANCE=1 CINEDUB_E2E_STATE_ROOT="$test_state" npm run test:e2e -- tests/e2e/performance.spec.ts
```

The direct probe generates original eSpeak NG Malayalam and preserves its audio, text, word suggestions and resource metadata under ignored `data/evaluation/`. The browser test uses a new guarded temporary database, actual English/Malayalam synthetic recordings and a labelled test-only candidate. It exercises real NumPy/ONNX execution rather than a mocked recognition response. The seed script is not an application route and cannot target the normal workspace database. No actor cloning or paid API call occurs.

## Malayalam smoke check

The 4.840-second sentence “നമസ്കാരം. ഇത് ഒരു ചെറിയ പരീക്ഷണം ആണ്.” produced six suggested words. The model reported 1.833 seconds load/inference/alignment time and 661.0 MiB peak process RSS on CPU/four threads. Mean word acoustic score was 0.1184 and greedy character-error ratio 0.5667; provisional agreement checks failed. Word placement alone does not prove that the text was recognized correctly. These results justify experimental review-only status, not promotion to a quality-approved aligner.

## Checked behavior

The complete backend suite passed 93 tests, including 15 take-analysis cases. All nine distinct browser workflows passed across the appropriate fixture/local-model configurations. Strict TypeScript, generated contracts, Ruff and ESLint passed; the production npm audit reported zero vulnerabilities. These checks validate execution and safeguards, not natural-performance quality.

- Explicit candidate choice can analyze an unselected take without changing the timeline or selected audio.
- Choosing the analyzed take later preserves measurements when text, timing, speaker and voice are unchanged.
- A known 200-to-400 Hz tone comparison yields approximately a 12-semitone pitch shift; trailing silence is counted as padding, not an internal pause.
- Original synthetic speech runs through the real Malayalam graph, yields review-only words, and supports word audition, signal plots, 390 px layout and reload.
- Demo tones receive signal measurements but never invented spoken-word timings.
- Foreign/duplicate/stale candidates, late human edits and changed audio/report bytes are rejected or explicitly marked historical.
- Revoking scoped clone consent quarantines typed/downloaded/ranged/HEAD JSON access and cancels dependent queued analysis.
- Cancellation/deadlines stop the native child, exclude credentials and retain durable failure state. Restart after committed evidence reuses the report without duplicate provider runs.
- Existing stage fingerprints exclude the new review-only options so a deployment does not invalidate prior paid-operation caches.

A sandbox worker-thread hand-off stalled during testing. A minimal AnyIO probe reproduced it inside the sandbox and completed outside; the endpoint tests passed on the normal host. This is an environment boundary, not a reason to block the production event loop with media hashing.

## Remaining acceptance

Evaluate a licensed natural Malayalam set with independent word boundaries, pronunciation/language review, accents, code-switching, noise, whispers and overlap. Compare full-precision or alternative models if quantized accuracy is insufficient. Calibrate agreement thresholds on separate clips, measure omissions/boundary error and editor correction effort, and evaluate cross-language performance preservation through listening. Natural-film separation/mixing and live Sarvam remain separate open gates. No synthetic test closes them.
