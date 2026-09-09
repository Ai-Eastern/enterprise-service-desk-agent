"""Validate the local Python runtime and project-managed paths."""

from __future__ import annotations

import json
from importlib import metadata
import platform
import re
import site
import struct
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

from src.config import ENV_PATHS, PROJECT_PATHS, PROJECT_ROOT, is_within_project


def normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def read_locked_requirements() -> list[tuple[str, str]]:
    requirements_path = SCRIPT_ROOT / "requirements.txt"
    locked: list[tuple[str, str]] = []
    seen: set[str] = set()
    pending = ""
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        pending = f"{pending} {line}".strip() if pending else line
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        requirement = re.sub(r"\s+--hash=\S+", "", pending)
        match = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s]+)", requirement
        )
        if not match:
            raise ValueError(f"requirements.txt 包含非标准 name==version 行：{pending}")
        name, version = match.groups()
        normalized_name = normalize_distribution_name(name)
        if normalized_name in seen:
            raise ValueError(f"requirements.txt 包含重复或规范化后重复的锁定包：{name}")
        seen.add(normalized_name)
        locked.append((normalized_name, version))
        pending = ""
    if pending:
        raise ValueError(f"requirements.txt 包含未闭合的续行：{pending}")
    if not locked:
        raise ValueError("requirements.txt 不得为空")
    return locked


def installed_distributions() -> dict[str, list[str]]:
    installed: dict[str, list[str]] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name") or distribution.name
        normalized_name = normalize_distribution_name(name)
        installed.setdefault(normalized_name, []).append(distribution.version)
    return installed


def read_pyvenv_config(path: Path) -> dict[str, str]:
    config: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = raw_line.partition("=")
        if separator:
            config[key.strip().casefold()] = value.strip()
    return config


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

    expected_venv = (PROJECT_ROOT / ".venv").resolve()
    expected_executable = (expected_venv / "Scripts" / "python.exe").resolve()
    executable_ok = Path(sys.executable).resolve() == expected_executable
    prefix_ok = Path(sys.prefix).resolve() == expected_venv
    pyvenv_path = expected_venv / "pyvenv.cfg"
    try:
        pyvenv_config = read_pyvenv_config(pyvenv_path)
        system_site_value = pyvenv_config.get("include-system-site-packages")
        system_site_ok = system_site_value == "false"
    except OSError as exc:
        pyvenv_config = {}
        system_site_value = None
        system_site_ok = False
        errors.append(f"无法读取项目虚拟环境配置：{exc}")
    user_site_ok = site.ENABLE_USER_SITE is False
    if not executable_ok:
        errors.append(f"Python 可执行文件不在项目虚拟环境：需要 {expected_executable}。")
    if not prefix_ok:
        errors.append(f"sys.prefix 不在项目虚拟环境：需要 {expected_venv}。")
    if not system_site_ok:
        errors.append("pyvenv.cfg 必须设置 include-system-site-packages=false。")
    if not user_site_ok:
        errors.append("Python user site 必须禁用。")

    requirements_checks: list[dict[str, object]] = []
    distribution_set_check: dict[str, object] = {}
    try:
        locked_requirements = read_locked_requirements()
    except (OSError, ValueError) as exc:
        errors.append(f"requirements.txt 无法按标准 name==version 读取：{exc}")
    else:
        locked_versions = dict(locked_requirements)
        installed = installed_distributions()
        locked_names = set(locked_versions)
        installed_names = set(installed)
        missing_names = sorted(locked_names - installed_names)
        extra_names = sorted(installed_names - locked_names)
        mismatched_names = sorted(
            name
            for name in locked_names & installed_names
            if installed[name] != [locked_versions[name]]
        )
        distribution_set_check = {
            "locked_count": len(locked_names),
            "installed_count": len(installed_names),
            "exact_set": not missing_names and not extra_names,
            "missing": missing_names,
            "extra": extra_names,
            "version_mismatch": mismatched_names,
        }
        if missing_names or extra_names:
            errors.append("已安装发行版集合与 requirements.txt 锁集合不完全相等。")
        if mismatched_names:
            errors.append("已安装发行版存在版本不匹配：" + ", ".join(mismatched_names))
        for name, required_version in locked_requirements:
            versions = installed.get(name, [])
            installed_version = versions[0] if len(versions) == 1 else None
            exact = versions == [required_version]
            requirements_checks.append(
                {
                    "name": name,
                    "required_version": required_version,
                    "installed_version": installed_version,
                    "installed_exact": exact,
                }
            )
            if not exact:
                actual = ", ".join(versions) if versions else "not installed"
                errors.append(f"依赖版本不匹配：{name} 需要 {required_version}，当前为 {actual}。")

    bootstrap_tools = {
        name: {
            "in_lock": normalize_distribution_name(name) in set(
                item["name"] for item in requirements_checks
            ),
            "installed_versions": installed_distributions().get(
                normalize_distribution_name(name), []
            ),
        }
        for name in ("pip", "setuptools", "wheel")
    }

    report: dict[str, object] = {
        "status": "ok" if not errors else "error",
        "checks": {
            "python": {
                "required": "Python 3.10.11 x64",
                "version": platform.python_version(),
                "architecture_bits": architecture_bits,
                "executable": sys.executable,
                "ok": python_ok and executable_ok and prefix_ok,
                "expected_executable": str(expected_executable),
                "sys_prefix": sys.prefix,
                "expected_prefix": str(expected_venv),
                "user_site_enabled": site.ENABLE_USER_SITE,
            },
            "venv_provenance": {
                "executable_exact": executable_ok,
                "prefix_exact": prefix_ok,
                "pyvenv_cfg": str(pyvenv_path),
                "include_system_site_packages": system_site_value,
                "include_system_site_packages_false": system_site_ok,
                "user_site_disabled": user_site_ok,
            },
            "project_root": {
                "path": str(PROJECT_ROOT.resolve()),
                "ok": root_ok,
            },
            "managed_paths": path_checks,
            "requirements": requirements_checks,
            "distribution_set": distribution_set_check,
            "bootstrap_tools": bootstrap_tools,
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
