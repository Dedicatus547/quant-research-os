"""Daily orchestration with retained synthetic HTTP originals and offline assessment."""

import copy
import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from quantos.contracts.base import canonical_json_bytes
from quantos.data.tushare import forward_daily as daily
from test_forward_action_coverage import sources as sources


@pytest.fixture
def acquisition(sources, monkeypatch):
    root, initial, save, _ = sources
    state = SimpleNamespace(
        price_status="SUCCEEDED",
        price_attempts=4,
        dividend_complete=True,
        response_missing=False,
        http_status=200,
        empty=False,
        document=False,
        calls=[],
        builds=[],
    )
    campaign = {
        "root": str(root),
        "calendar_sessions": ["2024-01-04", "2024-01-05", "2024-01-08"],
        "signal_dates": ["2024-01-08"],
        "execution_dates": ["2024-01-09"],
        "qlib_source_root": str(root / "qlib-source"),
        "calendar_root": str(root / "calendar"),
        "calendar_ledger_hash": "a" * 64,
    }
    previous = {
        "day": "2024-01-05",
        "acquisition_root": str(root / "prior"),
        "action_inputs": initial,
    }

    def prices(output, sessions, warmup, **kwargs):
        state.price_args = sessions, warmup, kwargs
        save(
            str(output.relative_to(root))
            + "/snapshots/sha256-"
            + "b" * 64
            + "/canonical/index_membership.parquet",
            (root / "members.parquet").read_bytes(),
        )
        return {
            "status": state.price_status,
            "request_attempts": state.price_attempts,
            "snapshot": {"sha256": "b" * 64},
        }

    def dividends(output, *_):
        if not state.response_missing:
            save(
                str(output.relative_to(root)) + "/600000.SH/provider-response.json",
                json.loads((root / "dividends.json").read_bytes()),
            )
        save(
            str(output.relative_to(root)) + "/600000.SH/exit.json",
            {"received_at": datetime(2024, 1, 8, 15, tzinfo=UTC)},
        )
        return {
            "request_attempts": 1,
            "completed_securities": int(state.dividend_complete),
            "expected_securities": 1,
            "results": [{"instrument_id": "600000.SH"}],
        }

    class Client:
        def __init__(self, hosts):
            assert "query.sse.com.cn" in hosts

        def send(self, request, **limits):
            state.calls.append((request, limits))
            # Attempt is durable before the provider is entered.
            assert len(list((root / "days").rglob("attempt.json"))) == len(state.calls)
            if request.contract.purpose == "DOCUMENT":
                body = b"synthetic original for unsupported action"
            elif request.contract.venue == "SSE":
                body = canonical_json_bytes(
                    {
                        "pageHelp": {
                            "pageNo": 1,
                            "pageCount": 0 if state.empty else 1,
                            "total": 0 if state.empty else 1,
                        },
                        "result": []
                        if state.empty
                        else [
                            [
                                {
                                    "ORG_BULLETIN_ID": "new-sse",
                                    "SECURITY_CODE": "600000",
                                    "URL": "/new.pdf",
                                    "SSEDATE": "2024-01-08",
                                    "TITLE": "吸收合并实施公告"
                                    if state.document
                                    else "董事会决议公告",
                                }
                            ]
                        ],
                    }
                )
            else:
                body = canonical_json_bytes({"announceCount": 0, "data": []})
            return SimpleNamespace(
                body=body,
                status_code=state.http_status,
                observed_at=datetime(2024, 1, 8, 15, tzinfo=UTC),
            )

    class Builder:
        def build(self, snapshot, output, source):
            state.builds.append((snapshot, output, source))
            return SimpleNamespace(path=root / "native-view")

    monkeypatch.setattr(daily, "acquire_snapshot", prices)
    monkeypatch.setattr(daily, "acquire_dividends", dividends)
    monkeypatch.setattr(daily, "UrllibHttpClient", Client)
    monkeypatch.setattr(daily.time, "sleep", lambda _: None)
    monkeypatch.setattr(daily, "QlibViewBuilder", Builder)
    monkeypatch.setattr(daily, "extend_qlib_calendar", lambda *args: root / "forward-view")
    monkeypatch.setattr(daily, "build_forward_catalog", lambda *args: {"synthetic": True})
    return root, campaign, previous, state


@pytest.mark.parametrize("empty", [False, True])
def test_one_empty_response_is_retained_as_zero_inventory(acquisition, empty):
    root, campaign, previous, state = acquisition
    state.empty = empty
    before = copy.deepcopy(previous)
    result = daily.acquire_day(campaign, previous, date(2024, 1, 8))
    assert len(state.calls) == 2
    assert result["request_attempts"] == 7
    assert result["assessment"]["status"] == "SUPPORTED_IN_DECLARED_SOURCE_SCOPE"
    assert result["assessment"]["announcement_counts"] == {"SSE": 1 if empty else 2, "SZSE": 1}
    assert state.price_args[2]["initial_bridge_sessions"] == 2
    assert state.price_args[0][-1] == date(2024, 1, 8)
    assert previous == before
    assert len(state.builds) == 1
    retained = root / "days/2024-01-08/acquisition-result.json"
    original = retained.read_bytes()
    with pytest.raises(FileExistsError):
        daily.acquire_day(campaign, previous, date(2024, 1, 8))
    assert retained.read_bytes() == original
    assert len(state.calls) == 2


@pytest.mark.parametrize(
    "failure,match",
    [
        ("price", "snapshot acquisition failed"),
        ("dividend", "inventory incomplete"),
        ("missing", "response unavailable"),
        ("http", "HTTP response rejected"),
        ("budget", "attempt budget exhausted"),
    ],
)
def test_incomplete_day_cannot_publish_a_successor(acquisition, failure, match):
    root, campaign, previous, state = acquisition
    if failure == "price":
        state.price_status = "FAILED"
    elif failure == "dividend":
        state.dividend_complete = False
    elif failure == "missing":
        state.response_missing = True
    elif failure == "http":
        state.http_status = 503
    else:
        state.price_attempts = 499
    with pytest.raises(RuntimeError, match=match):
        daily.acquire_day(campaign, previous, date(2024, 1, 8))
    assert not (root / "days/2024-01-08/acquisition-result.json").exists()
    assert not state.builds
    assert len(state.calls) == int(failure == "http")
    if failure == "http":
        assert (root / "days/2024-01-08/announcements/SSE/page-001/response.bin").exists()
        assert not (root / "days/2024-01-08/announcements/SSE/page-001/response.json").exists()


def test_unknown_action_original_is_retained_without_admission(acquisition):
    root, campaign, previous, state = acquisition
    state.document = True
    result = daily.acquire_day(campaign, previous, date(2024, 1, 8))
    assert result["request_attempts"] == 8
    assert len(state.calls) == 3
    assert state.calls[-1][1]["max_response_bytes"] == 8388608
    assert result["assessment"]["status"] == "UNSUPPORTED_OR_UNKNOWN"
    assert result["assessment"]["unresolved"][0]["reason"] == "OTHER_ACTION_REQUIRES_SOURCE_RULE"
    doc = result["action_inputs"]["documents"]["new-sse"]
    assert (
        json.loads((root / doc["receipt"]["path"]).read_bytes())["status"]
        == "RETAINED_NOT_ADMITTED"
    )
