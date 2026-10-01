"""Source-bound offline CI facts; a producer cannot award the Q12 gate."""

from __future__ import annotations

import errno
import re
import tomllib
from decimal import Decimal, InvalidOperation
from email.parser import BytesParser
from pathlib import Path
from typing import cast
from xml.etree import ElementTree

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_qualification import HostedQualificationCase, HostedRawInventory
from quantos.contracts.provenance import RuntimeFingerprint
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_regression_runtime import (
    ci_environment,
    ci_namespace_command,
    ci_python,
    expected_ci_runtime,
    verify_ci_declaration,
    verify_ci_runtime,
)
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    directory_inventory,
    read_relative,
)

CHECK_NAMES = ("ruff-format", "ruff", "pyright", "pytest", "diff-check")
CI_PREFIX = "qualification-checks/Q12"
CI_PACKAGES = ("ruff", "pyright", "pytest", "pytest-cov", "pytest-socket", "coverage")


def regression_commands(python: Path, workspace: Path, target: Path) -> dict[str, tuple[str, ...]]:
    return {
        "ruff-format": (str(python), "-m", "ruff", "format", "--check"),
        "ruff": (str(python), "-m", "ruff", "check"),
        "pyright": (str(python), "-m", "pyright", "--venvpath", str(python.parent.parent.parent)),
        "pytest": (
            str(python),
            "-m",
            "pytest",
            "--cov=quantos",
            "--cov-report=term-missing",
            f"--cov-report=xml:{target / 'coverage.xml'}",
            f"--junitxml={target / 'pytest.xml'}",
            f"--basetemp={target / 'pytest-root'}",
        ),
        "diff-check": ("/usr/bin/git", "-C", str(workspace), "diff", "--check"),
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HostedQualificationError(message)


def _xml(data: bytes):
    _require(
        b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(),
        "CI XML declarations are forbidden",
    )
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise HostedQualificationError("CI XML is invalid") from error


def verify_regression_reports(coverage: bytes, junit: bytes) -> None:
    """Recompute pytest's combined line/branch percentage, never trust a PASS string."""
    root = _xml(coverage)
    _require(root.tag == "coverage", "CI coverage schema differs")
    try:
        values = {
            name: int(root.attrib[name])
            for name in ("lines-valid", "lines-covered", "branches-valid", "branches-covered")
        }
        _require(all(value >= 0 for value in values.values()), "CI coverage counts are negative")
        lines, branches = values["lines-valid"], values["branches-valid"]
        _require(lines > 0 and branches > 0, "CI must include line and branch coverage")
        _require(
            values["lines-covered"] <= lines and values["branches-covered"] <= branches,
            "CI coverage counts exceed the denominator",
        )
        covered = values["lines-covered"] + values["branches-covered"]
        _require(
            Decimal(covered) / Decimal(lines + branches) >= Decimal("0.85"),
            "CI coverage is below the frozen 85 percent gate",
        )
        for key, numerator, denominator in (
            ("line-rate", values["lines-covered"], lines),
            ("branch-rate", values["branches-covered"], branches),
        ):
            _require(
                abs(Decimal(root.attrib[key]) - Decimal(numerator) / Decimal(denominator))
                <= Decimal("0.0001"),
                "CI coverage rates disagree with counts",
            )
    except (KeyError, ValueError, InvalidOperation) as error:
        raise HostedQualificationError("CI coverage numeric facts are invalid") from error
    totals = {key: 0 for key in values}
    filenames: set[str] = set()
    for cls in root.findall("./packages/package/classes/class"):
        filename = cls.attrib.get("filename", "")
        _require(
            filename.startswith("src/quantos/")
            and filename.endswith(".py")
            and ".." not in Path(filename).parts
            and filename not in filenames,
            "CI coverage file identity differs",
        )
        filenames.add(filename)
        seen: set[int] = set()
        for line in cls.findall("./lines/line"):
            try:
                number, hits = int(line.attrib["number"]), int(line.attrib["hits"])
                _require(
                    number > 0 and number not in seen and hits >= 0,
                    "CI line observations are invalid",
                )
                seen.add(number)
                totals["lines-valid"] += 1
                totals["lines-covered"] += int(hits > 0)
                if line.attrib.get("branch") == "true":
                    condition = re.fullmatch(
                        r"[0-9]+(?:\.[0-9]+)?% \(([0-9]+)/([0-9]+)\)",
                        line.attrib.get("condition-coverage", ""),
                    )
                    _require(condition is not None, "CI branch observations are absent")
                    assert condition is not None
                    covered_branches, valid_branches = map(int, condition.groups())
                    _require(
                        0 <= covered_branches <= valid_branches and valid_branches > 0,
                        "CI branch observations are invalid",
                    )
                    totals["branches-valid"] += valid_branches
                    totals["branches-covered"] += covered_branches
            except (KeyError, ValueError) as error:
                raise HostedQualificationError("CI line numeric facts are invalid") from error
    _require(
        totals == values and bool(filenames), "CI coverage totals differ from individual lines"
    )
    tests = _xml(junit)
    _require(tests.tag == "testsuites" and len(tests) == 1, "CI pytest suite registry differs")
    suite = tests[0]
    try:
        count = int(suite.attrib["tests"])
        _require(
            count > 0
            and int(suite.attrib["failures"]) == 0
            and int(suite.attrib["errors"]) == 0
            and int(suite.attrib["skipped"]) == 0,
            "CI pytest has failures, errors, skipped tests or an empty suite",
        )
        cases = suite.findall("testcase")
        _require(
            len(cases) == count
            and all(
                not case.findall("failure")
                and not case.findall("error")
                and not case.findall("skipped")
                for case in cases
            ),
            "CI pytest individual results disagree with totals",
        )
    except (KeyError, ValueError) as error:
        raise HostedQualificationError("CI pytest numeric facts are invalid") from error


def verify_q12(
    bundle: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    _require(
        case.case_id == "Q12" and {root.name for root in case.roots} == {"before", "after"},
        "Q12 needs the original before and after authorities",
    )
    deployment = sources.deployment
    target = deployment.root / CI_PREFIX
    originals: dict[str, bytes] = {}
    for path in case.evidence_paths:
        record = sources.files.get(path)
        _require(record is not None, "Q12 original management file is unavailable")
        assert record is not None
        if not record.source_path.startswith(CI_PREFIX + "/"):
            continue
        name = record.source_path.removeprefix(CI_PREFIX + "/")
        _require("/" not in name and name not in originals, "Q12 check source is ambiguous")
        data = read_relative(bundle, path)
        _require(
            data == read_relative(deployment.root, record.source_path),
            "Q12 exported check differs from original",
        )
        originals[name] = data
    expected = {
        "run.json",
        "runtime-fingerprint.json",
        "coverage.xml",
        "pytest.xml",
        *(f"{name}.txt" for name in CHECK_NAMES),
        *(f"{name}-prelaunch.json" for name in CHECK_NAMES),
        *(f"{name}-exit.json" for name in CHECK_NAMES),
        "tracked-before.json",
        "tracked-after.json",
        "runtime-install.json",
        "runtime-declaration.json",
    }
    _require(set(originals) == expected, "Q12 original check registry is incomplete")
    try:
        verify_ci_runtime(deployment.root, deployment.install)
        declaration = verify_ci_declaration(deployment.root, deployment.install)
    except (ArtifactIntegrityError, OSError, ValueError) as error:
        raise HostedQualificationError("Q12 frozen CI prefix or Node differs") from error
    fact = strict_json_object(originals["run.json"], max_bytes=16_777_216)
    fingerprint = RuntimeFingerprint.model_validate_json(originals["runtime-fingerprint.json"])
    _require(
        fingerprint.canonical_bytes() == originals["runtime-fingerprint.json"]
        and fingerprint.python_version == deployment.profile.python_version
        and fingerprint.operating_system == deployment.profile.operating_system
        and fingerprint.operating_system_release == deployment.profile.kernel_release
        and fingerprint.libc == deployment.profile.libc.replace(" ", "-")
        and next(
            (package.version for package in fingerprint.packages if package.name == "pyqlib"), None
        )
        == deployment.bundle.execution_bindings.qlib_version,
        "Q12 runtime differs from frozen deployment",
    )
    _require(
        canonical_json_bytes(fact) == originals["run.json"]
        and fact.get("schema_version") == "hosted-manager-regression/v1"
        and fact.get("deployment_profile_hash") == deployment.profile.content_hash
        and fact.get("exact_commit") == deployment.profile.exact_commit
        and fact.get("lockfile_hash") == deployment.profile.lock_hash
        and fact.get("runtime_fingerprint_hash") == fingerprint.content_hash
        and fact.get("qualification_eligibility") == "NOT_QUALIFIED",
        "Q12 source identity differs",
    )
    python, workspace = fact.get("python"), fact.get("workspace")
    _require(
        isinstance(python, str)
        and isinstance(workspace, str)
        and python == str(ci_python(deployment.root))
        and fact.get("python_prefix") == str(target / ".venv")
        and fact.get("capture_module_path")
        == str(
            target
            / ".venv/lib/python3.11/site-packages/quantos/infrastructure"
            / "hosted_regression_capture.py"
        )
        and Path(workspace).is_absolute(),
        "Q12 management executable or workspace is absent",
    )
    commands = regression_commands(Path(cast(str, python)), Path(cast(str, workspace)), target)
    installed = {item.relative_path: item.bytes_hash for item in deployment.install.files}
    _require(
        originals["runtime-install.json"]
        == expected_ci_runtime(deployment.install).canonical_bytes()
        and originals["runtime-declaration.json"] == canonical_json_bytes(declaration)
        and fact.get("ci_runtime_inventory_hash")
        == expected_ci_runtime(deployment.install).content_hash
        and fact.get("ci_runtime_declaration_hash")
        == sha256_bytes(originals["runtime-declaration.json"]),
        "Q12 checked runtime derivation differs",
    )
    _require(
        fact.get("python_executable_hash") == installed.get("python/bin/python3.11")
        and fact.get("python_executable_hash") is not None,
        "Q12 management Python differs from frozen installation",
    )
    _require(
        fact.get("capture_module_hash")
        == installed.get(
            "python/lib/python3.11/site-packages/quantos/infrastructure/hosted_regression_capture.py"
        )
        and fact.get("capture_module_hash") is not None
        and fact.get("manager_cache_prefix") == str(target / "manager-cache")
        and fact.get("manager_dont_write_bytecode") is True
        and fact.get("manager_isolated") is True
        and fact.get("manager_ignore_environment") is True
        and fact.get("manager_no_user_site") is True
        and fact.get("manager_safe_path") is True
        and fact.get("check_cache_absent") is True,
        "Q12 capture runtime differs from frozen source-only management",
    )
    tool_versions = fact.get("tool_versions")
    _require(
        isinstance(tool_versions, dict)
        and set(cast(dict[str, object], tool_versions)) == set(CI_PACKAGES),
        "Q12 tool identity registry differs",
    )
    locked = tomllib.loads(read_relative(deployment.paths.provenance, "uv.lock").decode())
    for name in CI_PACKAGES:
        tool_version = cast(dict[str, object], tool_versions)[name]
        _require(
            isinstance(tool_version, str)
            and any(
                package.get("name") == name and package.get("version") == tool_version
                for package in locked["package"]
            ),
            "Q12 tool version differs from frozen lock",
        )
        metadata_path = "python/lib/python3.11/site-packages/" + name.replace("-", "_")
        metadata_path += f"-{tool_version}.dist-info/METADATA"
        _require(metadata_path in installed, "Q12 tool is absent from frozen installation")
        metadata = BytesParser().parsebytes(read_relative(deployment.paths.install, metadata_path))
        _require(
            str(metadata["Name"] or "").lower().replace("_", "-") == name
            and metadata["Version"] == tool_version,
            "Q12 installed tool metadata differs",
        )
    from quantos.infrastructure.hosted_regression_capture import tracked_regression_inventory

    tracked = HostedRawInventory.model_validate_json(originals["tracked-before.json"])
    _require(
        tracked.canonical_bytes() == originals["tracked-before.json"]
        and originals["tracked-after.json"] == originals["tracked-before.json"]
        and tracked.content_hash == fact.get("tracked_inventory_hash")
        and tracked == tracked_regression_inventory(deployment.paths.provenance),
        "Q12 checked source differs from exact frozen provenance",
    )
    runs = fact.get("checks")
    _require(
        isinstance(runs, list) and len(cast(list[object], runs)) == len(CHECK_NAMES),
        "Q12 native child registry differs",
    )
    pids: set[int] = set()
    environment = ci_environment(Path(cast(str, python)), Path(cast(str, workspace)), target)
    for name, value in zip(CHECK_NAMES, cast(list[object], runs), strict=True):
        _require(isinstance(value, dict), "Q12 child observation is absent")
        run = cast(dict[str, object], value)
        namespace_argv = ci_namespace_command(
            Path(cast(str, python)), Path(cast(str, workspace)), target, environment, commands[name]
        )
        _require(
            run.get("name") == name
            and run.get("argv") == list(commands[name])
            and run.get("namespace_argv") == list(namespace_argv)
            and run.get("return_code") == 0
            and type(run.get("return_code")) is int
            and run.get("failure") is None
            and run.get("waitpid_observed") is True
            and run.get("output_hash") == sha256_bytes(originals[f"{name}.txt"])
            and type(run.get("pid")) is int
            and cast(int, run["pid"]) > 0
            and run.get("parent_pid") == fact.get("manager_pid"),
            "Q12 actual child, command, output or completion differs",
        )
        kernel = run.get("kernel_observations")
        _require(
            isinstance(kernel, list)
            and len(cast(list[object], kernel)) == 1
            and isinstance(cast(list[object], kernel)[0], dict),
            "Q12 native kernel observation is absent",
        )
        observation = cast(dict[str, object], cast(list[object], kernel)[0])
        ancestry = observation.get("kernel_ancestry")
        _require(
            isinstance(ancestry, list)
            and 2 <= len(cast(list[object], ancestry)) <= 9
            and all(type(pid) is int and pid > 0 for pid in cast(list[object], ancestry)),
            "Q12 native ancestry is absent",
        )
        chain = cast(list[int], ancestry)
        _require(
            type(observation.get("pid")) is int
            and cast(int, observation["pid"]) > 0
            and observation.get("wrapper_pid") == run["pid"]
            and observation.get("manager_pid") == fact.get("manager_pid")
            and observation.get("kernel_observed_before_exec") is True
            and observation.get("namespace_exit_observed") is True
            and type(observation.get("namespace_pid")) is int
            and cast(int, observation["namespace_pid"]) > 1
            and type(observation.get("namespace_parent_pid")) is int
            and observation["namespace_parent_pid"] == 1
            and type(observation.get("namespace_init_pid")) is int
            and observation["namespace_init_pid"] in chain[1:-1]
            and type(observation.get("pid_namespace_inode")) is int
            and cast(int, observation["pid_namespace_inode"]) > 0
            and type(observation.get("manager_pid_namespace_inode")) is int
            and cast(int, observation["manager_pid_namespace_inode"]) > 0
            and observation["pid_namespace_inode"] != observation["manager_pid_namespace_inode"]
            and observation.get("executable_hash") == installed.get("python/bin/python3.11")
            and type(observation.get("network_probe_errno")) is int
            and observation["network_probe_errno"] in {errno.ENETUNREACH, errno.EPERM, errno.EACCES}
            and type(observation.get("net_namespace_inode")) is int
            and cast(int, observation["net_namespace_inode"]) > 0
            and type(observation.get("manager_net_namespace_inode")) is int
            and cast(int, observation["manager_net_namespace_inode"]) > 0
            and observation["net_namespace_inode"] != observation["manager_net_namespace_inode"]
            and len(set(chain)) == len(chain)
            and chain[0] == observation["pid"]
            and chain[1] == observation.get("parent_pid")
            and chain[-1] == fact.get("manager_pid")
            and run["pid"] in chain[:-1],
            "Q12 original kernel isolation, ancestry or executable differs",
        )
        _require(
            canonical_json_bytes(run) == originals[f"{name}-exit.json"],
            "Q12 child exit differs from original completion",
        )
        _require(
            originals[f"{name}-prelaunch.json"]
            == canonical_json_bytes(
                {
                    "schema_version": "hosted-manager-regression-prelaunch/v1",
                    "deployment_profile_hash": deployment.profile.content_hash,
                    "manager_pid": fact["manager_pid"],
                    "name": name,
                    "argv": commands[name],
                    "namespace_argv": namespace_argv,
                    "cwd": workspace,
                    "environment_policy": "FIXED_OFFLINE_CI_NO_CREDENTIALS/v1",
                }
            ),
            "Q12 original prelaunch differs from completed command",
        )
        pids.add(cast(int, run["pid"]))
    _require(
        len(pids) == len(CHECK_NAMES)
        and type(fact.get("manager_pid")) is int
        and cast(int, fact["manager_pid"]) > 0
        and fact["manager_pid"] not in pids,
        "Q12 child identities are not independent",
    )
    before = HostedRawInventory.model_validate(fact["authority_before"])
    _require(
        before == HostedRawInventory.model_validate(fact["authority_after"]),
        "Q12 regression changed live authority",
    )
    for root in case.roots:
        inventory = HostedRawInventory.model_validate_json(
            read_relative(bundle, root.raw_inventory_path)
        )
        _require(
            inventory == before
            and sources.root_origin(root, inventory)
            == deployment.root / f"qualification-cases/Q12/{root.name}",
            "Q12 original snapshot identity differs",
        )
        _require(
            list(directory_inventory(bundle / root.logical_path))
            == fact.get("authority_directories")
            and list(directory_inventory(deployment.root / f"qualification-cases/Q12/{root.name}"))
            == fact.get("authority_directories"),
            "Q12 snapshot directory closure differs",
        )
    verify_regression_reports(originals["coverage.xml"], originals["pytest.xml"])
    coverage_files = {
        node.attrib["filename"]
        for node in _xml(originals["coverage.xml"]).findall("./packages/package/classes/class")
    }
    installed_files = {
        "src/quantos/"
        + file.relative_path.removeprefix("python/lib/python3.11/site-packages/quantos/")
        for file in deployment.install.files
        if file.relative_path.startswith("python/lib/python3.11/site-packages/quantos/")
        and file.relative_path.endswith(".py")
    }
    _require(coverage_files == installed_files, "Q12 coverage omitted frozen project source")
    return tuple(sorted({sha256_bytes(data) for data in originals.values()}))
