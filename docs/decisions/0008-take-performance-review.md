# Source and take performance review

Status: local signal comparison and experimental Malayalam word suggestions are connected. Natural-performance preservation and emotion inference remain unverified.

## Review before changing performance

`analyze_takes` is a durable, zero-API-charge job routed through `TakePerformanceAnalyzer`. It can compare selected takes or explicitly named unselected candidates from the active source-bound revision. A comparison never changes text, timing, voice settings, approval or selection. The editor provides a table, source/take pitch and RMS curves, listening controls and downloadable evidence rather than a single opaque quality score.

Freeze candidate IDs/checksums, the material signature, profile versions, source/recognition hashes, approved-stem selection, texts and time envelopes. Validate them before and after native work. A changed source, take, dialogue, timing, voice or consent prevents current publication. Report inspection rechecks media hashes in a worker thread, not in the web event loop. Selection-only version changes remain valid when the underlying text/time/voice signature is unchanged. Report downloads retain historical evidence but are quarantined after clone-consent revocation. Persist voice/candidate lineage in existing artifact/job tables; no new database schema is needed.

Adding analysis request options must not invalidate fingerprints for existing expensive jobs. Exclude the new fields from other stages, and reject use on those stages rather than silently interpreting them.

## Signal measurements

Prepare candidate audio as mono 16 kHz PCM16 within the exact saved envelope. Use canonical source recognition audio, from either the original or explicitly approved dialogue stem. `acoustic-dsp-v1` describes both signals; curves retain canonical scene times. Compare RMS levels, median pitch in semitones, energy-active spans and internal low-energy pauses. Account separately for padding inferred from the recorded fit ratio/raw duration. Internal pauses exclude leading/trailing low-energy regions. Words per minute are text-derived and not comparable as a universal speed score across languages.

Absolute pitch can differ naturally across actors, and gain/separation/background can change levels and estimated pauses. These measurements are not emotion, identity, validated voice activity, phonetic correspondence or a guarantee that the dub is natural. Do not automatically force target pitch or gain to match the source. Natural recordings and listening remain the acceptance test.

## Experimental Malayalam model

Pin [trysem/wav2vec2-malayalam-onnx-int8](https://huggingface.co/trysem/wav2vec2-malayalam-onnx-int8/tree/f16ea0d2a80812d38205d335c1f4806543dccad0), revision `f16ea0d2a80812d38205d335c1f4806543dccad0`, graph 356,698,513 bytes, SHA256 `40a80cff1d5750939ca8f657587ed05b826d75466df9f83f7344154b9e61f12a`. Config/vocabulary/preprocessor checksums are pinned too. Its card names [gvs/wav2vec2-large-xlsr-malayalam](https://huggingface.co/gvs/wav2vec2-large-xlsr-malayalam), revision `b073beb93616a83d26933e1aa98d9299a5f4af23`; that upstream card declares Apache-2.0. The conversion has no separate license declaration. Record those facts; commercial distribution still needs a provenance/license review rather than an invented conversion license.

Normalize Malayalam text to NFC and use the model's code-point vocabulary without dropping unsupported characters or inventing pronunciations. Unlike the English model, `[PAD]` is blank ID 75; ID 0 is a real Malayalam character. CTC tests cover this difference. Run up to 20 seconds per take on CPU, four threads by default, in a disposable child with a 10 GiB address-space ceiling and 900-second deadline. One graph is loaded at a time; English ASR/alignment and separation weights are not loaded by this job. Offline flags and an environment without API credentials are passed to the child. No weights or remote Python are downloaded at runtime.

Word suggestions require explicit opt-in, with no automatic application even when provisional agreement checks pass. Weak or unsupported text remains flagged. Known demo tones are not sent through word alignment. Original synthetic speech fixtures are labelled separately from tones and from production takes. Only record target-aligner execution when inference actually runs; loading weights or skipping a tone is not evidence of recognition success.
