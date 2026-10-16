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
