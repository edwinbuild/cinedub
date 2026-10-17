# Workspace backup and recovery

Back up the SQLite database and its media together before a risky upgrade or moving a project. Automatic migration `.bak` files contain only the database; they cannot replace a workspace snapshot. These commands support the current local SQLite/filesystem layout on Linux and require the matching schema checkout.

## Create a snapshot

Stop the API and worker first. Wait for their media/model child processes to exit; inherited leases also prevent backup while an orphaned writer remains alive. Do not delete lock files to bypass a refusal. The lock is held by an open descriptor, not by the file's existence.

From the repository root, substitute the actual database and storage paths from your local configuration. The CLI deliberately does not load `.env`.

```bash
PYTHONPATH=apps/api .venv/bin/python scripts/workspace-backup.py create --database ./data/cinedub.db --storage ./data/storage --output ./data/backups/manual-001
PYTHONPATH=apps/api .venv/bin/python scripts/workspace-backup.py verify ./data/backups/manual-001
```

Choose a new output directory outside the media storage directory every time. Existing destinations are never overwritten. An interrupted attempt leaves an incomplete directory without a valid completion manifest; keep the original workspace and choose another destination after resolving the cause.

A snapshot contains `database.sqlite3`, the media storage tree and a versioned `manifest.json` with SHA256 checksums, sizes, schema revision and table counts. Verification checks database integrity, foreign keys, referenced media and exact file inventory. Symlinks, unsupported schemas, missing media, changed copies and `.env` files in storage are refused.

Snapshots contain private media, dialogue, consent records and provider references. The output directory is private to its owner, but **the contents are not encrypted or signed**. Store them on trusted encrypted storage. Checksums detect changes; they do not prove the identity of whoever supplied a snapshot. Only restore trusted snapshots. Keep the matching code revision separately. API keys, external model caches, source code, `OLD/` and database-only migration backups outside storage are not included.

## Restore an isolated copy

```bash
PYTHONPATH=apps/api .venv/bin/python scripts/workspace-backup.py restore ./data/backups/manual-001 --output ./data/recovered-001
PYTHONPATH=apps/api .venv/bin/python scripts/workspace-backup.py verify-restored ./data/recovered-001
```

The new directory contains `workspace.sqlite3`, `storage/`, the source manifest and `restore-receipt.json`. The source workspace and snapshot remain unchanged. Media references and resumable voice chunk paths are rebased to the new storage root; dialogue, immutable reports and provider audit history are not rewritten.

`verify-restored` checks the initial recovery baseline before starting the application. Once legitimate application edits change that database or its media, the old receipt is no longer a current checksum baseline. Stop the application and create a new snapshot instead. Moving a restored directory again also invalidates its recorded location; restore the original snapshot into the intended destination.

## Start and review the recovered workspace

Use absolute paths in a separate local environment configuration:

```dotenv
CINEDUB_DATABASE_URL=sqlite:////absolute/path/to/data/recovered-001/workspace.sqlite3
CINEDUB_STORAGE_ROOT=/absolute/path/to/data/recovered-001/storage
```

Check `.env.example` for the remaining provider and model configuration. Keep keys server-side and launch the API and worker with the same recovered paths. Never point only one process at the recovered copy.

| Recovered state | Required action |
| --- | --- |
| Previously queued or running local/fake job | Held as failed with `restored_job_hold`; inspect it and explicitly choose **Resume saved local job** when appropriate. Normal input freshness and budget checks still apply. |
| Previously queued or running paid/provider job | Held without automatic retry. Check remote status, usage and checkpoints before deciding whether to submit new work; restoration is not permission to rebill a request. |
| Previously approved cloned voice | Changed to `recovery_hold`, with an audit entry; speaker and selected cloned-take choices are detached. Historical permission is not proof of current permission. Verify rights and create a fresh approved profile before reuse. |
| Provider clone requiring deletion | Explicitly revoke consent first, then request provider-copy deletion. A recovery hold is not a legal revocation and does not delete remote data. |
| Stock voice, saved text or immutable history | Retained; inspect playback, line history, briefs and exports in the recovered workspace. |

The automated recovery rehearsal covers a real HTTP edit, offline snapshot, isolated restore, stock media playback, clone quarantine, a restarted worker, explicit local export resume and a paid job staying held. It uses synthetic media and fake providers. Large-film disk exhaustion, power-loss durability, other operating systems, remote-provider recovery and human listening remain separate acceptance gates.

## When storage capacity is exhausted

Recognized SQLite `SQLITE_FULL` and direct filesystem `ENOSPC`/`EDQUOT` errors return HTTP 507 with a generic free-space/quota/restart instruction. SQL statements, draft text and filesystem paths are not copied into that capacity response. Other database/permission errors keep their existing behavior; a string saying “disk full” is not enough to classify an error.

The worker stops with a nonzero exit and a generic `storage_capacity_exhausted` diagnostic instead of trying to keep writing completion/error state into full storage. The supervised launcher then shuts down its owned services. A job may retain its last committed `running` state: that is a durable checkpoint, not proof the stopped worker is still active. The editor retains a draft after a 507 save failure; copy unsaved fields before closing/reloading the page.

Free space or resolve the quota on the database, media and temporary-storage locations, then restart CineDub. Do not delete the database, project media, SQLite journal/WAL files or lock files to make an error disappear. If moving the workspace, use a consistent verified database/media snapshot and a matching checkout. Normal restart recovery reuses safe committed work and known remote handles. An uncertain paid submission stays held for usage/history inspection, not automatic rebilling. Do not force a new paid job merely because the previous completion response was unavailable.

Normal worker restart also retains committed cancellation requests. A running job with no uncertain-submission marker becomes terminal `cancelled`, not requeued; its remote handle, checkpoints and charged estimate remain intact. The worker checks cancellation before entering any claimed processor, including fixture/export paths. Cancellation does not roll back previously committed artifacts or cancel/refund a remote request. If a provider submission was interrupted at an uncertain boundary, that hold takes precedence even when cancellation was requested: inspect remote usage/history before deciding on any new operation. These restart rules are separate from restoring an offline backup, which intentionally applies recovery holds.

The bounded tests impose SQLite's [maximum page count](https://www.sqlite.org/pragma.html#pragma_max_page_count) on small temporary databases and observe actual [SQLITE_FULL](https://www.sqlite.org/rescode.html#full), without filling the host disk. They verify a failed edit leaves saved text/version/approval/history intact, an explicit retry after capacity release works, and final worker-commit failure preserves checkpoints. Restart-recovery logic reuses the already-published SRT without changing bytes/mtime or duplicating artifacts; a simulated uncertain paid boundary retains its estimated charge and is not resubmitted. SQLite integrity checks remain `ok`. Direct filesystem errno cases and the sanitized worker exit are injected tests; the browser 507 case is an intercepted response paired with the real API/database test, not a filled-volume browser test.

This is not power-loss, rollback-I/O failure, physical filesystem exhaustion or large-film acceptance. FFmpeg/native child-process failures retain their existing structured failure paths unless a recognized capacity error reaches the API/worker boundary. Live provider reconciliation, other filesystems/operating systems and hardware-fault recovery remain open.
