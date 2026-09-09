"""Validate the local Python runtime and project-managed paths."""

from __future__ import annotations

import json
import platform
import struct
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

from src.config import ENV_PATHS, PROJECT_PATHS, PROJECT_ROOT, is_within_project


def build_report() -> tuple[dict[str, object], int]:
    errors: list[str] = []
    python_ok = sys.version_info[:2] == (3, 11) and struct.calcsize("P") * 8 == 64
    if not python_ok:
        errors.append(
            f"Python 版本不符合要求：需要 Python 3.11 x64，当前为 "
            f"{platform.python_version()} {struct.calcsize('P') * 8} 位。"
        )

    root_ok = PROJECT_ROOT.resolve() == SCRIPT_ROOT.resolve()
    if not root_ok:
        errors.append(f"项目根目录不一致：配置为 {PROJECT_ROOT}，脚本识别为 {SCRIPT_ROOT}。")

    managed_paths = {
        **PROJECT_PATHS,
        **{f"env:{name}": path for name, path in ENV_PATHS.items()},
    }
    path_checks = [
        {
            "name": name,
            "path": str(path.resolve()),
            "within_project_root": is_within_project(path),
        }
        for name, path in managed_paths.items()
    ]
    outside = [item for item in path_checks if not item["within_project_root"]]
    if outside:
        errors.append("发现项目根目录之外的管理路径：" + ", ".join(item["name"] for item in outside))

    report: dict[str, object] = {
        "status": "ok" if not errors else "error",
        "checks": {
            "python": {
                "required": "Python 3.11 x64",
                "version": platform.python_version(),
                "architecture_bits": struct.calcsize("P") * 8,
                "executable": sys.executable,
                "ok": python_ok,
            },
            "project_root": {
                "path": str(PROJECT_ROOT.resolve()),
                "ok": root_ok,
            },
            "managed_paths": path_checks,
        },
        "verified_scope": [
            "Python 3.11 x64",
            "项目根目录识别",
            "项目管理路径位于项目根目录内",
        ],
        "not_verified": ["RAG", "LangGraph", "MCP", "模型或外部服务"],
        "errors": errors,
    }
    return report, 0 if not errors else 1


def main() -> int:
    report, exit_code = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
