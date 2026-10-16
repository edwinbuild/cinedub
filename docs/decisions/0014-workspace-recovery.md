# Offline workspace recovery

Status: implemented for the local SQLite and filesystem workspace.

## Decision

Use explicit offline snapshots containing both database and media, verified before restoration into a new directory. Never overwrite the source workspace. Require the current schema rather than silently upgrading a backup during verification. Database-only migration backups remain an upgrade safeguard, not a complete recovery system.

API and worker lifetimes hold shared workspace leases. Backup and restore verification require an exclusive lease; a SQLite write reservation additionally prevents uncoordinated database writers during copying. Native media/model descendants inherit both workspace and single-worker lock descriptors, including across runner subprocesses, so abrupt worker exit cannot release protection while a writer survives. Leases are cooperative Linux filesystem locks, not protection against malicious writers or unsupported old API processes; stop all processes before backup.

Write a manifest only after copying and checking the exact inventory, hashes, database integrity, foreign keys and referenced media. Restore typed media references into the isolated destination and write a new receipt after the safety transformation. Preserve originals, provenance, charges and immutable reports. No recursive replacement of arbitrary JSON or dialogue strings.

## Recovery safety

Formerly active jobs become failed recovery holds. Local/fake jobs require an explicit resume and the existing freshness checks. Paid jobs do not automatically resume or resubmit. Previously approved clones become recovery holds and lose active selections, because an old database cannot prove current permission. Append an audit record instead of inventing legal revocation or silently deleting provider data. Stock voices and normal saved dialogue remain available.

## Consequences

Snapshots need space for a complete media copy and a second copy for a recovery rehearsal. Completion markers reject interrupted copies but do not promise power-loss durability. Checksums provide integrity, not authenticity or encryption. Source code, secrets and external model caches need separate management. Restored receipts describe the initial baseline, not a database that stays unchanged after editing. See [the recovery procedure](../recovery.md) for commands and remaining acceptance gates.
