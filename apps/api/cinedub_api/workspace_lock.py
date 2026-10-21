"""Cooperative process leases prevent offline snapshots racing API/media writes."""

import fcntl
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_lease_descriptors: ContextVar[tuple[int, ...]] = ContextVar("workspace_leases", default=())


@contextmanager
def inherit_lease(*descriptors):
    token = _lease_descriptors.set((*_lease_descriptors.get(), *descriptors))
    try:
        yield
    finally:
        _lease_descriptors.reset(token)


def child_process_options():
    descriptors = _lease_descriptors.get()
    if not descriptors and os.environ.get("CINEDUB_LEASE_FDS"):
        descriptors = tuple(int(value) for value in os.environ["CINEDUB_LEASE_FDS"].split(","))
    for descriptor in descriptors:
        os.fstat(descriptor)
    return {"pass_fds": descriptors} if descriptors else {}


def child_lease_environment():
    descriptors = child_process_options().get("pass_fds", ())
    return {"CINEDUB_LEASE_FDS": ",".join(map(str, descriptors))} if descriptors else {}


def lease_path(database_url: str, storage_root: Path) -> Path:
    if database_url.startswith("sqlite:///"):
        database = Path(database_url.removeprefix("sqlite:///")).resolve()
        return database.with_name(f"{database.name}.workspace.lock")
    return storage_root.resolve() / ".workspace.lock"


@contextmanager
def workspace_lease(database_url: str, storage_root: Path, *, exclusive=False):
    path = lease_path(database_url, storage_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as handle:
        try:
            fcntl.flock(handle, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "Workspace is in use; stop the API and worker before backup or restore"
            ) from exc
        with inherit_lease(handle.fileno()):
            yield
