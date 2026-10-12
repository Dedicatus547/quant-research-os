#!/usr/bin/env python3
"""Finite 0.162.1 P10 v4 preparation/replay and separately authorized managed execution."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import zipfile
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from quantos.application import p10_v4 as rubric  # noqa: E402
from quantos.application import p10_v4_runner as runner  # noqa: E402
from quantos.artifacts.store import (  # noqa: E402
    atomic_write_bytes,
    exclusive_directory_lock,
    sha256_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes  # noqa: E402
from quantos.infrastructure.hosted_storage import (  # noqa: E402
    StorageGuard,
    StorageRejected,
    configured_guard,
    supervise_storage_job,
)
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter  # noqa: E402

SDK_WHEEL_HASH = "ebb2254a7ae97432eda6c2fe9b48b5b7f2c59c6e1ea25686a45ceca11ddec4b2"
RUNTIME_WHEEL_HASH = "b087e5e0b2285309a56336ca0c2375105bf56ffacf00b4efec7fbd7c22b51f7b"


def publish(root: Path, name: str, value: object) -> None:
    atomic_write_bytes(root / name, canonical_json_bytes(value))


def overlay_support_hash(candidate: Path) -> str:
    """Bind package metadata/code and the Code Mode sidecar, excluding the primary binary."""
    overlay = candidate / "overlay"
    paths = tuple(
        sorted(
            p
            for p in overlay.rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and p != overlay / "codex_cli_bin/bin/codex"
        )
    )
    if any(p.is_symlink() or p.stat().st_size > 128 << 20 for p in paths):
        raise ValueError("candidate support files are not bounded regular inputs")
    return sha256_bytes(
        canonical_json_bytes({p.relative_to(overlay).as_posix(): sha256_file(p) for p in paths})
    )


def candidate_identity(candidate: Path) -> dict[str, str]:
    """Read-only reuse of retained official inputs; no install or runtime launch."""
    provenance = (candidate / "candidate-provenance.json").read_bytes()
    fact = json.loads(provenance)
    if (
        fact["sdk_version"] != rubric.VERSION
        or fact["runtime_version"] != rubric.VERSION
        or fact["runtime"]["binary_sha256_hashlib"] != rubric.RUNTIME_HASH
        or fact["publishing_commit"] != "52950c592404f11cc245a83a27fb02f2c23bc0c1"
    ):
        raise ValueError("candidate provenance is not the finite retained identity")
    wheel = candidate / "vendor/openai_codex-0.162.1-py3-none-any.whl"
    if sha256_file(wheel) != SDK_WHEEL_HASH:
        raise ValueError("retained SDK wheel identity mismatch")
    with zipfile.ZipFile(wheel) as archive:
        names = {
            name
            for name in archive.namelist()
            if name.startswith("openai_codex/") and not name.endswith("/")
        }
        installed = candidate / "overlay/openai_codex"
        actual = {
            "openai_codex/" + p.relative_to(installed).as_posix()
            for p in installed.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }
        if actual != names:
            raise ValueError("installed SDK file set mismatch")
        for name in names:
            path = candidate / "overlay" / name
            if path.is_symlink() or path.read_bytes() != archive.read(name):
                raise ValueError("installed SDK differs from retained official wheel")
    runtime_wheel = (
        candidate / "vendor/openai_codex_cli_bin-0.162.1-py3-none-manylinux_2_17_x86_64.whl"
    )
    if sha256_file(runtime_wheel) != RUNTIME_WHEEL_HASH:
        raise ValueError("retained runtime wheel identity mismatch")
    with zipfile.ZipFile(runtime_wheel) as archive:
        for name in archive.namelist():
            if (
                name.startswith("codex_cli_bin/")
                and not name.endswith("/")
                and name != "codex_cli_bin/bin/codex"
            ):
                path = candidate / "overlay" / name
                if path.is_symlink() or path.read_bytes() != archive.read(name):
                    raise ValueError("runtime support file differs from official wheel")
    # Adapter hashes the actual bundled binary again at execution; preparation does not launch it.
    binary_hash = sha256_file(candidate / "overlay/codex_cli_bin/bin/codex")
    if binary_hash != rubric.RUNTIME_HASH:
        raise ValueError("retained runtime binary identity mismatch")
    return {
        "candidate_provenance_hash": sha256_bytes(provenance),
        "sdk_wheel_hash": SDK_WHEEL_HASH,
        "runtime_binary_hash": binary_hash,
        "overlay_support_hash": overlay_support_hash(candidate),
    }


def preparation(candidate: Path, fixture: Path, *, model: str = "gpt-5.6-sol") -> dict[str, object]:
    inputs = rubric.load_inputs(fixture, model=model)
    request = rubric.build_request(inputs)
    spec = rubric.build_spec(inputs, request)
    return {
        "schema_version": "fr03-p10-v4-preparation/v1",
        "candidate_profile": rubric.PROFILE,
        "candidate_root": str(candidate),
        "fixture_root": str(inputs.fixture_root),
        "fixture_hashes": inputs.all_input_hashes,
        "spec_hash": spec.content_hash,
        "implementation_hash": spec.implementation_hash,
        "identity": candidate_identity(candidate),
        "budgets": {
            "preflight_account_reads": 1,
            "p10_account_reads": 1,
            "model_attempts": 1,
            "retry_count": 0,
            "max_input_tokens": 250000,
            "max_output_tokens": 4096,
            "preflight_seconds": 90,
            "p10_seconds": 900,
            "control_seconds_each": 5,
            "control_bytes_each": 4096,
            "preflight_growth_bytes": 32 << 20,
            "p10_growth_bytes": 256 << 20,
            "scratch_quota_bytes": 64 << 20,
            "memory_reservation_bytes": 1536 << 20,
        },
        "rubric": "P10_V4_9_OF_9_COMBINED_BOUNDARY",
        "live_authorization": "REQUIRED_SEPARATELY",
        "qualification": "NOT_EVALUATED",
        "fr03_status": "NO_GO",
        "canonical_pin_changed": False,
    }


def check_preparation(
    root: Path, candidate: Path, fixture: Path, *, check_support: bool, model: str = "gpt-5.6-sol"
) -> str:
    raw = (root / "preparation.json").read_bytes()
    fact = json.loads(raw)
    inputs = rubric.load_inputs(fixture, model=model)
    spec = rubric.build_spec(inputs, rubric.build_request(inputs))
    if (
        fact["candidate_root"] != str(candidate)
        or fact["fixture_root"] != str(inputs.fixture_root)
        or fact["spec_hash"] != spec.content_hash
        or fact["implementation_hash"] != spec.implementation_hash
    ):
        raise ValueError("prepared v4 inputs changed")
    # Recheck installed support inputs once inside the read-only outer wrapper.
    if check_support and fact["identity"]["overlay_support_hash"] != overlay_support_hash(
        candidate
    ):
        raise ValueError("prepared candidate support files changed")
    if fact["identity"]["candidate_provenance_hash"] != sha256_file(
        candidate / "candidate-provenance.json"
    ):
        raise ValueError("candidate provenance changed")
    return sha256_bytes(raw)


def run_preflight(root: Path, candidate: Path, authentication: Path) -> int:
    # Reuse the finite existing account/read operation in a fresh evidence root. No wheel copies.
    preflight = root / "preflight"
    preflight.mkdir(exist_ok=True)
    atomic_write_bytes(
        preflight / "candidate-provenance.json",
        (candidate / "candidate-provenance.json").read_bytes(),
    )
    (preflight / "overlay").symlink_to(candidate / "overlay", target_is_directory=True)
    source = REPO / "scripts/fr03_candidate_01621.py"
    spec = importlib.util.spec_from_file_location("fr03_v4_account_read", source)
    if spec is None or spec.loader is None:
        raise ValueError("existing account/read entry unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.preflight(preflight, authentication, 32 << 20))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("prepare", "verify", "supervise-preflight", "preflight", "supervise", "execute"),
    )
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--fixture-root", type=Path, default=REPO / "tests/fixtures/p10_codex_workspace_v4"
    )
    parser.add_argument("--authentication-home", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--verify-run", type=Path)
    parser.add_argument("--trusted-receipt-sha256")
    parser.add_argument("--model", choices=("gpt-5.6-sol", "gpt-6.1-sol"), default="gpt-5.6-sol")
    args = parser.parse_args()
    root, candidate, fixture = (
        args.output_root.resolve(),
        args.candidate_root.resolve(),
        args.fixture_root.resolve(),
    )
    if root.is_relative_to(candidate) or root.is_relative_to(fixture) or root == REPO:
        raise ValueError("v4 output must be isolated from retained candidate/fixture/source")
    if args.mode == "prepare":
        publish(root, "preparation.json", preparation(candidate, fixture, model=args.model))
        return 0
    if args.mode == "verify":
        if args.verify_run is None or args.trusted_receipt_sha256 is None:
            parser.error(
                "offline replay requires a run and an externally trusted manager receipt hash"
            )
        result = runner.verify(
            args.verify_run,
            fixture,
            expected_receipt_hash=args.trusted_receipt_sha256,
            model=args.model,
        )
        print(json.dumps(runner.summary(result), sort_keys=True))
        return result.process_return_code
    if args.authentication_home is None or args.scratch_root is None:
        parser.error(
            "authorized live modes require authentication and an existing bounded scratch pool"
        )
    preparation_hash = check_preparation(
        root,
        candidate,
        fixture,
        check_support=args.mode in {"preflight", "execute"},
        model=args.model,
    )
    preflight_mode = args.mode in {"preflight", "supervise-preflight"}
    growth = (32 if preflight_mode else 256) << 20
    base = configured_guard()
    guard = StorageGuard(
        replace(base.policy, scratch_root=args.scratch_root.resolve(), scratch_quota_bytes=64 << 20)
    )
    if guard.policy.linux_reserve_bytes < 16 << 30 or guard.policy.host_reserve_bytes < 32 << 30:
        raise ValueError("v4 preserves the frozen Linux/host storage floors")
    guard.require_root(root)
    if args.mode in {"supervise-preflight", "supervise"}:
        facts = guard.check(growth)
        if facts["scratch_available_bytes"] < 32 << 20:
            raise ValueError("bounded scratch headroom unavailable")
        auth = args.authentication_home.resolve() / "auth.json"
        common = (
            "--model",
            args.model,
            "--candidate-root",
            str(candidate),
            "--output-root",
            str(root),
            "--fixture-root",
            str(fixture),
            "--authentication-home",
            str(args.authentication_home),
            "--scratch-root",
            str(args.scratch_root),
        )
        argv = (
            "/usr/bin/bwrap",
            "--unshare-pid",
            "--die-with-parent",
            "--new-session",
            "--ro-bind",
            "/",
            "/",
            "--dev-bind",
            "/dev",
            "/dev",
            "--bind",
            str(root),
            str(root),
            "--bind",
            str(guard.policy.scratch_root),
            str(guard.policy.scratch_root),
            "--bind",
            str(guard.policy.scratch_root),
            "/tmp",
            "--ro-bind",
            str(auth),
            str(auth),
            "--bind",
            str(guard.policy.evidence_root / "storage-control/lease.lock"),
            str(guard.policy.evidence_root / "storage-control/lease.lock"),
            "--proc",
            "/proc",
            sys.executable,
            "-B",
            str(Path(__file__).resolve()),
            "--mode",
            "preflight" if preflight_mode else "execute",
            *common,
        )
        try:
            run = supervise_storage_job(guard, argv, stage="deployment", expected_new_bytes=growth)
        except StorageRejected:
            owner = json.loads(
                (guard.policy.evidence_root / "storage-control/lease.lock").read_bytes()
            )
            run = Path(owner["run"])
        if run.parent != guard.policy.evidence_root / "storage-control":
            raise ValueError("v4 guard exit origin is unbound")
        raw = (run / "exit.json").read_bytes()
        publish(
            root,
            "preflight-supervisor-exit.json" if preflight_mode else "p10-supervisor-exit.json",
            {"guard_run": str(run), "exit_hash": sha256_bytes(raw), "actual_exit": json.loads(raw)},
        )
        return 0 if json.loads(raw).get("return_code") == 0 else 1
    guard.require_lease()
    guard.check(growth)
    if preflight_mode:
        return run_preflight(root, candidate, args.authentication_home)
    report = json.loads((root / "preflight/account-read-report.json").read_bytes())
    supervisor = json.loads((root / "preflight-supervisor-exit.json").read_bytes())
    if (
        report.get("candidate_version") != rubric.VERSION
        or report.get("account_read_status") != "PASS"
        or report.get("initialize_status") != "PASS"
        or report.get("account_read_invocations") != 1
        or report.get("thread_start_count") != 0
        or report.get("turn_start_count") != 0
        or supervisor["actual_exit"].get("return_code") != 0
    ):
        raise ValueError("fresh successor preflight has not completed successfully")
    with exclusive_directory_lock(root):
        if (root / "model-reservation.json").exists():
            raise ValueError("v4 single model allowance already consumed")
        publish(
            root,
            "model-reservation.json",
            {
                "preparation_hash": preparation_hash,
                "preflight_hash": sha256_file(root / "preflight/account-read-report.json"),
                "max_attempts": 1,
                "max_model_turns": 1,
                "retry_count": 0,
            },
        )
    bootstrap = (
        "import sys,runpy;sys.path[:0]="
        + repr([str(candidate / "overlay"), str(REPO / "src")])
        + ";runpy.run_module('quantos.integrations.codex.sdk_host',run_name='__main__')"
    )
    adapter = CodexSdkAdapter(
        authentication_home=args.authentication_home,
        host_argv=(sys.executable, "-I", "-B", "-c", bootstrap),
        runtime_candidate_id=rubric.PROFILE,
    )
    result = runner.execute(
        fixture, root, adapter=adapter, preparation_hash=preparation_hash, model=args.model
    )
    # execute() already exported and replayed against the manager-owned receipt.
    publish(root, "p10-v4-result.json", runner.summary(result))
    return result.process_return_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        target = Path(sys.argv[sys.argv.index("--output-root") + 1])
        publish(
            target,
            "wrapper-failure.json",
            {
                "failure_type": type(error).__name__,
                "message_hash": sha256_bytes(str(error).encode()),
                "qualification": "NOT_EVALUATED",
            },
        )
        raise SystemExit(1) from None
