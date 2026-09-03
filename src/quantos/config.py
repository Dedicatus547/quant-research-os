"""Strict YAML loading for human-authored specifications."""

from collections.abc import Callable
from io import TextIOBase
from pathlib import Path
from typing import TypeVar, cast

from pydantic import BaseModel
from ruamel.yaml import YAML


class ConfigError(ValueError):
    """Raised when a YAML document is not an object specification."""


def load_yaml_mapping(path: Path) -> dict[str, object]:
    yaml = YAML(typ="safe")
    yaml.allow_duplicate_keys = False
    with path.open("r", encoding="utf-8") as stream:
        # ruamel.yaml does not publish a complete type for YAML.load; contain that gap here.
        loader = cast(Callable[[TextIOBase], object], yaml.load)  # pyright: ignore[reportUnknownMemberType]
        payload = loader(stream)
    if not isinstance(payload, dict):
        raise ConfigError("configuration root must be a mapping with string keys")
    mapping = cast(dict[object, object], payload)
    if not all(isinstance(key, str) for key in mapping):
        raise ConfigError("configuration root must be a mapping with string keys")
    return cast(dict[str, object], mapping)


ContractT = TypeVar("ContractT", bound=BaseModel)


def load_yaml_contract(path: Path, contract_type: type[ContractT]) -> ContractT:
    """Load a duplicate-key-safe YAML mapping and validate its public schema."""

    return contract_type.model_validate(load_yaml_mapping(path))
