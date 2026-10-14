# ADR 0006 Reviewed stereo exports

Status: implemented, 2026-10-15. The `stereo-review-v1` profile produces verifiable short-scene review deliverables. It is not theatrical, HDR or surround mastering.

## Reviewed inputs and timing

A mix uses the active timeline, every approved translated line, an explicitly selected timing-ready take for each line, and the active approved stem set for that timeline's source. Snapshot segment versions, candidate IDs/checksums, voice/consent versions, stem review version, source hash and mix settings when scheduling. Partial or incomplete mixes are rejected. Source dialogue is never mapped into the output, but estimated music/effects can still contain dialogue leakage and require listening review.

Audio extraction and separation share a container-relative timeline. Delayed audio tracks receive leading silence; early tracks are trimmed relative to the container origin. Canonical audio is padded/trimmed to the source duration. Older offset stems must be regenerated before mixing. Existing zero-offset stems remain usable. Dialogue is placed at integer 48 kHz sample positions; preparation preserves the timeline's millisecond boundaries.

Render float32 dialogue groups with bounded input counts, then sum them with music/effects. Apply explicit dialogue/music/effects gains and optional background mutes. Do not add the original dialogue stem or separation residual. Recheck file hashes and current approvals/takes after processing; changed inputs fail instead of publishing a current-looking stale render. Earlier renders remain historical records, with stale state shown in the editor.

## Loudness and media profile

Default output is 48 kHz stereo at -23 LUFS and maximum -2 dBTP. These are application review defaults, not a claim of theatrical compliance. Target loudness is adjustable from -30 to -14 LUFS and peak from -6 to -2 dBTP. The [FFmpeg loudnorm contract](https://ffmpeg.org/ffmpeg-filters.html#loudnorm) supplies two-pass measurements. Request linear normalization with LRA 50 to preserve dynamics when feasible. If peak constraints require dynamic processing, fail unless the editor explicitly enabled it; record and warn about the applied mode.

| Deliverable | Contract and checks |
| --- | --- |
| WAV master | PCM24, 48 kHz stereo, exactly source milliseconds × 48 samples, loudness within 1 LU, true peak within target + 0.2 dB, full audio decode |
| Listening WAV | PCM16, same duration/rate/channels and level checks; separate checksum |
| Review MP4 | Original-resolution SDR picture, H.264/AAC 256 kb/s stereo. Copy compatible H.264 picture packets; otherwise encode CRF 18 without downscaling, padding odd dimensions if necessary. Never use the low-resolution browser proxy as final picture input. |
| MP4 validation | Exactly one picture and one audio stream, expected dimensions, audio duration within 50 ms, container within 100 ms, picture start within one source-frame interval (100 ms fallback for unknown rate), full picture/audio decode. AAC true-peak tolerance is target + 1 dB; measure the encoded file. |
| Malayalam SRT | Saved text and timings from the same immutable render snapshot |
| Render manifest | File hashes/sizes, source and input hashes, candidate voice/model/consent provenance, stem model/review version, settings, renderer/FFmpeg versions, normalization and media-check results |

HDR input fails this profile rather than silently receiving an SDR conversion. A failed loudness/codec/duration check produces no published render record. FFmpeg work has deadlines, cancellation that terminates its process group, bounded threads and local-only input protocols. Provider keys are omitted from FFmpeg's environment.

## Listening acceptance and export bundle

Every technically valid render starts as `needs_review`. Approval requires a named reviewer, explicit listening/timing confirmation and a current input snapshot. Use optimistic version checks and append review history. Technical checks do not automatically grant listening acceptance.

Approval queues a durable local packaging job. The worker rechecks inputs and rendered-file hashes, writes a separate acceptance certificate bound to the render-manifest hash, and creates a verified ZIP containing master, listening copy, optional video, SRT, manifest and certificate. Packaging does not block the API process. Restart recovery reuses committed artifacts instead of duplicating certificates/bundles. An unsuccessful packaging job leaves the accepted event in history but produces no accepted download; correct the problem and explicitly review again.

Rejection and later edits do not erase historical files or certificates. The editor labels superseded acceptance as historical. Voice-consent revocation is stronger: it cancels dependent queued/running work and quarantines dependent audio, video, manifests, certificates and bundles, including HEAD/range downloads. Previously downloaded copies cannot be recalled.

## Evidence and remaining work

[Mix verification](../evaluations/retained-background-mix.md) covers actual FFmpeg rendering, original-resolution picture preservation, known-stem measurements, delayed audio, failure paths, consent and the browser export workflow. Synthetic audio and simulated checkbox approval do not establish Malayalam naturalness, actor identity, separation fidelity or human synchronization acceptance. Forced alignment, measured performance/emotion preservation and licensed natural-scene evaluation remain in the completion ledger.
