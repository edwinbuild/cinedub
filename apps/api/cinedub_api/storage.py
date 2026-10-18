"""Storage boundary for media and evidence files.

Every job writes under `<root>/<project>/<area>/<job>`; artifacts record a root-relative
`storage_key` so a restored or relocated workspace can resolve them again. The local
filesystem is the only backend today; an object store would implement the same methods.
"""

import os
import shutil
from pathlib import Path

from .config import get_settings


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def job_path(self, project_id: str, area: str, job_id: str, *parts: str) -> Path:
        """Where a job's files live; never creates anything (safe for provenance checks)."""
        path = self.root / project_id / area / job_id
        for part in parts:
            path = path / part
        path = path.resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("Storage path escapes the workspace")
        return path

    def job_dir(self, project_id: str, area: str, job_id: str, *parts: str) -> Path:
        path = self.job_path(project_id, area, job_id, *parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def upload_dir(self, project_id: str) -> Path:
        path = self.root / project_id / "source"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def contains(self, path: Path | str) -> bool:
        return Path(path).resolve().is_relative_to(self.root)

    def key_for(self, path: Path | str) -> str | None:
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.root):
            return None
        return resolved.relative_to(self.root).as_posix()

    def resolve(self, key: str) -> Path:
        if not key or key.startswith("/") or "\\" in key:
            raise ValueError("Invalid storage key")
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("Storage key escapes the workspace")
        return path

    def readable(self, path: Path | str) -> Path | None:
        """A file inside the workspace, or None. Guards every download and evidence read."""
        resolved = Path(path).resolve()
        return resolved if resolved.is_relative_to(self.root) and resolved.is_file() else None

    def usage(self, project_id: str | None = None) -> int:
        base = self.root / project_id if project_id else self.root
        if not base.is_dir():
            return 0
        return sum(
            (Path(folder) / name).stat().st_size
            for folder, _, names in os.walk(base)
            for name in names
            if not (Path(folder) / name).is_symlink()
        )

    def delete_project(self, project_id: str) -> None:
        if not project_id or "/" in project_id or project_id in {".", ".."}:
            raise ValueError("Invalid project identifier")
        path = (self.root / project_id).resolve()
        if path.parent != self.root:
            raise ValueError("Project storage escapes the workspace")
        if path.is_dir():
            shutil.rmtree(path)


def storage(root: Path | None = None) -> LocalStorage:
    return LocalStorage(root or get_settings().storage_root)
