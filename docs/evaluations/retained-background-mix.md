# Retained background mix verification

The 2026-10-15 implementation connects reviewed music/effects and selected dubbed takes to stereo review deliverables and a separately accepted export bundle. Test media is original procedural audio, eSpeak speech and generated video. No actor recording or paid API call is used.

## Verified media and failure behavior

| Check | Evidence |
| --- | --- |
| Music and effects retained | Known 330/550 Hz stereo music and gated 880 Hz effects survive final PCM rendering |
| Original audio replaced | A continuous 440 Hz source tone is absent from the exported audio; selected takes and known background remain |
| Gain and mute controls | A -6 dB music adjustment changes its ratio to dialogue by the expected factor; muted effects disappear |
| Duration and levels | PCM sample counts match the source timeline exactly; measured loudness/true peak meet recorded tolerances |
| Dynamics permission | A deliberately peaky fixture requires explicit opt-in before dynamic normalization; default processing refuses it |
| Track offset | An audio track starting 500 ms after picture retains its leading silence after extraction |
| Picture and encoded audio | 1440 × 810 source picture is retained rather than replaced with its 1280px proxy; compatible H.264 packet hashes are unchanged. Encoded AAC is decoded and measured. |
| Late edits and file changes | Editing during normalization publishes no stale render. Changed source/background/take/output checksums fail verification or packaging. |
| Listening acceptance | Missing confirmation/stale review versions are rejected. Acceptance is saved separately from technical validation. |
| Export integrity and recovery | ZIP CRC and per-file SHA-256 match the certificate, which references the render manifest. Recovery reuses committed packaging artifacts. |
| Consent | Revocation blocks every dependent export/certificate/bundle on GET/range/HEAD and cancels a queued render |
| Upgrade | Migration 0006 preserves selected stems and review history; the application creates a consistent pre-upgrade backup |

## Browser workflow

Install the optional separator and eSpeak NG, then run:

```bash
CINEDUB_E2E_SEPARATOR=1 npm run test:e2e -- tests/e2e/mix-workflow.spec.ts
```

The browser/API/worker use isolated temporary state. MRX actually separates a generated soundtrack; transcription, translation and synthesized dialogue remain visibly labelled fixtures/demo tones. The test reviews stems, selects takes, adjusts music level, renders full-resolution video, saves simulated listening acceptance, downloads the ZIP and reopens the project. Playback is decoded and advances in the browser; mobile width is checked at 390px. Simulated checkbox review is not a human listening score.

Use `npm test` for backend, contract, type and lint checks. The optional browser workflows need installed model weights; ordinary tests never download them or call Sarvam. [The stereo profile](../decisions/0006-reviewed-stereo-exports.md) defines exact media tolerances.

## Required natural scene acceptance

Use an authorized one- or two-speaker scene with natural Malayalam dubbing. A Malayalam-speaking reviewer must check meaning, pronunciation, pacing and vocal identity, then listen for dialogue leakage, missing ambience/transients, levels and stereo changes. Compare claps/onsets and dialogue boundaries against picture throughout the scene, not just at its start. Record human corrections and acceptance separately from automatic media checks. HDR/surround/theatrical mastering and performance-preserving alignment remain separate capabilities.
