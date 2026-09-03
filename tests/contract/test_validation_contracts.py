from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from quantos.contracts.provenance import RuntimeFingerprint, RuntimePackageVersion
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.research import HardGateId, ValidationPolicy, ValidationSubperiod
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.validation import (
    VALIDATION_GATE_ORDER,
    GateResult,
    GateSeverity,
    ValidationArtifactFile,
    ValidationReport,
)


def _reference() -> ArtifactRef:
    return ArtifactRef(
        kind="evidence",
        sha256="a" * 64,
        size_bytes=1,
        media_type="application/json",
        logical_path="evidence/item.json",
    )


def _gates(verdict: ValidationVerdict = ValidationVerdict.PASS) -> tuple[GateResult, ...]:
    return tuple(
        GateResult(
            gate_id=gate_id,
            severity=GateSeverity.HARD,
            verdict=verdict,
            reason_code=ReasonCode.LOOK_AHEAD if verdict is ValidationVerdict.REJECT else None,
            reason="deterministic outcome",
            evidence=(_reference(),),
        )
        for gate_id in VALIDATION_GATE_ORDER
    )


def _files() -> tuple[ValidationArtifactFile, ...]:
    return tuple(
        ValidationArtifactFile(logical_path=name, sha256="b" * 64, size_bytes=1)
        for name in (
            "authoring-spec.json",
            "research-policy.json",
            "runtime-fingerprint.json",
            "validation-policy.json",
        )
    )


def test_gate_results_require_reasons_and_evidence() -> None:
    with pytest.raises(ValidationError, match="reason code"):
        GateResult(
            gate_id=VALIDATION_GATE_ORDER[0],
            severity=GateSeverity.HARD,
            verdict=ValidationVerdict.REJECT,
            reason="bad",
            evidence=(_reference(),),
        )
    with pytest.raises(ValidationError, match="immutable evidence"):
        GateResult(
            gate_id=VALIDATION_GATE_ORDER[0],
            severity=GateSeverity.HARD,
            verdict=ValidationVerdict.PASS,
            reason="bad",
        )


def test_validation_report_self_hashes_and_requires_complete_gate_order() -> None:
    report = ValidationReport.create(
        experiment_id="validation-contract",
        authoring_spec_hash="1" * 64,
        validation_policy_hash="2" * 64,
        research_policy_hash="3" * 64,
        runtime_fingerprint_hash="4" * 64,
        run_status=RunStatus.SUCCEEDED,
        verdict=ValidationVerdict.PASS,
        canonical=True,
        gates=_gates(),
        files=_files(),
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )

    assert report.report_hash == report.content_hash
    assert report.limitations == ("SINGLE_SOURCE_NON_VINTAGE",)
    with pytest.raises(ValidationError, match="G0-G10"):
        ValidationReport.model_validate(
            report.model_copy(update={"gates": tuple(reversed(report.gates))}).model_dump()
        )
    with pytest.raises(ValidationError, match="verdict does not match"):
        ValidationReport.model_validate(
            report.model_copy(update={"verdict": ValidationVerdict.REJECT}).model_dump()
        )


def test_runtime_fingerprint_requires_the_complete_sorted_numeric_runtime() -> None:
    packages = tuple(
        RuntimePackageVersion(name=name, version="1.0")
        for name in sorted(
            (
                "lightgbm",
                "numpy",
                "pandas",
                "pyarrow",
                "pydantic",
                "pyqlib",
                "ruamel.yaml",
                "typer",
            )
        )
    )
    fingerprint = RuntimeFingerprint(
        python_version="3.11.0",
        python_implementation="CPython",
        operating_system="Linux",
        operating_system_release="test",
        architecture="x86_64",
        libc="glibc-2.36",
        packages=packages,
    )

    assert fingerprint.content_hash
    with pytest.raises(ValidationError, match="complete, sorted"):
        RuntimeFingerprint.model_validate(
            {**fingerprint.model_dump(), "packages": tuple(reversed(packages))}
        )


def test_validation_policy_freezes_complete_robustness_axes() -> None:
    policy = ValidationPolicy(
        policy_id="synthetic",
        hard_gates=tuple(HardGateId),
        parameter_windows=(1, 2),
        parameter_top_k=(1,),
        subperiods=(
            ValidationSubperiod(
                period_id="first",
                start=date(2024, 1, 1),
                end=date(2024, 1, 31),
            ),
        ),
    )

    assert policy.cost_stress_multipliers == (1.0, 1.5, 2.0)
    with pytest.raises(ValidationError, match="cost stress"):
        policy.model_copy(update={"cost_stress_multipliers": (1.0, 2.0)}).__class__.model_validate(
            {**policy.model_dump(), "cost_stress_multipliers": (1.0, 2.0)}
        )
