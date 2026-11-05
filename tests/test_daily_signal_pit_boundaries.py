"""Legacy daily compilation rejects unavailable, partial or malformed market inputs."""

from datetime import date

import pandas as pd
import pytest

from quantos.research.personal_qlib import compile_daily_signals
from test_personal_research import panel, request, service


@pytest.mark.parametrize(
    "attack",
    [
        "duplicate",
        "empty",
        "naive",
        "missing_membership",
        "nonboolean",
        "missing_sector",
        "negative_volume",
        "benchmark",
        "unbound_dates",
        "outside",
        "no_prior",
        "warmup",
        "no_members",
        "partial",
    ],
)
def test_daily_compiler_does_not_infer_missing_pit_facts(tmp_path, attack):
    app = service(tmp_path)
    prepared = app._prepared(app.prepare(request())["task_id"])
    data = panel()
    if attack == "duplicate":
        data = pd.concat([data, data.iloc[:1]])
    elif attack == "empty":
        data = data.iloc[:0]
    elif attack == "naive":
        data["available_at"] = pd.to_datetime(data["trade_date"])
    elif attack == "missing_membership":
        data["is_mainboard"] = data["is_mainboard"].astype(object)
        data.loc[0, "is_mainboard"] = None
    elif attack == "nonboolean":
        data["is_st"] = 0
    elif attack == "missing_sector":
        data["sector_momentum_5"] = float("nan")
    elif attack == "negative_volume":
        data["volume"] = -1
    elif attack == "benchmark":
        data = data[data.qlib_id != prepared.request.benchmark]
    elif attack in {"unbound_dates", "outside", "no_prior", "warmup"}:
        changes = (
            {"start_date": None}
            if attack == "unbound_dates"
            else {"start_date": date(2030, 1, 1), "end_date": date(2030, 1, 5)}
            if attack == "outside"
            else {"start_date": data.trade_date.min() if attack == "no_prior" else date(2024, 1, 4)}
        )
        prepared = prepared.model_copy(
            update={"request": prepared.request.model_copy(update=changes)}
        )
    elif attack == "no_members":
        data["is_mainboard"] = False
    else:
        data = data[~((data.qlib_id == "SH600001") & (data.trade_date == date(2024, 2, 6)))]
    with pytest.raises(ValueError):
        compile_daily_signals(data, prepared)
