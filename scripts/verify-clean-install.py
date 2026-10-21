"""Rehearse a committed Linux base install without copying local state or secrets."""

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DRIVER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
FORBIDDEN = {"OLD", ".git", ".agents", ".aws", ".codex", ".venv", "node_modules", "data", "models"}
BASE_TESTS = [
    "tests/api/test_clean_install.py",
    "tests/api/test_asr_profile.py",
    "tests/api/test_local_asr.py",
    "tests/api/test_asr_evaluation.py",
    "tests/api/test_emotion_benchmark.py",
    "tests/api/test_emotion_candidate.py",
    "tests/api/test_batch_editing.py",
    "tests/api/test_group_history.py",
    "tests/api/test_segment_history.py",
    "tests/api/test_storage_capacity.py",
]
BASE_BROWSER_TESTS = ["tests/e2e/grouped-edits.spec.ts", "tests/e2e/group-history.spec.ts"]


def passed_test_summary(log):
    match = re.search(r"(\d+) passed([^\n]*)", log)
    if (
        not match
        or int(match[1]) < 1
        or any(word in match[2] for word in ("skipped", "xfailed", "xpassed", "deselected"))
    ):
        raise ValueError("Base regression receipt requires passing tests without exclusions")
    return {"passed": int(match[1]), "summary": match[0].strip()}


def validate_members(members):
    for entry in members:
        path = PurePosixPath(entry.name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Archive paths must stay within the checkout")
        if any(part in FORBIDDEN for part in path.parts) or any(
            part == ".env" or (part.startswith(".env.") and part != ".env.example")
            for part in path.parts
        ):
            raise ValueError("Committed snapshot contains private or runtime state")
        if not (entry.isfile() or entry.isdir()):
            raise ValueError("Snapshot must contain only regular files/directories")


def base_environment():
    return {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "PATH",
            "HOME",
            "USER",
            "TMPDIR",
            "LANG",
            "LC_ALL",
            "SYSTEMROOT",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        }
    }


def stop_group(process):
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def run(command, checkout, environment, logs, name, *, timeout=600):
    print(f"Checking {name}", flush=True)
    with (logs / f"{name}.log").open("w") as log:
        process = subprocess.Popen(
            command, cwd=checkout, env=environment, stdout=log, stderr=log, start_new_session=True
        )
        try:
            if process.wait(timeout=timeout) != 0:
                raise RuntimeError(f"{name} failed; inspect its private log")
        finally:
            stop_group(process)


