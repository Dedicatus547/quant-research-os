"""Fixed management wrappers redact transport exceptions; no process is launched."""

import importlib
import json

import pytest


@pytest.mark.parametrize("module", ["hosted_admission_probe", "hosted_observation_probe"])
@pytest.mark.parametrize("failed", [False, True])
def test_offline_probe_wrapper_preserves_gate_and_hides_exception_text(
    module, failed, monkeypatch, capsys
):
    probe = importlib.import_module("quantos.infrastructure." + module)
    case = (
        probe.BOUNDED_REJECTION_CASES[0]
        if module == "hosted_admission_probe"
        else probe.HOST_OBSERVATION_CASES[0]
    )
    monkeypatch.setattr("sys.argv", [module, "--profile-hash", "a" * 64, "--case", case])
    calls = []

    def fixture(profile, selected, gate):
        calls.append((profile, selected, gate))
        if failed:
            raise RuntimeError("synthetic confidential exception detail")

    monkeypatch.setattr(probe, "run_transport_fixture", fixture)
    if failed:
        with pytest.raises(SystemExit) as exit_record:
            probe.main()
        assert exit_record.value.code == 1
        result = json.loads(capsys.readouterr().out)
        assert result["error_type"] == "RuntimeError"
        assert "confidential" not in json.dumps(result)
    else:
        probe.main()
        assert capsys.readouterr().out == ""
    assert calls == [("a" * 64, case, "Q04" if module == "hosted_admission_probe" else "Q08")]
