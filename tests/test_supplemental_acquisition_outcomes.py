"""Offline providers exercise bounded acquisition and retained failure originals."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from quantos.data.tushare import acquisition
from quantos.data.tushare import dividend_acquisition as dividend
from quantos.data.tushare import lifecycle_acquisition as lifecycle


@pytest.fixture(autouse=True)
def inert_limiter(monkeypatch):
    monkeypatch.setattr(
        acquisition, "_default_limiter", lambda _: SimpleNamespace(try_acquire=lambda _: True)
    )


@pytest.mark.parametrize("module", [dividend, lifecycle])
@pytest.mark.parametrize(
    "case", ["empty", "permission", "rate", "transport", "provider", "missing"]
)
def test_supplemental_acquisition_records_each_attempt_without_claiming_coverage(
    tmp_path, monkeypatch, module, case
):
    # Provider is inert; avoid the real limiter's background event loop.
    monkeypatch.setattr(
        acquisition, "_default_limiter", lambda _: SimpleNamespace(try_acquire=lambda _: True)
    )
    calls = []
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    if case != "missing":
        monkeypatch.setenv("TUSHARE_TOKEN", "SYNTHETIC_INERT_PROVIDER_VALUE")

    def query(endpoint, fields, **params):
        calls.append((endpoint, params))
        errors = {
            "permission": RuntimeError("permission denied"),
            "rate": RuntimeError("rate limit"),
            "transport": ConnectionError("offline transport failure"),
            "provider": RuntimeError("opaque failure"),
        }
        if case in errors:
            raise errors[case]
        return pd.DataFrame(columns=fields.split(","))

    monkeypatch.setattr(
        module,
        "TushareSnapshotSource",
        lambda _: SimpleNamespace(client=SimpleNamespace(query=query)),
    )
    root = tmp_path / "attempt"
    result = module.acquire(root)
    stored = json.loads((root / "exit.json").read_bytes())
    assert stored["request_count"] == len(calls)
    expected = 2 if module is dividend else 6
    assert len(calls) == (0 if case == "missing" else 1 if case == "transport" else expected)
    assert result["status"] == (
        "BLOCKED" if case == "missing" else "COMPLETE" if case == "empty" else "INCOMPLETE"
    )
    if case != "missing" or module is dividend:
        assert len(stored["requests"]) == expected
        for index, row in enumerate(stored["requests"], 1):
            retained = json.loads((root / f"request-{index:02d}/exit.json").read_bytes())
            assert retained == row
            assert (root / f"request-{index:02d}/plan.json").is_file()
        if case == "transport":
            assert all(row["status"] == "NOT_ATTEMPTED" for row in stored["requests"][1:])
        if case == "empty":
            assert all(row["response_rows"] == 0 for row in stored["requests"])
            assert stored["historical_vendor_vintage"] is False
            if module is dividend:
                assert stored["coverage"] == "UNKNOWN"
    with pytest.raises(FileExistsError):
        module.acquire(root)


@pytest.mark.parametrize("failure", ["initialization", "interrupt", "writer"])
def test_dividend_failure_is_retained_and_does_not_invent_success(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("TUSHARE_TOKEN", "SYNTHETIC_INERT_PROVIDER_VALUE")

    def source(_):
        if failure == "initialization":
            raise ConnectionError("offline")
        return SimpleNamespace(client=None)

    monkeypatch.setattr(dividend, "TushareSnapshotSource", source)

    def execute(*_):
        if failure == "interrupt":
            raise KeyboardInterrupt
        raise OSError("synthetic writer failure")

    monkeypatch.setattr(dividend.TusharePlanExecutor, "execute", execute)
    result = dividend.acquire(tmp_path / "attempt")
    assert result["request_count"] == 0
    assert (
        result["requests"][0]["reason"]
        == {
            "initialization": "TRANSPORT_UNAVAILABLE",
            "interrupt": "INTERRUPTED",
            "writer": "ACQUISITION_FAILED",
        }[failure]
    )
    assert result["requests"][1]["status"] == (
        "BLOCKED"
        if failure == "initialization"
        else "NOT_ATTEMPTED"
        if failure == "interrupt"
        else "FAILED"
    )
