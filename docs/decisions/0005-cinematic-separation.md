# ADR 0005: Bounded cinematic separation with explicit stem review

Status: implemented evaluation baseline, 2026-10-14. Not a cinema-quality acceptance claim.

## Decision and provenance

Use the optional `local-separation` adapter with [audiojs's MRX ONNX conversion](https://huggingface.co/audiojs/mrx), pinned to revision `dedc823a0bea2ed085d19e8b7f32589d35169ee8`. Its 31,287,081-byte model has SHA-256 `d876c92d224f5d8cd2207d528b23369da895a6de71fb24132416fcb16f9f8424`. Stored int8 weights are expanded for float32 computation; this is not an int8-compute performance claim.

The original model is by Darius Petermann, Gordon Wichern, Zhong-Qiu Wang and Jonathan Le Roux (MERL), *The Cocktail Fork Problem: Three-Stem Audio Separation for Real-World Soundtracks*, ICASSP 2022. [Upstream code](https://github.com/merlresearch/cocktail-fork-separation/tree/19b3de827ebc4bfb014570cf92dd32b4ee3b6921) and [checkpoint licensing](https://github.com/merlresearch/cocktail-fork-separation/blob/19b3de827ebc4bfb014570cf92dd32b4ee3b6921/.reuse/dep5) identify MIT. See [retained attribution and license](../licenses/mrx-MIT.txt). Training-data licenses are distinct from weight licensing: the model card notes mixed source-data terms, including non-commercial clips. This is not blanket clearance for media, redistribution or commercial deployment; assess intended use before release.

## Application behavior

- Separate the selected original soundtrack, not recognition audio. Prepare stereo 44.1 kHz float32 PCM, pad/trim to the source timeline, measure loudness and normalize model input toward -27 LUFS, then restore the original gain.
- The local transform implementation follows the graph's three centered Hann STFT inputs (1024/2048/8192, hop 256, normalized by square-root FFT size). Sum reconstructed resolution outputs per stem. Process channels independently, preserving positions, with 16-second cores and two-second context on each side; crossfade overlaps. This is not a learned stereo-spatial model.
- CPU only, four threads, sequential worker, maximum two-minute scene, 900-second deadline and 10 GiB child address-space cap. The cap is not a reservation or total-application RAM figure. Model memory is released when the child exits. Installation is explicit; jobs are offline with no API keys, runtime downloads or remote Python execution.
- Freeze provider/model manifest, settings, source ID/hash and duration. Reject changed sources/models. Checksum weights before inference. After a crash, reuse a completed result only after validating output model/codec/duration/channel/rate; retain durable progress and source lineage. Cancellation stops the inference process group, including children.
- Persist three 48 kHz stereo float32 masters and separately checksummed PCM16 listening copies. Listening/recognition gain is reduced if needed for headroom; masters retain their original scale. Save source loudness, model gain, resource/latency measurements and artifact hashes. No original input or earlier run is overwritten.
- New stem sets always need review. Explicit reviewer identity/notes and optimistic version/active-source checks protect approval. Audit each approve/reject decision; do not change approval while processing is active. Reruns do not replace the selected set automatically.
- Original-audio transcription remains the default. Only an approved selected set can supply dialogue recognition audio; freeze its ID/version and artifact in the transcription request. A new transcript still creates a separate candidate revision.
- Never add reconstruction residual to retained music/effects automatically: it can reintroduce dialogue. Independent stem audition players are explicitly not synchronized scene proxies. Final background mixing is the next milestone, not part of this completion claim.

## Evidence and tradeoffs

See [local separation measurement](../evaluations/local-separation.md). A synthetic clip demonstrates actual CPU execution and isolation improvement, not natural-film fidelity. Effects preservation is an especially weak quality boundary. Human leakage/effects/stereo review and licensed natural-scene evaluation remain required. The provider-neutral seam permits replacing MRX without coupling the editor to another vendor or checkpoint.
