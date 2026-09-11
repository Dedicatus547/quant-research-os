from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from quantos.application import resolve_experiment
from quantos.config import load_yaml_contract
from quantos.contracts import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ResolvedExperimentSpec,
    canonical_json_bytes,
)
from quantos.contracts.status import ReasonCode
from quantos.research.qlib import (
    QlibResearchError,
    ResearchResultArtifactBuilder,
    verify_research_result,
)
from quantos.research.qlib import result as result_module

ROOT = Path(__file__).parents[2]


def _inputs(tmp_path: Path) -> tuple[ResolvedExperimentSpec, ResearchPolicy, Path]:
    authoring = load_yaml_contract(
        ROOT / "configs/research/hs300_momentum_v1.yaml", ExperimentAuthoringSpec
    )
    policy = load_yaml_contract(ROOT / "configs/research/policy_v1.yaml", ResearchPolicy)
    resolved = resolve_experiment(
        authoring,
        snapshot_hash="a" * 64,
        qlib_view_hash="b" * 64,
        qlib_version="0.9.7",
        qlib_view_spec_hash="c" * 64,
        pit_audit_evidence_hash="d" * 64,
        research_policy_hash=policy.content_hash,
        validation_policy_hash="e" * 64,
        cost_policy_hash="f" * 64,
        backtest_policy_hash="0" * 64,
        code_commit_hash="1" * 40,
        lockfile_hash="2" * 64,
    )
    native = tmp_path / "native"
    (native / "sig_analysis").mkdir(parents=True)
    index = pd.MultiIndex.from_tuples(
        [
            ("SH600000", pd.Timestamp("2024-01-02")),
            ("SZ000001", pd.Timestamp("2024-01-02")),
            ("SH600000", pd.Timestamp("2024-01-03")),
            ("SZ000001", pd.Timestamp("2024-01-03")),
        ],
        names=("instrument", "datetime"),
    )
    pd.DataFrame({"score": [0.1, 0.2, 0.3, 0.4]}, index=index).to_pickle(
        native / "pred.pkl"
    )
    pd.DataFrame({"LABEL0": [0.2, 0.1, 0.4, 0.3]}, index=index).to_pickle(
        native / "label.pkl"
    )
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    pd.Series([0.1, 0.2], index=dates).to_pickle(native / "sig_analysis/ic.pkl")
    pd.Series([0.3, 0.4], index=dates).to_pickle(native / "sig_analysis/ric.pkl")
    (native / "metrics.json").write_bytes(
        canonical_json_bytes({"IC": 0.15, "ICIR": 3.0, "Rank IC": 0.35, "Rank ICIR": 7.0})
    )
    return resolved, policy, native


def test_native_qlib_result_is_immutable_and_reproducible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolved, policy, native = _inputs(tmp_path)
    monkeypatch.setattr(
        result_module,
        "verify_signal_artifact",
        lambda _path: SimpleNamespace(
            resolved_experiment_hash=resolved.content_hash, artifact_hash="3" * 64
        ),
    )
    builder = ResearchResultArtifactBuilder()
    first = builder.build(
        resolved,
        policy,
        tmp_path / "signal",
        native,
        tmp_path / "result-a",
        qlib_run_id="qlib-run-1",
        label_expression="Ref($close,-1)/$close-1",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    second = builder.build(
        resolved,
        policy,
        tmp_path / "signal",
        native,
        tmp_path / "result-b",
        qlib_run_id="qlib-run-1",
        label_expression="Ref($close,-1)/$close-1",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert first.manifest.artifact_hash == second.manifest.artifact_hash
    assert first.manifest.files == second.manifest.files
    assert first.manifest.metrics[2].name == "Rank IC"
    assert first.manifest.metrics[2].value == 0.35
    assert verify_research_result(first.path) == first.manifest
    assert verify_research_result(second.path) == second.manifest


def test_research_result_tamper_and_missing_native_output_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolved, policy, native = _inputs(tmp_path)
    monkeypatch.setattr(
        result_module,
        "verify_signal_artifact",
        lambda _path: SimpleNamespace(
            resolved_experiment_hash=resolved.content_hash, artifact_hash="3" * 64
        ),
    )
    builder = ResearchResultArtifactBuilder()
    built = builder.build(
        resolved,
        policy,
        tmp_path / "signal",
        native,
        tmp_path / "result",
        qlib_run_id="qlib-run-1",
        label_expression="Ref($close,-1)/$close-1",
    )
    (built.path / "rank-ic-series.json").write_bytes(b"[]")
    with pytest.raises(QlibResearchError) as corrupted:
        verify_research_result(built.path)
    assert corrupted.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    (native / "sig_analysis/ic.pkl").unlink()
    with pytest.raises(QlibResearchError) as incomplete:
        builder.build(
            resolved,
            policy,
            tmp_path / "signal",
            native,
            tmp_path / "missing",
            qlib_run_id="qlib-run-2",
            label_expression="Ref($close,-1)/$close-1",
        )
    assert incomplete.value.reason_code is ReasonCode.QLIB_EXECUTION_FAILED
