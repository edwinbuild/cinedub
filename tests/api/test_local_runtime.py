import fcntl
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from cinedub_api.config import Settings, get_settings
from cinedub_api.local_runtime import configuration, free_port, preflight, unlocked, web_environment
from test_timeline import synthetic_wav


def available_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def wait_for(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Expected runtime state did not arrive before the deadline")


def running(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def test_preflight_does_not_initialize_database_or_change_configuration(tmp_path, monkeypatch):
    database, storage = tmp_path / "new/source.db", tmp_path / "new/media"
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///" + str(database),
        storage_root=storage,
        api_port=available_port(),
        SARVAM_API_KEY="synthetic-private-key",
    )
    monkeypatch.setattr("cinedub_api.local_runtime.Settings", lambda: settings)
    monkeypatch.setenv("PORT", str(available_port()))
    monkeypatch.delenv("CINEDUB_WEB_ORIGIN", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_CINEDUB_API_URL", raising=False)
    cache = get_settings.cache_info()
    _, api, web, warnings = preflight()
    assert api.startswith("http://127.0.0.1:") and web.startswith("http://127.0.0.1:")
    assert "synthetic-private-key" not in repr(warnings)
    assert not database.parent.exists()
    assert get_settings.cache_info() == cache
    database.parent.mkdir()
    with database.with_name(database.name + ".workspace.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        with pytest.raises(RuntimeError, match="Workspace is in use"):
            preflight()  # Even an API without its worker must prevent a second launcher.


@pytest.mark.parametrize("value", ["bad-secret-value", "0", "65536"])
def test_invalid_port_does_not_echo_input(monkeypatch, value):
    monkeypatch.setenv("PORT", value)
    with pytest.raises(RuntimeError) as failure:
        configuration()
    assert value not in str(failure.value)


def test_busy_ports_and_worker_locks_are_refused(tmp_path):
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        with pytest.raises(RuntimeError, match="port"):
            free_port(connection.getsockname()[1])
    lock_path = tmp_path / "worker.lock"
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(RuntimeError, match="Workspace is in use"):
            unlocked(lock_path, True)


def test_web_child_does_not_inherit_provider_keys_or_unrelated_secrets(monkeypatch):
    for name in ("SARVAM_API_KEY", "CINEDUB_SARVAM_API_KEY", "OTHER_PRIVATE_TOKEN"):
        monkeypatch.setenv(name, "synthetic-private-key")
    environment = web_environment("http://127.0.0.1:8001")
    assert environment["NEXT_PUBLIC_CINEDUB_API_URL"] == "http://127.0.0.1:8001"
    assert "synthetic-private-key" not in repr(environment)


@pytest.mark.parametrize("failure", [False, True])
def test_supervisor_stops_owned_native_sessions_not_unrelated_processes(tmp_path, failure):
    marker = tmp_path / "native-pid"
    native = (
        "from pathlib import Path; import os,time; "
        f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{native!r}], start_new_session=True); "
        + ("time.sleep(1); sys.exit(3)" if failure else "time.sleep(60)")
    )
    supervisor = (
        "import os,sys; from cinedub_api.local_runtime import supervise; "
        f"supervise([('test-worker', [sys.executable,'-c',{parent!r}], os.environ.copy())])"
    )
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    with (tmp_path / "supervisor.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", supervisor],
            env={**os.environ, "PYTHONPATH": "apps/api"},
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            wait_for(marker.exists)
            native_pid = int(marker.read_text())
            if not failure:
                process.send_signal(signal.SIGINT)
            assert process.wait(timeout=15) == (1 if failure else 0)
            wait_for(lambda: not running(native_pid))
            assert unrelated.poll() is None
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            unrelated.terminate()
            unrelated.wait(timeout=5)


def test_actual_launcher_ready_upload_shutdown_and_clean_restart(tmp_path):
    api_port, web_port = available_port(), available_port()
    environment = {
        **os.environ,
        "PYTHONPATH": "apps/api",
        "PORT": str(web_port),
        "CINEDUB_API_HOST": "127.0.0.1",
        "CINEDUB_API_PORT": str(api_port),
        "CINEDUB_WEB_ORIGIN": f"http://127.0.0.1:{web_port}",
        "NEXT_PUBLIC_CINEDUB_API_URL": f"http://127.0.0.1:{api_port}",
        "CINEDUB_DATABASE_URL": "sqlite:///" + str(tmp_path / "workspace.db"),
        "CINEDUB_STORAGE_ROOT": str(tmp_path / "storage"),
        "CINEDUB_TRANSCRIBER": "fake",
        "CINEDUB_TRANSLATOR": "fake",
        "CINEDUB_VOICE_SYNTHESIZER": "fake",
        "SARVAM_API_KEY": "",
        "CINEDUB_SARVAM_API_KEY": "",
    }
    check = subprocess.run(
        [sys.executable, "scripts/local-runtime.py", "check"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert '"ready_to_launch": true' in check.stdout
    assert not (tmp_path / "workspace.db").exists()
    for attempt in range(2):
        with (tmp_path / f"launch-{attempt}.log").open("w+") as log:
            process = subprocess.Popen(
                [sys.executable, "scripts/local-runtime.py", "start"],
                env=environment,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            try:

                def ready(process=process, log_path=Path(log.name)):
                    assert process.poll() is None, log_path.read_text()
                    return "CineDub local workspace ready" in log_path.read_text()

                wait_for(ready, 60)
                with httpx.Client(base_url=f"http://127.0.0.1:{api_port}", timeout=10) as client:
                    assert client.get("/health").json()["local_only"]
                    if attempt == 0:
                        response = client.post("/projects", json={"name": "Launcher rehearsal"})
                        assert response.status_code == 201
                        identifier = response.json()["id"]
                        response = client.post(
                            f"/projects/{identifier}/assets",
                            files={"file": ("scene.wav", synthetic_wav(), "audio/wav")},
                        )
                        assert response.status_code == 201
                        wait_for(
                            lambda identifier=identifier: any(
                                job["stage"] == "ingest" and job["status"] == "completed"
                                for job in client.get(f"/projects/{identifier}").json()["jobs"]
                            ),
                            20,
                        )
                    else:
                        assert (
                            client.get(f"/projects/{identifier}").json()["name"]
                            == "Launcher rehearsal"
                        )
                process.send_signal(signal.SIGINT)
                assert process.wait(timeout=15) == 0
                free_port(api_port)
                free_port(web_port)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
