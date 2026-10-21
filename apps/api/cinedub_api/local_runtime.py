"""Linux local launcher: side-effect-free preflight and owned-process supervision."""

import ctypes
import fcntl
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from pydantic import ValidationError

from .config import Settings

ROOT = Path(__file__).resolve().parents[3]


def configuration():
    try:
        settings = Settings()
        port = int(os.environ.get("PORT", "3000"))
        if not 1 <= port <= 65535 or not 1 <= settings.api_port <= 65535:
            raise ValueError
    except (ValidationError, ValueError):
        raise RuntimeError(
            "Invalid local configuration; check .env and numeric PORT/API_PORT"
        ) from None
    if settings.api_host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError(
            "Local launcher requires API_HOST=127.0.0.1 or localhost; no public auth"
        )
    api = f"http://127.0.0.1:{settings.api_port}"
    web = f"http://127.0.0.1:{port}"
    if os.environ.get("CINEDUB_WEB_ORIGIN", web) != web:
        raise RuntimeError("CINEDUB_WEB_ORIGIN must match the selected local web port")
    if os.environ.get("NEXT_PUBLIC_CINEDUB_API_URL", api) != api:
        raise RuntimeError("NEXT_PUBLIC_CINEDUB_API_URL must match the selected local API port")
    return settings, port, api, web


def free_port(port):
    with socket.socket() as connection:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            connection.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(
                f"Local port {port} is unavailable; stop its owner or choose another"
            ) from None


def unlocked(path, exclusive):
    if not path.exists():
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                "Workspace is in use by a worker or offline backup; stop it first"
            ) from None


def preflight():
    if sys.platform != "linux" or sys.version_info < (3, 12):
        raise RuntimeError("The supported local launcher requires Linux and Python 3.12+")
    settings, port, api, web = configuration()
    for executable in ("node", "ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise RuntimeError(f"Required executable missing: {executable}")
    try:
        version = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, check=True, timeout=5
        ).stdout.strip()
        if int(version.removeprefix("v").split(".")[0]) < 22:
            raise ValueError
    except (ValueError, subprocess.SubprocessError):
        raise RuntimeError("Node.js 22+ is required") from None
    for path in (ROOT / "node_modules/next/dist/bin/next", ROOT / ".venv/bin/uvicorn"):
        if not path.is_file():
            raise RuntimeError("Dependencies missing; run uv sync --group dev and npm ci")
    if port == settings.api_port:
        raise RuntimeError("Web and API ports must be different")
    free_port(port)
    free_port(settings.api_port)
    if settings.database_url.startswith("sqlite:///"):
        database = Path(settings.database_url.removeprefix("sqlite:///")).resolve()
        unlocked(database.with_name(database.name + ".workspace.lock"), True)
        unlocked(database.with_name(database.name + ".worker.lock"), True)
    else:
        raise RuntimeError("Local launcher currently supports SQLite workspaces only")
    warnings = []
    if not settings.sarvam_api_key and "sarvam" in {
        settings.transcriber,
        settings.translator,
        settings.voice_synthesizer,
    }:
        warnings.append("Sarvam routes are disabled until a server-side key is configured")
    warnings.append("This check does not load/download models; inspect app capabilities before use")
    return settings, api, web, warnings


def descendants():
    """Find only this supervisor's descendants, including adopted native sessions."""
    parents = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            tail = path.read_text().rsplit(")", 1)[1].split()
            if tail[0] != "Z":
                parents[int(path.parent.name)] = int(tail[1])
        except (OSError, ValueError, IndexError):
            continue
    owned, frontier = set(), {os.getpid()}
    while frontier:
        children = {pid for pid, parent in parents.items() if parent in frontier} - owned
        owned.update(children)
        frontier = children
    return owned


