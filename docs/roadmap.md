# CineDub completion ledger

Current branch: v0.2 development, not a released or complete cinema-dubbing product. This ledger preserves the agreed scope; green fixture tests do not close live or human-quality gates.

## Target and boundaries

Local single-user browser workspace, initially English → Malayalam scenes up to two minutes, designed for a 24 GB RAM laptop. Provider-neutral per-stage routing; Sarvam plus resource-bounded local models, with future providers replaceable through adapters. Stock voices first, then consented cloning. Timing-fit review is in scope; full facial lip-sync generation is not the initial release target. `OLD/` remains ignored and read-only. The user authorized milestone commits, a small number of branches and corresponding PRs on 2026-10-14. This does not authorize merging shared branches or deploying.

## Work and required evidence

| Area | Current evidence | Work/gate still required |
| --- | --- | --- |
| Durable foundation | SQLite migrations/backups, worker lock, revision-bound jobs, checkpoints, budget reservation and edit-conflict tests | Broader failure injection, recovery/backup restoration drills and packaging checks |
| Real timeline/editor | Actual proxy playback/waveform, source/speaker/timing/text corrections, draft preservation, revision switching and SRT browser tests | Undo/redo, keyboard/accessibility audit, long-session performance and more granular correction tools |
| Recognition/diarization | Sarvam Batch SDK recorded-contract tests; real CPU int8 local English model and manual speaker assignment | Live Sarvam diarization, licensed natural-scene ASR evaluation and speaker-to-character continuity across reruns |
| Translation/adaptation | Mayura/Sarvam adapter, colloquial default, revision-safe drafts and preserved human edits | Live Malayalam review, glossary/names, scene/character context and duration-aware adaptation |
| Stock voice/timing candidates | Catalog, per-speaker selection, explicit takes, safe stretch/padding and dialogue-only MP4/WAV tests | Live Malayalam listening/pronunciation, measured timing and natural-performance acceptance |
| Consented clones | Scoped consent, reference PCM preparation, saved-voice contract, explicit selection, revocation/quarantine and provider-cleanup jobs | Live account entitlement/enrollment/billing/deletion verification and authorized natural-reference fidelity evaluation |
| Dialogue/background separation | Optional pinned MRX CPU runner, three source-bound float32 stems, listening copies, versioned approval and dialogue-stem transcription; synthetic two-minute run measured at 44.5 s inference and 1.81 GiB child RSS | Licensed natural-scene leakage/effects/stereo listening and broader host/content resource acceptance |
| Alignment/performance | Conservative duration fit; local ASR estimates word timings in raw evidence | Forced alignment, energy/pitch/tempo/pauses, reviewable delivery and properly evaluated emotion inference (not sentiment masquerading as speech emotion) |
| Final mix/export | Reviewed music/effects plus selected takes, gain/mute controls, measured stereo normalization, PCM24/MP4/SRT, checksummed manifest and separate accepted ZIP/certificate; delayed audio and full-resolution picture tests | Natural-scene sync/leakage/listening acceptance, professional HDR/surround/theatrical mastering profiles where required |
| Release quality | 66 backend tests; standard and opt-in browser workflows include actual separation-to-reviewed-export, plus lint/types/contracts/build gates | Licensed natural scenes, Malayalam-speaking reviewer, human listening, broader runtime/packaging acceptance |

## Next execution order

1. Local dialogue/background separation is connected and measured on synthetic material, with one model loaded at a time. Natural-scene effects/leakage/stereo listening remains open; three output WAVs alone are not acceptance.
2. Reviewed stereo mixing/export is connected with verifiable technical checks and acceptance history. Natural-scene listening and broader delivery profiles remain open.
3. Next implementation: add forced alignment and measured acoustic performance features, then evaluate emotion/performance preservation without invented labels. Improve contextual translation/adaptation and editor corrections as the actual media exposes weaknesses.
4. Complete reliability/editing/packaging and human-quality gates. Do not widen to full films or training large models before the short-scene path is demonstrably good.

## Deferred external gates

The user will configure `SARVAM_API_KEY` later. Continue independent local implementation; do not make paid calls or claim service verification without it. Natural actor recordings require authorization and a reviewer; synthetic fixtures cannot prove cinematic quality. The goal remains active until the full agreed workflow and its acceptance evidence exist.
