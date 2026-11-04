"""Install only the personal research Skill and STDIO MCP entry for this user."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

NAME = "quantos_research"
BEGIN = "\n# BEGIN quantos-personal-research managed entry\n"
END = "# END quantos-personal-research managed entry\n"


def _replace(path: Path, data: bytes, mode: int) -> None:
    fd, scratch = tempfile.mkstemp(prefix=".quantos-install-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(scratch, path)
    finally:
        if os.path.exists(scratch):
            os.unlink(scratch)


def install(repo: Path, root: Path, python: Path, user_home: Path, action: str) -> dict:
    repo, root, python = repo.resolve(strict=True), root.resolve(strict=True), python.absolute()
    if not python.is_file() or not (repo / "skills/quantos-research/SKILL.md").is_file():
        raise ValueError("product interpreter or Skill is missing")
    config = user_home / ".codex/config.toml"
    skill = user_home / ".agents/skills/quantos-research"
    source_skill = repo / "skills/quantos-research"
    if config.is_symlink():
        raise ValueError("config symlink requires explicit manual integration")
    before = config.read_bytes() if config.exists() else b""
    mode = stat.S_IMODE(config.stat().st_mode) if config.exists() else 0o600
    parsed = tomllib.loads(before.decode())
    entry = {
        "command": str(python),
        "args": [
            "-B",
            "-m",
            "quantos.personal_research_mcp",
            "--root",
            str(root),
            "--repo-root",
            str(repo),
        ],
        "startup_timeout_sec": 30,
        "tool_timeout_sec": 3600,
    }
    current = parsed.get("mcp_servers", {}).get(NAME)
    predecessor = {**entry, "tool_timeout_sec": 120}
    if action == "status":
        return {
            "entry_matches": current == entry,
            "skill_matches": skill.is_symlink() and skill.resolve() == source_skill,
            "config": str(config),
            "skill": str(skill),
        }
    if action in {"install", "upgrade"}:
        if (
            current is not None
            and current != entry
            and not (action == "upgrade" and current == predecessor)
        ):
            raise ValueError("existing product MCP entry differs; no unrelated config overwritten")
        if (skill.exists() or skill.is_symlink()) and (
            not skill.is_symlink() or skill.resolve() != source_skill
        ):
            raise ValueError("existing Skill conflicts; preserved unchanged")
        block = (
            BEGIN
            + f"[mcp_servers.{NAME}]\n"
            + "\n".join(f"{key} = {json.dumps(value)}" for key, value in entry.items())
            + "\n"
            + END
        ).encode()
        if current == entry:
            after = before
        elif current == predecessor:
            text = before.decode()
            if text.count(BEGIN) != 1 or text.count(END) != 1:
                raise ValueError("managed markers missing; upgrade preserved config")
            start = text.index(BEGIN)
            stop = text.index(END, start) + len(END)
            after = (text[:start] + block.decode() + text[stop:]).encode()
        else:
            after = before + block
    else:
        if current is not None and current not in (entry, predecessor):
            raise ValueError("product entry changed since install; automatic removal refused")
        text = before.decode()
        if current is not None:
            if text.count(BEGIN) != 1 or text.count(END) != 1:
                raise ValueError("managed markers missing; preserved config for manual removal")
            start = text.index(BEGIN)
            stop = text.index(END, start) + len(END)
            after = (text[:start] + text[stop:]).encode()
        else:
            after = before
        if (skill.exists() or skill.is_symlink()) and (
            not skill.is_symlink() or skill.resolve() != source_skill
        ):
            raise ValueError("Skill changed since install; removal refused")
    # Check semantic preservation before touching user configuration.
    updated = tomllib.loads(after.decode())
    old_other, new_other = dict(parsed), dict(updated)
    old_servers = dict(old_other.pop("mcp_servers", {}))
    new_servers = dict(new_other.pop("mcp_servers", {}))
    old_servers.pop(NAME, None)
    new_servers.pop(NAME, None)
    if old_other != new_other or old_servers != new_servers:
        raise ValueError("unrelated configuration would change")
    config.parent.mkdir(parents=True, exist_ok=True)
    backup = (
        config.parent
        / "backups/quantos-personal-research"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup, 0o700)
    if config.exists():
        shutil.copy2(config, backup / "config.toml")
        os.chmod(backup / "config.toml", 0o600)
    changed = before != after
    if changed:
        _replace(config, after, mode)
    try:
        if action in {"install", "upgrade"}:
            skill.parent.mkdir(parents=True, exist_ok=True)
            if not skill.is_symlink():
                skill.symlink_to(source_skill, target_is_directory=True)
        elif skill.is_symlink():
            skill.unlink()
    except BaseException:
        if changed:
            _replace(config, before, mode)
        raise
    receipt = {
        "action": action,
        "name": NAME,
        "config_changed": changed,
        "config_mode_preserved": not config.exists() or mode == stat.S_IMODE(config.stat().st_mode),
        "unrelated_configuration_preserved": True,
        "backup_directory": str(backup),
        "config_sha256": hashlib.sha256(after).hexdigest(),
        "skill": str(skill),
        "repo": str(repo),
        "root": str(root),
        "python": str(python),
        "client_restart_required": True,
        "real_codex_tool_call_verified": False,
    }
    (backup / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "upgrade", "uninstall", "status"])
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--user-home", type=Path, default=Path.home())
    args = parser.parse_args()
    print(
        json.dumps(
            install(args.repo_root, args.root, args.python, args.user_home, args.action),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
