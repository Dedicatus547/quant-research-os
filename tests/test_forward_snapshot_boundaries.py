"""Snapshot-boundary failure checks with an in-process synthetic provider."""

import json
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from quantos.data.tushare import forward_snapshot as snapshot


@pytest.mark.parametrize(
    "sessions,start,bridge",
    [
        ([], date(2024, 1, 2), 1),
        ([date(2024, 1, 3), date(2024, 1, 2)], date(2024, 1, 3), 1),
        ([date(2024, 1, 2)] * 2, date(2024, 1, 2), 1),
        ([date(2024, 1, 2)], date(2024, 1, 1), 1),
        ([date(2024, 1, 2)], date(2024, 1, 2), 3),
    ],
)
def test_invalid_session_scope_rejected_before_provider(
    tmp_path, monkeypatch, sessions, start, bridge
):
    def unexpected(*_args, **_kwargs):
        pytest.fail("invalid scope must not construct a provider")

    monkeypatch.setattr(snapshot, "TushareSnapshotSource", unexpected)
    root = tmp_path / "acquisition"
    with pytest.raises(ValueError):
        snapshot.acquire(root, sessions, start, initial_bridge_sessions=bridge)
    assert not root.exists()


def test_missing_credential_creates_no_acquisition(tmp_path, monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    root = tmp_path / "acquisition"
    with pytest.raises(ValueError, match="credential unavailable"):
        snapshot.acquire(root, [date(2024, 1, 2)], date(2024, 1, 2))
    assert not root.exists()


@pytest.mark.parametrize(
    "mode,reason,attempts",
    [
        ("exception", "PROVIDER_UNAVAILABLE", 1),
        ("secret", "RESPONSE_REJECTED", 1),
        ("columns", "RESPONSE_REJECTED", 1),
        ("rows", "RESPONSE_REJECTED", 1),
        ("value", "RESPONSE_REJECTED", 1),
        ("scope", "REQUEST_SCOPE_REJECTED", 0),
    ],
)
def test_provider_failure_is_bounded_and_preserves_sanitized_exit(
    tmp_path, monkeypatch, capsys, mode, reason, attempts
):
    # This value is synthetic. Never read an operator credential in this test.
    sentinel = "synthetic-provider-sensitive-marker"
    monkeypatch.setenv("TUSHARE_TOKEN", sentinel)
    root = tmp_path / "acquisition"
    calls = []

    class Provider:
        def query(self, endpoint, *, fields, **params):
            calls.append((endpoint, params))
            # An attempt must be durable before the provider is entered.
            assert (root / "attempts" / "0001.json").is_file()
            print(sentinel)
            if mode == "exception":
                raise RuntimeError(sentinel)
            names = fields.split(",")
            if mode == "columns":
                return pd.DataFrame({"unexpected": [1]})
            if mode == "rows":
                return pd.DataFrame({name: [1] * 10001 for name in names})
            values = {name: [1] for name in names}
            values[names[0]] = [sentinel if mode == "secret" else {"unexpected": 1}]
            return pd.DataFrame(values)

    def source(_credential):
        print(sentinel)
        return SimpleNamespace(client=Provider())

    class Executor:
        def __init__(self, client, _policy):
            self.client = client

        def execute(self, plan, _root):
            request = plan.requests[0]
            self.client.query(
                "outside-scope" if mode == "scope" else request.endpoint,
                fields=",".join(request.fields),
                **request.params,
            )
            pytest.fail("rejected response must not reach snapshot construction")

    monkeypatch.setattr(snapshot, "TushareSnapshotSource", source)
    monkeypatch.setattr(snapshot, "TusharePlanExecutor", Executor)
    result = snapshot.acquire(root, [date(2024, 1, 2)], date(2024, 1, 2))
    assert result == {"status": "FAILED", "reason": reason, "request_attempts": attempts}
    assert json.loads((root / "exit.json").read_bytes()) == result
    assert len(calls) == attempts
    assert len(list((root / "attempts").glob("*.json"))) == attempts
    assert all(
        sentinel.encode() not in path.read_bytes() for path in root.rglob("*") if path.is_file()
    )
    output = capsys.readouterr()
    assert sentinel not in output.out + output.err
