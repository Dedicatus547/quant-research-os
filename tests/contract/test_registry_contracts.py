from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from quantos.contracts.provenance import RuntimeFingerprint, RuntimePackageVersion
from quantos.contracts.registry import (
    RegistryExperimentIndexEntry,
    RegistryExperimentManifest,
    RegistryIndex,
    RegistryStrategyRecord,
    StrategyVersionRecord,
)
from quantos.contracts.status import RunStatus, StrategyStatus, ValidationVerdict


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


def _manifest() -> RegistryExperimentManifest:
    runtime = _runtime()
    return RegistryExperimentManifest.create(
        experiment_id="registry-contract",
        authoring_spec_hash="1" * 64,
        strategy_spec_hash="2" * 64,
        validation_policy_hash="3" * 64,
        research_policy_hash="4" * 64,
        runtime_fingerprint_hash=runtime.content_hash,
        runtime_fingerprint=runtime,
        validation_report_hash="6" * 64,
        artifact_hashes=("6" * 64,),
        run_status=RunStatus.SUCCEEDED,
        verdict=ValidationVerdict.REJECT,
        canonical=True,
        limitations=("SINGLE_SOURCE_NON_VINTAGE",),
        registered_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_registry_experiment_manifest_self_hashes_and_rejects_incomplete_pass() -> None:
    manifest = _manifest()

    assert manifest.manifest_hash == manifest.content_hash
    incomplete = manifest.model_dump(mode="python", exclude={"manifest_hash", "verdict"})
    incomplete["runtime_fingerprint"] = manifest.runtime_fingerprint
    with pytest.raises(ValidationError, match="complete artifact chain"):
        RegistryExperimentManifest.create(
            **incomplete,
            verdict=ValidationVerdict.PASS,
        )
    with pytest.raises(ValidationError, match="manifest_hash"):
        RegistryExperimentManifest.model_validate(
            {**manifest.model_dump(), "manifest_hash": "f" * 64}
        )


def test_registry_index_and_strategy_versions_are_canonical() -> None:
    manifest = _manifest()
    version = StrategyVersionRecord(
        strategy_id="momentum",
        version=1,
        strategy_spec_hash=manifest.strategy_spec_hash,
        status=StrategyStatus.DRAFT,
        event_hashes=("7" * 64,),
    )
    experiment = RegistryExperimentIndexEntry(
        experiment_id=manifest.experiment_id,
        manifest_hash=manifest.manifest_hash,
        validation_report_hash=manifest.validation_report_hash,
        run_status=manifest.run_status,
        verdict=manifest.verdict,
        canonical=manifest.canonical,
        event_hashes=("8" * 64,),
    )
    index = RegistryIndex.create(
        experiments=(experiment,),
        strategies=(RegistryStrategyRecord(strategy_id="momentum", versions=(version,)),),
        source_manifest_hashes=(manifest.manifest_hash,),
        source_event_hashes=tuple(sorted(("7" * 64, "8" * 64))),
        generated_at=datetime(2024, 1, 2, tzinfo=UTC),
    )

    assert index.index_hash == index.content_hash
    with pytest.raises(ValidationError, match="contiguous"):
        RegistryStrategyRecord(
            strategy_id="momentum",
            versions=(version.model_copy(update={"version": 2}),),
        )
    with pytest.raises(ValidationError, match="index_hash"):
        RegistryIndex.model_validate({**index.model_dump(), "index_hash": "9" * 64})
