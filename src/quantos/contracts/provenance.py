"""Canonical code, lockfile, and runtime provenance contracts."""

from typing import Literal

from pydantic import Field, field_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN


class CodeProvenance(CanonicalContract):
    schema_version: Literal["code-provenance/v1"] = "code-provenance/v1"
    commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    worktree_clean: Literal[True] = True


class RuntimePackageVersion(CanonicalContract):
    schema_version: Literal["runtime-package-version/v1"] = "runtime-package-version/v1"
    name: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    version: str = Field(min_length=1)


class RuntimeFingerprint(CanonicalContract):
    """Exact process environment required for numeric reproducibility."""

    schema_version: Literal["runtime-fingerprint/v1"] = "runtime-fingerprint/v1"
    python_version: str = Field(min_length=1)
    python_implementation: str = Field(min_length=1)
    operating_system: str = Field(min_length=1)
    operating_system_release: str = Field(min_length=1)
    architecture: str = Field(min_length=1)
    libc: str = Field(min_length=1)
    packages: tuple[RuntimePackageVersion, ...]

    @field_validator("packages")
    @classmethod
    def packages_are_complete_and_sorted(
        cls, value: tuple[RuntimePackageVersion, ...]
    ) -> tuple[RuntimePackageVersion, ...]:
        required = {
            "lightgbm",
            "numpy",
            "pandas",
            "pyarrow",
            "pydantic",
            "pyqlib",
            "ruamel.yaml",
            "typer",
        }
        names = [item.name for item in value]
        if names != sorted(names) or set(names) != required or len(names) != len(required):
            raise ValueError("runtime packages must be complete, sorted, and unique")
        return value
