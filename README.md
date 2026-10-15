# CineDub

A local English → Malayalam cinema dubbing workspace. The current development branch connects media playback, transcription, translation, human review, stock/consented-voice candidates, timing fit and stereo exports with reviewed music/effects. Optional offline models support English transcription, cinematic separation, English source-word alignment, and experimental Malayalam take-word suggestions. Source/take pitch, energy and pauses can be compared locally. Cloning contracts and consent/reference workflows are connected but not live-verified. Natural Malayalam quality, accurate target-voice alignment and emotion preservation remain unfinished.

`OLD/` remains an ignored reference archive. Nothing in the current application imports or executes it.

## Local setup

Requirements: Linux, Python 3.12+, Node.js 22+, npm, uv, and FFmpeg/ffprobe. Local AI models and a GPU are not required for v0.2.

```bash
cp .env.example .env
uv sync --group dev
npm ci
npm run dev
```

Copy the environment example only on first setup. Keep an existing `.env` and its credentials. The UI opens at <http://127.0.0.1:3000>, with API documentation at <http://127.0.0.1:8000/docs>. Keep the terminal open and use Ctrl+C to stop the web, API and worker.

If port 3000 belongs to another application:

```bash
PORT=3001 npm run dev
```

Open <http://127.0.0.1:3001>. The launcher derives the allowed browser origin from this port and passes an explicit port to Next.js rather than silently moving to a different origin. Run only one API and worker against a local workspace. The worker holds an exclusive SQLite-database lock (or a storage-directory lock for other databases).

SQLite, local filesystem artifacts and a separate database-backed worker are the development defaults. Before upgrading a previous schema, application startup creates a consistent sibling `.v01-*.bak`, `.v02-*.bak`, `.v02-voices-*.bak`, `.v02-consent-*.bak`, `.v02-stems-*.bak` or `.v02-mixes-*.bak` backup. Migration 0002 preserves existing dialogue and approvals in a legacy/demo revision; 0003 adds candidates; 0004 adds scoped clone consent and explicit speaker voice selection; 0005 adds reviewed source-bound stems; 0006 adds mix renders and listening acceptance history; 0007 adds immutable dialogue briefs. Stock choices survive upgrade; legacy generic clone approvals require new scoped consent. To return to an older schema, stop all processes and restore its backup; dropping history through a downgrade is intentionally unsupported.

## Use real Sarvam processing

Set `SARVAM_API_KEY` privately in root `.env`. The example selects Sarvam for transcription/diarization, translation and stock-voice synthesis: `saaras:v4`, colloquial `mayura:v1`, and `bulbul:v3`. Restart the API and worker after changing configuration. Keys never enter the web configuration. Live Sarvam verification is pending; a configured adapter is not a quality guarantee.

1. Create a project and import an English video/audio scene up to two minutes.
2. Wait for audio, actual waveform data and an optional video proxy to finish preparing.
3. Play or seek the scene, select its source, optionally specify the speaker count, then select **Transcribe scene**.
4. Review the timestamped speaker lines and select **Translate dialogue**.
5. Correct English or Malayalam, speaker assignment and timing. Save changes, then approve the corrected line separately.
6. Export Malayalam subtitles from the saved active revision. Missing translations require explicit confirmation and fall back to English.
7. Assign a stock voice to each speaker, approve all translated lines, then generate candidates. Play and explicitly select a timing-ready take for each line.
8. Render and download a dialogue-only WAV or video MP4 preview. This intentionally excludes original dialogue, music and effects; it is not the final cinematic mix.

Sarvam processing happens in the worker. Batch job IDs and checkpoints persist; polling uses a deadline and can resume an existing remote job after a timeout. Creating a remote job or making a translation request with an uncertain result is never blindly resubmitted after a crash. Cancellation cannot guarantee cancellation or a refund for an already-submitted remote operation.

Each transcription creates a revision. The first becomes active automatically; later ones are candidates selected through **Use this timeline**. Previous revisions and edits remain saved. Translation reruns preserve human-edited/approved lines; **Regenerate translation** explicitly requests another draft for one saved line. Late results do not overwrite newer edits, and unused translation candidates remain downloadable.

