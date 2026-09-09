"""Project-local paths and cache environment variables."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PROJECT_PATHS = {
    "tooling": PROJECT_ROOT / ".tooling",
    "venv": PROJECT_ROOT / ".venv",
    "cache": PROJECT_ROOT / ".cache",
    "temp": PROJECT_ROOT / ".tmp",
    "runtime": PROJECT_ROOT / "runtime",
    "artifacts": PROJECT_ROOT / "artifacts",
    "reports": PROJECT_ROOT / "reports",
    "outputs": PROJECT_ROOT / "outputs",
    "logs": PROJECT_ROOT / "logs",
    "data": PROJECT_ROOT / "data",
}

ENV_PATHS = {
    "HF_HOME": PROJECT_PATHS["cache"] / "huggingface",
    "HF_HUB_CACHE": PROJECT_PATHS["cache"] / "huggingface" / "hub",
    "TRANSFORMERS_CACHE": PROJECT_PATHS["cache"] / "huggingface" / "transformers",
    "SENTENCE_TRANSFORMERS_HOME": PROJECT_PATHS["cache"] / "sentence-transformers",
    "PIP_CACHE_DIR": PROJECT_PATHS["cache"] / "pip",
    "TEMP": PROJECT_PATHS["temp"],
    "TMP": PROJECT_PATHS["temp"],
}

# Import this module before any future Hugging Face or model-library import.
for _name, _path in ENV_PATHS.items():
    os.environ[_name] = str(_path)


def is_within_project(path: Path) -> bool:
    """Return whether *path* resolves inside the project root."""

    resolved = path.resolve()
    root = PROJECT_ROOT.resolve()
    return resolved == root or root in resolved.parents
