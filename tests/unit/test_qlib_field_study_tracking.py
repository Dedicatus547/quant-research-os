"""Real recorder metadata and recovery; no data, training or backtest execution."""

import os
from pathlib import Path

import pytest
import qlib
from qlib.workflow import R

from quantos.research.qlib.workflow import _WORKFLOW_LOCK, _workflow_tracking_runtime


def test_field_study_recorder_round_trip_below_artifacts(tmp_path: Path) -> None:
    runtime = tmp_path / "artifacts" / "study" / "mlflow-runtime"
    runtime.mkdir(parents=True)
    original_cwd = Path.cwd()
    original_setting = os.environ.get("MLFLOW_ALLOW_FILE_STORE")
    with _WORKFLOW_LOCK, _workflow_tracking_runtime(runtime, "frozen-field-study/v1") as uri:
        assert Path.cwd() == runtime
        assert uri == f"sqlite:///{runtime / 'tracking.sqlite'}"
        qlib.init(provider_uri=str(tmp_path), region="cn")
        with R.start(experiment_name="metadata-only", uri=uri):
            recorder = R.get_recorder()
            recorder_id = recorder.id
            recorder.save_objects(marker={"authority": "RECORDER_METADATA_PROBE"})
        with R.start(
            experiment_name="metadata-only", recorder_id=recorder_id, uri=uri, resume=True
        ):
            restored = R.get_recorder()
            assert restored.id == recorder_id
            assert restored.load_object("marker") == {"authority": "RECORDER_METADATA_PROBE"}
    assert (runtime / "tracking.sqlite").is_file()
    assert (runtime / "mlruns").is_dir()
    assert Path.cwd() == original_cwd
    assert os.environ.get("MLFLOW_ALLOW_FILE_STORE") == original_setting


def test_legacy_tracking_uri_and_context_restore_on_error(tmp_path: Path) -> None:
    original_cwd = Path.cwd()
    original_setting = os.environ.get("MLFLOW_ALLOW_FILE_STORE")
    with (
        pytest.raises(RuntimeError, match="controlled"),
        _WORKFLOW_LOCK,
        _workflow_tracking_runtime(tmp_path, "legacy-price/v2") as uri,
    ):
        assert uri == tmp_path.as_uri()
        assert Path.cwd() == Path("/")
        assert os.environ["MLFLOW_ALLOW_FILE_STORE"] == "true"
        raise RuntimeError("controlled")
    assert Path.cwd() == original_cwd
    assert os.environ.get("MLFLOW_ALLOW_FILE_STORE") == original_setting
