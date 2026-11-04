"""Expose only the pinned optional MCP package to the scientific type environment."""

from __future__ import annotations

import argparse
from pathlib import Path


def prepare(repo: Path) -> Path:
    source = repo.resolve() / ".tools/personal-research-mcp-1.26.0/lib/python3.11/site-packages/mcp"
    if not source.is_dir():
        raise ValueError("install the pinned optional MCP environment first")
    destination = repo.resolve() / ".tools/personal-research-mcp-typing/mcp"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if not destination.is_symlink() or destination.resolve() != source:
            raise ValueError("existing optional typing path differs; preserved")
    else:
        destination.symlink_to(source, target_is_directory=True)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    print(prepare(parser.parse_args().repo_root))
