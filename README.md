# CineDub

CineDub is a local-first cinema dubbing workspace. The current rebuild provides a provider-neutral API, a durable background worker, and a browser editor for an English-to-Malayalam workflow.

`OLD/` is an ignored reference snapshot and is never imported by the application.

## v0.1.0: First working demo

- project creation and validated media upload;
- database-backed jobs with progress, cancellation requests, and failure records;
- deterministic demo transcription, translation, performance analysis, and export;
- editable and approvable timeline segments;
- consent-gated voice profiles;
- experimental Sarvam translation and voice-cloning adapters behind capability routing;
- FFmpeg/ffprobe media inspection and subtitle export;
- provider diagnostics without exposing credentials.

## Local setup

Install Python 3.12+, Node.js 22+, npm, uv, and FFmpeg (including ffprobe). Run commands from the repository root.

```bash
cp .env.example .env
uv sync --group dev
npm ci
```

Copy `.env.example` only on first setup; preserve an existing `.env` and its credentials.

Start the API, durable worker, and web editor together:

```bash
npm run dev
```

Open <http://127.0.0.1:3000>. The API documentation is at <http://127.0.0.1:8000/docs>.

If another application occupies port 3000, explicitly start the web editor on port 3001 and authorize that origin:

```bash
CINEDUB_WEB_ORIGIN=http://127.0.0.1:3001 PORT=3001 npm run dev
```

Then open <http://127.0.0.1:3001>. Run only one CineDub API and worker at a time; stop the processes with Ctrl+C before restarting.

Run the repeatable checks with `npm test`; use `npm run build:web` for the production web build.

The default configuration uses versioned Alembic migrations, SQLite, and a database-backed queue so it works without system services. `CINEDUB_DATABASE_URL` can later point at PostgreSQL, and the queue implementation is isolated behind the worker boundary.

## Try the demo

Create a project and select **Build demo timeline**. Review the four fixture lines and two speakers, edit Malayalam text, approve lines, and select **Validate export** to download an SRT subtitle file. **Generate candidates** produces test tones rather than speech.

Importing media probes the file and queues real FFmpeg audio extraction, waveform-data generation, and a video proxy when applicable. The editor currently displays source metadata and a decorative waveform; synchronized playback is pending.

## Remaining work

- Sarvam transcription and speaker diarization into real timeline segments.
- Live verification of the Sarvam adapters, speaker reference capture, and voice-consent UI. The current UI always requests fake synthesis, even if a real voice provider is configured.
- Local models for separation, alignment, and performance analysis. Demo emotion, energy, and pace are fixture metadata, not measured signals; the editor currently displays these values without editing controls.
- Playable video/audio previews, real waveform rendering, timing edits, and candidate selection.
- Timing-fit dialogue, background-stem mixing, and a rendered dubbed video. Current video export is an unchanged picture reference alongside subtitles.
- Recovery of jobs interrupted while running, atomic worker claims, bounded retries, cost controls, and broader failure-path testing. Queued jobs are persisted, but automatic recovery of an already-running job after a crash is not implemented.
- Human Malayalam review and listening evaluations on licensed test scenes.

This release is a local development foundation. Provider availability diagnostics do not establish model quality or successful live execution. Tests use deterministic providers and synthetic audio; no paid-provider quality claim is made.

## Safety

The development server binds to localhost. Sarvam is disabled until `SARVAM_API_KEY` is configured. A voice profile cannot be activated unless its consent record is approved.
