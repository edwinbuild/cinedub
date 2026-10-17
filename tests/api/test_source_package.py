import gzip
import io
import json
import runpy
import tarfile
from pathlib import Path

import pytest

driver = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/package-source.py"))


def snapshot(extra=None):
    contents = {
        "package.json": json.dumps({"version": "0.2.0"}).encode(),
        "package-lock.json": b"locked-node",
        "uv.lock": b"locked-python",
        "README.md": b"Install instructions",
        ".env.example": b"SARVAM_API_KEY=",
        **(extra or {}),
    }
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, data in contents.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return output.getvalue()


def test_source_metadata_binds_committed_locks():
    metadata = driver["inspect_snapshot"](snapshot())
    assert metadata["application_version"] == "0.2.0"
    assert metadata["lock_sha256"]["uv.lock"] == driver["sha256"](b"locked-python")


@pytest.mark.parametrize("name", ["OLD/code.py", ".env", "data/actor.wav", "models/weights.bin"])
def test_source_package_refuses_private_runtime_paths(name):
    with pytest.raises(ValueError):
        driver["inspect_snapshot"](snapshot({name: b"synthetic"}))


def stub_git(monkeypatch):
    def check_output(command, **kwargs):
        return "a" * 40 if command[1] == "rev-parse" else snapshot()

    monkeypatch.setattr(driver["subprocess"], "check_output", check_output)


def test_existing_output_is_never_overwritten(tmp_path, monkeypatch):
    stub_git(monkeypatch)
    marker = tmp_path / "keep"
    marker.write_bytes(b"untouched")
    with pytest.raises(FileExistsError):
        driver["package"]("HEAD", tmp_path)
    assert marker.read_bytes() == b"untouched"
    assert list(tmp_path.iterdir()) == [marker]


def test_repeat_packaging_has_identical_bytes_and_checksums(tmp_path, monkeypatch):
    stub_git(monkeypatch)
    first = tmp_path / "first"
    second = tmp_path / "second"
    one = driver["package"]("HEAD", first)
    two = driver["package"]("HEAD", second)
    assert one == two
    assert gzip.decompress((first / one["archive"]).read_bytes()) == snapshot()
    for file in first.iterdir():
        assert file.read_bytes() == (second / file.name).read_bytes()
    for line in (first / "SHA256SUMS").read_text().splitlines():
        checksum, name = line.split("  ")
        assert driver["sha256"]((first / name).read_bytes()) == checksum


def test_invalid_snapshot_does_not_create_output(tmp_path, monkeypatch):
    monkeypatch.setattr(
        driver["subprocess"],
        "check_output",
        lambda command, **kwargs: (
            "a" * 40 if command[1] == "rev-parse" else snapshot({".env": b"x"})
        ),
    )
    output = tmp_path / "rejected"
    with pytest.raises(ValueError):
        driver["package"]("HEAD", output)
    assert not output.exists()
