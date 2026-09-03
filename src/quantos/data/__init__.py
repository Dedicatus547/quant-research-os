"""Network-bounded acquisition and offline snapshot normalization."""

from quantos.data.qlib_view import (
    QlibViewBuilder,
    QlibViewBuildError,
    QlibViewBuildResult,
    verify_qlib_view,
)
from quantos.data.snapshot import (
    SnapshotBuildError,
    SnapshotBuildResult,
    SyntheticSnapshotBuilder,
    diff_snapshots,
    verify_snapshot,
)

__all__ = [
    "QlibViewBuildError",
    "QlibViewBuildResult",
    "QlibViewBuilder",
    "SnapshotBuildError",
    "SnapshotBuildResult",
    "SyntheticSnapshotBuilder",
    "diff_snapshots",
    "verify_qlib_view",
    "verify_snapshot",
]
