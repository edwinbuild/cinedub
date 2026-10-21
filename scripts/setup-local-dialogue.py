"""Explicit pinned local dialogue setup. No installer shell, services or global packages."""

import argparse
import json
import platform
import tarfile
from pathlib import Path

import httpx
from cinedub_api.providers.local_dialogue import (
    ENGINE_COMMIT,
    ENGINE_FILE,
    ENGINE_SHA256,
    ENGINE_SIZE,
    ENGINE_TAG,
    ENGINE_URL,
    MODEL_FILE,
    MODEL_ID,
    MODEL_REVISION,
    MODEL_SHA256,
    digest,
    read_manifest,
    verify_runtime,
)


def install_runtime(directory):
    archive = directory / ENGINE_FILE
    if archive.is_symlink() or (directory / "runtime").is_symlink():
        raise ValueError("Refusing a symlinked runtime archive or installation directory")
    if not archive.exists():
        pending = archive.with_suffix(".download")
        with httpx.stream("GET", ENGINE_URL, follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            size = 0
            with pending.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > ENGINE_SIZE:
                        raise ValueError("Runtime archive exceeds pinned size")
                    output.write(chunk)
        if size != ENGINE_SIZE or digest(pending) != ENGINE_SHA256:
            raise ValueError("Downloaded runtime does not match pinned checksum")
        pending.replace(archive)
    if archive.stat().st_size != ENGINE_SIZE or digest(archive) != ENGINE_SHA256:
        raise ValueError("Existing runtime archive changed; do not execute it")
    runtime = directory / "runtime"
    runtime.mkdir(exist_ok=True)
    with tarfile.open(archive, "r:gz") as package:
        package.extractall(runtime, filter="data")
    verify_runtime(runtime, archive)
    executables = list(runtime.rglob("llama-completion")) or list(runtime.rglob("llama-cli"))
    if len(executables) != 1:
        raise ValueError("Expected one supported completion executable")
    return executables[0].relative_to(runtime).as_posix()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("models/qwen3-dialogue"))
    parser.add_argument("--runtime-only", action="store_true")
    args = parser.parse_args()
    if args.directory.is_symlink():
        parser.error("Refusing a symlinked installation directory")
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This pinned runtime supports Linux x86_64 CPU only")
    args.directory.mkdir(parents=True, exist_ok=True)
    executable = install_runtime(args.directory)
    print(f"Verified CPU runtime: {executable}", flush=True)
    if args.runtime_only:
        return
    from huggingface_hub import hf_hub_download

    hf_hub_download(
        MODEL_ID,
        MODEL_FILE,
        revision=MODEL_REVISION,
        local_dir=args.directory,
        token=False,
    )
    manifest = {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "model_sha256": MODEL_SHA256,
        "engine_tag": ENGINE_TAG,
        "engine_commit": ENGINE_COMMIT,
        "engine_archive_sha256": ENGINE_SHA256,
        "executable": executable,
        "upstream": "Qwen/Qwen3-4B-Instruct-2507",
        "license": "Apache-2.0 declared by upstream and quantization cards",
        "purpose": "Experimental dialogue alternatives, not certified Malayalam or emotion",
    }
    (args.directory / "cinedub-manifest.json").write_text(json.dumps(manifest, indent=2))
    read_manifest(args.directory, verify=True)
    print(f"Verified optional CPU dialogue model: {args.directory}")


if __name__ == "__main__":
    main()
