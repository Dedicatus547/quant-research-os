"""Future calendar acquisition retains checkpoints without provider secrets."""

from datetime import date

import pandas as pd
import pytest

from quantos.data.forward_calendar import observed_calendar
from quantos.data.tushare.forward_calendar import acquire_calendar

SYNTHETIC_SECRET = "synthetic-private-value-not-a-real-credential"


class FakeClient:
    def __init__(self, mode):
        self.mode = mode
        self.calls = 0

    def query(self, api_name, fields="", **params):
        self.calls += 1
        assert api_name == "trade_cal"
        print(SYNTHETIC_SECRET)
        if self.mode == "error" and self.calls == 2:
            raise RuntimeError(SYNTHETIC_SECRET)
        result = pd.DataFrame(
            [
                {
                    "exchange": params["exchange"],
                    "cal_date": "20261105",
                    "is_open": 1,
                    "pretrade_date": "20261104",
                }
            ]
        )
        result.attrs["provider_secret"] = SYNTHETIC_SECRET
        if self.mode == "echo":
            result.loc[0, "pretrade_date"] = SYNTHETIC_SECRET
        return result


@pytest.mark.parametrize("mode", ["ok", "error", "echo"])
def test_calendar_safe_output_and_independent_checkpoints(tmp_path, capsys, mode):
    client = FakeClient(mode)
    root = tmp_path / "calendar"
    result = acquire_calendar(
        root, date(2026, 11, 1), date(2026, 11, 30), SYNTHETIC_SECRET, client=client
    )
    assert SYNTHETIC_SECRET not in capsys.readouterr().out
    assert all(
        SYNTHETIC_SECRET.encode() not in p.read_bytes() for p in root.rglob("*") if p.is_file()
    )
    assert result["request_attempts"] == client.calls
    if mode == "ok":
        assert result["status"] == "ACQUIRED_NOT_VALIDATED"
        assert len(list((root / "checkpoints").glob("*.json"))) == 2
    else:
        assert result["status"] == "FAILED"
        assert len(list((root / "checkpoints").glob("*.json"))) == (1 if mode == "error" else 0)
    with pytest.raises(FileExistsError):
        acquire_calendar(
            root, date(2026, 11, 1), date(2026, 11, 30), SYNTHETIC_SECRET, client=client
        )


def test_calendar_authority_rejects_partial_response_and_modified_raw(tmp_path):
    root = tmp_path / "partial"
    result = acquire_calendar(
        root, date(2026, 11, 1), date(2026, 11, 30), SYNTHETIC_SECRET, client=FakeClient("ok")
    )
    with pytest.raises(ValueError, match="requested bounds"):
        observed_calendar(root, result["ledger_hash"])
    root = tmp_path / "complete"
    result = acquire_calendar(
        root, date(2026, 11, 5), date(2026, 11, 5), SYNTHETIC_SECRET, client=FakeClient("ok")
    )
    assert observed_calendar(root, result["ledger_hash"])["open_sessions"] == (date(2026, 11, 5),)
    raw = next((root / "raw-requests").glob("*.parquet"))
    raw.write_bytes(raw.read_bytes() + b"modified")
    with pytest.raises(Exception, match=r"hash|digest|integrity"):
        observed_calendar(root, result["ledger_hash"])
