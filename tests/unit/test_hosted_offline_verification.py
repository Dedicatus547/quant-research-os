"""Offline instrumentation rejects fabricated zero counters and weak environments."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from quantos.contracts.base import canonical_json_bytes
from quantos.infrastructure.hosted_offline_verification import verify_offline_observation
from quantos.infrastructure.hosted_verification import HostedQualificationError


@pytest.mark.parametrize("mode", ["RECEIPT_REUSE", "REEXECUTE"])
@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "network",
        "hash_seed",
        "bool_flags",
        "threads",
        "calls",
        "workflow",
        "report",
        "model_source",
    ],
)
def test_offline_observation_requires_native_counts_and_frozen_environment(
    mode: str, mutation: str | None
) -> None:
    identities = ("a" * 64, "b" * 64)
    facts = SimpleNamespace(
        report=SimpleNamespace(campaign_hash="c" * 64, content_hash="d" * 64),
        execution_identities=identities,
    )
    sources = SimpleNamespace(
        deployment=SimpleNamespace(profile=SimpleNamespace(content_hash="e" * 64))
    )
    calls = [] if mode == "RECEIPT_REUSE" else list(identities)
    value = {
        "schema_version": "hosted-offline-observation/v1",
        "mode": mode,
        "deployment_profile_hash": "e" * 64,
        "campaign_hash": "c" * 64,
        "report_hash": "d" * 64,
        "python_executable": "/install/python-seeded",
        "python_hash_seed_environment": "0",
        "network_attempts": [],
        "python_flags": {
            "isolated": 1,
            "ignore_environment": 1,
            "no_user_site": 1,
            "safe_path": True,
            "hash_randomization": 0,
        },
        "numeric_environment": {
            name: "1"
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
        "execute_calls": calls,
        "workflow_calls": calls,
    }
    if mutation == "network":
        value["network_attempts"] = ["SOCKET_CONNECT"]
    elif mutation == "hash_seed":
        value["python_hash_seed_environment"] = "random"
    elif mutation == "bool_flags":
        value["python_flags"]["isolated"] = True
    elif mutation == "threads":
        value["numeric_environment"]["OMP_NUM_THREADS"] = "2"
    elif mutation == "calls":
        value["execute_calls"] = [identities[0]]
    elif mutation == "workflow":
        value["workflow_calls"] = [identities[0], identities[0]]
    elif mutation == "report":
        value["report_hash"] = "f" * 64
    elif mutation == "model_source":
        value["schema_version"] = "host-self-asserted-offline/v1"
    if mutation is None:
        assert (
            verify_offline_observation(
                canonical_json_bytes(value), mode=mode, sources=sources, facts=facts
            )["mode"]
            == mode
        )
    else:
        with pytest.raises(HostedQualificationError):
            verify_offline_observation(
                canonical_json_bytes(value), mode=mode, sources=sources, facts=facts
            )
