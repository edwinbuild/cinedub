"""Pinned optional CPU dialogue model; weights and runtime are explicit local installs."""

import hashlib
import json
import os
import platform
import tarfile
from pathlib import Path

from ..dialogue_prompt import SYSTEM
from ..local_process import run_inference

MODEL_ID = "unsloth/Qwen3-4B-Instruct-2507-GGUF"
MODEL_REVISION = "a06e946bb6b655725eafa393f4a9745d460374c9"
MODEL_FILE = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
MODEL_SIZE = 2_497_281_120
MODEL_SHA256 = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
MODEL_NAME = f"{MODEL_ID}@{MODEL_REVISION}:Q4_K_M"
ENGINE_TAG = "b11642"
ENGINE_COMMIT = "2639a3b4e029d1be80ca4a472d62dfea23609075"
ENGINE_FILE = "llama-b11642-bin-ubuntu-x64.tar.gz"
ENGINE_SIZE = 17_827_461
ENGINE_SHA256 = "374efdb7638a3b3c06eda2a384485015ecf751f172364a4309be88e7bdaa1aa7"
ENGINE_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{ENGINE_TAG}/{ENGINE_FILE}"
EXECUTABLE = "llama-b11642/llama-completion"


def qwen_prompt(request):
    # Escape delimiters in all supplied text; the native CLI also uses --no-escape.
    data = (
        json.dumps(request["data"], ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return (
        f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n{data}<|im_end|>\n<|im_start|>assistant\n"
    )


def serialized_prompt_digest(request):
    return hashlib.sha256(qwen_prompt(request).encode("utf-8")).hexdigest()


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_manifest(directory: Path, *, verify=False):
    directory = directory.resolve()
    manifest = json.loads((directory / "cinedub-manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or any(
        manifest.get(key) != value
        for key, value in {
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "model_sha256": MODEL_SHA256,
            "engine_tag": ENGINE_TAG,
            "engine_commit": ENGINE_COMMIT,
            "engine_archive_sha256": ENGINE_SHA256,
        }.items()
    ):
        raise ValueError("Dialogue model/runtime do not match the supported installation")
    model = directory / MODEL_FILE
    if not model.is_file() or model.stat().st_size != MODEL_SIZE:
        raise ValueError("Dialogue model installation is incomplete")
    if verify and digest(model) != MODEL_SHA256:
        raise ValueError("Dialogue model checksum changed; reinstall explicitly")
    runtime = directory / "runtime"
    if manifest.get("executable") != EXECUTABLE:
        raise ValueError("Dialogue completion executable does not match the pinned runtime")
    executable = runtime / EXECUTABLE
    if not executable.resolve().is_relative_to(runtime) or not os.access(executable, os.X_OK):
        raise ValueError("Dialogue runtime is unavailable")
    archive = directory / ENGINE_FILE
    if not archive.is_file() or archive.stat().st_size != ENGINE_SIZE:
        raise ValueError("Pinned runtime archive is unavailable")
    if verify and digest(archive) != ENGINE_SHA256:
        raise ValueError("Dialogue runtime archive checksum changed")
    if verify:
        verify_runtime(runtime, archive)
    return manifest


def verify_runtime(runtime, archive):
    """Compare executable/library bytes and symlinks with the checksum-pinned archive."""
    expected = set()
    with tarfile.open(archive, "r:gz") as package:
        for member in package.getmembers():
            if member.isdir():
                continue
            path = runtime / member.name
            if not path.resolve().is_relative_to(runtime.resolve()):
                raise ValueError("Runtime member escapes the installation")
            expected.add(member.name)
            if member.issym():
                if not path.is_symlink() or os.readlink(path) != member.linkname:
                    raise ValueError("Runtime library symlink changed")
            elif member.isfile():
                with package.extractfile(member) as handle:
                    wanted = hashlib.file_digest(handle, "sha256").hexdigest()
                if path.is_symlink() or not path.is_file() or digest(path) != wanted:
                    raise ValueError("Runtime executable/library bytes changed")
            else:
                raise ValueError("Unsupported native runtime member")
    actual = {
        path.relative_to(runtime).as_posix()
        for path in runtime.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != expected:
        raise ValueError("Unexpected or missing native runtime files")


def availability(directory: Path):
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        return False, "This optional local dialogue profile currently supports Linux x86_64 CPU"
    try:
        read_manifest(directory)
    except (OSError, ValueError, TypeError, KeyError):
        return False, "Run scripts/setup-local-dialogue.py for the optional CPU dialogue adapter"
    return True, "Experimental local 4B dialogue adaptation · human Malayalam review required"


class LocalDialogueAdapter:
    name = "local"

    def __init__(self, directory, threads=4, timeout_seconds=1800):
        self.directory = Path(directory).resolve()
        self.threads = threads
        self.timeout_seconds = timeout_seconds

    def adapt(self, request, output_dir, *, cancel, progress):
        read_manifest(self.directory, verify=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "adaptation-input.json"
        path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")

        def verify_serialized_prompts(lines):
            for result, line in zip(lines, request["lines"], strict=False):
                if result.get("prompt_sha256") != serialized_prompt_digest(line):
                    raise ValueError("Serialized local dialogue prompt provenance changed")

        def notify(completed, total):
            state = json.loads((output_dir / "adaptation-partial.json").read_text(encoding="utf-8"))
            if (
                state.get("input_sha256") != digest(path)
                or not completed <= len(state.get("lines", [])) <= total
                or total != len(request["lines"])
            ):
                raise ValueError("Local dialogue checkpoint provenance does not match this request")
            verify_serialized_prompts(state["lines"])
            progress(state["lines"])

        run_inference(
            "cinedub_api.local_dialogue_runner",
            [
                "--model-dir",
                str(self.directory),
                "--request",
                str(path.resolve()),
                "--output-dir",
                str(output_dir.resolve()),
                "--threads",
                str(self.threads),
            ],
            output_dir,
            threads=self.threads,
            timeout_seconds=self.timeout_seconds,
            cancel=cancel,
            progress=notify,
        )
        read_manifest(self.directory, verify=True)
        payload = json.loads((output_dir / "adaptation-result.json").read_text(encoding="utf-8"))
        verify_serialized_prompts(payload["lines"])
        return payload
