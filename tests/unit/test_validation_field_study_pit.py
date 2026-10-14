"""G2 dispatch and hard rejection for compact PIT evidence (controlled verifier)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from quantos.artifacts.store import sha256_file
from quantos.contracts.pit import PITGateId, SafeExpressionNode, SafeQlibExpressionSpec
from quantos.contracts.research_execution import (
    PITCrossSectionEvidenceCollection,
    PITCrossSectionEvidenceCollectionV3,
)
from quantos.contracts.status import ReasonCode
from quantos.research.qlib import QlibResearchError
from quantos.validation import ValidationService
from quantos.validation import service as validation_service


def _evidence(version: str, digest: str):
    """Schema-valid one-member proof; source reconstruction is intentionally mocked."""
    expression = SafeQlibExpressionSpec(
        expression_id="g2_dispatch",
        nodes=(SafeExpressionNode(node_id="close", operator="field", field_name="close"),),
        output_node_id="close",
    )
    instant = datetime(2026, 1, 5, 8, tzinfo=UTC)
    temporal = {
        "event_time": instant,
        "known_at": instant,
        "available_at": instant,
        "observed_at": instant,
        "evidence_level": "CONSERVATIVE_DERIVED",
        "policy_id": "controlled-g2-fixture",
    }
    payload = {
        "snapshot_hash": "1" * 64,
        "qlib_view_hash": "2" * 64,
        "expression_spec_hash": expression.content_hash,
        "expression": expression,
        "operator_delays": (),
        "universe_index": "000300.SH",
        "bundles": [
            {
                "snapshot_hash": "1" * 64,
                "expression_spec_hash": expression.content_hash,
                "universe_index": "000300.SH",
                "schedule": {
                    "signal_time": instant,
                    "signal_available_at": instant,
                    "decision_time": instant,
                    "execution_time": instant + timedelta(days=1),
                },
                "required_observations": 1,
                "source_window": (instant.date(),),
                "members": ("000001.SZ",),
                "source_sets": [
                    {
                        "table_name": "bars",
                        "logical_field_name": "close",
                        "source_field_name": "close",
                        "expected_row_count": 1,
                        "present_row_count": 1,
                        "missing_row_count": 0,
                        "row_set_hash": digest,
                        "maximum_temporal": temporal,
                    }
                ],
                "membership_set": {
                    "row_count": 1,
                    "row_set_hash": "4" * 64,
                    "maximum_temporal": temporal,
                },
                "output_temporal": temporal,
                "gates": [
                    {"gate_id": gate, "verdict": "PASS", "detail": "fixture"} for gate in PITGateId
                ],
            }
        ],
    }
    contract = (
        PITCrossSectionEvidenceCollectionV3
        if version == "v3"
        else PITCrossSectionEvidenceCollection
    )
    return contract.model_validate(payload)


@pytest.mark.parametrize("version", ["v2", "v3"])
@pytest.mark.parametrize("corrupted", [False, True], ids=["valid", "rebound-corrupt-digest"])
def test_g2_rebuilds_compact_evidence_and_preserves_hard_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str, corrupted: bool
) -> None:
    original = _evidence(version, "3" * 64)
    evidence = _evidence(version, "5" * 64) if corrupted else original
    signal_path = tmp_path / "signal"
    signal_path.mkdir()
    path = signal_path / "pit-evidence.json"
    path.write_text(evidence.model_dump_json(), encoding="utf-8")
    state = SimpleNamespace(
        locators=SimpleNamespace(
            pit_report_path=None,
            signal_path=signal_path,
            snapshot_path=tmp_path / "snapshot",
            qlib_view_path=tmp_path / "view",
        ),
        resolved=SimpleNamespace(pit_audit_evidence_hash=evidence.content_hash),
        snapshot=SimpleNamespace(snapshot_hash=evidence.snapshot_hash),
    )
    error = QlibResearchError(ReasonCode.ARTIFACT_CORRUPTED, "source digest cannot be reproduced")
    verifier = Mock(side_effect=error if corrupted else None)
    monkeypatch.setattr(validation_service, "verify_compact_pit_evidence", verifier)

    if corrupted:
        assert evidence.content_hash != original.content_hash
        with pytest.raises(validation_service._GateRejected) as rejected:
            ValidationService()._g2(state)
        assert rejected.value.reason_code is error.reason_code
        assert rejected.value.__cause__ is error
        references = rejected.value.evidence
    else:
        references = ValidationService()._g2(state).evidence

    verifier.assert_called_once_with(
        evidence, state.locators.snapshot_path, state.locators.qlib_view_path
    )
    assert len(references) == 1
    assert references[0].sha256 == sha256_file(path)
