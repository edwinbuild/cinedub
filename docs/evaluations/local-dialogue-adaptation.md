# Local dialogue adaptation verification

The optional local model generates reviewable Malayalam alternatives from saved context. The initial CPU smoke check on 2026-10-15 used original written examples, not actor recordings or a language-expert test set. Context-sensitive output is demonstrated; cinematic translation quality remains unaccepted.

## Reproduce

```bash
uv sync --all-extras --group dev
PYTHONPATH=apps/api .venv/bin/python scripts/setup-local-dialogue.py
PYTHONPATH=apps/api .venv/bin/python scripts/evaluate-local-dialogue.py
CINEDUB_E2E_ADAPTATION=1 npm run test:e2e -- tests/e2e/dialogue-adaptation.spec.ts
```

The optional extras install Python adapters, not model weights. Setup explicitly downloads and verifies the roughly 2.5 GB GGUF and 18 MB CPU-runtime archive. Inference is offline and has no API charge; electricity and hardware costs are not estimated. Outputs, prompts, native logs and resource evidence stay under ignored local evaluation/test storage. Normal project data and Sarvam credentials are not used by these checks.

## Context contrast

Both requests use the same English source, “Meet me by the bank.”, with a 2200 ms target window. Only the scene sense and preferred term differ.

| Scene sense | Faithful draft returned | Concise draft returned |
| --- | --- | --- |
| River shore | നമുക്കു നദിക്കരിൽ കാണാമോ? | നദിക്കരിൽ കാണാമോ? |
| Financial institution | നമുക്ക് ബാങ്കിൽ കാണാമോ? | ബാങ്കിൽ കാണാമോ? |

The initial run reported 332 and 329 prompt tokens, 22.829 and 22.615 seconds generation time, 46.249 seconds total runner time, and 4541.7 MiB peak native-process RSS on CPU/four threads. These figures exclude browser/API memory and are not maximum-scene latency or whole-laptop resource acceptance. The exact model/runtime profile is in [ADR 0010](../decisions/0010-local-dialogue-adaptation.md).

Both faithful candidates end in question marks although the English is an imperative. An editor must judge whether that change preserves the scene's intent. Generated notes asserting correctness are not independent evidence. Preferred-form checks may flag valid inflections; no term is automatically replaced. Character count and the word “concise” do not establish spoken timing.

## Workflow verification

Final checks passed 127 backend tests, generated contracts, strict TypeScript, Ruff/format, ESLint and the production build. Six browser workflows passed for this milestone, including actual CPU model inference and four existing media/editor/voice workflows. The model and editorial-brief cases were rechecked after removing native imports that could initialize app settings. A fresh-process test verifies that the model runner does not initialize database/configuration state; cancellation/deadline tests stop a native grandchild and verify that credentials are absent from its environment. No live Sarvam call or human-quality approval occurred.

The real-model browser test supplies an original river-context line, preserves its saved human draft during generation, inspects the two alternatives and native resource metadata, requires language/replacement/warning confirmations, applies one draft, retains timing, requires approval again and reopens the saved result. A 390 px view checks overflow. Checkbox automation proves the workflow, not actual human language review.

Recorded-adapter tests cover input/model/request/prompt provenance, read-only generation, multiple line applications, stale context, version conflicts, selected-take invalidation, malformed output, wrong-script guards, checkpointed restart/explicit retry, report integrity and historical access after prompt changes. The standard suite never downloads weights or makes paid requests. Native cancellation uses the shared process-group/deadline boundary.

## Remaining quality gate

Use licensed natural scenes and independent Malayalam-speaking reviewers. Score meaning and intent, omissions/additions, names/numbers, glossary handling, idiom/register, character consistency and correction effort. Include whispers, interruptions, humor, code-switching and longer context. Compare against the plain translated baseline; an alternative that reduces fidelity is not an improvement. Synthesize approved candidates and measure/listen to their timing rather than estimating it from text. Evaluate other local sizes/quantizations or a verified context-capable Sarvam adapter if this small model is insufficient. Emotion inference and performance-preserving voice generation remain separate unfinished work.
