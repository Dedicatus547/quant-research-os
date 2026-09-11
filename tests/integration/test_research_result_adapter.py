from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pytest
from qlib.workflow.record_temp import SigAnaRecord

from quantos.application import resolve_experiment
from quantos.config import load_yaml_contract
from quantos.contracts import ExperimentAuthoringSpec, ResearchPolicy, canonical_json_bytes
from quantos.research.qlib import ResearchResultArtifactBuilder, verify_research_result
from quantos.research.qlib import result as result_module

ROOT = Path(__file__).parents[2]


class _NativeRecorder:
    def __init__(self, prediction: pd.DataFrame, label: pd.DataFrame) -> None:
        self.objects: dict[str, object] = {"pred.pkl": prediction, "label.pkl": label}
        self.metrics: dict[str, float] = {}

    def load_object(self, path: str) -> object:
        return self.objects[path.rsplit("/", 1)[-1]]

    def log_metrics(self, **metrics: float) -> None:
        self.metrics.update(metrics)


def test_native_sigana_outputs_flow_into_immutable_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    instruments = ("SH600000", "SZ000001", "SZ000002")
    index = pd.MultiIndex.from_tuples(
        [(instrument, trade_date) for trade_date in dates for instrument in instruments],
        names=("instrument", "datetime"),
    )
    prediction = pd.DataFrame({"score": [1.0, 2.0, 3.0] * 3}, index=index)
    label = pd.DataFrame(
        {"LABEL0": [1.0, 2.0, 3.0, 3.0, 2.0, 1.0, 1.0, 3.0, 2.0]},
        index=index,
    )
    recorder = _NativeRecorder(prediction, label)
    native_objects = SigAnaRecord(recorder)._generate()
    assert isinstance(native_objects, dict)

    native = tmp_path / "native"
    (native / "sig_analysis").mkdir(parents=True)
    prediction.to_pickle(native / "pred.pkl")
    label.to_pickle(native / "label.pkl")
    cast("pd.Series[Any]", native_objects["ic.pkl"]).to_pickle(
        native / "sig_analysis/ic.pkl"
    )
    cast("pd.Series[Any]", native_objects["ric.pkl"]).to_pickle(
        native / "sig_analysis/ric.pkl"
    )
    (native / "metrics.json").write_bytes(canonical_json_bytes(recorder.metrics))

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
    monkeypatch.setattr(
        result_module,
        "verify_signal_artifact",
        lambda _path: SimpleNamespace(
            resolved_experiment_hash=resolved.content_hash, artifact_hash="3" * 64
        ),
    )
    built = ResearchResultArtifactBuilder().build(
        resolved,
        policy,
        tmp_path / "signal",
        native,
        tmp_path / "results",
        qlib_run_id="native-sigana-run",
        label_expression="Ref($close,-1)/$close-1",
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
    )

    verified = verify_research_result(built.path)
    assert verified.source_files[3].logical_path == "sig_analysis/ic.pkl"
    assert verified.ic_row_count == 3
    assert verified.rank_ic_row_count == 3
    assert tuple(item.name for item in verified.metrics) == (
        "IC",
        "ICIR",
        "Rank IC",
        "Rank ICIR",
    )
