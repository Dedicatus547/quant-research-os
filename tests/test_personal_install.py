"""Only the known managed predecessor may be upgraded; other settings survive."""

import importlib.util
import json
import os
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "personal_installer", REPO / "scripts/install_personal_research.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_upgrade_retains_other_configuration_mode_and_private_backup(tmp_path):
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text(
        'model = "keep-user-choice"\n[mcp_servers.unrelated]\ncommand = "keep-command"\n'
    )
    os.chmod(config, 0o640)
    product = tmp_path / "product"
    product.mkdir()
    python = REPO / ".tools/personal-research-mcp-1.26.0/bin/python"
    module.install(REPO, product, python, tmp_path, "install")
    # Reconstruct the exactly known predecessor, rather than accepting arbitrary settings.
    config.write_text(
        config.read_text().replace("tool_timeout_sec = 3600", "tool_timeout_sec = 120")
    )
    before = config.read_bytes()
    receipt = module.install(REPO, product, python, tmp_path, "upgrade")
    after = tomllib.loads(config.read_text())
    assert after["model"] == "keep-user-choice"
    assert after["mcp_servers"]["unrelated"] == {"command": "keep-command"}
    assert after["mcp_servers"]["quantos_research"]["tool_timeout_sec"] == 3600
    backup = Path(receipt["backup_directory"])
    assert (backup / "config.toml").read_bytes() == before
    assert backup.stat().st_mode & 0o777 == 0o700
    assert (backup / "config.toml").stat().st_mode & 0o777 == 0o600
    assert config.stat().st_mode & 0o777 == 0o640
    assert json.loads((backup / "receipt.json").read_bytes())["unrelated_configuration_preserved"]
    module.install(REPO, product, python, tmp_path, "uninstall")
    assert tomllib.loads(config.read_text())["mcp_servers"] == {
        "unrelated": {"command": "keep-command"}
    }


def test_upgrade_refuses_unknown_product_edit_and_preserves_original(tmp_path):
    product = tmp_path / "product"
    product.mkdir()
    python = REPO / ".tools/personal-research-mcp-1.26.0/bin/python"
    module.install(REPO, product, python, tmp_path, "install")
    config = tmp_path / ".codex/config.toml"
    config.write_text(
        config.read_text().replace("tool_timeout_sec = 3600", "tool_timeout_sec = 43")
    )
    before = config.read_bytes()
    with pytest.raises(ValueError, match="entry differs"):
        module.install(REPO, product, python, tmp_path, "upgrade")
    assert config.read_bytes() == before
