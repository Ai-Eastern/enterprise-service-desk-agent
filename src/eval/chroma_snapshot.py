"""Small stdlib helpers for isolated Chroma directory snapshots."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


def copy_snapshot(source: Path, destination: Path) -> Path:
    return Path(shutil.copytree(source, destination))


def file_manifest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        manifest[path.relative_to(root).as_posix()] = digest.hexdigest()
    return manifest
