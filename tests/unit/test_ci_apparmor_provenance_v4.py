import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from ci.apparmor.provenance_v4 import binding, capture
from ci.apparmor.provenance_v4.dependencies import dependencies
from test_ci_apparmor_provenance import encoded, inventory, write


def fake_dpkg(argv):
    if "--search" not in argv:
        return {
            "argv": list(argv),
            "status": "ok",
            "exit": 0,
            "stdout": "apparmor\t.8\tamd64\n",
            "stderr": "",
        }
    paths = argv[argv.index("--") + 1 :]
    unowned = {
        path
        for path in paths
        if path.startswith(("/usr/lib/apparmor/", "/usr/sbin/")) or path == "/etc/default/apparmor"
    }
    return {
        "argv": list(argv),
        "status": "error" if unowned else "ok",
        "exit": 1 if unowned else 0,
        "stdout": "".join(f"apparmor: {path}\n" for path in paths if path not in unowned),
        "stderr": "".join(
            f"dpkg-query: no path found matching pattern {path}\n" for path in sorted(unowned)
        ),
    }


def packet(root, monkeypatch, directive=b"include if exists <local/optional>\n"):
    for path in [
        *capture.CONFIG,
        "/usr/sbin/apparmor_parser",
        "/usr/bin/bwrap",
        "/sys/kernel/security/apparmor/features/policy/versions",
    ]:
        write(root, path, b"# synthetic fixture\n")
    for logical, target in capture.ALIASES.items():
        (root / logical[1:]).symlink_to(target)
    for name, value in [
        (".ns_name", b"root\n"),
        (".ns_level", b"0\n"),
        (".ns_stacked", b"no\n"),
        (".stacked", b"no\n"),
    ]:
        write(root, "/sys/kernel/security/apparmor/" + name, value)
    write(root, "/etc/apparmor.d/named", directive)
    monkeypatch.setattr(capture, "command", fake_dpkg)
    plan = {
        "schema": "quantos-apparmor-source-plan-v4",
        "files": [{"path": "/etc/apparmor.d/named"}, {"path": "/etc/apparmor.d/local/optional"}],
        "profiles": [{"lineage": ["synthetic"], "source_candidates": ["/etc/apparmor.d/named"]}],
    }
    original = inventory()
    report = capture.capture(encoded(original), plan, capture.Reader(root), "synthetic-image")
    report["revision_after_sources"] = original["revision_after"]
    return report


def test_explicit_absence_and_partial_ownership_keep_original_facts(tmp_path, monkeypatch):
    report = packet(tmp_path, monkeypatch)
    assert report["collection_complete"] is True
    assert report["dependency_status"]["missing"] == [
        {
            "path": "/etc/apparmor.d/local/optional",
            "status": "missing",
            "classification": "EXPLICIT_IF_EXISTS_ABSENT",
        }
    ]
    packages = report["packages"]
    assert packages["owners"]["exit"] == 1
    assert "/etc/default/apparmor" in packages["owners"]["stderr"]
    queries = {item["path"]: item["queries"] for item in packages["per_path"]}
    assert queries["/usr/sbin/apparmor_parser"] == [
        {"query_path": "/usr/sbin/apparmor_parser", "state": "UNOWNED", "owners": []},
        {"query_path": "/sbin/apparmor_parser", "state": "OWNED", "owners": ["apparmor"]},
    ]
    assert packages["archive_origin"] == "UNRESOLVED"
    assert any(x["path"] == "/usr/lib/apparmor/rc.apparmor.functions" for x in report["settings"])
    assert binding.compare(encoded(report), encoded(report))["load_authorized"] is False


@pytest.mark.parametrize("failure", ["required", "symlink", "default", "generated"])
def test_missing_required_or_investigation_gap_cannot_be_waived(tmp_path, monkeypatch, failure):
    if failure == "symlink":
        write(tmp_path, "/etc/apparmor.d/local/target")
        (tmp_path / "etc/apparmor.d/local/optional").symlink_to("target")
    directive = (
        b"abi <local/optional>,\ninclude if exists <local/optional>\n"
        if failure == "required"
        else b"include if exists <local/optional>\n"
    )
    report = packet(tmp_path, monkeypatch, directive)
    if failure == "default":
        (tmp_path / "etc/default/apparmor").unlink()
        report = capture.capture(
            encoded(inventory()), report["plan"], capture.Reader(tmp_path), "x"
        )
    if failure == "generated":
        plan = copy.deepcopy(report["plan"])
        plan["profiles"].append({"lineage": ["docker-default"], "source_candidates": []})
        report = capture.capture(encoded(inventory()), plan, capture.Reader(tmp_path), "x")
    assert report["collection_complete"] is False
    assert report["errors"]
    assert report["load_authorized"] is False


def test_literal_abi_required_include_and_if_exists_are_separate():
    edges, failures = dependencies(
        b"abi <abi/4.0>,\n#include <tunables/global>\n"
        b"include if exists <abstractions/base.d>\n"
        b"# include the programs that parse input\n"
    )
    assert not failures
    assert [(x["path"], x["if_exists"], x["kind"]) for x in edges] == [
        ("/etc/apparmor.d/abi/4.0", False, "abi"),
        ("/etc/apparmor.d/tunables/global", False, "include"),
        ("/etc/apparmor.d/abstractions/base.d", True, "include"),
    ]


