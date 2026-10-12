#!/usr/bin/env python3
"""One-shot P13 successor using the existing SDK runner and hosted storage supervisor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from quantos.application import p13_agent_runner as runner  # noqa: E402
from quantos.artifacts.store import (  # noqa: E402
    atomic_write_bytes,
    exclusive_directory_lock,
    sha256_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes  # noqa: E402
from quantos.infrastructure.hosted_storage import (  # noqa: E402
    StorageRejected,
    configured_guard,
    supervise_storage_job,
)
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter  # noqa: E402

CANDIDATE = Path("/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-fr03-01621-02")
STORE = Path("/home/zjw/quant-research-os/artifacts/evidence-stores") / (
    "sha256-4fb04acc23c62b72d37df826560e2515a68cf7c7973ce1a0527a42a2b14fc306"
)
BINDINGS = {
    "expected_store_hash": "4fb04acc23c62b72d37df826560e2515a68cf7c7973ce1a0527a42a2b14fc306",
    "expected_evidence_hash": "e1e8591a6b3daa9678923c0fd4318fac991679587e1f434efc7da8ae29a1e800",
    "benchmark_policy_hash": "a1eecec872b784c1dea5f90cbf6197a47e494a0be79eb65fa411879fa2c0b8f3",
}
GROWTH = 256 << 20


def publish(root: Path, name: str, payload: object) -> None:
    atomic_write_bytes(root / name, canonical_json_bytes(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("supervise", "execute"), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--p10-root", type=Path, required=True)
    args = parser.parse_args()
    root, p10 = args.output_root.resolve(), args.p10_root.resolve()
    guard = configured_guard()
    guard.require_root(root)
    # No new independent account/read. The SDK runner retains its built-in read.
    p10_result = json.loads((p10 / "p10-v4-result.json").read_bytes())
    p10_exit = json.loads((p10 / "p10-supervisor-exit.json").read_bytes())
    if (
        p10_result["decision"] != "GO"
        or p10_exit["actual_exit"]["return_code"] != 0
        or not p10_exit["actual_exit"]["cleanup_verified"]
    ):
        raise ValueError("P13 requires completed P10 GO and clean actual exit")
    report_path = Path(p10_result["report_path"])
    manifest = json.loads((report_path.parent / "agent-run-manifest.json").read_bytes())
    if (
        manifest["provider_model_identifier"] != "gpt-6.1-sol"
        or manifest["sdk_version"] != "0.162.1"
        or manifest["runtime_package_version"] != "0.162.1"
    ):
        raise ValueError("P10 does not bind this successor tuple")
    source_inventory = json.loads((root / "source-inventory.json").read_bytes())
    for name, expected in source_inventory.items():
        if sha256_file(REPO / name) != expected:
            raise ValueError("P13 source/fixture changed after frozen preparation")
    inputs = runner.load_p13_agent_inputs(
        REPO,
        STORE,
        expected_store_hash=BINDINGS["expected_store_hash"],
        expected_evidence_hash=BINDINGS["expected_evidence_hash"],
    )
    request = runner._execution_request(  # pyright: ignore[reportPrivateUsage]
        REPO, inputs, qualification_profile=runner.GPT61_PROFILE, mcp_python=Path(sys.executable)
    )
    spec = runner._run_spec(  # pyright: ignore[reportPrivateUsage]
        inputs,
        BINDINGS["benchmark_policy_hash"],
        request,
        qualification_profile=runner.GPT61_PROFILE,
    )
    if (root / "harness-request.json").read_bytes() != request.canonical_bytes() or (
        root / "agent-run-spec.json"
    ).read_bytes() != spec.canonical_bytes():
        raise ValueError("P13 request/spec changed after preparation")
    if args.mode == "supervise":
        capacity = guard.check(GROWTH)
        publish(root, "capacity-prelaunch.json", capacity)
        auth = Path("/home/zjw/.codex/auth.json")
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
            "--output-root",
            str(root),
            "--p10-root",
            str(p10),
        )
        try:
            run = supervise_storage_job(guard, argv, stage="deployment", expected_new_bytes=GROWTH)
        except StorageRejected:
            owner = json.loads(
                (guard.policy.evidence_root / "storage-control/lease.lock").read_bytes()
            )
            run = Path(owner["run"])
        if run.parent != guard.policy.evidence_root / "storage-control":
            raise ValueError("P13 supervisor exit origin is unbound")
        raw = (run / "exit.json").read_bytes()
        publish(
            root,
            "p13-supervisor-exit.json",
            {"guard_run": str(run), "exit_hash": sha256_bytes(raw), "actual_exit": json.loads(raw)},
        )
        return 0 if json.loads(raw).get("return_code") == 0 else 1
    guard.require_lease()
    guard.check(GROWTH)
    with exclusive_directory_lock(root):
        if (root / "model-reservation.json").exists():
            raise ValueError("P13 one-shot runtime allowance already reserved")
        publish(
            root,
            "model-reservation.json",
            {
                "run_spec_hash": spec.content_hash,
                "max_attempts": 1,
                "max_model_turns": 1,
                "automatic_retries": 0,
                "p10_report_file_sha256": sha256_file(report_path),
                "token_thresholds": "post-execution acceptance, not provider billing caps",
            },
        )
    bootstrap = (
        "import sys,runpy;sys.path[:0]="
        + repr([str(CANDIDATE / "overlay"), str(REPO / "src")])
        + ";runpy.run_module('quantos.integrations.codex.sdk_host',run_name='__main__')"
    )
    adapter = CodexSdkAdapter(
        authentication_home=Path("/home/zjw/.codex"),
        host_argv=(sys.executable, "-I", "-B", "-c", bootstrap),
        runtime_candidate_id=runner.GPT61_PROFILE,
    )
    # The immutable failed run is published by the same P13 runner as successful runs.
    try:
        result = runner.execute_p13_agent(
            REPO,
            STORE,
            root / "agent-runs",
            expected_store_hash=BINDINGS["expected_store_hash"],
            expected_evidence_hash=BINDINGS["expected_evidence_hash"],
            benchmark_policy_hash=BINDINGS["benchmark_policy_hash"],
            qualification_profile=runner.GPT61_PROFILE,
            mcp_python=Path(sys.executable),
            harness=adapter,
        )
    except runner.P13AgentRunnerError as error:
        if error.manifest is None:
            raise
        path = root / "agent-runs" / f"sha256-{error.manifest.content_hash}"
        observation = (
            json.loads((path / "host-observations.json").read_bytes())
            if (path / "host-observations.json").exists()
            else None
        )
        publish(
            root,
            "p13-result.json",
            {
                "status": "FAILED",
                "validation": "NOT_EVALUATED",
                "manifest_hash": error.manifest.content_hash,
                "run_path": str(path),
                "failure_reason_code": error.manifest.failure_reason_code,
                "proposal_hashes": error.manifest.output_proposal_hashes,
                "actual_model_turn_started": observation.get("model_turn_started")
                if observation
                else None,
                "provider_reported_usage": None,
                "zero_usage_manifest_scope": (
                    "No model turn when explicitly observed; not a provider usage report"
                ),
                "runtime_invocations": 1,
                "retry_count": 0,
                "fr03": "NO_GO",
            },
        )
        return 1
    replay = runner.load_p13_agent_run(
        REPO,
        STORE,
        result.path,
        expected_store_hash=BINDINGS["expected_store_hash"],
        expected_evidence_hash=BINDINGS["expected_evidence_hash"],
        benchmark_policy_hash=BINDINGS["benchmark_policy_hash"],
        qualification_profile=runner.GPT61_PROFILE,
        mcp_python=Path(sys.executable),
    )
    publish(
        root,
        "p13-result.json",
        {
            "status": "AGENT_SUCCEEDED",
            "validation": "NOT_EVALUATED",
            "manifest_hash": replay.manifest.content_hash,
            "proposal_hash": replay.proposal.content_hash,
            "run_path": str(replay.path),
            "runtime_invocations": 1,
            "retry_count": 0,
        },
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        if "--output-root" in sys.argv:
            publish(
                Path(sys.argv[sys.argv.index("--output-root") + 1]),
                "wrapper-failure.json",
                {
                    "failure_type": type(error).__name__,
                    "message_hash": sha256_bytes(str(error).encode()),
                    "status": "FAILED",
                    "validation": "NOT_EVALUATED",
                },
            )
        raise SystemExit(1) from None
