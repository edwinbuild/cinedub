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

## Workflow verification (original v1 milestone)

Final checks passed 127 backend tests, generated contracts, strict TypeScript, Ruff/format, ESLint and the production build. Six browser workflows passed for this milestone, including actual CPU model inference and four existing media/editor/voice workflows. The model and editorial-brief cases were rechecked after removing native imports that could initialize app settings. A fresh-process test verifies that the model runner does not initialize database/configuration state; cancellation/deadline tests stop a native grandchild and verify that credentials are absent from its environment. No live Sarvam call or human-quality approval occurred.

The real-model browser test supplies an original river-context line, preserves its saved human draft during generation, inspects the two alternatives and native resource metadata, requires language/replacement/warning confirmations, applies one draft, retains timing, requires approval again and reopens the saved result. A 390 px view checks overflow. Checkbox automation proves the workflow, not actual human language review.

Recorded-adapter tests cover input/model/request/prompt provenance, read-only generation, multiple line applications, stale context, version conflicts, selected-take invalidation, malformed output, wrong-script guards, checkpointed restart/explicit retry, report integrity and historical access after prompt changes. The standard suite never downloads weights or makes paid requests. Native cancellation uses the shared process-group/deadline boundary.

## Measured take-feedback execution

The `cinema-dialogue-v2` browser rehearsal explicitly synthesizes a fake-provider tone for a saved Malayalam draft, chooses that take as feedback, and runs the installed CPU text model. The raw take has 54,400 PCM frames at 48 kHz (1133 ms rounded) for a 3400 ms slot, a 0.333333 raw-duration ratio, and a 1.15 safe speed-up ceiling. The frozen report labels it `demo=true`; it is not spoken-Malayalam evidence. The adapter receives seven timing/demo fields while full IDs, voice parameters and checksums stay in audited job/report provenance.

The final compact-prompt run used 655 prompt tokens, 157.408 seconds line latency, 157.829 seconds native runner time and 3056.9 MiB peak child RSS with four threads. The initial verbose trial sent irrelevant hashes/IDs, used 1048 prompt tokens and 225.059 seconds runner time; it completed successfully after the browser's earlier 120-second wait expired and delayed the shared worker's next test. The browser wait was corrected to accommodate measured CPU latency, and the final six-workflow run passed. This is not a controlled speed benchmark, maximum-scene latency or whole-laptop RAM guarantee; the original v1 context-only smoke figures above remain historical.

The two returned alternatives in this one demo trial were identical (`നദിക്കരിൽ എന്നോടൊപ്പം വരാം.`). That establishes neither meaningful compression nor faithful imperative intent, naturalness or timing improvement. The browser checks explicit selection, immutable evidence, unmodified text during generation, language/replacement/warning gates, application, mobile width and reopened history. Unit/API cases separately cover an actual overlong raw tone, legacy raw checksums, stale/foreign/duplicate takes, changed selected voices, byte changes before/during/after generation, report tampering and clone-revocation quarantine/cancellation. No new weights or paid API calls were needed.

Final v2 verification passed all 213 backend tests (30 focused adaptation tests), six supervised browser workflows, generated contracts, strict types, Ruff/format, ESLint and the production web build. The full backend run was sequential after browser shutdown, avoiding shared Next.js dev-server state. Mobile layout screenshot inspected. No normal-workspace migration or live-provider/language/listening acceptance is claimed.

## Remaining quality gate

Use licensed natural scenes and independent Malayalam-speaking reviewers. Score meaning and intent, omissions/additions, names/numbers, glossary handling, idiom/register, character consistency and correction effort. Include whispers, interruptions, humor, code-switching and longer context. Compare against the plain translated baseline; an alternative that reduces fidelity is not an improvement. Synthesize approved candidates and measure/listen to their timing rather than estimating it from text. Evaluate other local sizes/quantizations or a verified context-capable Sarvam adapter if this small model is insufficient. Emotion inference and performance-preserving voice generation remain separate unfinished work.
