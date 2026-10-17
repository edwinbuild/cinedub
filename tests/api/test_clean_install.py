import importlib.util
import tarfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "clean_install_driver", Path(__file__).resolve().parents[2] / "scripts/verify-clean-install.py"
)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def test_snapshot_accepts_code_and_public_configuration_only():
    driver.validate_members(
        [
            tarfile.TarInfo(name)
            for name in (
                "apps/api/cinedub_api/main.py",
                ".env.example",
                "package-lock.json",
                "uv.lock",
            )
        ]
    )


@pytest.mark.parametrize(
    "name",
    [
        "OLD/app.py",
        ".env",
        "apps/web/.env.local",
        ".git/config",
        "models/weights.bin",
        "data/actor.wav",
        "node_modules/package.json",
        "apps/web/node_modules/package.json",
        "apps/api/.venv/bin/python",
        "packages/ai/models/voice.bin",
        "apps/web/.aws/credentials",
        ".aws/credentials",
        "../escape",
        "/tmp/escape",
    ],
)
def test_snapshot_refuses_private_runtime_and_escaping_paths(name):
    with pytest.raises(ValueError):
        driver.validate_members([tarfile.TarInfo(name)])


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_snapshot_refuses_nonregular_entries(kind):
    entry = tarfile.TarInfo("apps/escape")
    entry.type = kind
    entry.linkname = "../../outside"
    with pytest.raises(ValueError):
        driver.validate_members([entry])


def test_rehearsal_environment_does_not_inherit_provider_keys_or_runtime_overrides(monkeypatch):
    for name in (
        "SARVAM_API_KEY",
        "CINEDUB_SARVAM_API_KEY",
        "CINEDUB_DATABASE_URL",
        "NODE_OPTIONS",
    ):
        monkeypatch.setenv(name, "synthetic-private-value")
    environment = driver.base_environment()
    assert "synthetic-private-value" not in repr(environment)


@pytest.mark.parametrize("log,count", [("130 passed in 4.2s\n", 130), ("  2 passed (23.9s)\n", 2)])
def test_regression_summary_records_actual_passing_count(log, count):
    assert driver.passed_test_summary(log)["passed"] == count


@pytest.mark.parametrize(
    "log",
    [
        "",
        "1 failed",
        "0 passed",
        "2 passed, 1 skipped",
        "2 passed, 1 xfailed",
        "2 passed, 1 xpassed",
        "2 passed, 1 deselected",
    ],
)
def test_regression_summary_refuses_empty_or_partial_acceptance(log):
    with pytest.raises(ValueError):
        driver.passed_test_summary(log)
