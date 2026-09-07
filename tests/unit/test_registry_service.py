from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from typer.testing import CliRunner

from quantos.artifacts import sha256_file
from quantos.cli import app
from quantos.config import load_yaml_contract
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.events import EventType
from quantos.contracts.provenance import RuntimeFingerprint, RuntimePackageVersion
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ValidationPolicy,
)
from quantos.contracts.status import ReasonCode, RunStatus, StrategyStatus, ValidationVerdict
from quantos.contracts.validation import (
    VALIDATION_GATE_ORDER,
    GateResult,
    GateSeverity,
    ValidationArtifactFile,
    ValidationReport,
)
from quantos.registry import RegistryConflictError, RegistryError, RegistryService

ROOT = Path(__file__).parents[2]
NOW = datetime(2024, 2, 1, tzinfo=UTC)


def _runtime() -> RuntimeFingerprint:
    return RuntimeFingerprint(
        python_version="3.11.0",
        python_implementation="CPython",
        operating_system="Linux",
        operating_system_release="test",
        architecture="x86_64",
        libc="glibc-test",
        packages=tuple(
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
        ),
    )


def _evidence() -> ArtifactRef:
    return ArtifactRef(
        kind="test",
        sha256="a" * 64,
        size_bytes=1,
        media_type="application/json",
        logical_path="test/evidence.json",
    )


def _gates(status: RunStatus, verdict: ValidationVerdict) -> tuple[GateResult, ...]:
    results: list[GateResult] = []
    for index, gate_id in enumerate(VALIDATION_GATE_ORDER):
        if status is RunStatus.FAILED:
            results.append(
                GateResult(
                    gate_id=gate_id,
                    severity=GateSeverity.HARD,
                    verdict=ValidationVerdict.NOT_EVALUATED,
                    reason_code=(ReasonCode.QLIB_EXECUTION_FAILED if index == 0 else None),
                    reason="execution failed" if index == 0 else "not evaluated",
                )
            )
        elif verdict is ValidationVerdict.REJECT and index == 0:
            results.append(
                GateResult(
                    gate_id=gate_id,
                    severity=GateSeverity.HARD,
                    verdict=ValidationVerdict.REJECT,
                    reason_code=ReasonCode.SCHEMA_INVALID,
                    reason="rejected",
                    evidence=(_evidence(),),
                )
            )
        else:
            results.append(
                GateResult(
                    gate_id=gate_id,
                    severity=GateSeverity.HARD,
                    verdict=ValidationVerdict.NOT_EVALUATED,
                    reason="not evaluated",
                )
            )
    return tuple(results)


def _publish_report(
    tmp_path: Path,
    *,
    experiment_id: str,
    status: RunStatus = RunStatus.SUCCEEDED,
    verdict: ValidationVerdict = ValidationVerdict.REJECT,
    policy_suffix: str = "one",
) -> tuple[Path, ExperimentAuthoringSpec]:
    authoring = load_yaml_contract(
        ROOT / "configs" / "research" / "hs300_momentum_v1.yaml",
        ExperimentAuthoringSpec,
    ).model_copy(update={"experiment_id": experiment_id})
    research = load_yaml_contract(ROOT / "configs" / "research" / "policy_v1.yaml", ResearchPolicy)
    policy = load_yaml_contract(
        ROOT / "configs" / "validation" / "engineering_v1.yaml", ValidationPolicy
    ).model_copy(update={"policy_id": f"registry_{policy_suffix}"})
    runtime = _runtime()
    payloads = {
        "authoring-spec.json": authoring.canonical_bytes(),
        "research-policy.json": research.canonical_bytes(),
        "runtime-fingerprint.json": runtime.canonical_bytes(),
        "validation-policy.json": policy.canonical_bytes(),
    }
    files = tuple(
        ValidationArtifactFile(
            logical_path=name,
            sha256=__import__("hashlib").sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )
        for name, payload in sorted(payloads.items())
    )
    report = ValidationReport.create(
        experiment_id=experiment_id,
        authoring_spec_hash=authoring.content_hash,
        validation_policy_hash=policy.content_hash,
        research_policy_hash=research.content_hash,
        runtime_fingerprint_hash=runtime.content_hash,
        run_status=status,
        verdict=verdict,
        canonical=True,
        gates=_gates(status, verdict),
        files=files,
        created_at=NOW,
    )
    destination = tmp_path / "validation" / f"sha256-{report.report_hash}"
    destination.mkdir(parents=True)
    for name, payload in payloads.items():
        (destination / name).write_bytes(payload)
    (destination / "report.json").write_bytes(
        canonical_json_bytes(report.model_dump(mode="python"))
    )
    return destination, authoring


