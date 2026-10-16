"""Diagnostic v4 projection with the unchanged v3 inventory/byte rejection checks."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.apparmor.provenance_v3 import binding as v3
from ci.apparmor.provenance_v4.capture import ALIASES, closure, ownership


def candidate(raw: bytes) -> dict[str, object]:
    value: object = json.loads(raw)
    report = v3.mapping(value)
    if report.get("schema") != "quantos-apparmor-provenance-v4":
        raise ValueError("unsupported successor provenance schema")
    plan = v3.mapping(report["plan"])
    if plan.get("schema") != "quantos-apparmor-source-plan-v4":
        raise ValueError("unsupported successor plan schema")
    if report.get("compilation_history") != "UNRESOLVED":
        raise ValueError("this collector cannot assert historical compilation")
    alias_records = [v3.mapping(entry) for entry in v3.items(report["usrmerge_aliases"])]
    if len(alias_records) != len(ALIASES) or {entry.get("path") for entry in alias_records} != set(
        ALIASES
    ):
        raise ValueError("missing/duplicate fixed alias observation")
    for entry in alias_records:
        if entry.get("status") == "ok":
            target, mode = entry.get("target"), entry.get("mode")
            expected_target = ALIASES[str(entry["path"])]
            if (
                target not in (None, expected_target, "/" + expected_target)
                or not isinstance(mode, int)
                or not (stat.S_ISDIR(mode) if target is None else stat.S_ISLNK(mode))
            ):
                raise ValueError("unsupported usrmerge alias metadata")
    expected = closure(
        [v3.mapping(record) for record in v3.items(report["sources"])],
        [v3.mapping(record) for record in v3.items(report["include_directories"])],
        plan,
    )
    if expected != report.get("dependency_status"):
        raise ValueError("dependency classification mismatch")
    packages, package_errors = ownership(
        [
            str(record["path"])
            for group in ("sources", "settings", "binaries")
            for entry in v3.items(report[group])
            if (record := v3.mapping(entry)).get("status") == "ok"
        ],
        alias_records,
        observations=v3.mapping(report["packages"]),
    )
    if packages != report["packages"]:
        raise ValueError("ownership classification mismatch")
    if report.get("collection_complete") is True and (
        expected["errors"] != []
        or bool(package_errors)
        or any(
            v3.mapping(record).get("status") != "ok"
            for group in ("settings", "features", "namespace", "binaries", "usrmerge_aliases")
            for record in v3.items(report[group])
        )
        or v3.mapping(report["policy_root_listing"]).get("status") != "ok"
    ):
        raise ValueError("incomplete observations cannot assert completeness")
    # Internal validation adapter only: never persist/relabel this as a v3 capture.
    # Reuse full inventory, namespace, original-byte/hash and authority refusals.
    checked = v3.candidate(v3.canonical({**report, "schema": "quantos-apparmor-provenance-v3"}))
    checked["schema"] = "quantos-apparmor-binding-proposal-v4"
    checked["raw_capture_sha256"] = v3.digest(raw)
    checked["candidate_content_sha256"] = v3.digest(
        v3.canonical(
            {
                "schema": "quantos-apparmor-binding-content-v4",
                "validated_projection_sha256": checked["candidate_content_sha256"],
            }
        )
    )
    return checked


def compare(left: bytes, right: bytes) -> dict[str, object]:
    first, second = candidate(left), candidate(right)
    complete = first["collection_complete"] is True and second["collection_complete"] is True
    return {
        "left": first,
        "right": second,
        "content_equal": first["candidate_content_sha256"] == second["candidate_content_sha256"],
        "decision": "UNRESOLVED_SOURCE_REVIEW_REQUIRED"
        if complete
        else "REJECTED_INCOMPLETE_CAPTURE",
        "load_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    args = parser.parse_args()

    def read(path: Path) -> bytes:
        with path.open("rb") as stream:
            raw = stream.read(12 * 1024 * 1024 + 1)
        if len(raw) > 12 * 1024 * 1024:
            raise ValueError("capture size limit")
        return raw

    try:
        result = compare(read(args.left), read(args.right))
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        result = {"decision": "REJECTED", "error": str(error), "load_authorized": False}
    print(json.dumps(result, sort_keys=True, indent=2))
    raise SystemExit(1)


if __name__ == "__main__":
    main()
