"""Immutable publication for bounded acquisition capability evidence."""

from pathlib import Path

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.refs import ArtifactRef
from quantos.data.tushare import CapabilityReport


def publish_capability_report(report: CapabilityReport, root: Path) -> ArtifactRef:
    encoded = report.canonical_bytes()
    relative = Path("tushare-capabilities") / f"sha256-{report.content_hash}.json"
    digest = atomic_write_bytes(root / relative, encoded)
    return ArtifactRef(
        kind="tushare_capability_report",
        sha256=digest,
        size_bytes=len(encoded),
        media_type="application/json",
        logical_path=relative.as_posix(),
    )