def test_registry_retains_rejected_and_failed_experiments_and_is_idempotent(
    tmp_path: Path,
) -> None:
    rejected_path, authoring = _publish_report(tmp_path, experiment_id="registry-rejected")
    failed_path, _ = _publish_report(
        tmp_path,
        experiment_id="registry-failed",
        status=RunStatus.FAILED,
        verdict=ValidationVerdict.NOT_EVALUATED,
    )
    service = RegistryService(tmp_path / "registry")

    rejected = service.register_experiment(rejected_path, registered_at=NOW)
    repeated = service.register_experiment(rejected_path, registered_at=NOW)
    failed = service.register_experiment(failed_path, registered_at=NOW)

    assert repeated.manifest == rejected.manifest
    assert repeated.event == rejected.event
    assert failed.manifest.run_status is RunStatus.FAILED
    assert [item.experiment_id for item in service.list_experiments()] == [
        "registry-failed",
        "registry-rejected",
    ]
    assert len(tuple((tmp_path / "registry" / "events").rglob("*.json"))) == 2
    assert service.get_experiment("registry-rejected").strategy_spec_hash == (
        authoring.strategy.content_hash
    )


def test_registry_detects_duplicate_ids_and_enforces_strategy_state_machine(
    tmp_path: Path,
) -> None:
    report_path, authoring = _publish_report(tmp_path, experiment_id="registry-rejected")
    conflicting_path, _ = _publish_report(
        tmp_path,
        experiment_id="registry-rejected",
        policy_suffix="different",
    )
    service = RegistryService(tmp_path / "registry")
    service.register_experiment(report_path, registered_at=NOW)

    with pytest.raises(RegistryConflictError) as conflict:
        service.register_experiment(conflicting_path, registered_at=NOW)
    assert conflict.value.reason_code is ReasonCode.DUPLICATE_ID_CONFLICT

    draft = service.register_strategy(
        "hs300-momentum", authoring.strategy.content_hash, version=1, occurred_at=NOW
    )
    assert draft.status is StrategyStatus.DRAFT
    assert (
        service.register_strategy(
            "hs300-momentum", authoring.strategy.content_hash, version=1, occurred_at=NOW
        )
        == draft
    )
    with pytest.raises(RegistryConflictError):
        service.register_strategy("hs300-momentum", "f" * 64, version=1, occurred_at=NOW)
    with pytest.raises(RegistryError, match="without gaps"):
        service.register_strategy(
            "hs300-momentum", authoring.strategy.content_hash, version=3, occurred_at=NOW
        )

    validating = service.append_strategy_event(
        "hs300-momentum",
        1,
        EventType.VALIDATION_STARTED,
        "registry-rejected",
        occurred_at=NOW,
    )
    assert validating.status is StrategyStatus.VALIDATING
    rejected = service.append_strategy_event(
        "hs300-momentum",
        1,
        EventType.VALIDATION_REJECTED,
        "registry-rejected",
        occurred_at=NOW,
    )
    assert rejected.status is StrategyStatus.REJECTED
    with pytest.raises(RegistryError) as invalid:
        service.append_strategy_event(
            "hs300-momentum",
            1,
            EventType.STRATEGY_VERSION_VALIDATED,
            "registry-rejected",
            occurred_at=NOW,
        )
    assert invalid.value.reason_code is ReasonCode.STATE_TRANSITION_INVALID