Candidate generation preserves text approvals. Changes to dialogue, speaker, timing or voice settings invalidate selected takes; old audio remains available as history. Short takes are padded with silence. Long takes may be sped up by at most 15% by default; unsafe takes are rejected rather than clipped. Silence padding is not a replacement for natural performance adaptation or lip sync.

Sarvam provides phrase timings. The optional local aligner below can suggest English source-word timings independently of the transcriber. Acoustic emotion inference and performance-preserving voice generation remain unfinished.

## Dialogue brief and local editorial checks

Before generating voices, open **Dialogue brief & editorial checks**. Save scene/adaptation notes, character intent and preferred Malayalam names or terms, then **Check saved dialogue** and inspect the result. These local checks show missing translations, preferred-text omissions, surrounding dialogue and saved time windows without replacing text or changing approvals. Refresh preserves drafts; a newer saved brief requires an explicit reload. Historical reports become stale when their context changes. Current translation models do not receive this brief, and no speech-duration estimate or emotion/quality score is invented. [Context and adapter boundary](docs/decisions/0009-dialogue-briefs.md).

## Optional offline English transcription

Install only this one model initially; GPU libraries and PyTorch are not needed:

```bash
uv sync --extra local-asr --group dev
PYTHONPATH=apps/api .venv/bin/python scripts/setup-local-asr.py
```

