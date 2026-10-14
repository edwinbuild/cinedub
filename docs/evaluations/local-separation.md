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

Still required: authorized natural-film clips, dialogue leakage measurement/listening, quiet and overlapping dialogue, ambience/transient retention, cross-chunk continuity, phase/stereo review and human acceptance. Maximum-duration resource measurement is recorded below; reviewed mix exports have independent technical and listening gates.

## Two minute resource run on 2026-10-15

A 120-second stereo input, made by looping the original synthetic mixture, completed all 16 inference chunks through the bounded `LocalSeparator` adapter. Reported child inference latency was **44,486 ms**, peak process RSS **1,849.1 MiB** (about 1.81 GiB), CPU four threads and zero input normalization gain. The parent enforced a 180-second deadline; the child retained its 10 GiB address-space cap. This measures one synthetic maximum-duration input, not all content or total application memory. The host had 30 GiB installed RAM and about 11 GiB available before this run; the result supports the 24 GiB design budget but is not a physical 24 GiB host certification.

All three float32 WAV masters had exactly 5,760,000 frames, 48 kHz, two channels and 120,000 ms duration, and passed a full FFmpeg decode. The ignored local evidence is under `data/evaluation/mrx-120s-PTjf5n/`. Reconstruction SNR (22.73 dB) remains a sum diagnostic, not isolation quality.

The short-scene resource envelope is now measured at two minutes on this host. Natural-scene leakage, effects/stereo and human listening gates remain open. [Reviewed stereo mixing/export](../decisions/0006-reviewed-stereo-exports.md) was connected after the initial separation benchmark.