def available_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def execute(ref, *, base_regressions=False):
    if sys.platform != "linux" or sys.version_info < (3, 12):
        raise RuntimeError("Requires Linux and Python 3.12+")
    for executable in ("git", "uv", "npm", "node", "ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise RuntimeError(f"Required host tool missing: {executable}")
    if shutil.disk_usage(tempfile.gettempdir()).free < 2 * 1024**3:
        raise RuntimeError("At least 2 GiB temporary disk space is required")
    environment = base_environment()
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"],
        cwd=ROOT,
        env=environment,
        text=True,
    ).strip()
    tracked = subprocess.check_output(
        ["git", "ls-tree", "-r", "-z", "--name-only", commit], cwd=ROOT, env=environment
    )
    validate_members(
        [tarfile.TarInfo(name.decode("utf-8")) for name in tracked.split(b"\0") if name]
    )
    directory = Path(tempfile.mkdtemp(prefix="cinedub-clean-install-"))
    print(f"Private rehearsal: {directory}\nApplication commit: {commit}", flush=True)
    checkout, logs = directory / "checkout", directory / "logs"
    checkout.mkdir(mode=0o700)
    logs.mkdir(mode=0o700)
    archive = directory / "source.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "--output", str(archive), commit],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    with tarfile.open(archive) as source:
        validate_members(source.getmembers())
        source.extractall(checkout, filter="data")
    lock_hashes = {
        name: hashlib.sha256((checkout / name).read_bytes()).hexdigest()
        for name in ("uv.lock", "package-lock.json")
    }
    install_env = {**environment, "UV_CACHE_DIR": "/tmp/cinedub-uv-cache"}
    run(
        ["uv", "sync", "--frozen", "--no-dev", "--python", str(Path(sys.executable).resolve())],
        checkout,
        install_env,
        logs,
        "python-base-install",
    )
    run(["npm", "ci", "--no-audit", "--no-fund"], checkout, environment, logs, "node-install")
    python = str(checkout / ".venv/bin/python")
    probe = (
        "import importlib.util,json; "
        "names=['numpy','onnxruntime','faster_whisper','torch','huggingface_hub']; "
        "found={name:importlib.util.find_spec(name) is not None for name in names}; "
        "assert not any(found.values()), found; print(json.dumps(found))"
    )
    result = subprocess.check_output(
        [python, "-c", probe], cwd=checkout, env=environment, text=True
    )
    optional_packages = json.loads(result)
    run(["npm", "run", "build:web"], checkout, environment, logs, "production-build")
    api_port, web_port = available_port(), available_port()
    while web_port == api_port:
        web_port = available_port()
    api, web = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
    app_env = {
        **environment,
        "PYTHONPATH": str(checkout / "apps/api"),
        "PORT": str(web_port),
        "CINEDUB_ENV": "clean-install-rehearsal",
        "CINEDUB_API_HOST": "127.0.0.1",
        "CINEDUB_API_PORT": str(api_port),
        "CINEDUB_WEB_ORIGIN": web,
        "NEXT_PUBLIC_CINEDUB_API_URL": api,
        "CINEDUB_DATABASE_URL": "sqlite:///" + str(directory / "workspace.db"),
        "CINEDUB_STORAGE_ROOT": str(directory / "storage"),
        "CINEDUB_TRANSCRIBER": "fake",
        "CINEDUB_TRANSLATOR": "fake",
        "CINEDUB_VOICE_SYNTHESIZER": "fake",
        "SARVAM_API_KEY": "",
        "CINEDUB_SARVAM_API_KEY": "",
    }
    run([python, "scripts/local-runtime.py", "check"], checkout, app_env, logs, "doctor")
    launcher = None
    try:
        with (logs / "runtime.log").open("w") as log:
            launcher = subprocess.Popen(
                [python, "scripts/local-runtime.py", "start"],
                cwd=checkout,
                env=app_env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            deadline = time.monotonic() + 60
            while "CineDub local workspace ready" not in (logs / "runtime.log").read_text():
                if launcher.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(
                        "Clean application did not become ready; inspect runtime.log"
                    )
                time.sleep(0.1)
            smoke_driver = (ROOT / "scripts/clean-install-smoke.mjs").read_text()
            run(
                ["node", "--input-type=module", "--eval", smoke_driver],
                checkout,
                {**environment, "CINEDUB_SMOKE_WEB": web, "CINEDUB_SMOKE_API": api},
                logs,
                "browser-smoke",
                timeout=180,
            )
    finally:
        if launcher and launcher.poll() is None:
            launcher.send_signal(signal.SIGINT)
            if launcher.wait(timeout=20) != 0:
                raise RuntimeError("Supervisor did not stop cleanly")
    # Verify the supervisor released both HTTP listeners after the smoke flow.
    for port in (api_port, web_port):
        with socket.socket() as connection:
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            connection.bind(("127.0.0.1", port))
    smoke = json.loads((logs / "browser-smoke.log").read_text().strip().splitlines()[-1])
    regressions = None
    if base_regressions:
        run(
            ["uv", "sync", "--frozen", "--group", "dev"],
            checkout,
            install_env,
            logs,
            "base-dev-install",
        )
        result = subprocess.check_output(
            [python, "-c", probe], cwd=checkout, env=environment, text=True
        )
        regression_optional = json.loads(result)
        run(
            [python, "-m", "pytest", "-q", *BASE_TESTS],
            checkout,
            environment,
            logs,
            "base-regression-tests",
        )
        summary = passed_test_summary((logs / "base-regression-tests.log").read_text())
        regression_env = {
            **environment,
            "CINEDUB_E2E_LAUNCHER": "1",
            "CINEDUB_E2E_TRANSCRIBER": "fake",
            "CINEDUB_E2E_BROWSER": "chrome",
        }
        run(
            ["npm", "run", "test:e2e", "--", *BASE_BROWSER_TESTS],
            checkout,
            regression_env,
            logs,
            "base-browser-regressions",
            timeout=180,
        )
        browser_summary = passed_test_summary((logs / "base-browser-regressions.log").read_text())
        for port in (8011, 3011):
            with socket.socket() as connection:
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                connection.bind(("127.0.0.1", port))
        subprocess.run(
            [python, "-c", probe],
            cwd=checkout,
            env=environment,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        if (checkout / "models").exists():
            raise RuntimeError("Base regression tests must not install model weights")
        regressions = {
            "backend": summary,
            "backend_test_files": BASE_TESTS,
            "browser": browser_summary,
            "browser_test_files": BASE_BROWSER_TESTS,
            "optional_packages": regression_optional,
            "owned_services_stopped": True,
        }
    if lock_hashes != {
        name: hashlib.sha256((checkout / name).read_bytes()).hexdigest() for name in lock_hashes
    }:
        raise RuntimeError("Committed dependency locks changed during installation")
    versions = {
        name: subprocess.check_output(command, cwd=checkout, env=environment, text=True).strip()
        for name, command in {
            "python": [python, "--version"],
            "node": ["node", "--version"],
            "npm": ["npm", "--version"],
            "uv": ["uv", "--version"],
        }.items()
    }
    receipt = {
        "format_version": 1,
        "application_commit": commit,
        "driver_sha256": DRIVER_SHA256,
        "browser_driver_sha256": hashlib.sha256(smoke_driver.encode()).hexdigest(),
        "lock_sha256": lock_hashes,
        "tool_versions": versions,
        "optional_packages": optional_packages,
        "production_build": True,
        "doctor": True,
        "browser": smoke,
        "owned_services_stopped": True,
        "base_regressions": regressions,
        "scope": "Fresh venv/node_modules using existing Linux host tools and package caches; "
        "not a pristine OS or live-provider test",
    }
    (directory / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": True,
                "receipt": str(directory / "receipt.json"),
                "application_commit": commit,
            },
            indent=2,
        )
    )
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref", default="HEAD", help="Committed application revision; excludes uncommitted work"
    )
    parser.add_argument(
        "--base-regressions",
        action="store_true",
        help="Also test model-free editor/ASR contracts with the dev group, no extras",
    )
    arguments = parser.parse_args()
    try:
        execute(arguments.ref, base_regressions=arguments.base_regressions)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print(
            "Clean-install rehearsal failed; inspect its printed private directory. "
            "No local application state was copied.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
