"""Ingest the generated knowledge documents into persistent Chroma."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import PROJECT_PATHS
from src.retrieval.chroma_store import CHROMA_PATH, ingest


def main() -> int:
    parser = argparse.ArgumentParser(description="将虚构知识文档写入持久化 Chroma。")
    parser.add_argument("--knowledge-dir", type=Path, default=PROJECT_PATHS["data"] / "knowledge")
    parser.add_argument("--chroma-path", type=Path, default=CHROMA_PATH)
    args = parser.parse_args()
    try:
        report = ingest(args.knowledge_dir, args.chroma_path)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