def test_registry_serializes_conflicting_strategy_writers(tmp_path: Path) -> None:
    service = RegistryService(tmp_path / "registry-concurrent")
    barrier = Barrier(2)

    def register(digest: str) -> str:
        barrier.wait()
        try:
            service.register_strategy("concurrent", digest, version=1, occurred_at=NOW)
        except RegistryConflictError:
            return "conflict"
        return "published"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(register, ("a" * 64, "b" * 64)))

    assert sorted(outcomes) == ["conflict", "published"]
    versions = service.get_strategy_versions("concurrent")
    assert len(versions) == 1
    assert versions[0].strategy_spec_hash in {"a" * 64, "b" * 64}
    assert len(tuple((tmp_path / "registry-concurrent" / "events").rglob("*.json"))) == 1


def test_registry_rebuild_detects_tampering_and_recovers_writer_temporary_files(
    tmp_path: Path,
) -> None:
    report_path, _ = _publish_report(tmp_path, experiment_id="registry-tamper")
    root = tmp_path / "registry"
    service = RegistryService(root)
    result = service.register_experiment(report_path, registered_at=NOW)
    original_index_hash = result.index.index_hash
    temporary = root / "events" / "experiments" / "registry-tamper" / ".event.json.partial"
    temporary.write_bytes(b"partial")

    assert service.verify().index_hash == original_index_hash
    assert service.recover_partial_writes() == (temporary.relative_to(root).as_posix(),)
    assert not temporary.exists()

    manifest_path = next((root / "manifests").rglob("*.json"))
    manifest_bytes = manifest_path.read_bytes()
    manifest_path.write_bytes(manifest_bytes + b"\n")
    with pytest.raises(RegistryError) as corrupted:
        service.verify()
    assert corrupted.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED
    manifest_path.write_bytes(manifest_bytes)

    event_path = next((root / "events").rglob("*.json"))
    event_path.write_bytes(event_path.read_bytes() + b"\n")
    with pytest.raises(RegistryError) as corrupted_event:
        service.verify()
    assert corrupted_event.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED
    assert sha256_file(report_path / "report.json")


def test_registry_cli_registers_transitions_lists_shows_verifies_and_recovers(
    tmp_path: Path,
) -> None:
    report_path, authoring = _publish_report(tmp_path, experiment_id="registry-cli")
    root = tmp_path / "registry"
    runner = CliRunner()

    registered = runner.invoke(
        app,
        [
            "registry",
            "register-experiment",
            str(report_path),
            "--registry-root",
            str(root),
        ],
    )
    assert registered.exit_code == 0
    assert json.loads(registered.stdout)["verdict"] == "REJECT"

    strategy = runner.invoke(
        app,
        [
            "registry",
            "register-strategy",
            "cli-momentum",
            authoring.strategy.content_hash,
            "--version",
            "1",
            "--registry-root",
            str(root),
        ],
    )
    assert strategy.exit_code == 0
    assert json.loads(strategy.stdout)["strategy"]["status"] == "DRAFT"
    for event_type, expected in (
        ("ValidationStarted", "VALIDATING"),
        ("ValidationRejected", "REJECTED"),
    ):
        transitioned = runner.invoke(
            app,
            [
                "registry",
                "transition",
                "cli-momentum",
                "1",
                event_type,
                "registry-cli",
                "--registry-root",
                str(root),
            ],
        )
        assert transitioned.exit_code == 0
        assert json.loads(transitioned.stdout)["strategy"]["status"] == expected

    listed = runner.invoke(app, ["registry", "list", "--registry-root", str(root)])
    shown_experiment = runner.invoke(
        app, ["registry", "show", "registry-cli", "--registry-root", str(root)]
    )
    shown_strategy = runner.invoke(
        app, ["registry", "show", "cli-momentum", "--registry-root", str(root)]
    )
    verified = runner.invoke(app, ["registry", "verify", str(root)])
    assert json.loads(listed.stdout)["index"]["experiments"][0]["experiment_id"] == ("registry-cli")
    assert json.loads(shown_experiment.stdout)["kind"] == "experiment"
    assert json.loads(shown_strategy.stdout)["kind"] == "strategy"
    assert json.loads(verified.stdout)["experiment_count"] == 1

    invalid = runner.invoke(
        app,
        [
            "registry",
            "transition",
            "cli-momentum",
            "1",
            "not-an-event",
            "registry-cli",
            "--registry-root",
            str(root),
        ],
    )
    assert invalid.exit_code == 17
    assert json.loads(invalid.stdout)["reason_code"] == "SCHEMA_INVALID"

    temporary = root / "events" / "strategies" / "cli-momentum" / ".event.json.partial"
    temporary.write_bytes(b"partial")
    recovered = runner.invoke(app, ["registry", "recover", str(root)])
    assert recovered.exit_code == 0
    assert json.loads(recovered.stdout)["count"] == 1


