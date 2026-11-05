"""Bind configured native Qlib policies without running an exchange or backtest."""

from dataclasses import replace

import pandas as pd
import pytest

from quantos.research.personal_qlib import PersonalQlibExecutor
from test_personal_adjusted_service import _adjusted_setup
from test_personal_cash_service import _cash_setup
from test_personal_lifecycle_service import _request, _setup


@pytest.mark.parametrize("profile", ["lifecycle", "cash", "adjusted"])
@pytest.mark.parametrize("attack", ["valid", "limit_binding", "facts", "boundary"])
def test_native_config_requires_exact_daily_limits_and_lifecycle_roots(
    tmp_path, monkeypatch, profile, attack
):
    if profile == "lifecycle":
        service, _, _, manifest = _setup(tmp_path, monkeypatch)
        request = _request()
    elif profile == "cash":
        service, _, _, manifest, request = _cash_setup(tmp_path, monkeypatch)
    else:
        service, _, _, manifest, request, _ = _adjusted_setup(tmp_path, monkeypatch)
    prepared = service._prepared(service.prepare(request)["task_id"])
    binding = service.catalog[manifest.dataset_id]
    manifest = manifest.model_copy(
        update={"source_files": {"canonical/price_limits.parquet": "a" * 64}}
    )
    if attack == "limit_binding":
        manifest = manifest.model_copy(update={"kind": "market"})
    prepared = prepared.model_copy(update={"dataset_manifest": manifest})
    binding = replace(
        binding,
        manifest=manifest,
        snapshot_path=None if attack == "limit_binding" else tmp_path / "snapshot",
        lifecycle_path=None if attack == "facts" else tmp_path / "facts.json",
    )
    boundary = None if attack == "boundary" else tmp_path / "boundaries"
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2023-01-06"), "SH600000")], names=["datetime", "instrument"]
    )
    signal = pd.DataFrame({"score": [1.0]}, index=index)
    if attack != "valid":
        with pytest.raises(ValueError, match=r"canonical daily limits|bound facts"):
            PersonalQlibExecutor._config(prepared, signal, binding=binding, boundary_root=boundary)
        return
    config = PersonalQlibExecutor._config(prepared, signal, binding=binding, boundary_root=boundary)
    assert config["executor"]["module_path"] == "qlib.backtest.executor"
    exchange = config["backtest"]["exchange_kwargs"]["exchange"]
    assert exchange["class"] == "HS300OpenLimitExchange"
    assert exchange["kwargs"]["price_limits_sha256"] == "a" * 64
    assert exchange["kwargs"]["deal_price"] == "$open"
    strategy = config["strategy"]
    assert (
        strategy["class"]
        == {
            "lifecycle": "LifecycleBoundaryTopKStrategy",
            "cash": "CashRuntimeBoundaryTopKStrategy",
            "adjusted": "AdjustedUnitBoundaryTopKStrategy",
        }[profile]
    )
    assert strategy["kwargs"]["lifecycle_manifest_hash"] == manifest.lifecycle_manifest_hash
    if profile == "adjusted":
        assert strategy["kwargs"][
            "future_quote_binding"
        ] == manifest.future_quote_binding.model_dump(mode="json")
        assert strategy["kwargs"]["adjusted_unit_policy_hash"] == manifest.adjusted_unit_policy_hash
    if profile in {"cash", "adjusted"}:
        assert strategy["kwargs"]["native_source_hashes"] == manifest.native_source_hashes
