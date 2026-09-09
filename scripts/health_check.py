"""Validate the local Python runtime and project-managed paths."""

from __future__ import annotations

import json
from importlib import metadata
import platform
import struct
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

from src.config import ENV_PATHS, PROJECT_PATHS, PROJECT_ROOT, is_within_project


def read_locked_requirements() -> list[tuple[str, str]]:
    requirements_path = SCRIPT_ROOT / "requirements.txt"
    locked: list[tuple[str, str]] = []
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        if not separator or not name.strip() or not version.strip():
            raise ValueError(f"requirements.txt 包含非标准 name==version 行：{raw_line}")
        locked.append((name.strip(), version.strip()))
    return locked


def build_report() -> tuple[dict[str, object], int]:
    errors: list[str] = []
    architecture_bits = struct.calcsize("P") * 8
    python_ok = sys.version_info[:3] == (3, 10, 11) and architecture_bits == 64
    if not python_ok:
        errors.append(
            f"Python 版本不符合要求：需要 Python 3.10.11 x64，当前为 "
            f"{platform.python_version()} {architecture_bits} 位。"
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

    requirements_checks: list[dict[str, object]] = []
    try:
        locked_requirements = read_locked_requirements()
    except (OSError, ValueError) as exc:
        errors.append(f"requirements.txt 无法按标准 name==version 读取：{exc}")
    else:
        for name, required_version in locked_requirements:
            try:
                installed_version = metadata.version(name)
                installed = installed_version == required_version
            except metadata.PackageNotFoundError:
                installed_version = None
                installed = False
            requirements_checks.append(
                {
                    "name": name,
                    "required_version": required_version,
                    "installed_version": installed_version,
                    "installed_exact": installed,
                }
            )
            if not installed:
                actual = installed_version or "not installed"
                errors.append(f"依赖版本不匹配：{name} 需要 {required_version}，当前为 {actual}。")

    report: dict[str, object] = {
        "status": "ok" if not errors else "error",
        "checks": {
            "python": {
                "required": "Python 3.10.11 x64",
                "version": platform.python_version(),
                "architecture_bits": architecture_bits,
                "executable": sys.executable,
                "ok": python_ok,
            },
            "project_root": {
                "path": str(PROJECT_ROOT.resolve()),
                "ok": root_ok,
            },
            "managed_paths": path_checks,
            "requirements": requirements_checks,
        },
        "verified_scope": [
            "Python 3.10.11 x64",
            "项目根目录识别",
            "项目管理路径位于项目根目录内",
            "requirements.txt 锁定发行版的精确安装版本",
        ],
        "not_verified": ["RAG", "模型", "外部服务", "生产环境"],
        "errors": errors,
    }
    return report, 0 if not errors else 1


def main() -> int:
    report, exit_code = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
