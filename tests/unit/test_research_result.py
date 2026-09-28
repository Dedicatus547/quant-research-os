from __future__ import annotations

from datetime import UTC, date, datetime
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
    verify_p14dq_native_label_audit,
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
    pd.DataFrame({"score": [0.1, 0.2, 0.3, 0.4]}, index=index).to_pickle(native / "pred.pkl")
    pd.DataFrame({"LABEL0": [0.2, 0.1, 0.4, 0.3]}, index=index).to_pickle(native / "label.pkl")
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


def test_dq_native_nan_label_audit_rebuilds_export_and_rejects_tampering(
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
    labels = pd.read_pickle(native / "label.pkl")
    labels.loc[("SZ000001", pd.Timestamp("2024-01-03")), "LABEL0"] = float("nan")
    labels.to_pickle(native / "label.pkl")
    calendar = (date(2024, 1, 2), date(2024, 1, 3))
    builder = ResearchResultArtifactBuilder()

    with pytest.raises(QlibResearchError) as strict_failure:
        builder.build(
            resolved,
            policy,
            tmp_path / "signal",
            native,
            tmp_path / "strict-results",
            qlib_run_id="strict-run",
            label_expression="Ref($close,-1)/$close-1",
        )
    assert strict_failure.value.reason_code is ReasonCode.QLIB_EXECUTION_FAILED

    built = builder.build(
        resolved,
        policy,
        tmp_path / "signal",
        native,
        tmp_path / "dq-results",
        qlib_run_id="dq-run",
        label_expression="Ref($close,-1)/$close-1",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        dq_calendar=calendar,
        dq_audit_root=tmp_path / "dq-audits",
    )
    assert built.export_audit_hash is not None
    assert built.export_audit_path is not None
    audit = verify_p14dq_native_label_audit(built.path, native, built.export_audit_path, calendar)
    assert audit.audit_hash == built.export_audit_hash
    assert (audit.raw_pair_count, audit.exported_pair_count, audit.omitted_nan_label_count) == (
        4,
        3,
        1,
    )
    assert built.manifest.prediction_row_count == built.manifest.label_row_count == 3
    assert built.manifest.ic_row_count == built.manifest.rank_ic_row_count == 2
    wrong_path = built.export_audit_path.with_name("wrong-name.json")
    wrong_path.write_bytes(built.export_audit_path.read_bytes())
    with pytest.raises(QlibResearchError) as path_mismatch:
        verify_p14dq_native_label_audit(built.path, native, wrong_path, calendar)
    assert path_mismatch.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    retry = builder.build(
        resolved,
        policy,
        tmp_path / "signal",
        native,
        tmp_path / "dq-results",
        qlib_run_id="dq-run",
        label_expression="Ref($close,-1)/$close-1",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        dq_calendar=calendar,
        dq_audit_root=tmp_path / "dq-audits",
    )
    assert retry.manifest.artifact_hash == built.manifest.artifact_hash
    assert retry.export_audit_hash == built.export_audit_hash
    assert retry.export_audit_path == built.export_audit_path

    audit_bytes = built.export_audit_path.read_bytes()
    with pytest.raises(QlibResearchError) as calendar_mismatch:
        verify_p14dq_native_label_audit(built.path, native, built.export_audit_path, calendar[:1])
    assert calendar_mismatch.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    built.export_audit_path.write_bytes(b"tampered immutable audit")
    with pytest.raises(QlibResearchError) as conflicting_retry:
        builder.build(
            resolved,
            policy,
            tmp_path / "signal",
            native,
            tmp_path / "dq-results",
            qlib_run_id="dq-run",
            label_expression="Ref($close,-1)/$close-1",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            dq_calendar=calendar,
            dq_audit_root=tmp_path / "dq-audits",
        )
    assert conflicting_retry.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED
    built.export_audit_path.write_bytes(audit_bytes)

    (native / "metrics.json").write_bytes(
        canonical_json_bytes({"IC": 0.15, "ICIR": 3.0, "Rank IC": 0.36, "Rank ICIR": 7.0})
    )
    with pytest.raises(QlibResearchError) as tampered:
        verify_p14dq_native_label_audit(built.path, native, built.export_audit_path, calendar)
    assert tampered.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


@pytest.mark.parametrize(
    "fault",
    (
        "empty_calendar",
        "unordered_calendar",
        "prediction_not_dataframe",
        "multiple_prediction_columns",
        "index_mismatch",
        "duplicate_index",
        "empty_prediction",
        "non_tuple_key",
        "wrong_key_arity",
        "missing_instrument",
        "missing_timestamp",
        "outside_calendar",
        "nonfinite_prediction",
        "infinite_label",
        "wrong_ic_type",
        "duplicate_ic_date",
        "nonfinite_ic",
    ),
)
def test_dq_native_projection_rejects_malformed_qlib_evidence(tmp_path: Path, fault: str) -> None:
    _, _, native = _inputs(tmp_path)
    calendar = (date(2024, 1, 2), date(2024, 1, 3))
    prediction = pd.read_pickle(native / "pred.pkl")
    label = pd.read_pickle(native / "label.pkl")

    if fault in {"empty_calendar", "unordered_calendar"}:
        calendar = () if fault == "empty_calendar" else tuple(reversed(calendar))
    elif fault == "prediction_not_dataframe":
        prediction.iloc[:, 0].to_pickle(native / "pred.pkl")
    elif fault == "multiple_prediction_columns":
        prediction["second"] = prediction.iloc[:, 0]
        prediction.to_pickle(native / "pred.pkl")
    elif fault == "index_mismatch":
        label.iloc[::-1].to_pickle(native / "label.pkl")
    elif fault == "duplicate_index":
        duplicate_index = pd.MultiIndex.from_tuples(
            [prediction.index[0], prediction.index[0], *prediction.index[2:]],
            names=("instrument", "datetime"),
        )
        prediction.index = duplicate_index
        label.index = duplicate_index
        prediction.to_pickle(native / "pred.pkl")
        label.to_pickle(native / "label.pkl")
    elif fault == "empty_prediction":
        prediction.iloc[:0].to_pickle(native / "pred.pkl")
        label.iloc[:0].to_pickle(native / "label.pkl")
    elif fault == "non_tuple_key":
        index = pd.Index(["SH600000", "SZ000001", "SH600000", "SZ000001"])
        prediction.index = index
        label.index = index
        prediction.to_pickle(native / "pred.pkl")
        label.to_pickle(native / "label.pkl")
    elif fault == "wrong_key_arity":
        index = pd.MultiIndex.from_tuples(
            [(key[0], key[1], "extra") for key in prediction.index],
            names=("instrument", "datetime", "extra"),
        )
        prediction.index = index
        label.index = index
        prediction.to_pickle(native / "pred.pkl")
        label.to_pickle(native / "label.pkl")
    elif fault == "missing_instrument":
        index = pd.MultiIndex.from_tuples(
            [(1, key[1]) for key in prediction.index], names=("instrument", "datetime")
        )
        prediction.index = index
        label.index = index
        prediction.to_pickle(native / "pred.pkl")
        label.to_pickle(native / "label.pkl")
    elif fault == "missing_timestamp":
        index = pd.MultiIndex.from_tuples(
            [(key[0], "not-a-date") for key in prediction.index],
            names=("instrument", "datetime"),
        )
        prediction.index = index
        label.index = index
        prediction.to_pickle(native / "pred.pkl")
        label.to_pickle(native / "label.pkl")
    elif fault == "outside_calendar":
        index = list(prediction.index)
        index[0] = (index[0][0], pd.Timestamp("2024-01-04"))
        prediction.index = pd.MultiIndex.from_tuples(index, names=("instrument", "datetime"))
        label.index = prediction.index
        prediction.to_pickle(native / "pred.pkl")
        label.to_pickle(native / "label.pkl")
    elif fault == "nonfinite_prediction":
        prediction.iloc[0, 0] = float("nan")
        prediction.to_pickle(native / "pred.pkl")
    elif fault == "infinite_label":
        label.iloc[0, 0] = float("inf")
        label.to_pickle(native / "label.pkl")
    elif fault == "wrong_ic_type":
        pd.DataFrame({"IC": [0.1, 0.2]}, index=pd.to_datetime(calendar)).to_pickle(
            native / "sig_analysis/ic.pkl"
        )
    elif fault == "duplicate_ic_date":
        pd.Series([0.1, 0.2], index=pd.to_datetime([calendar[0], calendar[0]])).to_pickle(
            native / "sig_analysis/ic.pkl"
        )
    elif fault == "nonfinite_ic":
        pd.Series([float("nan"), 0.2], index=pd.to_datetime(calendar)).to_pickle(
            native / "sig_analysis/ic.pkl"
        )

    with pytest.raises(ValueError):
        result_module._dq_native_projection(native, calendar)


@pytest.mark.parametrize(
    "fault",
    (
        "value_wrong_type",
        "value_multiple_columns",
        "value_non_tuple_key",
        "value_wrong_key_arity",
        "value_missing_instrument",
        "value_missing_timestamp",
        "value_invalid_timestamp",
        "value_nonfinite",
        "value_empty",
        "value_duplicate_keys",
        "series_wrong_type",
        "series_empty",
        "series_duplicate_dates",
        "invalid_trade_date",
    ),
)
def test_native_qlib_row_converters_reject_invalid_shapes(fault: str) -> None:
    date_value = pd.Timestamp("2024-01-02")
    if fault == "value_wrong_type":
        with pytest.raises(ValueError):
            result_module._value_rows(object(), name="prediction")
    elif fault == "value_multiple_columns":
        with pytest.raises(ValueError):
            result_module._value_rows(pd.DataFrame({"a": [0.1], "b": [0.2]}), name="prediction")
    elif fault == "value_non_tuple_key":
        with pytest.raises(ValueError):
            result_module._value_rows(pd.Series([0.1], index=["SH600000"]), name="prediction")
    elif fault == "value_wrong_key_arity":
        index = pd.MultiIndex.from_tuples(
            [("SH600000", date_value, "extra")], names=("instrument", "datetime", "extra")
        )
        with pytest.raises(ValueError):
            result_module._value_rows(pd.Series([0.1], index=index), name="prediction")
    elif fault == "value_missing_instrument":
        index = pd.MultiIndex.from_tuples([(1, date_value)], names=("instrument", "datetime"))
        with pytest.raises(ValueError):
            result_module._value_rows(pd.Series([0.1], index=index), name="prediction")
    elif fault == "value_missing_timestamp":
        index = pd.MultiIndex.from_tuples(
            [("SH600000", "not-a-date")], names=("instrument", "datetime")
        )
        with pytest.raises(ValueError):
            result_module._value_rows(pd.Series([0.1], index=index), name="prediction")
    elif fault == "value_invalid_timestamp":
        index = pd.MultiIndex.from_tuples([("SH600000", 1)], names=("instrument", "datetime"))
        with pytest.raises(ValueError):
            result_module._value_rows(pd.Series([0.1], index=index), name="prediction")
    elif fault == "value_nonfinite":
        index = pd.MultiIndex.from_tuples(
            [("SH600000", date_value)], names=("instrument", "datetime")
        )
        with pytest.raises(ValueError):
            result_module._value_rows(pd.Series([float("inf")], index=index), name="prediction")
    elif fault == "value_empty":
        with pytest.raises(ValueError):
            result_module._value_rows(pd.DataFrame({"prediction": []}), name="prediction")
    elif fault == "value_duplicate_keys":
        index = pd.MultiIndex.from_tuples(
            [("SH600000", date_value), ("SH600000", date_value)],
            names=("instrument", "datetime"),
        )
        with pytest.raises(ValueError):
            result_module._value_rows(pd.Series([0.1, 0.2], index=index), name="prediction")
    elif fault == "series_wrong_type":
        with pytest.raises(ValueError):
            result_module._series_rows(pd.DataFrame({"IC": [0.1]}), name="IC")
    elif fault == "series_empty":
        with pytest.raises(ValueError):
            result_module._series_rows(pd.Series(dtype=float), name="IC")
    elif fault == "series_duplicate_dates":
        with pytest.raises(ValueError):
            result_module._series_rows(
                pd.Series([0.1, 0.2], index=[date_value, date_value]), name="IC"
            )
    else:
        with pytest.raises(ValueError):
            result_module._trade_date("2024-01-02")


def test_trade_date_accepts_a_calendar_date() -> None:
    expected = date(2024, 1, 2)
    assert result_module._trade_date(expected) == expected


@pytest.mark.parametrize("missing", ("calendar", "audit_root"))
def test_dq_builder_requires_calendar_and_audit_root_as_a_pair(
    tmp_path: Path, missing: str
) -> None:
    resolved, policy, native = _inputs(tmp_path)
    kwargs: dict[str, object] = {
        "dq_calendar": (date(2024, 1, 2),),
        "dq_audit_root": tmp_path / "dq-audits",
    }
    kwargs["dq_calendar" if missing == "calendar" else "dq_audit_root"] = None

    with pytest.raises(ValueError, match="requires both"):
        ResearchResultArtifactBuilder().build(
            resolved,
            policy,
            tmp_path / "signal",
            native,
            tmp_path / "results",
            qlib_run_id="paired-inputs-run",
            label_expression="Ref($close,-1)/$close-1",
            **kwargs,
        )
