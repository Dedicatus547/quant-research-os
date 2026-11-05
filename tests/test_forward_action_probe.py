"""Action probes retain independent results and suppress credential-bearing output."""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from quantos.data.tushare.forward_action_probe import probe


@pytest.fixture(autouse=True)
def inert_provider_limiter(monkeypatch):
    # These fixtures never contact a provider; no background event loop is needed.
    from quantos.data.tushare import acquisition

    monkeypatch.setattr(
        acquisition, "_default_limiter", lambda _: SimpleNamespace(try_acquire=lambda _: True)
    )


@pytest.mark.parametrize("mode", ["denied", "echo", "ok"])
def test_probe_independent_endpoints_and_secret_suppression(tmp_path, capsys, mode):
    secret = "synthetic-probe-private-value"

    class Client:
        def query(self, api_name, fields="", **kwargs):
            print(secret)
            if api_name == "anns_d" and mode == "denied":
                raise RuntimeError("权限 " + secret)
            columns = fields.split(",")
            result = pd.DataFrame(columns=columns)
            result.attrs["secret"] = secret
            if api_name == "anns_d" and mode == "echo":
                result.loc[0] = [secret] * len(columns)
            return result

    root = tmp_path / "probe"
    result = probe(root, date(2024, 1, 2), secret, client=Client())
    assert result["request_attempts"] == 2
    assert result["coverage_granted"] is False
    assert result["results"][0]["status"] == "ACQUIRED_NOT_ADMITTED"
    second = result["results"][1]
    if mode == "ok":
        assert second["status"] == "ACQUIRED_NOT_ADMITTED"
        assert second["rows"] == 0
    else:
        assert second["status"] == "FAILED"
        assert second["reason"] == (
            "PERMISSION_DENIED" if mode == "denied" else "RESPONSE_REJECTED"
        )
    assert secret not in capsys.readouterr().out
    assert all(secret.encode() not in p.read_bytes() for p in root.rglob("*") if p.is_file())
