# CineDub

A local English → Malayalam cinema dubbing workspace. The current development branch connects media playback, transcription, translation, human review, stock/consented-voice candidates, timing fit and stereo exports with reviewed music/effects. Optional offline models support English transcription, cinematic separation, English source-word alignment, and experimental Malayalam take-word suggestions. Source/take pitch, energy and pauses can be compared locally. Cloning contracts and consent/reference workflows are connected but not live-verified. Natural Malayalam quality, accurate target-voice alignment and emotion preservation remain unfinished.

`OLD/` remains an ignored reference archive. Nothing in the current application imports or executes it.

## Local setup

Requirements: Linux, Python 3.12+, Node.js 22+, npm, uv, and FFmpeg/ffprobe. Local AI models and a GPU are not required for v0.2.

```bash
cp .env.example .env
uv sync --group dev
npm ci
npm run doctor
npm run dev
```

Copy the environment example only on first setup. Keep an existing `.env` and its credentials. `doctor` checks local prerequisites and ports without creating or upgrading a database, loading models or calling providers. Missing Sarvam credentials produce a warning; editing and media ingest can still run. The UI opens at <http://127.0.0.1:3000>, with API documentation at <http://127.0.0.1:8000/docs>. Wait for **CineDub local workspace ready**, keep the terminal open and use Ctrl+C to stop the web, API, worker and their owned media/model children. Stopping cannot undo or refund an already submitted paid request.

If port 3000 belongs to another application:

```bash
PORT=3001 npm run dev
```

Open <http://127.0.0.1:3001>. Use the same `PORT=3001` prefix with `npm run doctor`. The launcher derives the allowed browser origin from this port; set `CINEDUB_API_PORT` for a different API port. Conflicting shell URL/origin overrides are refused, not silently redirected. Both services bind to loopback. Run only one editor dev server per checkout and one worker per workspace; if a service fails, the supervisor stops its remaining services. Never kill another application's port owner or delete a lock file to bypass a refusal. See [launcher behavior and limits](docs/decisions/0015-local-runtime-supervision.md). This launcher supports Linux/SQLite, not a desktop installer or production service manager.

SQLite, local filesystem artifacts and a separate database-backed worker are the development defaults. Before upgrading a previous schema, application startup creates a consistent sibling database-only `.bak` backup. Migration 0002 preserves existing dialogue and approvals in a legacy/demo revision; 0003 adds candidates; 0004 adds scoped clone consent and explicit speaker voice selection; 0005 adds reviewed source-bound stems; 0006 adds mix renders and listening acceptance history; 0007 adds immutable dialogue briefs; 0008 adds separate emotion reviews; 0009 preserves retired originals during structural timeline edits. Stock choices survive upgrade; legacy generic clone approvals require new scoped consent. Dropping history through a downgrade is intentionally unsupported.

For complete recovery, use the [offline database and media snapshot procedure](docs/recovery.md), not a database-only migration backup. Recovery creates a separate verified workspace, holds active jobs for explicit review and quarantines historical clone approvals; it never overwrites the source or automatically replays paid work. Run `npm run test:recovery` for the synthetic backup and real HTTP recovery rehearsal.

