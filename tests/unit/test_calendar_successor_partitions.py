"""Calendar append ranges must not collide solely because the exchange repeats."""

import pandas as pd
import pytest

from quantos.data.tushare.acquisition import (
    TushareAcquisitionError,
    TushareExecutionPolicy,
    TusharePlanExecutor,
    TushareRequest,
    TushareRequestPlan,
)


class Limiter:
    def try_acquire(self, *_args):
        return True


def request(sequence, exchange, start, end):
    return TushareRequest(
        sequence=sequence,
        endpoint="trade_cal",
        params={"exchange": exchange, "start_date": start, "end_date": end},
        fields=("exchange", "cal_date", "is_open", "pretrade_date"),
        primary_key=("exchange", "cal_date"),
    )


@pytest.mark.parametrize(
    "case", ["append", "other-exchange", "overlap", "wrong-date", "wrong-exchange"]
)
def test_calendar_successor_ranges_and_actual_rows(tmp_path, case):
    one = request(1, "SSE", "20261102", "20261103")
    two = request(
        2,
        "SZSE" if case == "other-exchange" else "SSE",
        "20261103" if case in {"overlap", "other-exchange"} else "20261104",
        "20261105",
    )
    plan = TushareRequestPlan(build_spec_hash="a" * 64, requests=(one, two))

    class Client:
        def query(self, api_name, fields="", **params):
            exchange = "OTHER" if case == "wrong-exchange" else params["exchange"]
            day = "20261101" if case == "wrong-date" else params["start_date"]
            return pd.DataFrame([[exchange, day, 1, "20261030"]], columns=fields.split(","))

    executor = TusharePlanExecutor(
        Client(),
        TushareExecutionPolicy(policy_id="synthetic", requests_per_minute=60, max_attempts=1),
        limiter=Limiter(),
    )
    if case in {"append", "other-exchange"}:
        first = executor.execute(plan, tmp_path)
        assert len(first.entries) == 2

        class NoNetwork:
            def query(self, *args, **kwargs):
                raise AssertionError("completed responses must be reused")

        reused = TusharePlanExecutor(NoNetwork(), executor._policy, limiter=Limiter()).execute(
            plan, tmp_path
        )
        assert reused.content_hash == first.content_hash
    else:
        with pytest.raises(TushareAcquisitionError, match=r"calendar|primary key"):
            executor.execute(plan, tmp_path)
