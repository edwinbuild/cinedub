# CineDub completion ledger

Current branch: v0.2 development, not a released or complete cinema-dubbing product. This ledger preserves the agreed scope; green fixture tests do not close live or human-quality gates.

## Target and boundaries

Local single-user browser workspace, initially English → Malayalam scenes up to two minutes, designed for a 24 GB RAM laptop. Provider-neutral per-stage routing; Sarvam plus resource-bounded local models, with future providers replaceable through adapters. Stock voices first, then consented cloning. Timing-fit review is in scope; full facial lip-sync generation is not the initial release target. `OLD/` remains ignored and read-only. The user authorized milestone commits, a small number of branches and corresponding PRs on 2026-10-14. This does not authorize merging shared branches or deploying.

## Work and required evidence

| Area | Current evidence | Work/gate still required |
| --- | --- | --- |
| Durable foundation | SQLite migrations/backups, worker lock, revision-bound jobs, generative line checkpoints/restart/explicit retry, budget reservation and edit-conflict tests | Broader failure injection, recovery/backup restoration drills and packaging checks |
| Real timeline/editor | Actual proxy playback/waveform, source/speaker/timing/text corrections, draft preservation, revision switching and SRT browser tests | Undo/redo, keyboard/accessibility audit, long-session performance and more granular correction tools |
| Recognition/diarization | Sarvam Batch SDK recorded-contract tests; real CPU int8 local English model and manual speaker assignment | Live Sarvam diarization, licensed natural-scene ASR evaluation and speaker-to-character continuity across reruns |
| Translation/adaptation | Mayura/Sarvam translation unchanged; immutable briefs/local checks; optional pinned 4B CPU context model produces faithful/concise drafts with explicit, version-safe application and provenance | Natural Malayalam meaning/register/character evaluation, comparison against plain translation, and synthesized timing-feedback adaptation. Supplying a time window is not measured speech-duration fit |
| Stock voice/timing candidates | Catalog, per-speaker selection, explicit takes, safe stretch/padding and dialogue-only MP4/WAV tests | Live Malayalam listening/pronunciation, measured timing and natural-performance acceptance |
| Consented clones | Scoped consent, reference PCM preparation, saved-voice contract, explicit selection, revocation/quarantine and provider-cleanup jobs | Live account entitlement/enrollment/billing/deletion verification and authorized natural-reference fidelity evaluation |
| Dialogue/background separation | Optional pinned MRX CPU runner, three source-bound float32 stems, listening copies, versioned approval and dialogue-stem transcription; synthetic two-minute run measured at 44.5 s inference and 1.81 GiB child RSS | Licensed natural-scene leakage/effects/stereo listening and broader host/content resource acceptance |
| Alignment/performance | English CTC source alignment and explicit timing application; readonly source/take signal comparison with consent/staleness checks; optional experimental Malayalam word suggestions (synthetic agreement weak, review-only) | Natural-word timing/threshold calibration, accurate Malayalam alignment, natural-performance preservation and properly evaluated emotion inference (not sentiment masquerading as speech emotion) |
| Final mix/export | Reviewed music/effects plus selected takes, gain/mute controls, measured stereo normalization, PCM24/MP4/SRT, checksummed manifest and separate accepted ZIP/certificate; delayed audio and full-resolution picture tests | Natural-scene sync/leakage/listening acceptance, professional HDR/surround/theatrical mastering profiles where required |
| Release quality | 127 backend tests, six editor/brief/model browser workflows and contracts/types/lint/build passed; real-model/brief paths rechecked after native-settings isolation. Prior installed-model browser evidence covers separation/export, source alignment and source/take Malayalam-model review | Licensed natural scenes, Malayalam-speaking reviewer, human listening, broader runtime/packaging acceptance |

## Next execution order

1. Local dialogue/background separation is connected and measured on synthetic material, with one model loaded at a time. Natural-scene effects/leakage/stereo listening remains open; three output WAVs alone are not acceptance.
2. Reviewed stereo mixing/export is connected with verifiable technical checks and acceptance history. Natural-scene listening and broader delivery profiles remain open.
3. English alignment, source/take acoustic comparison, experimental Malayalam suggestions, saved briefs and optional model dialogue alternatives are connected. Next implement genuinely evaluated speech-emotion inference and more granular editor tools, while evaluating natural-word timing and contextual adaptation. Compare alternatives with the plain translated baseline and measured synthesized timing; keep human language/listening review. Do not promote weak alignment, signal deltas or context-sensitive text output to natural-performance acceptance.
4. Complete reliability/editing/packaging and human-quality gates. Do not widen to full films or training large models before the short-scene path is demonstrably good.

## Deferred external gates

The user will configure `SARVAM_API_KEY` later. Continue independent local implementation; do not make paid calls or claim service verification without it. Natural actor recordings require authorization and a reviewer; synthetic fixtures cannot prove cinematic quality. The goal remains active until the full agreed workflow and its acceptance evidence exist.
