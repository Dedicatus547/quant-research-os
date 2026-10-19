from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from quantos.contracts.status import ReasonCode
from quantos.research.qlib.universe import (
    WorkflowRecorderInterfaceError,
    WorkflowRequiredMetricNonFiniteError,
)
from quantos.research.qlib.workflow import _fit_and_generate_signal_record, _native_objects


def test_model_metrics_finish_before_signal_record_artifacts_are_written() -> None:
    events: list[str] = []
    metric_file = {"contents": ""}

    class AsyncLog:
        def __init__(self) -> None:
            self.pending: list[Callable[[], None]] = []

        def wait(self) -> None:
            for operation in self.pending:
                operation()
            self.pending.clear()
            events.append("metrics-drained")

    class Recorder:
        def __init__(self) -> None:
            self.async_log: AsyncLog | None = AsyncLog()

        def queue_metric_write(self) -> None:
            assert self.async_log is not None

            def write_metric() -> None:
                metric_file["contents"] = "l2.valid 0.25 0\n"
                events.append("metric-written")

            self.async_log.pending.append(write_metric)

    recorder = Recorder()

    class Model:
        def fit(self, _dataset: object, *, verbose_eval: int) -> None:
            assert verbose_eval == 0
            events.append("model-fit")
            recorder.queue_metric_write()

    class SignalRecord:
        def __init__(self, _model: object, _dataset: object, _recorder: object) -> None:
            pass

        def generate(self) -> None:
            if not metric_file["contents"]:
                raise ValueError("Metric 'l2.valid' is malformed. No data found.")
            assert recorder.async_log is None
            events.append("signal-artifacts-written")

    _fit_and_generate_signal_record(Model(), object(), recorder, SignalRecord)

    assert events == [
        "model-fit",
        "metric-written",
        "metrics-drained",
        "signal-artifacts-written",
    ]


@pytest.mark.parametrize("missing", ["load_object", "list_metrics"])
def test_native_recorder_missing_interface_has_internal_diagnostic(missing):
    recorder = SimpleNamespace(load_object=lambda name: object(), list_metrics=lambda: {})
    setattr(recorder, missing, None)
    with pytest.raises(WorkflowRecorderInterfaceError) as raised:
        _native_objects(recorder)
    assert raised.value.reason_code is ReasonCode.QLIB_EXECUTION_FAILED


@pytest.mark.parametrize("metric", ["IC", "ICIR", "Rank IC", "Rank ICIR"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_required_metric_propagates_through_workflow_and_stage(
    tmp_path, monkeypatch, metric, value
):
    from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
    from quantos.research.qlib import workflow

    metrics = {name: 0.25 for name in ("IC", "ICIR", "Rank IC", "Rank ICIR")}
    metrics[metric] = value
    recorder = SimpleNamespace(load_object=lambda name: object(), list_metrics=lambda: metrics)
    errors = []

    def fail_native(**kwargs):
        try:
            _native_objects(recorder)
        except WorkflowRequiredMetricNonFiniteError as error:
            errors.append(error)
            raise

    monkeypatch.setattr(workflow.qlib, "init", fail_native)
    monkeypatch.setattr(
        workflow,
        "translate_safe_expression",
        lambda expression: SimpleNamespace(output_expression="$close"),
    )
    monkeypatch.setattr(workflow, "_label_expression", lambda policy: "Ref($close,-1)/$close-1")
    monkeypatch.setattr(workflow, "effective_model_segments", lambda *args: {})
    monkeypatch.setattr(workflow, "_workflow_tracking_runtime", lambda *args: nullcontext("unused"))
    view = tmp_path / "view"
    (view / "calendars").mkdir(parents=True)
    (view / "calendars" / "day.txt").write_text("2026-01-05\n")
    adapter = object.__new__(QuantosResearchExecutionAdapter)
    adapter.output_root = tmp_path / "execution"
    adapter._discovery_runtime_hash = "a" * 64
    request = SimpleNamespace(content_hash="b" * 64, execution_identity="d" * 64)

    def build():
        return workflow.QlibWorkflowResearchService().run(
            SimpleNamespace(expression=object()),
            object(),
            tmp_path / "signal",
            view,
            tmp_path / "workflow",
            execution_identity="d" * 64,
            research_result_root=tmp_path / "results",
            workspace=tmp_path,
        )

    with pytest.raises(WorkflowRequiredMetricNonFiniteError) as raised:
        adapter._discovery_stage(request, "workflow", {}, build, lambda outputs: outputs)
    assert raised.value is errors[0]
    [completion] = adapter.output_root.rglob("completion.json")
    record = json.loads(completion.read_bytes())
    assert record["status"] == "FAILED"
    assert record["failure_reason_code"] == "QLIB_EXECUTION_FAILED"
    assert record["failure_detail_code"] == "WORKFLOW_REQUIRED_METRIC_NON_FINITE"
    assert not list(adapter.output_root.rglob("sha256-*.json"))
    assert not list((tmp_path / "workflow").rglob("metrics.json"))
