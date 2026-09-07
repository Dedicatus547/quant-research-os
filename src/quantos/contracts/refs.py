"""Content-addressed references shared by vertical slices."""

from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, NonNegativeInt, field_validator

from quantos.contracts.base import CanonicalContract

SHA256_PATTERN = r"^[0-9a-f]{64}$"


def validate_logical_path(value: str) -> str:
    """Return a canonical relative POSIX path or reject it."""

    path = PurePosixPath(value)
    normalized = path.as_posix()
    if (
        path.is_absolute()
        or normalized in {"", "."}
        or ".." in path.parts
        or "\\" in value
        or "\x00" in value
        or normalized != value
    ):
        raise ValueError("logical_path must be a safe relative POSIX path")
    return normalized


class ArtifactRef(CanonicalContract):
    schema_version: Literal["artifact-ref/v1"] = "artifact-ref/v1"
    kind: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt
    media_type: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)

    @field_validator("logical_path")
    @classmethod
    def logical_path_is_relative(cls, value: str) -> str:
        return validate_logical_path(value)


class DataSnapshotRef(CanonicalContract):
    schema_version: Literal["data-snapshot-ref/v1"] = "data-snapshot-ref/v1"
    kind: Literal["data_snapshot"] = "data_snapshot"
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt
    media_type: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)

    @field_validator("logical_path")
    @classmethod
    def logical_path_is_relative(cls, value: str) -> str:
        return validate_logical_path(value)
