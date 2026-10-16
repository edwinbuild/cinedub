# Experimental source speech emotion and human review

## Decision

Add an optional CPU audio-only `EmotionAnalyzer` adapter. Run pinned wav2vec2 SUPERB emotion and Silero speech-presence ONNX graphs in an offline, cancellable child process. Keep predictions separate from human performance direction, acoustic measurements and synthesis settings. This is an experimental editor aid, not a quality acceptance signal.

The English classifier has four labels: neutral, happy, angry and sad. The [upstream model card](https://huggingface.co/superb/wav2vec2-base-superb-er) describes IEMOCAP training/evaluation and declares Apache-2.0; the [conversion](https://huggingface.co/onnx-community/wav2vec2-base-superb-er-ONNX) declares the same license. [Silero conversion](https://huggingface.co/onnx-community/silero-vad) declares MIT. These declarations do not settle training-data provenance, actor personality rights or commercial clearance. No IEMOCAP actor recordings are downloaded or committed.

## Execution and limits

- Explicit installation downloads about 381 MB of graphs. Jobs cannot download weights or execute remote model code. Installed identities, revisions, sizes and SHA256 values are checked; the job freezes its profile and installation manifest.
- The worker runs one native job at a time. Four CPU threads by default, a 10 GiB address-space ceiling, cancellation and a 900-second default deadline bound the optional analyzer for the 24 GB laptop target. VAD is released before loading the classifier.
- Use mono 16 kHz PCM16 source audio or the explicitly selected, approved, source-bound dialogue stem. The classifier's pinned preprocessor requires `do_normalize=false`; do not apply per-window z-score normalization.
- Only saved English source windows of 0.7 to 20 seconds are eligible. Overlapping dialogue, short/long windows and insufficient speech are skipped without labels. Whole scenes remain limited to two minutes and at most 500 selected windows.
- The native request contains timing/overlap information, never transcript, translation, sentiment or character notes. The report retains the historical transcript for editor reference only.
- Speech detection and suggestion thresholds are provisional, versioned engineering choices. Normalized model scores are not calibrated confidence; an uncertain distribution has no suggested label. The model cannot cover sarcasm, nuanced delivery or Malayalam performance.

## Evidence and review

`analyze_emotion` freezes source hashes, revision, line windows/speakers/overlap, optional stem version and model profile. The immutable JSON artifact is checksummed. Provider runs are recorded only for executed inference and have no API charge. Timing, speaker, overlap, source or approved-stem changes prevent late publication or stale review. Transcript/translation-only edits do not change an audio-only prediction.

`GET /speech-emotion-reports/{id}` validates report bytes and lineage, exposes current staleness and appends saved review history to the typed response. The original downloadable JSON remains immutable and contains no subsequent human reviews.

`POST /speech-emotion-reports/{id}/review` requires explicit listening confirmation, reviewer attribution and optimistic review-version matching. Accepting requires an actual suggestion; corrections may use broader human labels; rejection retains no chosen label. Reviews are append-only in migration `0008_speech_emotion_reviews`, with a backup on application upgrade from `0007_dialogue_briefs`. Reviews never alter timeline emotion fields, translations, selected takes, voice settings or approvals.

## Acceptance boundary

The synthetic execution/negative-control and browser checks are described in [the evaluation record](../evaluations/speech-emotion.md). Before using predictions to guide synthesis, evaluate authorized natural English performances, out-of-class/overlapping/music-heavy inputs and human disagreement. Measure class balance, abstention and errors on a held-out corpus without tuning thresholds to the test sample. Malayalam emotion preservation requires separate target listening and language-expert evaluation.