Set `CINEDUB_TRANSCRIBER=local` in `.env`, then restart `npm run dev`. Keep the local-asr extra on later `uv sync` commands. The explicitly downloaded, pinned MIT-licensed [faster-whisper-small.en model](https://huggingface.co/Systran/faster-whisper-small.en) occupies about 464 MiB under ignored `models/`. Inference never downloads weights or executes remote Python code.

The laptop profile uses CPU int8, four threads, one scene/job at a time, a ten-minute deadline and a 10 GiB child-process address-space limit. The model process exits after each job so its memory is released. On this laptop, a 14.8-second original synthetic scene took about 4.5 seconds with 624 MiB peak process memory. This single fixture is not a cinema-accuracy benchmark. An 8 GB NVIDIA GPU was detected but was not used or inference-tested.

Local ASR recognizes English and stores estimated word timings in the raw transcript. It does **not** identify speakers or perform forced alignment. Use **Add speaker**, assign each line and save. Empty translations can still be filled after speaker correction; existing human-written translations are protected. Sarvam diarization remains an alternative selected through routing, with no silent fallback or paid calls.

## Optional local dialogue/music/effects separation

Install only if needed; keep installed extras on subsequent syncs:

```bash
uv sync --extra local-asr --extra local-separation --group dev
PYTHONPATH=apps/api .venv/bin/python scripts/setup-local-separation.py
```

The optional MRX model is about 30 MiB on disk, with offline CPU inference and no PyTorch/GPU requirement. Four threads, disposable model process, 10 GiB address-space limit and a 15-minute deadline bound this two-minute-scene profile. A controlled 18.644-second synthetic clip used about 1.45 GiB peak model-process RAM and 9.2 seconds inference time; not an accuracy or maximum-resource guarantee. It is a cinematic three-stem separator, not a music-vocal remover. See [model/license decision](docs/decisions/0005-cinematic-separation.md) and [measured limitations](docs/evaluations/local-separation.md).

Restart the app, import a scene and choose **Separate dialogue & background**. Listen to dialogue, music and effects; enter reviewer/notes and approve or reject. Originals and earlier runs remain unchanged. New runs never replace the approved set automatically. To transcribe cleaned dialogue, explicitly choose **Reviewed dialogue stem** in **Transcription audio**. Original audio remains the default. Approval also enables retained music/effects mixing below. Independent stem listening players are not synchronized scene proxies.

To verify actual local separation followed by local recognition, install eSpeak NG and both models, then run:

```bash
CINEDUB_E2E_SEPARATOR=1 CINEDUB_E2E_TRANSCRIBER=local npm run test:e2e -- tests/e2e/separation.spec.ts
```

This uses isolated temporary projects and original synthetic media, not paid APIs or actor recordings. The default suite skips this optional inference test.

## Optional source alignment and acoustic measurements

Install the English source aligner if needed, preserving any other extras you use:

```bash
uv sync --extra local-asr --extra local-separation --extra local-alignment --group dev
PYTHONPATH=apps/api .venv/bin/python scripts/setup-local-alignment.py
```

The pinned ONNX float32 graph occupies about 361 MiB, runs on CPU with four threads, and requires no PyTorch or GPU. A disposable process enforces a 10 GiB address-space ceiling and a ten-minute deadline. Each phrase uses at most 20 seconds of audio including context; split longer phrases before alignment. On a two-minute synthetic clip, inference took 10.1 seconds and about 1.0 GiB peak child-process RAM. This is a throughput check, not a natural-scene accuracy score. The smaller quantized conversion failed the speech smoke check and is not the supported model. See [model choice and contracts](docs/decisions/0007-source-alignment.md) and [evaluation](docs/evaluations/source-alignment.md).

Restart the app, activate a source-bound transcript and save corrections. **Transcription audio** also selects the analysis input: original audio by default, or an explicitly approved dialogue stem. Open **Source timing & performance**, select **Align source words**, then inspect the saved report. Click a word to audition its suggested range in the scene player. RMS level, estimated pitch, text pace and low-energy pauses describe the analysis signal; they are not emotion, speaker identity or validated speech detection. Detailed curves and provenance are in the evidence JSON.

Listening confirmation is required to apply a suggestion. Applying changes only that line's start/end, preserves its text, clears its selected voice take, and requires approval again. Previously reviewed timing needs explicit replacement confirmation. Weak acoustic/text agreement, unsupported symbols and long phrases stay visible without automatic application. Numbers must be written as spoken English words. Edits, active-revision changes or rejected/replaced dialogue stems invalidate affected suggestions; old reports remain as history. Accurate Malayalam word timing and emotion/performance matching remain open.

Real-model browser verification and a reproducible two-minute resource check use original synthetic speech, not paid APIs:

```bash
CINEDUB_E2E_ALIGNMENT=1 CINEDUB_E2E_TRANSCRIBER=local npm run test:e2e -- tests/e2e/alignment.spec.ts
PYTHONPATH=apps/api .venv/bin/python scripts/evaluate-local-alignment.py --duration-seconds 120
```

Both need eSpeak NG and the installed aligner; the browser test also needs local ASR. The browser check covers explicit application, reload/mobile review, and refusing a script that was not spoken. A harder synthetic phrase remains flagged for manual review. Threshold calibration and manually timed natural speech are still required before accuracy claims.

## Compare source and voice takes

Open **Source versus voice** after generating a timing-ready take. Choose one take to inspect before selection, or analyze the selected takes. The analysis uses **Transcription audio** as its source input and never changes dialogue, timing, approval, voice settings or take selection.

The local `analyze_takes` job measures pitch/energy curves, text pace, energy-active span, internal low-energy pauses and approximate fitting padding. Leading/trailing low-energy regions are excluded from internal-pause totals so padding is not mistaken for an acting pause. Different actors, languages, background audio and input gain can explain the differences; there is no automatic emotion, identity or naturalness score. Measurements require the optional local-alignment dependencies but no model weights or API key.

For experimental Malayalam word suggestions, install the additional pinned ONNX graph and restart:

```bash
PYTHONPATH=apps/api .venv/bin/python scripts/setup-target-alignment.py
```

The approximately 340 MiB graph uses CPU, four threads, a disposable 10 GiB address-space-limited process and a 15-minute deadline. A 4.84-second original synthetic utterance used 661 MiB peak child memory and 1.83 seconds for model load/inference/alignment. Its word agreement was weak: this is a smoke test, not an accuracy pass. **Include experimental Malayalam word suggestions** starts unchecked. Suggestions cover takes up to 20 seconds, stay inside their saved scene envelope, and can be auditioned; they cannot automatically change the performance. Demo tones never get invented spoken-word timings. See [decision](docs/decisions/0008-take-performance-review.md) and [evaluation](docs/evaluations/take-performance.md).

Inspect saved comparison reports or download their JSON. Selecting the analyzed take does not invalidate unchanged measurements. Changed dialogue/timing/voice, revised stems or changed media are marked stale. Revoked clone consent quarantines comparison JSON and cancels dependent queued work just as it does for the voice audio.

The real-model browser check uses clearly labelled original synthetic speech in a new isolated test database; it never enrolls a real voice or modifies the user's workspace:

```bash
test_state=$(mktemp -d /tmp/cinedub-e2e-XXXXXX)
CINEDUB_E2E_PERFORMANCE=1 CINEDUB_E2E_STATE_ROOT="$test_state" npm run test:e2e -- tests/e2e/performance.spec.ts
```

It requires eSpeak NG, the optional dependencies and the installed Malayalam graph. The ordinary suite skips it. The test-only seeder refuses workspace databases and symlinked database/storage paths. Natural speech, manually checked word timings and Malayalam-expert listening remain required for quality acceptance.

## Mix reviewed dialogue with music and effects

Open **Mix & export** in the scene editor after approving the source stems, approving every translated line and explicitly selecting a timing-ready take for each line. Select the active timeline's source before reviewing. Adjust dialogue/music/effects gains or mute a background stem, then **Render retained-background mix**. The renderer never maps original dialogue into the output, but separated background may retain speech leakage: listen before accepting.

Defaults are 48 kHz stereo, -23 LUFS and maximum -2 dBTP. Linear normalization preserves dynamics when feasible; dynamics processing needs explicit opt-in. Targets and actual measurements are recorded in the report. Failed level, checksum, duration, codec or current-edit checks publish no valid render.

Download a PCM24 WAV master, PCM16 listening copy, matching Malayalam SRT, render manifest and (for video input) original-resolution SDR H.264/AAC MP4. Compatible H.264 picture is copied rather than downscaled to the browser proxy. This profile does not perform HDR conversion, surround or theatrical mastering. See [profile and tolerances](docs/decisions/0006-reviewed-stereo-exports.md).

Listen against picture, enter reviewer/notes and confirm review, then **Approve mix and export bundle**. A worker job verifies the files and creates a ZIP plus an acceptance certificate. New edits or stem/voice changes make older renders historical; rejection does not erase them. Clone consent revocation blocks dependent media, manifests and bundles. Demo takes remain labelled demo tones even after simulated approval.

Audio preparation now preserves audio-track offsets relative to the container timeline. If an older scene has an offset track, prepare/separate it again and review a fresh transcript; zero-offset scenes are unaffected.

The actual separator-to-export browser workflow uses generated video/audio and no paid APIs:

```bash
CINEDUB_E2E_SEPARATOR=1 npm run test:e2e -- tests/e2e/mix-workflow.spec.ts
```

It needs the optional separator and eSpeak NG; speech/translation remain labelled fixtures. [Verification and natural-scene acceptance](docs/evaluations/retained-background-mix.md) distinguish these integration checks from human quality review.

## Consented voice references and cloning

Open **Voice references & consent** in the editor. Stock-voice users can leave this panel closed. Never infer actor cloning rights from possession of a film.

1. Import an authorized clean recording if the scene itself does not contain a suitable single-speaker reference. Choose a 10–15 second range, the target speaker, rights holder, attester and consent evidence note. All permission/review checkboxes start unchecked.
2. Save the profile, then **Prepare reference**. This remains local and creates a checksum-tracked 24 kHz mono WAV. Silent/too-quiet clips are rejected; level/clipping warnings require review. Known overlaps with another assigned speaker are rejected. These checks do not independently verify speaker identity, background cleanliness or legal rights.
3. Listen to the prepared clip and explicitly confirm review. **Upload and register with Sarvam** stores a saved voice with the provider; saving consent alone never uploads it. The key and beta/account entitlement must be configured. Set a registration allowance in INR because the exact enrollment tariff/account limits are not live-verified. This is a project-budget estimate, not a provider charge cap.
4. Select **Use this clone** explicitly, approve translated lines and generate/select candidates as with stock voices. Clone requests use the 1000-character endpoint limit and request QC, but human listening is still required. Cloning fidelity, pronunciation, pacing and emotion preservation are unverified until real evaluation.
5. **Revoke consent** blocks further use and quarantines the reference, generated candidates and dependent rendered mixes, including downloads. Queued work is cancelled; already-dispatched requests and downloaded copies cannot be recalled. It does not erase original uploads or local audit history. Unrelated stock takes remain usable.
6. After revocation, **Delete provider copy** is a separate destructive action requiring confirmation. CineDub retains the remote identifier/audit tombstone. If enrollment timed out without an identifier, inspect the provider dashboard manually before retrying or cleanup; automatic duplicate registration is prohibited.

The demo provider exercises the same review/consent flow with synthetic tones and no external voice storage. It never clones a real voice. See [consent architecture and limitations](docs/decisions/0004-scoped-voice-consent.md) and Sarvam's [saved voice](https://docs.sarvam.ai/api-reference/voice-cloning/create-voice) and [cloned speech](https://docs.sarvam.ai/api-reference/voice-cloning/clone) contracts.

## Costs and routing

The editor shows an INR estimate before paid operations and defaults to a ₹50 estimated budget per project. Change that project's budget in the editor; `CINEDUB_PROJECT_BUDGET_INR` sets the initial budget for new projects. Sarvam transcription reserves one pass; translation and synthesis reserve up to three attempts. Submitted attempts consume the estimate even when their billing outcome is unknown. Unused reservations are released when the job finishes. Local transcription has no API charge (electricity/hardware costs are not estimated).

Rates are configurable snapshots stored with each job. Defaults checked on 2026-10-14: transcription with diarization ₹45/hour, translation ₹20/10,000 characters, and Bulbul v3 synthesis ₹30/10,000 characters. Estimates are not the provider invoice and exclude applicable taxes. [Sarvam pricing](https://docs.sarvam.ai/api/getting-started/pricing)

Set `CINEDUB_TRANSCRIBER=fake`, `CINEDUB_TRANSLATOR=fake` and `CINEDUB_VOICE_SYNTHESIZER=fake` for entirely no-key demo development. Without any `.env`, these are also the code defaults. Sarvam diarization runs with its batch transcriber. The UI and exports label fixture-derived results as demo. Fake transcription never recognizes the supplied audio. **Build demo timeline** creates the original four-line fixture; fake synthesis produces test tones, not speech.

The application owns timeline and job contracts. Frontend contracts are generated from the API's Pydantic schemas; run `npm run contracts:generate` after schema changes. `npm test` checks that generated contracts match. Provider-specific request/response details stay in adapters. A configured key means an adapter is available, not that its live output or quality has been verified.

## Verification

```bash
npm test
npm run build:web
npm run test:e2e
```

`npm test` runs Python lint/tests, shared/web TypeScript checks and ESLint. Browser tests use an isolated temporary database, synthetic media and fake providers on ports 3011/8011. They never call paid APIs or modify your projects. Install Google Chrome for the default browser, or install Playwright Chromium with `npx playwright install chromium` and run `CINEDUB_E2E_BROWSER=chromium npm run test:e2e`.

For an original spoken evaluation scene, install `espeak-ng` and run:

```bash
python3 scripts/make-evaluation-scene.py
```

Import the generated `data/evaluation/synthetic-scene.mp4` into the real Sarvam workflow. Synthetic speech validates integration, not actor voice fidelity or cinema quality. A licensed natural scene and a Malayalam-speaking reviewer are still required for release evaluation. See [v0.2 acceptance record](docs/evaluations/v0.2-acceptance.md).

After installing the optional local model and eSpeak NG, run its real offline browser workflow separately:

```bash
CINEDUB_E2E_TRANSCRIBER=local npm run test:e2e -- tests/e2e/local-asr.spec.ts
```

This uses temporary projects, no Sarvam key and no model download. The ordinary browser suite skips this opt-in test.

## Following milestones

- Live stock-voice listening, Malayalam expert review and timing-quality evaluation.
- Live consented-cloning acceptance and natural-scene separation/mix listening.
- Accurate Malayalam candidate alignment, acoustic emotion evaluation and performance preservation.
- Broader reliability, editing polish and human quality evaluation before a v1.0 completion claim.

Local models run one at a time and release memory between jobs. The optional models currently use CPU; GPU use requires separate driver, inference and VRAM checks. The target remains a 24 GB RAM laptop. No fine-tuning or full-film processing is included in v0.2.

The full implementation/acceptance scope is tracked in the [completion ledger](docs/roadmap.md).
