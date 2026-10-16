"""Literal dependency inventory, not an AppArmor parser or attachment matcher."""

from __future__ import annotations

import re

ROOT = "/etc/apparmor.d/"
DIRECTIVE = re.compile(
    r"^\s*(?:(?:#\s*)?include(?P<optional>\s+if\s+exists)?|(?P<abi>abi))"
    r'\s+(?:<(?P<magic>[^>\n]+)>|"(?P<absolute>[^"\n]+)")'
    r"\s*(?P<comma>,)?\s*(?:#.*)?$"
)


def policy_path(path: str) -> str:
    if (
        not path.startswith(ROOT)
        or any(part in ("", ".", "..") for part in path[len(ROOT) :].split("/"))
        or not re.fullmatch(r"[A-Za-z0-9_./+@-]+", path)
    ):
        raise ValueError("unsupported literal policy dependency path")
    return path


def dependencies(raw: bytes) -> tuple[list[dict[str, object]], list[str]]:
    """Record only the retained grammar's literal include/ABI forms; refuse ambiguity.

    The packaged apparmor.d(5) specifies <relative-to-policy-root> and quoted
    absolute paths. No variable expansion, AARE evaluation or policy compilation.
    A complete literal inventory still does not establish compiler/load history.
    """
    edges: list[dict[str, object]] = []
    errors: list[str] = []
    for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        stripped = line.lstrip()
        # Ordinary prose comments (including '# include the programs ...') aren't directives.
        relevant = (
            re.match(r"(?:include|abi)\b", stripped) is not None
            or stripped.startswith("#include")
            or re.match(r'#\s+include\s+(?:if\s+exists\s+)?[<"]', stripped) is not None
        )
        if not relevant:
            continue
        match = DIRECTIVE.fullmatch(line)
        try:
            if match is None or bool(match["abi"]) != bool(match["comma"]):
                raise ValueError("unsupported dependency directive")
            target = ROOT + match["magic"] if match["magic"] else match["absolute"]
            edges.append(
                {
                    "line": number,
                    "directive": line.strip(),
                    "path": policy_path(target),
                    "if_exists": bool(match["optional"]),
                    "kind": "abi" if match["abi"] else "include",
                }
            )
        except ValueError as error:
            errors.append(f"line {number}: {error}: {line.strip()}")
    return edges, errors
