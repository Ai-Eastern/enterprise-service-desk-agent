"""Run the frozen T2Retrieval subset evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import PROJECT_ROOT  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "运行评测套件：默认 T2Retrieval 60×3000 检索子集（仅 retrieval），"
            "结果为非官方完整成绩，不代表权限/工具评测或政企 RAG 质量。"
        )
    )
    parser.add_argument("--suite", choices=("t2", "project", "workflow"), default="t2")
    parser.add_argument("--top-k", type=int, choices=(5,), default=5)
    args = parser.parse_args()
    try:
        if args.suite == "project":
            from src.eval.project_eval import run_project_evaluation

            report = run_project_evaluation()
        elif args.suite == "workflow":
            from src.eval.workflow_eval import run_workflow_faults

            report = run_workflow_faults()
        else:
            from src.eval.retrieval_eval import run_evaluation

            report = run_evaluation(top_k=args.top_k)
    except Exception:
        print(json.dumps({"status": "error", "error": "评测运行失败。"}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report_exit_code(args.suite, report)


def report_exit_code(suite: str, report: dict[str, object]) -> int:
    if suite == "project":
        return 0 if report.get("normal_chroma_unchanged") is True else 1
    if suite == "workflow":
        cases = report.get("cases")
        statuses = cases.values() if isinstance(cases, dict) else ()
        return 0 if report.get("normal_chroma_unchanged") is True and all(
            isinstance(case, dict) and case.get("status") == "PASS" for case in statuses
        ) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
