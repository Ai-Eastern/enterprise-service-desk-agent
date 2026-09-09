"""Run or resume the local LangGraph human-review workflow."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.workflow import CHECKPOINT_PATH, TICKETS_PATH, resume_workflow, start_workflow
from src.retrieval.chroma_store import CHROMA_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="运行智达科技虚构 LangGraph 工作流。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="启动工作流，可能在副作用前中断。")
    start.add_argument("--thread-id", required=True)
    start.add_argument("--user-id", required=True)
    start.add_argument("--query", required=True)
    start.add_argument("--product-id", required=True)
    start.add_argument("--idempotency-key", required=True)
    start.add_argument("--checkpoint-path", type=Path, default=CHECKPOINT_PATH)
    start.add_argument("--tickets-path", type=Path, default=TICKETS_PATH)
    start.add_argument("--chroma-path", type=Path, default=CHROMA_PATH)

    resume = subparsers.add_parser("resume", help="用相同 thread_id 恢复人工复核。")
    resume.add_argument("--thread-id", required=True)
    resume.add_argument("--decision", required=True, choices=("approve", "reject"))
    resume.add_argument("--checkpoint-path", type=Path, default=CHECKPOINT_PATH)

    args = parser.parse_args()
    try:
        if args.command == "start":
            result = start_workflow(
                thread_id=args.thread_id,
                user_id=args.user_id,
                query=args.query,
                product_id=args.product_id,
                idempotency_key=args.idempotency_key,
                checkpoint_path=args.checkpoint_path,
                tickets_path=args.tickets_path,
                chroma_path=args.chroma_path,
            )
        else:
            result = resume_workflow(
                thread_id=args.thread_id,
                approved=args.decision == "approve",
                checkpoint_path=args.checkpoint_path,
            )
    except Exception:
        print(json.dumps({"status": "error", "error": "工作流执行失败。"}, ensure_ascii=False), file=sys.stderr)
        return 1

    result["process_id"] = os.getpid()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
