#!/usr/bin/env python3
"""Finite successor P10 execution/replay; canonical and historical runners stay unchanged."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from quantos.application.harness_runner import FrozenSpikeInputs, HarnessRunResult  # noqa: E402
from quantos.artifacts.store import atomic_write_bytes, exclusive_directory_lock  # noqa: E402
from quantos.contracts.base import canonical_json_bytes, sha256_bytes  # noqa: E402
from quantos.infrastructure.hosted_storage import (  # noqa: E402
    StorageGuard,
    StorageRejected,
    configured_guard,
    supervise_storage_job,
)
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter  # noqa: E402

_GROWTH = 256 << 20
_VERSION = "0.162.1"
_PROFILE = "openai-codex-0.162.1-p10-v3"


class _Runner(Protocol):
    CODEX_SDK_VERSION: str
    CODEX_RUNTIME_PACKAGE_VERSION: str
    CodexSdkAdapter: Callable[[], CodexSdkAdapter]

    def load_frozen_spike_inputs(self, fixture_root: Path) -> FrozenSpikeInputs: ...
    def execute_codex_spike(self, fixture_root: Path, output_root: Path) -> HarnessRunResult: ...
    def verify_codex_spike_artifact(self, run: Path, fixture_root: Path) -> HarnessRunResult: ...
    def safe_result_summary(self, result: HarnessRunResult) -> dict[str, object]: ...


def publish(root: Path, name: str, value: object) -> None:
    atomic_write_bytes(root / name, canonical_json_bytes(value))


def runner(candidate: Path, authentication: Path) -> _Runner:
    source = REPO / "src/quantos/application/harness_runner.py"
    spec = importlib.util.spec_from_file_location("quantos_fr03_01621_p10_runner", source)
    if spec is None or spec.loader is None:
        raise ValueError("frozen P10 runner source is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    fixed = cast(_Runner, cast(object, module))
    fixed.CODEX_SDK_VERSION = fixed.CODEX_RUNTIME_PACKAGE_VERSION = _VERSION
    bootstrap = (
        "import sys,runpy;sys.path[:0]="
        + repr([str(candidate / "overlay"), str(REPO / "src")])
        + ";runpy.run_module('quantos.integrations.codex.sdk_host',run_name='__main__')"
    )
    fixed.CodexSdkAdapter = lambda: CodexSdkAdapter(
        authentication_home=authentication,
        host_argv=(sys.executable, "-I", "-B", "-c", bootstrap),
        runtime_candidate_id=_PROFILE,
    )
    return fixed


def prepare(root: Path, candidate: Path, fixture: Path, authentication: Path) -> _Runner:
    report = json.loads((candidate / "account-read-report.json").read_bytes())
    if (
        report.get("candidate_version") != _VERSION
        or report.get("account_read_status") != "PASS"
        or report.get("initialize_status") != "PASS"
        or report.get("account_read_invocations") != 1
        or report.get("thread_start_count") != 0
        or report.get("turn_start_count") != 0
    ):
        raise ValueError("finite candidate preflight is not successful")
    fixed = runner(candidate, authentication)
    inputs = fixed.load_frozen_spike_inputs(fixture)
    publish(
        root,
        "candidate-p10-preparation.json",
        {
            "schema_version": "fr03-candidate-p10-preparation/v1",
            "candidate_profile": _PROFILE,
            "candidate_version": _VERSION,
            "fixture_hashes": inputs.all_input_hashes,
            "candidate_provenance_hash": sha256_bytes(
                (candidate / "candidate-provenance.json").read_bytes()
            ),
            "preflight_report_hash": sha256_bytes(
                (candidate / "account-read-report.json").read_bytes()
            ),
            "runner_source_hash": sha256_bytes(
                (REPO / "src/quantos/application/harness_runner.py").read_bytes()
            ),
            "wrapper_source_hash": sha256_bytes(Path(__file__).read_bytes()),
            "model": "gpt-5.6-sol",
            "reasoning_effort": "medium",
            "max_attempts": 1,
            "max_input_tokens": 250000,
            "max_output_tokens": 4096,
            "timeout_seconds": 900,
            "rubric": "FROZEN_CODE_MODE_V3_9_OF_9",
            "canonical_lock_changed": False,
            "qualification": "NOT_EVALUATED",
        },
    )
    return fixed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("prepare", "execute", "supervise", "verify"), required=True
    )
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--authentication-home", type=Path, required=True)
    parser.add_argument(
        "--fixture-root", type=Path, default=REPO / "tests/fixtures/p10_codex_workspace_v3"
    )
    parser.add_argument("--verify-run", type=Path)
    args = parser.parse_args()
    root, candidate, fixture = (
        args.output_root.resolve(),
        args.candidate_root.resolve(),
        args.fixture_root.resolve(),
    )
    fixed = prepare(root, candidate, fixture, args.authentication_home)
    if args.mode == "prepare":
        return 0
    if args.mode == "verify":
        if args.verify_run is None:
            parser.error("offline verification needs an explicit retained run")
        result = fixed.verify_codex_spike_artifact(args.verify_run, fixture)
        publish(root, "candidate-p10-offline-verification.json", fixed.safe_result_summary(result))
        return 0 if result.report.decision == "GO" else 1
    guard = configured_guard()
    guard.require_root(root)
    if args.mode == "supervise":
        guard = StorageGuard(
            replace(
                guard.policy,
                scratch_root=REPO / "artifacts/hosted-scratch/recovery-runtime01",
                scratch_quota_bytes=64 << 20,
            )
        )
        facts = guard.check(_GROWTH)
        if facts["scratch_available_bytes"] < 32 << 20:
            raise ValueError("complete P10 scratch headroom is unavailable")
        auth = args.authentication_home.resolve() / "auth.json"
        common = (
            "--candidate-root",
            str(candidate),
            "--output-root",
            str(root),
            "--authentication-home",
            str(args.authentication_home),
            "--fixture-root",
            str(fixture),
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
            "execute",
            *common,
        )
        try:
            run = supervise_storage_job(guard, argv, stage="deployment", expected_new_bytes=_GROWTH)
        except StorageRejected:
            owner = json.loads(
                (guard.policy.evidence_root / "storage-control/lease.lock").read_bytes()
            )
            run = Path(owner["run"])
        if run.parent != guard.policy.evidence_root / "storage-control":
            raise ValueError("P10 guard exit source is unbound")
        exit_data = (run / "exit.json").read_bytes()
        publish(
            root,
            "candidate-p10-supervisor-exit.json",
            {
                "guard_run": str(run),
                "exit_hash": sha256_bytes(exit_data),
                "actual_exit": json.loads(exit_data),
            },
        )
        return 0 if json.loads(exit_data).get("return_code") == 0 else 1
    guard.require_lease()
    guard.check(_GROWTH)
    with exclusive_directory_lock(root):
        if (root / "candidate-p10-reservation.json").exists():
            raise ValueError("candidate P10 single allowance already consumed")
        publish(
            root,
            "candidate-p10-reservation.json",
            {
                "candidate_profile": _PROFILE,
                "max_attempts": 1,
                "max_model_turns": 1,
                "max_input_tokens": 250000,
                "max_output_tokens": 4096,
                "timeout_seconds": 900,
            },
        )
    result = fixed.execute_codex_spike(fixture, root / "bundles")
    summary = fixed.safe_result_summary(result)
    publish(root, "candidate-p10-live-result.json", summary)
    verified = fixed.verify_codex_spike_artifact(result.report_path.parent, fixture)
    publish(root, "candidate-p10-offline-verification.json", fixed.safe_result_summary(verified))
    return 0 if verified.report.decision == "GO" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Authority failures retain a safe diagnosis, without exception text or proposal bytes.
        target = Path(sys.argv[sys.argv.index("--output-root") + 1])
        publish(
            target,
            "candidate-p10-wrapper-failure.json",
            {
                "failure_type": type(error).__name__,
                "failure_message_hash": sha256_bytes(str(error).encode()),
                "qualification": "NOT_EVALUATED",
            },
        )
        raise SystemExit(1) from None
