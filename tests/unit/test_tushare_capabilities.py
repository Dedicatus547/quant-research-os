from datetime import date
from pathlib import Path

import pandas as pd

from quantos.application.capabilities import publish_capability_report
from quantos.data.tushare import EndpointProbeStatus, TushareSnapshotSource


class SuccessfulClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
        self.calls.append((api_name, fields, kwargs))
        columns = fields.split(",")
        if api_name == "trade_cal":
            return pd.DataFrame(
                [
                    {
                        "exchange": kwargs["exchange"],
                        "cal_date": "20240105",
                        "is_open": 1,
                        "pretrade_date": "20240104",
                    }
                ],
                columns=columns,
            )
        return pd.DataFrame([{column: _sample_value(column) for column in columns}])


class FailingStockStClient(SuccessfulClient):
    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
        if api_name == "stock_st":
            raise RuntimeError(f"permission denied for {self._token}")
        return super().query(api_name, fields, **kwargs)


class RateLimitedStockStClient(SuccessfulClient):
    def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
        if api_name == "stock_st":
            raise RuntimeError("每分钟最多访问该接口一次 account-sensitive-detail")
        return super().query(api_name, fields, **kwargs)


def _sample_value(column: str) -> object:
    if column in {"trade_date", "list_date"}:
        return "20240105"
    if column == "weight":
        return 100.0
    return "synthetic"


def test_all_required_endpoints_can_be_reported_available() -> None:
    client = SuccessfulClient()
    report = TushareSnapshotSource("secret", client=client).probe_capabilities(
        today=date(2024, 1, 8)
    )

    assert report.all_required_available
    assert report.probe_trade_date == date(2024, 1, 5)
    assert len(report.endpoints) == report.request_count == report.request_budget == 12
    assert len(client.calls) == 12
    assert sum(api_name == "trade_cal" for api_name, _, _ in client.calls) == 2
    assert {
        kwargs["list_status"] for api_name, _, kwargs in client.calls if api_name == "stock_basic"
    } == {"L", "D", "P"}
    assert {item.endpoint for item in report.endpoints} == {
        "stock_basic",
        "trade_cal",
        "daily",
        "adj_factor",
        "index_daily",
        "index_weight",
        "stock_st",
        "suspend_d",
        "stk_limit",
    }


def test_provider_error_is_redacted_and_blocks_release() -> None:
    token = "top-secret-token"
    report = TushareSnapshotSource(token, client=FailingStockStClient(token)).probe_capabilities(
        today=date(2024, 1, 8)
    )
    stock_st = next(item for item in report.endpoints if item.endpoint == "stock_st")

    assert not report.all_required_available
    assert stock_st.status is EndpointProbeStatus.PERMISSION_DENIED
    assert stock_st.error_message is not None
    assert token not in stock_st.error_message
    assert stock_st.error_message == "provider permission denied; raw message suppressed"


def test_capability_evidence_is_immutable_and_secret_free(tmp_path: Path) -> None:
    secret = "top-secret-token"
    report = TushareSnapshotSource(secret, client=FailingStockStClient(secret)).probe_capabilities(
        today=date(2024, 1, 8)
    )

    first = publish_capability_report(report, tmp_path)
    repeated = publish_capability_report(report, tmp_path)
    payload = (tmp_path / first.logical_path).read_text(encoding="utf-8")

    assert first == repeated
    assert secret not in payload
    assert first.sha256 == report.content_hash


def test_rate_limit_is_classified_without_persisting_provider_text() -> None:
    report = TushareSnapshotSource("secret", client=RateLimitedStockStClient()).probe_capabilities(
        today=date(2024, 1, 8)
    )
    stock_st = next(item for item in report.endpoints if item.endpoint == "stock_st")

    assert stock_st.status is EndpointProbeStatus.RATE_LIMITED
    assert stock_st.error_message == "provider rate limit reached; raw message suppressed"
    assert "account-sensitive-detail" not in report.model_dump_json()
