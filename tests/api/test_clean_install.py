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
