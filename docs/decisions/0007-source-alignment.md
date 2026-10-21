# English source alignment and acoustic measurements

Status: implemented for English source review; Malayalam candidate alignment and emotion inference remain separate work.

## Model and resource choice

Use the optional [ONNX Community conversion](https://huggingface.co/onnx-community/wav2vec2-base-960h-ONNX/tree/729c1a6730fb549c20a1c73a3d3f96f11020225e) of [Meta wav2vec2 base 960h](https://huggingface.co/facebook/wav2vec2-base-960h), revision `729c1a6730fb549c20a1c73a3d3f96f11020225e`. The publisher identifies the upstream English model, whose card declares Apache-2.0 and 16 kHz input; the conversion card has no separate license declaration. Record this provenance rather than inventing a conversion license. Model data remains ignored and is not redistributed in Git.

Pin `onnx/model.onnx`, 377,911,891 bytes, SHA256 `00b7cc69516c1ab63c429e63a2b543e4d42bb77441ec5b98ee935de175b00de1`, plus configuration/vocabulary checksums in the adapter. The 95 MB quantized graph decoded the controlled English clip mostly as repeated E characters; the full-precision graph recovered recognizable speech. Prefer the measured float32 path rather than lowering acoustic checks to accept the smaller graph.

Run one CPU model in a disposable child, four threads by default, with a 10 GiB address-space ceiling and 600-second deadline. Native inference can be killed on cancellation/deadline. Inference uses only local model files with offline flags; credentials and remote Python are not passed into it. Windows are bounded to 20 seconds including up to 300 ms of context on each side; longer phrases yield an actionable warning. Full two-minute clips are processed line by line, not in one quadratic-attention window.

## Contracts and timeline safety

`Aligner` is a provider-neutral capability selected by the registry. `align` is a durable, zero-API-charge job with immutable source/revision/line/model snapshots. The analysis uses the explicitly selected original or approved dialogue-stem recognition audio, mapped to the canonical scene timeline. Offset sources prepared with older mapping require preparation again. Source and analysis-audio bytes are hashed before and after execution; late edits publish no current alignment report.

The existing artifact/job tables store immutable schema-versioned JSON reports and provenance, so no database schema mutation is needed. Shared web types are generated from Pydantic. Reports retain word timings, uncalibrated acoustic emission scores, independent greedy text agreement, acoustic curves, warnings and model/resource metadata. Applying a result records the normal `SegmentEdit` history and its evidence artifact ID. Downloads remain historical evidence, not a current approval certificate.

CTC Viterbi alignment uses blank/interleaved token states, with blank transitions between repeated letters. It cannot silently discard unknown letters or invent pronunciations for numbers. Missing/unfittable text produces no accepted timing. The frame stride is 20 ms; these are acoustic estimates, not phoneme- or lip-sync guarantees.

Provisional application checks require mean word score at least 0.45, minimum word score at least 0.2, and greedy character-error ratio at most 0.5. These are conservative workflow guards, not calibrated confidence or evidence of naturalness. Weak results stay inspectable but cannot be applied automatically. Always require listening confirmation; replacing an edited/approved line needs explicit permission. Application changes only the line envelope, preserves translation, invalidates the old selected take and sets `needs_review`. Per-line version checks allow unaffected suggestions to remain reviewable after another line is applied. Active-timeline or approved-stem changes invalidate the whole report for application.

## Acoustic scope

`acoustic-dsp-v1` measures 40 ms frames every 20 ms at 16 kHz. It reports RMS/peak dBFS, normalized-autocorrelation pitch estimates between 70 and 500 Hz, text-derived words per minute, and low-energy intervals of at least 150 ms. Activity uses a threshold of the greater of -50 dBFS and 35 dB below the maximum frame RMS. Pitch requires a sufficiently strong local autocorrelation peak; unmeasurable values remain null.

These quantities describe the chosen analysis signal. Separation/gain, music, noise, overlap, whispers and octave errors affect them. They are not speaker identity, semantic intent, validated voice activity or emotion labels. No measured feature overwrites existing editor emotion/energy/pace fields or silently changes synthesis parameters. Target-language candidate measurements, comparison across performances, and evaluated emotion analysis remain required.
