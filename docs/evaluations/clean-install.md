# Clean base installation rehearsal

The committed application at `ce3fe6a2e385a47440d942d6c60dbef4eda1e495` passed installation into a new Python environment and new `node_modules`, followed by build, supervised startup and a real browser workflow. No optional model packages or weights were present. This closes a base-environment smoke check, not pristine-machine, live-provider or cinema-quality acceptance.

## Run the check

From a trusted CineDub checkout with Linux, Python 3.12+, uv, Node/npm, FFmpeg/ffprobe and installed Google Chrome:

```bash
npm run verify:clean-install
# Or choose a particular committed application revision:
UV_CACHE_DIR=/tmp/cinedub-uv-cache uv run --no-project --python 3.12 python scripts/verify-clean-install.py --ref HEAD
```

The controller uses only Python's standard library, so it does not need the original checkout's Python environment. The npm command selects the verified Python 3.12 profile through uv without loading the original project dependencies. It tests the selected committed revision, not uncommitted application edits. The snapshot installs base Python dependencies with `uv sync --frozen --no-dev` and no extras, then the locked npm graph with `npm ci`. The npm development graph includes the browser test driver. Only run reviewed, trusted commits: application code and package installation scripts execute normally; this is not a security sandbox.

At least 2 GiB free temporary space is required. Each attempt creates a private `cinedub-clean-install-*` directory under the system temporary directory. Existing destinations and normal application state are not overwritten. Artifacts are retained for inspection; remove only the exact printed rehearsal directory when finished. The measured checkout occupied about 643 MiB, excluding shared package caches. A failure returns nonzero and produces no passing receipt; inspect the printed private logs when a directory was created.

## Isolation and checked flow

The controller resolves a commit, checks tracked paths before archiving, then validates regular archive entries before extraction. It refuses `OLD/`, local configuration, state/models/dependencies, escaping paths, symlinks and special files. It does not copy ignored `.env`, media, models or the original `.venv`. Use a trusted reviewed commit; filename checks are not a general secret scanner.

The application starts on separate loopback ports with a new database/storage directory, explicit fake transcription/translation/voice routes and both Sarvam key aliases empty. Browser HTTP requests are restricted to those local origins. Synthetic audio exercises upload, FFmpeg ingest/waveform, clearly labelled fixture transcription/translation, a manual Malayalam edit, saved subtitle download and persistence after reload. Optional capabilities must report unavailable rather than download weights or pretend to run. The supervisor is stopped and both listeners must be released afterward.

The completion receipt records application commit, driver hashes, unchanged dependency-lock hashes, tool versions, absent optional packages and browser/shutdown results. It is an unsigned local verification record, not an authenticity or natural-quality certificate. Runtime logs, workspace data and screenshots remain outside Git.

## Observed result

| Check | Result |
| --- | --- |
| Fresh Python environment | Passed; base dependencies only, no Python dev group |
| Optional packages | NumPy, ONNX Runtime, faster-whisper, Torch and Hugging Face Hub all absent |
| Fresh Node dependencies and production build | Passed; committed lockfiles unchanged |
| Doctor and API/worker/web startup | Passed |
| Browser upload through edited subtitle download and reload | Passed |
| Optional model capabilities without packages/weights | Correctly unavailable |
| External application browser HTTP requests and paid jobs | Zero in the smoke workflow |
| Supervisor shutdown and released HTTP listeners | Passed |
| Snapshot/environment safety unit checks | 19 passed, including nested private/runtime folders |

Observed tools: Python 3.12.13, Node v24.19.0, npm 11.17.0 and uv 0.12.1 on Linux x86_64. The rehearsals passed, including the final nested-path hardening run with frozen driver and lock hashes. Existing host tools and package caches were reused. The application source was the recorded commit; this milestone adds the rehearsal tooling/docs rather than changing the application runtime.

## Remaining acceptance

A separate physical machine/pristine OS, other supported tool versions, optional model installation/resource acceptance, desktop/service packaging, live Sarvam and authorized natural-language/listening evaluation remain open. Fixture tones and synthetic confirmations do not prove natural dubbing, speaker identity or model accuracy. This run is not a cold-registry-download or whole-laptop RAM benchmark.
