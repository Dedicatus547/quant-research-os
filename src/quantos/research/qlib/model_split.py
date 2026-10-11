"""Calendar-based DatasetH segment resolution and independent native split audit verification."""

from datetime import date
from pathlib import Path

from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.model_data_split import QlibModelDataSplitAudit
from quantos.contracts.research import ResearchPolicy, ResearchSegment, ResolvedExperimentSpec
from quantos.contracts.research_result import ResearchResultSourceFile


def effective_model_segments(
    policy: ResearchPolicy, resolved: ResolvedExperimentSpec, calendar: tuple[date, ...]
) -> dict[str, ResearchSegment]:
    """Remove the declared tail sessions from train and valid before native Qlib fitting."""
    if not calendar or calendar != tuple(sorted(set(calendar))):
        raise ValueError("model split calendar is not unique and ordered")
    declared = {
        "train": policy.train,
        "valid": policy.validation,
        "test": ResearchSegment(start=resolved.evaluation_start, end=resolved.evaluation_end),
    }
    result: dict[str, ResearchSegment] = {}
    for name, segment in declared.items():
        sessions = tuple(day for day in calendar if segment.start <= day <= segment.end)
        purge = policy.purge_trading_days if name != "test" else 0
        if len(sessions) <= purge:
            raise ValueError("model split has insufficient calendar sessions after purge")
        result[name] = ResearchSegment(start=sessions[0], end=sessions[-1 - purge])
    for left, right in (("train", "valid"), ("valid", "test")):
        label_index = calendar.index(result[left].end) + policy.label_horizon_trading_sessions
        if label_index >= len(calendar) or calendar[label_index] >= result[right].start:
            raise ValueError("purged model split forward labels cross the next segment")
    return result


def verify_model_data_split(
    path: Path,
    *,
    resolved: ResolvedExperimentSpec,
    research_policy: ResearchPolicy,
    calendar: tuple[date, ...],
    source_files: tuple[ResearchResultSourceFile, ...] | None = None,
) -> QlibModelDataSplitAudit:
    """Recompute cutoffs and bind sample evidence to the original five native Qlib records."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1 << 20:
        raise ValueError("model split audit is missing or unsafe")
    raw = path.read_bytes()
    audit = QlibModelDataSplitAudit.model_validate_json(raw)
    if audit.canonical_bytes() != raw:
        raise ValueError("model split audit is not canonical")
    if (
        audit.resolved_spec_hash != resolved.content_hash
        or audit.code_commit_hash != resolved.code_commit_hash
        or audit.lockfile_hash != resolved.lockfile_hash
        or audit.snapshot_hash != resolved.snapshot_hash
        or audit.qlib_view_hash != resolved.qlib_view_hash
        or audit.research_policy_hash != research_policy.content_hash
        or audit.research_policy_hash != resolved.research_policy_hash
        or audit.calendar_hash != sha256_bytes(canonical_json_bytes(calendar))
        or audit.purge_trading_days != research_policy.purge_trading_days
        or audit.label_horizon_trading_sessions != research_policy.label_horizon_trading_sessions
    ):
        raise ValueError("model split audit differs from its actual frozen inputs")
    effective = effective_model_segments(research_policy, resolved, calendar)
    declared = {
        "train": research_policy.train,
        "valid": research_policy.validation,
        "test": ResearchSegment(start=resolved.evaluation_start, end=resolved.evaluation_end),
    }
    calendar_set = set(calendar)
    for name in ("train", "valid", "test"):
        item = getattr(audit, name)
        if item.declared != declared[name] or item.effective != effective[name]:
            raise ValueError("model split audit cutoffs differ from calendar purge policy")
        if not set(item.observed_sessions) <= calendar_set:
            raise ValueError("model split audit samples are outside its fixed calendar")
    if source_files is not None and audit.source_files != source_files:
        raise ValueError("model split native sources differ from ResearchResult")
    for source in audit.source_files:
        native = path.parent / source.logical_path
        if (
            native.is_symlink()
            or not native.is_file()
            or (native.stat().st_size != source.size_bytes or sha256_file(native) != source.sha256)
        ):
            raise ValueError("model split audit lacks its bound original native records")
    return audit
