import fcntl
import os
import subprocess
import sys

from cinedub_api.worker import worker_lock_path


def test_second_worker_refuses_database_before_migrating():
    path = worker_lock_path()
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            [sys.executable, "-c", "from cinedub_api.worker import run_worker; run_worker()"],
            env={**os.environ, "PYTHONPATH": "apps/api"},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0
        assert "worker is already running for this database" in result.stderr
