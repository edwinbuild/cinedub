# Local runtime supervision

Status: implemented for the Linux single-user SQLite workspace.

## Decision

Keep the API, durable worker and Next.js editor as separate processes, but launch them through one Python supervisor rather than background shell jobs. No new runtime dependency, service installation, model download or cloud deployment is needed.

`npm run doctor` validates configuration, Python/Node versions, FFmpeg tools, installed application entry points, distinct available loopback ports and existing workspace/worker locks. It uses `Settings()` without directory creation or database imports. It does not migrate data, verify optional model hashes or contact providers. Missing Sarvam credentials warn rather than prevent editing and media ingest. Numeric configuration errors never echo their input values.

`npm run dev` runs the same preflight, initializes the schema once under supervision, then starts the API, worker and editor. Derive API URL and browser origin from the chosen ports; reject conflicting shell overrides. Both HTTP services bind to loopback, because this workspace has no public-user authentication. Pass only a small operating-system environment allowlist and the public API URL to Next.js; server-side provider keys remain outside that child environment.

The supervisor reports readiness only after API health and the web entry page return HTTP 200 with the three service processes still running. A service exit or readiness timeout stops the remaining owned processes and returns failure. Readiness is not model availability or proof of a successful dubbing job.

## Shutdown and limits

Linux child-subreaper adoption keeps native model/media sessions discoverable after their worker exits. On Ctrl+C or SIGTERM, signal only descendants of the supervisor, give them five seconds, then kill surviving owned processes and reap them. Do not match process names, kill unrelated port owners or delete lock files. Workspace leases remain the final protection against backup races if the supervisor itself is killed abruptly.

Stopping interrupts work; committed checkpoints and uncertain-provider-submission rules still govern restart. It cannot cancel or refund an already submitted paid request. This launcher is a development convenience, not an OS service manager or a packaged desktop installer. A fresh-machine install, supervisor SIGKILL, disk failure and other operating systems remain separate release gates.

## Acceptance

Runtime tests exercise side-effect-free preflight, invalid configuration without secret echo, busy ports and locks, stripped web credentials, owned native-session cleanup after Ctrl+C and worker failure, and actual API/web/worker startup with upload/ingest followed by shutdown/restart and saved-project recovery. Browser workflows can use the same launcher with `CINEDUB_E2E_LAUNCHER=1`; do not run another Next.js dev server for the checkout concurrently.
