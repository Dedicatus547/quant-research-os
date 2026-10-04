"""Large exact source exports retain bounded scanning and credential rejection."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.hosted_qualification import HostedManagerExport
from quantos.infrastructure.hosted_deployment import KnownValueGuard
from quantos.infrastructure.hosted_manager import guard_manager_export, publish_manager_export
from quantos.security import SecretArtifactRejected


def _deployment(root: Path, capability: bytes) -> SimpleNamespace:
    (root / "evidence").mkdir()
    (root / "source.bin").write_bytes(b"frozen-source")
    return SimpleNamespace(
        root=root,
        capability=capability,
        profile=SimpleNamespace(content_hash="a" * 64, exact_commit="b" * 40),
    )


def _mappings(count: int = 9000) -> tuple[tuple[str, str], ...]:
    directory = "/".join("frozen-component" for _ in range(20))
    return tuple(
        (f"cases/Q05/{ordinal:05d}/{directory}/artifact.json", "source.bin")
        for ordinal in range(count)
    )


def test_complete_large_matrix_publishes_with_existing_reader_bound(tmp_path: Path) -> None:
    deployment = _deployment(tmp_path, b"S" * 32)
    export = publish_manager_export(deployment, _mappings())
    data = (tmp_path / "evidence" / export.content_hash).read_bytes()
    assert 4_194_304 < len(data) < 16_777_216
    assert HostedManagerExport.model_validate_json(data) == export
    assert len(HostedManagerExport.model_validate_json(data).files) == 9000
    before = {path.name: path.read_bytes() for path in (tmp_path / "evidence").iterdir()}
    guard_manager_export(deployment, HostedManagerExport.model_validate_json(data))
    assert before == {path.name: path.read_bytes() for path in (tmp_path / "evidence").iterdir()}
    with pytest.raises(ArtifactIntegrityError, match="another frozen deployment"):
        guard_manager_export(
            deployment,
            HostedManagerExport.model_validate_json(data).model_copy(
                update={"exact_commit": "c" * 40}
            ),
        )
    # The general guard keeps its per-call cap; only typed exports use windows.
    with pytest.raises(ValueError, match="known-value scan byte cap"):
        KnownValueGuard(())(data)


def test_large_export_rejects_known_value_crossing_record_and_window_boundary(
    tmp_path: Path,
) -> None:
    deployment = _deployment(tmp_path, b"S" * 32)
    mappings = _mappings()
    export = publish_manager_export(deployment, mappings)
    data = export.canonical_bytes()
    edge = 1_048_576
    separator = data.rfind(b"},{", 0, edge)
    padding = edge - separator
    first, *rest = mappings
    mappings = ((first[0] + "x" * padding, first[1]), *rest)
    export = publish_manager_export(deployment, mappings)
    data = export.canonical_bytes()
    assert data[edge : edge + 3] == b"},{"
    value = data[edge - 16 : edge + 16]
    deployment.capability = value
    # Each decoded record and header independently lack this sensitive byte run.
    assert value not in data[:200]
    for record in HostedManagerExport.model_validate_json(data).files:
        assert value not in record.canonical_bytes()
    prior = {path.name: path.read_bytes() for path in (tmp_path / "evidence").iterdir()}
    with pytest.raises(SecretArtifactRejected):
        publish_manager_export(deployment, mappings)
    with pytest.raises(SecretArtifactRejected):
        guard_manager_export(deployment, HostedManagerExport.model_validate_json(data))
    assert prior == {path.name: path.read_bytes() for path in (tmp_path / "evidence").iterdir()}


def test_export_over_reader_limit_is_not_persisted(tmp_path: Path) -> None:
    deployment = _deployment(tmp_path, b"S" * 32)
    with pytest.raises(ValueError, match="manager export byte cap"):
        publish_manager_export(deployment, _mappings(35000))
    assert not tuple((tmp_path / "evidence").iterdir())


def test_known_value_in_record_is_rejected_before_publication(tmp_path: Path) -> None:
    deployment = _deployment(tmp_path, b"S" * 32)
    with pytest.raises(SecretArtifactRejected):
        publish_manager_export(
            deployment, (("cases/" + deployment.capability.hex(), "source.bin"),)
        )
    assert not tuple((tmp_path / "evidence").iterdir())
