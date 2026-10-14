# Local cinematic separation: controlled fixture, 2026-10-14

This records actual local inference, not provider marketing or human listening results. Input: one original 18.644-second stereo clip, eSpeak English dialogue plus procedural chords and noise-hit effects with known reference stems. No actor recording or downloaded soundtrack was used.

Model: `audiojs/mrx@dedc823a0bea2ed085d19e8b7f32589d35169ee8`. CPU, four inference threads, one child process; no GPU inference or API charges. A direct runner evaluation with **zero input normalization gain** measured 9,222 ms inference time and 1,487.0 MiB peak process RSS. This excludes browser/API memory and is not a maximum for two-minute scenes. The normal worker instead measures input loudness and applies the gain recorded with that job; do not attribute the following direct-run scores to every UI run.

| Known stem | Mixture SI-SDR | Separated SI-SDR | Improvement |
| --- | ---: | ---: | ---: |
| Dialogue | 6.49 dB | 16.27 dB | +9.78 dB |
| Music | -6.67 dB | 10.31 dB | +16.98 dB |
| Effects | -24.28 dB | 3.65 dB | +27.93 dB |

Higher SI-SDR indicates less reference-relative distortion on this clip. The large effects improvement starts from an extremely weak baseline; **3.65 dB absolute effects isolation is not strong preservation**. This result does not justify removing manual review. Reconstruction SNR was 22.74 dB, a separate sum-of-stems diagnostic, not an isolation or naturalness score.

## Reproduce the direct measurement

Install both optional extras and download the pinned models as described in the README. From the repository root:

```bash
.venv/bin/python scripts/make-separation-fixture.py
ffmpeg -y -i data/evaluation/separation/mixture.wav -ar 44100 -ac 2 -f f32le data/evaluation/separation/input.f32
PYTHONPATH=apps/api OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=4 .venv/bin/python -m cinedub_api.local_separation_runner --model-dir models/mrx --audio data/evaluation/separation/input.f32 --output-dir data/evaluation/separation/result --duration-ms 18644 --gain-db 0 --threads 4
.venv/bin/python scripts/evaluate-separation.py
```

The fixture duration is recorded in `fixture.json`; if speech-tool versions change it, use that actual duration instead. Weights, fixture media and evaluation JSON remain in ignored local storage. Runtime jobs use the bounded parent adapter rather than invoking the child directly.

## Integration and remaining quality gates

Unit/integration checks cover STFT inverse identity, overlap crossfades, stereo channel distinction, no-key subprocess cancellation/deadline, missing installation, source hashes, crash-checkpoint reuse, 48 kHz stereo artifact contracts, review conflicts, audit history and immutable transcription input. These use recorded adapter output except the explicit opt-in browser test.

The opt-in browser test executes real MRX and local ASR, plays three browser-decodable listening files, explicitly approves a fixture set, recognizes its dialogue, keeps the approved choice during a rerun and rejects it back to original-audio routing. Its simulated review checkbox is **not** human listening evidence.

Still required: authorized natural-film clips, dialogue leakage measurement/listening, quiet and overlapping dialogue, ambience/transient retention, cross-chunk continuity, phase/stereo review, two-minute resource envelope, and human acceptance. Final retained-background mixing/loudness/export remains a separate milestone.
