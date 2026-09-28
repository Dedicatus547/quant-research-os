from __future__ import annotations

from collections.abc import Callable

from quantos.research.qlib.workflow import _fit_and_generate_signal_record


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
