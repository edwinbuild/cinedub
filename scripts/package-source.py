"""Package a trusted committed source snapshot; no dependencies, data or release publication."""

import argparse
import gzip
import hashlib
import io
import json
import runpy
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
validate_members = runpy.run_path(str(ROOT / "scripts/verify-clean-install.py"))["validate_members"]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def inspect_snapshot(snapshot):
    with tarfile.open(fileobj=io.BytesIO(snapshot), mode="r:") as archive:
        validate_members(archive.getmembers())
        required = {}
        for name in ("package.json", "package-lock.json", "uv.lock", "README.md", ".env.example"):
            member = archive.getmember(name)
            if not member.isfile():
                raise ValueError(f"Required source file is not regular: {name}")
            required[name] = archive.extractfile(member).read()
    return {
        "application_version": json.loads(required["package.json"])["version"],
        "lock_sha256": {name: sha256(required[name]) for name in ("package-lock.json", "uv.lock")},
    }


def package(ref, output):
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        cwd=ROOT,
        text=True,
    ).strip()
    snapshot = subprocess.check_output(["git", "archive", "--format=tar", commit], cwd=ROOT)
    metadata = inspect_snapshot(snapshot)
    # Validate before creating anything. Never overwrite an existing destination.
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    name = f"cinedub-source-{commit[:12]}.tar.gz"
    compressed = gzip.compress(snapshot, mtime=0)
    (output / name).write_bytes(compressed)
    manifest = {
        "format_version": 1,
        "kind": "source-only-development-snapshot",
        "application_commit": commit,
        **metadata,
        "archive": name,
        "archive_sha256": sha256(compressed),
        "archive_bytes": len(compressed),
        "scope": "Committed source only. No runtime, dependencies, models, data, credentials, "
        "test receipt, release approval or authenticity signature included. "
        "Use README.md for prerequisites and installation; review the commit before execution.",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "SHA256SUMS").write_text(
        f"{sha256(compressed)}  {name}\n"
        f"{sha256((output / 'manifest.json').read_bytes())}  manifest.json\n"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Trusted committed revision; ignores edits")
    parser.add_argument(
        "--output", required=True, type=Path, help="New directory in an existing parent"
    )
    arguments = parser.parse_args()
    try:
        manifest = package(arguments.ref, arguments.output)
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError):
        parser.exit(1, "Source packaging failed; destination was not overwritten.\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