Recognized SQLite/storage-quota errors now give an actionable 507 response or stop the worker with a sanitized capacity diagnostic. Keep/copy unsaved editor fields, restore space or resolve the quota, then restart and inspect job/provider history before retrying paid work. Do not delete database/media/journal/lock files to bypass the failure. [Capacity recovery and test limits](docs/recovery.md#when-storage-capacity-is-exhausted).

For an isolated base-install smoke check, run `npm run verify:clean-install` from a trusted checkout. It installs locked dependencies into a private temporary snapshot, without your `.env`, data or optional models, then checks build/startup and a browser upload-to-subtitle workflow. It requires installed Chrome and may use network/package caches and about 1 GiB temporary space; it keeps private results/logs for inspection and requires at least 2 GiB free space. [Scope, results and remaining machine checks](docs/evaluations/clean-install.md).

## Workflow pipeline, review gates and operations (v0.3 development)

**Dubbing workflow.** In the editor, **Run dubbing workflow** creates a pipeline. It runs every stage in order and stops at each human review step:

1. ingest
2. separation (optional) → approve stems
3. transcription → speakers
4. translation → editorial checks and alternatives (optional) → approve every line
5. assign voices → voice takes → select takes
6. timing and performance analysis (optional)
7. mix → accept the mix and export bundle

**Continue after review** opens a step only when the saved review satisfies it. Nothing is approved automatically. Paid steps stop before exceeding the workflow budget you confirm.

With every provider set to `fake` the whole run uses DEMO fixtures (see [Costs and routing](#costs-and-routing)). The equivalent API calls are:

- `POST /projects/{id}/pipelines/plan` previews the steps.
- `POST /projects/{id}/pipelines` starts a run.
- `POST /pipelines/{id}/continue` opens the next gate and can raise `confirmed_budget_inr`.
- `POST /pipelines/{id}/cancel` stops the run.

**Timeline.** The editor shows a time-based timeline: the source waveform, dialogue lines, selected takes (with red warnings for overruns) and approved stems.

The editing workspace keeps the source monitor in the centre, dialogue review on
the right and the labelled timeline below. Use **Media**, **Workflow**, **Voices**,
**Analysis**, **Export** and **Project** on the left to open the tools you need.
Switching tools keeps unsaved forms intact. **Export** in the header opens the
mix/subtitle controls; rendering and acceptance still require explicit actions.
On smaller screens the panels stack. See [workspace decisions](docs/decisions/0021-editor-workspace.md).

- Zoom with the toolbar or Ctrl+wheel.
- Click to seek.
- Drag a line edge, or focus it and use the arrow keys (Shift for 100 ms).
- Drag the body of a dialogue clip to move its complete timing window. Duration is
  preserved and movement stops at neighbouring lines. Arrow keys also move a
  focused clip; Shift uses 100 ms steps.
- **Split / merge** opens the existing structural editor for the selected line.
  Partition its text and confirm the change before applying it.
- Import with the file picker or drop one video/audio file into **Media**.
- Close the tools or dialogue panel with its **×**, restore it from the header,
  and use **Hide timeline** / **Show timeline** to change the workspace layout.
- Drag the dividers beside the tools/inspector or above the timeline to resize
  them. Focus a divider and use arrow keys (Shift for larger steps), Home/End for
  limits, or Enter/double-click to reset. Sizes are remembered in this browser;
  narrower windows keep the monitor usable, and phones use a stacked layout.

Timeline edits only change the line's unsaved draft. Save, conflict detection, grouped save and undo stay in the line editor. **Needs attention** lists unapproved, untranslated, speakerless, mistimed, warned and DEMO items, with a jump to each line.

**Live updates.** The editor subscribes to `GET /projects/{id}/events`, server-sent typed `ProjectEvent`s for `job`, `pipeline`, `project`, `timeline` and `artifact`. It falls back to 5-second polling while the stream is unavailable.

**Traceability.**

- Every response carries an `X-Request-ID`. Pass your own to follow a request into its job, provider runs and artifacts. Logs are one JSON object per line.
- `GET /artifacts/{id}/lineage` shows which files, source media, jobs and provider runs produced an artifact. Accepted export bundles include `lineage.json`.
- Job failures carry stable `error_code`s (for example `stale_input`, `budget_exceeded`, `deadline_exceeded`, `uncertain_submission`). The editor shows the next action for each.

**Safe retries.** Job submission, uploads, pipeline creation and mix review accept an `Idempotency-Key` header. A retry with the same key and body returns the first response instead of repeating work; the same key with a different body is refused.

**Deleting and cleaning up.**

- `DELETE /projects/{id}?confirm=<exact project name>` removes a project's rows and files. It is refused while work is active, or while a cloned voice may still exist at a provider: revoke consent and run provider deletion first.
- `GET /diagnostics/storage` reports usage.
- `PYTHONPATH=apps/api .venv/bin/python scripts/storage-cleanup.py` lists leftovers: unreferenced old uploads, orphaned project directories, and expired cancelled or non-resumable failed job directories. Add `--apply` to remove them, with the API and worker stopped. Completed and resumable work, backups and lock files are never touched.

**Startup checks.** The API and worker validate configuration at startup. Invalid settings, disallowed DEMO providers, or a missing Sarvam key in `CINEDUB_ENV=production` stop the service. Development warnings appear in the log and in `/health`.

## Portable source snapshot (not a published release)

From a trusted Git checkout, package a reviewed commit into a **new** directory:

```bash
python3 scripts/package-source.py --ref HEAD --output /tmp/cinedub-source-handoff
cd /tmp/cinedub-source-handoff
sha256sum --check SHA256SUMS
```

The bundle contains committed source, installation instructions and example configuration, plus a separate manifest binding the commit, version, dependency locks and archive checksum. It refuses tracked `OLD/`, private configuration, models, runtime data, dependency folders and unsafe archive entries. Ignored and uncommitted files are never copied. Existing output directories are never overwritten. Only package trusted, reviewed commits: path checks are not a general secret scanner. Checksums detect accidental changes, not authenticity; there is no signature or release approval.

Extract into a new empty workspace, then follow **Local setup** above and configure your own `.env`; no dependencies, system tools, models or user projects are bundled. Optional models still require explicit setup. Creating a bundle makes no network/provider calls and does not publish a GitHub release. The archive has no Git history: packaging and committed-snapshot rehearsal commands require the original Git checkout. This source handoff is not a desktop installer, supported-device certification or cinematic-quality acceptance.

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

For a selected Sarvam stock voice, **Generation variation (not emotion)** provides a manual 0.01–1 control (default 0.6). Save/Discard is explicit. Higher values can add variation or artifacts; this is not a “happy/sad” control or automatic emotion preservation. Saving clears selected takes for that speaker but keeps text approvals and makes no synthesis request. Failed saves and same-profile refresh retain the draft; newer saved settings block stale drafts. Save or copy it before changing voice/leaving the editor. New synthesis jobs freeze the value; unfinished legacy stock jobs without it require usage inspection and a fresh request, not silent retries. [Contract and compatibility limits](docs/decisions/0002-revision-bound-jobs.md#manual-stock-generation-variation).

Each transcription creates a revision. The first becomes active automatically; later ones are candidates selected through **Use this timeline**. Previous revisions and edits remain saved. Translation reruns preserve human-edited/approved lines; **Regenerate translation** explicitly requests another draft for one saved line. Late results do not overwrite newer edits, and unused translation candidates remain downloadable.

Candidate generation preserves text approvals. Changes to dialogue, speaker, timing or voice settings invalidate selected takes; old audio remains available as history. Short takes are padded with silence. Long takes may be sped up by at most 15% by default; unsafe takes are rejected rather than clipped. Silence padding is not a replacement for natural performance adaptation or lip sync.

Sarvam provides phrase timings. The optional local aligner below can suggest English source-word timings independently of the transcriber. Acoustic emotion inference and performance-preserving voice generation remain unfinished.

## Dialogue brief and local editorial checks

Before generating voices, open **Dialogue brief & editorial checks**. Save scene/adaptation notes, character intent and preferred Malayalam names or terms, then **Check saved dialogue** and inspect the result. These local checks show missing translations, preferred-text omissions, surrounding dialogue and saved time windows without replacing text or changing approvals. Refresh preserves drafts; a newer saved brief requires an explicit reload. Historical reports become stale when their context changes. Plain translation does not receive this brief; the optional model stage below uses it separately. No speech-duration estimate or emotion/quality score is invented. [Context and adapter boundary](docs/decisions/0009-dialogue-briefs.md).

## Optional local dialogue alternatives

```bash
uv sync --all-extras --group dev
PYTHONPATH=apps/api .venv/bin/python scripts/setup-local-dialogue.py
```

Restart the API/worker, save your dialogue brief and open **Model dialogue alternatives**. Choose one line initially, then **Generate dialogue alternatives** and inspect the faithful/concise drafts. Generation never changes saved text. Check the Malayalam against the English before explicitly applying; replacing reviewed work or accepting flagged terminology needs separate confirmations. Application preserves timing, clears old selected voice audio and requires approval again.

To use an existing take's measured duration, choose that line and explicitly select **Measured timing feedback** before generation. This measures raw audio before stretching/padding and shows its duration, slot and safe speed-up limit in the report. Overlong takes are supported; stale text/voice/consent or changed audio is refused. Older fitted takes without a raw checksum must be regenerated explicitly. After applying a new draft, approve and synthesize it again, then measure/listen: the model does not predict or certify the new text's duration. Demo-tone measurements remain labelled and are not spoken-Malayalam evidence.

The pinned Linux x86_64 CPU profile uses a roughly 2.5 GB Qwen3 4B quantization, four threads, a 4096-token context and a 10 GiB process address-space cap. The original two-example smoke run took about 46 seconds with 4542 MiB peak native memory; this is not whole-application or cinematic-quality acceptance. Sarvam/plain translation routing stays unchanged. There is no API charge for this stage, and no runtime model download, GPU or PyTorch requirement. Keep installed optional extras on later dependency syncs. [Setup/provenance and safeguards](docs/decisions/0010-local-dialogue-adaptation.md) · [Measured examples and remaining review](docs/evaluations/local-dialogue-adaptation.md).

## Optional offline English transcription

Install only this one model initially; GPU libraries and PyTorch are not needed:

```bash
uv sync --extra local-asr --group dev
PYTHONPATH=apps/api .venv/bin/python scripts/setup-local-asr.py
```

Set `CINEDUB_TRANSCRIBER=local` in `.env`, then restart `npm run dev`. Keep the local-asr extra on later `uv sync` commands. The explicitly downloaded, pinned MIT-licensed [faster-whisper-small.en model](https://huggingface.co/Systran/faster-whisper-small.en) occupies about 464 MiB under ignored `models/`. Inference never downloads weights or executes remote Python code.

The laptop profile uses CPU int8, four threads, one scene/job at a time, a ten-minute deadline and a 10 GiB child-process address-space limit. The model process exits after each job so its memory is released. On this laptop, a 14.8-second original synthetic scene took about 4.5 seconds with 624 MiB peak process memory. This single fixture is not a cinema-accuracy benchmark. An 8 GB NVIDIA GPU was detected but was not used or inference-tested.

Local ASR recognizes English and stores estimated word timings in the raw transcript. It does **not** identify speakers or perform forced alignment. Use **Add speaker**, assign each line and save. Empty translations can still be filled after speaker correction; existing human-written translations are protected. Sarvam diarization remains an alternative selected through routing, with no silent fallback or paid calls.

New local transcription jobs freeze the `english-asr-v1` decoding profile, runtime versions, runner hash and model checksums. Raw transcript evidence records each decoded segment's selected temperature and diagnostics; sampling fallback produces a review warning, not a deterministic-quality claim. Changed settings/runtime/runner inputs create a different cache identity. Old queued local jobs without a profile must be submitted afresh; existing historical raw results remain readable with an explicit missing-profile warning. Restart API/worker after upgrading, and use a fresh transcription request rather than repeatedly retrying a legacy job. [Profile and compatibility details](docs/decisions/0003-bounded-offline-asr.md).

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

Unrendered settings and unsaved mix-review notes survive project refresh and warn before leaving or explicitly switching timelines. Each timeline opens with its latest render settings or defaults. Failed operations keep the draft; a completed render or successful review clears the relevant warning. The two **Discard mix… draft** buttons reset only unsaved controls/notes, not saved renders or acceptance history. Drafts stay in the open page only, not browser storage, and are not crash recovery.

If another tab changes the active timeline while you have mix or emotion-review drafts, refresh keeps the old scene and fields visible and pauses its editing actions. Copy any needed values, then explicitly confirm **Discard review drafts and load current timeline**. A failed refresh does not discard anything. This only loads the server's current timeline; it does not reactivate the old one or alter saved renders/reviews. Other timeline-specific forms are discarded on confirmation; displaced dialogue drafts remain available to copy.

Audio preparation now preserves audio-track offsets relative to the container timeline. If an older scene has an offset track, prepare/separate it again and review a fresh transcript; zero-offset scenes are unaffected.

The actual separator-to-export browser workflow uses generated video/audio and no paid APIs:

```bash
CINEDUB_E2E_SEPARATOR=1 npm run test:e2e -- tests/e2e/mix-workflow.spec.ts
```

It needs the optional separator and eSpeak NG; speech/translation remain labelled fixtures. [Verification and natural-scene acceptance](docs/evaluations/retained-background-mix.md) distinguish these integration checks from human quality review.

## Consented voice references and cloning

Open **Voice references & consent** in the editor. Stock-voice users can leave this panel closed. Never infer actor cloning rights from possession of a film.

Unsaved reference/consent fields survive project refresh and timeline switching. The Projects link and supported browser reload/close actions warn before losing them. Use **Discard reference draft** to explicitly reset the form; this never revokes saved consent or deletes a provider copy. Drafts stay in the open page only, not browser storage, and cannot survive a crash. Save the reference to make it durable.

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

Every stage has a deterministic DEMO provider, so the complete workflow (separation → transcription → translation → adaptation → voices → takes → alignment/take/emotion analysis → mix → accepted export) runs without models, keys or network:

```bash
CINEDUB_TRANSCRIBER=fake CINEDUB_TRANSLATOR=fake CINEDUB_VOICE_SYNTHESIZER=fake \
CINEDUB_STEM_SEPARATOR=fake CINEDUB_TIMING_ALIGNER=fake CINEDUB_TARGET_TIMING_ALIGNER=fake \
CINEDUB_PERFORMANCE_ANALYZER=fake CINEDUB_DIALOGUE_ADAPTER=fake CINEDUB_EMOTION_ANALYZER=fake npm run dev
```

DEMO stems copy the original mix as "dialogue" and use synthetic tones for music/effects. DEMO alignment spreads placeholder word slots evenly. DEMO adaptation trims words by rule. DEMO emotion reports every window as `not_analyzed` with no scores. Every DEMO job, artifact and provider run is labelled `fake`/`demo`, and the UI shows a **DEMO** badge. These outputs never count as quality evidence. DEMO providers are refused when `CINEDUB_ENV=production` unless `CINEDUB_ALLOW_DEMO_PROVIDERS=true`.

Set `CINEDUB_TRANSCRIBER=fake`, `CINEDUB_TRANSLATOR=fake` and `CINEDUB_VOICE_SYNTHESIZER=fake` for entirely no-key demo development. Without any `.env`, these are also the code defaults. Sarvam diarization runs with its batch transcriber. The UI and exports label fixture-derived results as demo. Fake transcription never recognizes the supplied audio. **Build demo timeline** creates the original four-line fixture; fake synthesis produces test tones, not speech.

The application owns timeline and job contracts. Frontend contracts are generated from the API's Pydantic schemas; run `npm run contracts:generate` after schema changes. `npm test` checks that generated contracts match. Provider-specific request/response details stay in adapters. A configured key means an adapter is available, not that its live output or quality has been verified.

## Verification

```bash
npm test
npm run build:web
npm run test:e2e
```

`npm test` runs Python lint/tests, shared/web TypeScript checks, ESLint and the web unit tests (`npm run test:web`: timeline geometry and the review/error mapping). Browser tests use an isolated temporary database, synthetic media and fake providers on ports 3011/8011. They never call paid APIs or modify your projects. Install Google Chrome for the default browser, or install Playwright Chromium with `npx playwright install chromium` and run `CINEDUB_E2E_BROWSER=chromium npm run test:e2e`.

GitHub Actions runs **Backend and production build** and **Base-install editor workflows** on pull requests and pushes to `main`/the foundation release branch. The first job installs locked development/alignment packages (for NumPy unit coverage, not model weights), checks formatting/contracts/types/lint, builds production web output and runs the full backend suite. The second installs only base/development dependencies, verifies optional AI packages are absent, then runs the selected Chromium media/editor/voice/consent/brief/history/structure/draft workflows plus the DEMO end-to-end, timeline and pipeline workflows through the supervised launcher. Each job has its own fresh Ubuntu runner, pinned Python/Node/uv versions and action commit SHAs, read-only repository permissions and no retained checkout credentials. Older checks for the same PR are cancelled. Locks/generated contracts must stay unchanged, and no `models/` directory may be created.

See the PR's actual check results for hosted evidence; a configured workflow is not a passing run. These jobs use fake paid providers, synthetic fixtures and no repository secrets, and never install model weights or deploy. They do not establish real-model quality, live Sarvam behavior, device accessibility or a complete laptop installer. Private-repository runs may consume GitHub Actions allowances/billed minutes; no billing or branch-protection settings are changed. Manual dispatch becomes available after the workflow exists on the default branch. Workflow inputs follow [GitHub's permission guidance](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions) and [Playwright's Chromium setup](https://playwright.dev/docs/browsers#chromium-new-headless-mode).

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

## Reuse characters after transcription reruns

Open **Reuse earlier character**, choose a current speaker and an earlier same-project character, and preview the change. Audition both before confirming. Provider speaker numbers are not stable identity labels. You may opt in to copying a selected stock voice/pace into a separate current-speaker profile; cloned voices, consent and scene briefs never transfer automatically. Applying retains dialogue text/timing but clears affected approvals and selected takes for review. Source revisions and voice choices remain historical. Save or discard drafts first. [Reuse rules and audit history](docs/decisions/0016-reviewed-speaker-reuse.md).

Migration 0010 adds reuse audit history without rewriting existing choices; startup from schema 0009 creates a database-only `v02-structure` backup. Complete database/media recovery still requires the [workspace snapshot procedure](docs/recovery.md).

## Saved edits and keyboard navigation

After editing two or more dialogue lines, use **Save all dialogue drafts together** beside the timeline filters. Confirm the count: this includes filtered-out lines, but not brief, emotion, mix or consent forms. Up to 100 dialogue drafts save in one transaction. A stale version, invalid timing/speaker, removed line or changed active timeline prevents the whole request from saving. Changed dialogue/timing clears selected takes and requires review again; it does not bulk-approve content.

Failed requests keep all open-page drafts. If the connection failed after submission, **Refresh project** to inspect saved versions before retrying; do not assume the server did nothing. Removed-line drafts must be copied/discarded first. Successful saves retain per-line history with a shared group identifier. Focus returns to the timeline heading when the save control disappears, unless you deliberately moved elsewhere.

Open **Grouped edit history** below the dialogue list to inspect the latest 20 saved groups and undo/redo their content-changing members together. Review before/after text, speaker and timing, then acknowledge cleared selected takes and renewed review requirements. All material members must have the group as their next eligible undo/redo item; later edits, independent partial restoration, replaced lines or a changed active timeline block the operation. Approval/status-only members are shown as excluded and are never reversed here. Save/discard all other drafts first. Restoration appends history rather than deleting it and survives reload; old approvals, consent and selected audio are never reinstated.

Open a dialogue line's **Saved edit history** to inspect its recent before/after records and undo or redo saved text, speaker or timing changes. Acknowledged restoration requires approval again and clears selected voice audio; it never restores old consent, voices or emotion settings. Save or explicitly discard drafts before restoring. History survives reload and detects conflicts with other tabs or provider changes. See [history rules and remaining editor scope](docs/decisions/0012-saved-line-history.md).

Use the first keyboard link, **Skip to dialogue editor**, to bypass setup panels. Alt+↑/↓ moves between visible lines; **Previous line** and **Next line** do the same. Ctrl/⌘+Enter saves the focused line and restores editing focus after saving unless you moved elsewhere. Failed saves preserve the draft. Composition events do not trigger editor shortcuts, and native select/media handling stays intact. A polite saved-status message distinguishes pending review from an approved line. Native text undo stays available inside text boxes; saved undo/redo uses the history buttons. Physical IMEs and screen-reader usability still need device testing.

The **Split, merge & structural history** panel below the timeline can divide a saved line at a manually chosen time or combine adjacent lines assigned to the same speaker. Enter the intended text explicitly and confirm replacement. Originals and artifacts stay historical; changed lines require review and new take selection. Structural history offers guarded reversal, including reversal of a reversal, while refusing to overwrite later edits. Unsaved forms survive refresh/conflicts. See [structural editing and migration rules](docs/decisions/0013-timeline-structure.md).

If another tab removes a line you are editing, its unsaved dialogue stays visible as a preserved draft. Download or copy it before explicitly discarding it; it will not be applied automatically to replacement lines.

## Optional speech emotion hints

Install the `local-emotion` extra alongside your existing extras, then run `PYTHONPATH=apps/api .venv/bin/python scripts/setup-local-emotion.py`. Restart the API and worker to refresh availability. The editor's **Speech-emotion hints** panel runs an offline English audio classifier with a speech-presence guard. Its four classes are experimental, uncalibrated hints; explicit human reviews are saved separately and never change translations, timing, voice settings or approvals. About 381 MB of graphs are downloaded only during setup. See [setup, measurements and limitations](docs/evaluations/speech-emotion.md).

Unsaved emotion-review fields are tracked per report and line. Project refresh and inspecting the same report retain them; leaving the scene, switching timeline or inspecting a different report requires confirmation. Failed saves retain the fields, and a successful save clears only that line's form, including its listening checkbox. A newer saved review blocks the older draft rather than silently adopting the newer version. Copy any needed notes before **Discard emotion review draft**; discard never changes saved review history. Drafts stay only in the open page and are not crash recovery.

## Following milestones

- Live stock-voice listening, Malayalam expert review and timing-quality evaluation.
- Live consented-cloning acceptance and natural-scene separation/mix listening.
- Accurate Malayalam candidate alignment, acoustic emotion evaluation and performance preservation.
- Broader reliability, editing polish and human quality evaluation before a v1.0 completion claim.

Local models run one at a time and release memory between jobs. The optional models currently use CPU; GPU use requires separate driver, inference and VRAM checks. The target remains a 24 GB RAM laptop. No fine-tuning or full-film processing is included in v0.2.

The full implementation/acceptance scope is tracked in the [completion ledger](docs/roadmap.md).
