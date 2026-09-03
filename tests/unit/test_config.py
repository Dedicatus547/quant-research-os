from pathlib import Path

import pytest
from ruamel.yaml.constructor import DuplicateKeyError

from quantos.config import ConfigError, load_yaml_contract, load_yaml_mapping
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ValidationPolicy,
)
from quantos.contracts.snapshot import SnapshotBuildSpec


def test_load_yaml_mapping_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text("schema_version: one\nschema_version: two\n", encoding="utf-8")

    with pytest.raises(DuplicateKeyError):
        load_yaml_mapping(path)


def test_load_yaml_mapping_requires_object_root(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- one\n- two\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="root must be a mapping"):
        load_yaml_mapping(path)


def test_repository_configs_are_safe_mappings() -> None:
    root = Path(__file__).parents[2]
    for path in sorted((root / "configs").rglob("*.yaml")):
        assert "schema_version" in load_yaml_mapping(path)


def test_repository_configs_validate_against_their_public_contracts() -> None:
    root = Path(__file__).parents[2] / "configs"
    load_yaml_contract(root / "tushare" / "snapshot.yaml", SnapshotBuildSpec)
    load_yaml_contract(root / "research" / "hs300_momentum_v1.yaml", ExperimentAuthoringSpec)
    load_yaml_contract(root / "research" / "policy_v1.yaml", ResearchPolicy)
    for path in sorted((root / "validation").glob("*.yaml")):
        load_yaml_contract(path, ValidationPolicy)