def terminate_owned(processes, grace=5):
    deadline = time.monotonic() + grace
    signaled = set()
    while True:
        owned = descendants()
        if not owned:
            break
        for pid in owned:
            if pid in signaled and time.monotonic() < deadline:
                continue
            try:
                os.kill(pid, signal.SIGTERM if time.monotonic() < deadline else signal.SIGKILL)
                signaled.add(pid)
            except ProcessLookupError:
                pass
        for process in processes:
            process.poll()
        if time.monotonic() > deadline + 2:
            raise RuntimeError("Owned subprocesses did not exit; inspect them before restarting")
        time.sleep(0.05)
    for process in processes:
        process.wait(timeout=1)
    # Reap adopted model/media descendants after their original parents have exited.
    while True:
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0:
                break
        except ChildProcessError:
            break


def supervise(services, *, ready=None, startup_timeout=45, initialize=None):
    # Native inference starts separate sessions. Adoption lets shutdown find those
    # processes even if their worker died before cleanup; no global process matching.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError("Unable to enable Linux child-process supervision")
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    processes = []
    try:
        if initialize:
            command, environment = initialize
            process = subprocess.Popen(command, env=environment, start_new_session=True)
            processes.append(process)
            while process.poll() is None and not stopped:
                time.sleep(0.05)
            if stopped:
                return 0
            if process.returncode != 0:
                raise RuntimeError("Workspace initialization failed; no services were started")
            processes.clear()
        for name, command, environment in services:
            if stopped:
                return 0
            processes.append(subprocess.Popen(command, env=environment, start_new_session=True))
            print(f"Started {name}", flush=True)
        deadline = time.monotonic() + startup_timeout
        announced = False
        while not stopped:
            for (name, _, _), process in zip(services, processes, strict=True):
                if process.poll() is not None:
                    raise RuntimeError(f"{name} exited; the remaining local services will stop")
            if not announced:
                if ready is None or ready():
                    print("CineDub local workspace ready", flush=True)
                    announced = True
                elif time.monotonic() >= deadline:
                    raise RuntimeError("Local services did not become ready before the deadline")
            time.sleep(0.1)
        return 0
    finally:
        try:
            terminate_owned(processes)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def reachable(url):
    try:
        with urlopen(url, timeout=0.5) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def web_environment(api):
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "TERM", "FORCE_COLOR"}
    }
    environment["NEXT_PUBLIC_CINEDUB_API_URL"] = api
    return environment


def main():
    os.chdir(ROOT)
    try:
        settings, api, web, warnings = preflight()
        if sys.argv[1:] == ["check"]:
            print(
                json.dumps(
                    {"ready_to_launch": True, "api": api, "web": web, "warnings": warnings},
                    indent=2,
                )
            )
            return 0
        if sys.argv[1:] not in ([], ["start"]):
            raise RuntimeError("Usage: local-runtime.py [check|start]")
        for warning in warnings:
            print(f"Warning: {warning}", flush=True)
        server_env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "apps/api"),
            "CINEDUB_API_HOST": "127.0.0.1",
            "CINEDUB_WEB_ORIGIN": web,
        }
        # Next.js must not inherit provider credentials from the launcher's shell.
        web_env = web_environment(api)
        python = str(ROOT / ".venv/bin/python")
        services = [
            (
                "API",
                [
                    python,
                    "-m",
                    "uvicorn",
                    "cinedub_api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(settings.api_port),
                ],
                server_env,
            ),
            ("worker", [python, "apps/worker/main.py"], server_env),
            (
                "web",
                [
                    "node",
                    str(ROOT / "node_modules/next/dist/bin/next"),
                    "dev",
                    "apps/web",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    web.rsplit(":", 1)[1],
                ],
                web_env,
            ),
        ]
        print(
            f"Workspace: {web}\nAPI docs: {api}/docs\n"
            "Ctrl+C stops owned services and media children.",
            flush=True,
        )
        # Upgrade once before competing API/worker startups can touch a new schema.
        return supervise(
            services,
            ready=lambda: reachable(api + "/health") and reachable(web),
            initialize=(
                [
                    python,
                    "-c",
                    "from cinedub_api.database import create_database; create_database()",
                ],
                server_env,
            ),
        )
    except RuntimeError as exc:
        # These messages are authored above, never raw validation inputs/environment.
        print(f"Local launch refused: {exc}", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError):
        print("Local launch failed; check dependencies and service logs.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
