import pytest
from pydantic import ValidationError

from quantos.contracts import ArtifactRef, DataSnapshotRef


def test_artifact_ref_accepts_safe_content_addressed_reference() -> None:
    reference = DataSnapshotRef(
        sha256="a" * 64,
        size_bytes=123,
        media_type="application/vnd.apache.parquet",
        logical_path="snapshots/sha256-abc/manifest.json",
    )

    assert reference.kind == "data_snapshot"


@pytest.mark.parametrize(
    "path",
    [
        "/absolute",
        "../escape",
        "folder\\escape",
        ".",
        "folder/./file",
        "folder//file",
        "file\x00name",
    ],
)
def test_artifact_ref_rejects_unsafe_path(path: str) -> None:
    with pytest.raises(ValidationError):
        ArtifactRef(
            kind="test",
            sha256="a" * 64,
            size_bytes=1,
            media_type="text/plain",
            logical_path=path,
        )


def test_artifact_ref_rejects_invalid_digest() -> None:
    with pytest.raises(ValidationError):
        ArtifactRef(
            kind="test",
            sha256="not-a-digest",
            size_bytes=1,
            media_type="text/plain",
            logical_path="safe.txt",
        )
