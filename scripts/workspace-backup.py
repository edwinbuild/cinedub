"""Offline private workspace backup, verification and non-overwriting recovery."""

import argparse
import json
import sqlite3
from pathlib import Path

from cinedub_api.backup_manifest import verify_snapshot
from cinedub_api.workspace_backup import create_snapshot, restore_snapshot, verify_restored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser(
        "create", help="Stop API/worker first; copies database and all media"
    )
    backup.add_argument("--database", type=Path, required=True)
    backup.add_argument("--storage", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="Verify a trusted completed snapshot")
    verify.add_argument("snapshot", type=Path)
    restore = commands.add_parser(
        "restore", help="Create a NEW recovery workspace; never overwrite"
    )
    restore.add_argument("snapshot", type=Path)
    restore.add_argument("--output", type=Path, required=True)
    restored = commands.add_parser(
        "verify-restored", help="Verify recovery baseline before editing"
    )
    restored.add_argument("workspace", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "create":
            result = create_snapshot(args.database, args.storage, args.output)
        elif args.command == "verify":
            manifest = verify_snapshot(args.snapshot)
            result = {
                "snapshot": str(args.snapshot.resolve()),
                "schema_revision": manifest.schema_revision,
                "files": len(manifest.files),
                "verified": True,
            }
        elif args.command == "restore":
            result = restore_snapshot(args.snapshot, args.output)
        else:
            result = verify_restored(args.workspace)
    except (OSError, ValueError, RuntimeError, KeyError, sqlite3.Error) as exc:
        parser.exit(1, f"Recovery operation refused: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