def test_registry_query_and_error_paths_are_fail_closed(tmp_path: Path) -> None:
    empty = RegistryService(tmp_path / "empty")
    assert empty.rebuild_index(now=NOW).experiments == ()
    assert empty.recover_partial_writes() == ()
    with pytest.raises(RegistryError):
        empty.get_experiment("missing")
    with pytest.raises(RegistryError):
        empty.get_strategy("missing")
    with pytest.raises(RegistryError) as unsafe:
        empty.get_strategy("../unsafe")
    assert unsafe.value.reason_code is ReasonCode.SCHEMA_INVALID

    report_path, authoring = _publish_report(tmp_path, experiment_id="registry-errors")
    root = tmp_path / "registry-errors-root"
    service = RegistryService(root)
    service.register_experiment(report_path, registered_at=NOW)
    service.register_strategy(
        "error-momentum", authoring.strategy.content_hash, version=1, occurred_at=NOW
    )
    with pytest.raises(RegistryError) as invalid_hash:
        service.register_strategy("new-strategy", "invalid", version=1, occurred_at=NOW)
    assert invalid_hash.value.reason_code is ReasonCode.SCHEMA_INVALID
    with pytest.raises(RegistryError) as unsupported:
        service.append_strategy_event(
            "error-momentum",
            1,
            EventType.OOS_ACCESSED,
            "registry-errors",
            occurred_at=NOW,
        )
    assert unsupported.value.reason_code is ReasonCode.STATE_TRANSITION_INVALID
    with pytest.raises(RegistryError):
        service.get_strategy("error-momentum", version=2)

    service.register_strategy(
        "error-momentum", authoring.strategy.content_hash, version=2, occurred_at=NOW
    )
    assert [item.version for item in service.get_strategy_versions("error-momentum")] == [1, 2]
    assert service.get_strategy("error-momentum").version == 2

    unexpected = root / "unexpected.json"
    unexpected.write_bytes(b"{}")
    with pytest.raises(RegistryError) as corrupted:
        service.verify()
    assert corrupted.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    runner = CliRunner()
    (tmp_path / "empty").mkdir()
    missing = runner.invoke(
        app, ["registry", "show", "not-found", "--registry-root", str(tmp_path / "empty")]
    )
    assert missing.exit_code == 18
    assert json.loads(missing.stdout)["reason_code"] == "SOURCE_INCOMPLETE"
    invalid_artifact = tmp_path / "invalid-report"
    invalid_artifact.mkdir()
    failed_registration = runner.invoke(
        app,
        [
            "registry",
            "register-experiment",
            str(invalid_artifact),
            "--registry-root",
            str(tmp_path / "invalid-registry"),
        ],
    )
    assert failed_registration.exit_code == 17
    assert json.loads(failed_registration.stdout)["reason_code"] == "ARTIFACT_CORRUPTED"
    failed_verify = runner.invoke(app, ["registry", "verify", str(root)])
    assert failed_verify.exit_code == 18
    assert json.loads(failed_verify.stdout)["reason_code"] == "ARTIFACT_CORRUPTED"
