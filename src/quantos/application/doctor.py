"""Environment diagnostics that never disclose secret values."""

from __future__ import annotations

import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DoctorReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["doctor-report/v1"] = "doctor-report/v1"
    offline_status: Literal["READY", "BLOCKED"]
    data_qualified_status: Literal["READY_FOR_PROBE", "BLOCKED_TOKEN_MISSING"]
    python_version: str
    python_supported: bool
    platform: str
    architecture: str
    git_repository_initialized: bool
    tushare_token_configured: bool
    package_versions: dict[str, str | None]
    blockers: tuple[str, ...]


RUNTIME_DISTRIBUTIONS = (
    "pydantic",
    "pyarrow",
    "tushare",
    "pyqlib",
    "lightgbm",
    "typer",
    "tenacity",
    "pyrate-limiter",
    "ruamel.yaml",
)


def _distribution_version(distribution: str) -> str | None:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def build_doctor_report(workspace: Path | None = None) -> DoctorReport:
    root = workspace or Path.cwd()
    package_versions = {
        distribution: _distribution_version(distribution) for distribution in RUNTIME_DISTRIBUTIONS
    }
    python_supported = sys.version_info[:2] == (3, 11)
    missing = sorted(name for name, installed in package_versions.items() if installed is None)
    blockers: list[str] = []
    if not python_supported:
        blockers.append("PYTHON_3_11_REQUIRED")
    if missing:
        blockers.append(f"MISSING_DISTRIBUTIONS:{','.join(missing)}")

    token_configured = bool(os.environ.get("TUSHARE_TOKEN"))
    return DoctorReport(
        offline_status="READY" if not blockers else "BLOCKED",
        data_qualified_status=("READY_FOR_PROBE" if token_configured else "BLOCKED_TOKEN_MISSING"),
        python_version=platform.python_version(),
        python_supported=python_supported,
        platform=platform.system(),
        architecture=platform.machine(),
        git_repository_initialized=(root / ".git" / "HEAD").is_file(),
        tushare_token_configured=token_configured,
        package_versions=package_versions,
        blockers=tuple(blockers),
    )
