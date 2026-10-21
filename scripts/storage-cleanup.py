"""Report (default) or remove storage that no database row needs.

Usage: PYTHONPATH=apps/api .venv/bin/python scripts/storage-cleanup.py [--apply] [--grace-days N]

Stop the API and worker first when applying. Completed job directories, active or resumable
jobs, lock files and anything outside the configured storage root are never removed.
"""

import argparse

from cinedub_api.database import SessionLocal
from cinedub_api.storage import storage
from cinedub_api.storage_cleanup import apply_cleanup, plan_cleanup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="remove the reported leftovers")
    parser.add_argument("--grace-days", type=int, default=7)
    args = parser.parse_args()
    store = storage()
    with SessionLocal() as session:
        report = plan_cleanup(session, store, grace_days=args.grace_days)
    for label, paths in [
        ("orphaned upload", report.orphaned_files),
        ("orphaned project directory", report.orphaned_project_directories),
        ("stale job directory", report.stale_job_directories),
    ]:
        for path in paths:
            print(f"{label}: {path.relative_to(store.root)}")
    print(f"reclaimable: {report.reclaimable_bytes} bytes")
    if args.apply:
        apply_cleanup(store, report)
        print("removed")
    else:
        print("dry run: nothing removed (use --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