@pytest.mark.parametrize(
    "directive",
    [
        b"include <../escape>\n",
        b'include "/etc/shadow"\n',
        b"include <abstractions/@{variable}>\n",
        b"abi <abi/4.0>\n",
    ],
)
def test_unresolved_dependency_syntax_is_retained(directive):
    edges, failures = dependencies(directive)
    assert not edges
    assert failures


def test_directory_children_read_once_and_new_dependency_is_not_followed(tmp_path, monkeypatch):
    report = packet(tmp_path, monkeypatch, b"include if exists <local/optional>\n")
    write(tmp_path, "/etc/apparmor.d/local/optional/addition", b"include <unplanned>\n")
    plan = report["plan"]
    plan["files"].append({"path": "/etc/apparmor.d/local/optional/addition"})
    calls = []
    original = capture.Reader.read

    def counted(self, path, binary=False):
        calls.append(path)
        return original(self, path, binary)

    monkeypatch.setattr(capture.Reader, "read", counted)
    report = capture.capture(encoded(inventory()), plan, capture.Reader(tmp_path), "x")
    assert calls.count("/etc/apparmor.d/local/optional/addition") == 1
    assert "/etc/apparmor.d/unplanned" not in calls
    assert report["include_directories"][0]["status"] == "ok"
    assert report["collection_complete"] is False
    assert any(x["status"] == "unplanned" for x in report["dependency_status"]["missing"])


def test_unexpected_alias_and_unaccounted_dpkg_error_stay_rejected(tmp_path, monkeypatch):
    packet(tmp_path, monkeypatch)
    (tmp_path / "lib").unlink()
    (tmp_path / "lib").symlink_to("etc")
    assert capture.aliases(capture.Reader(tmp_path))[0]["status"] == "error"
    monkeypatch.setattr(
        capture,
        "command",
        lambda argv: {
            "status": "error",
            "exit": 2,
            "stdout": "",
            "stderr": "database unavailable\n",
        },
    )
    packages, errors = capture.ownership(["/etc/apparmor.d/named"], [])
    assert errors
    assert packages["owners"]["stderr"] == "database unavailable\n"
    assert packages["per_path"][0]["queries"][0]["state"] == "UNRESOLVED"


@pytest.mark.parametrize(
    "change", ["hash", "closure", "authority", "history", "complete", "owner", "alias"]
)
def test_successor_binding_retains_hash_and_authority_refusals(tmp_path, monkeypatch, change):
    report = packet(tmp_path, monkeypatch)
    if change == "hash":
        next(record for record in report["sources"] if record["status"] == "ok")["sha256"] = (
            "0" * 64
        )
    elif change == "closure":
        report["dependency_status"]["missing"] = []
    elif change == "authority":
        report["source_to_loaded_correspondence"] = "VERIFIED"
    elif change == "history":
        report["compilation_history"] = "VERIFIED"
    elif change == "owner":
        report["packages"]["per_path"][0]["queries"][0]["owners"] = ["invented-owner"]
    elif change == "alias":
        report["usrmerge_aliases"][0]["target"] = "etc"
    else:
        report["settings"][0]["status"] = "missing"
    with pytest.raises(ValueError):
        binding.candidate(encoded(report))


@pytest.mark.parametrize("guard", ["MAX_FILES", "MAX_LISTING_BYTES"])
def test_fixed_root_listing_has_shared_entry_and_byte_guards(tmp_path, monkeypatch, guard):
    write(tmp_path, "/etc/apparmor.d/a")
    write(tmp_path, "/etc/apparmor.d/b")
    monkeypatch.setattr(capture, guard, 1)
    assert capture.root_listing(capture.Reader(tmp_path))["status"] == "error"


def test_isolated_successor_cli_wrong_hash_exits_before_source_access(tmp_path):
    path = tmp_path / "inventory.json"
    path.write_bytes(encoded(inventory()))
    proc = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "ci/apparmor/provenance_v4/capture.py",
            "--inventory",
            str(path),
            "--inventory-sha256",
            "0" * 64,
            "--image-version",
            "synthetic",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert not proc.stdout
    assert "inventory size/hash mismatch" in proc.stderr


def test_successor_cli_equal_complete_synthetic_report_still_refuses(tmp_path, monkeypatch):
    report = packet(tmp_path, monkeypatch)
    path = tmp_path / "report.json"
    path.write_bytes(encoded(report))
    proc = subprocess.run(
        [sys.executable, "-I", "-B", "ci/apparmor/provenance_v4/binding.py", str(path), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["content_equal"] is True
    assert result["decision"] == "UNRESOLVED_SOURCE_REVIEW_REQUIRED"
    assert result["load_authorized"] is False


def test_retained_bundle_plan_requests_required_closure_without_loading_claim():
    plan = json.loads(Path("ci/apparmor/provenance_v4/source-plan.json").read_bytes())
    paths = {x["path"] for x in plan["files"]}
    assert {
        "/etc/apparmor.d/abi/3.0",
        "/etc/apparmor.d/abi/4.0",
        "/etc/apparmor.d/abstractions/user-tmp",
        "/etc/apparmor.d/abstractions/transmission-common",
    } <= paths
    for profile in plan["profiles"]:
        name = profile["lineage"][0]
        if name.startswith("transmission-"):
            assert profile["source_candidates"] == ["/etc/apparmor.d/transmission"]
        if name.startswith("ubuntu_pro_esm_cache_system"):
            assert profile["source_candidates"] == ["/etc/apparmor.d/ubuntu_pro_esm_cache"]
        assert profile["correspondence"] == "UNRESOLVED"
    assert plan["reference_is_runner_source_proof"] is False
