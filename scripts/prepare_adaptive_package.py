#!/usr/bin/env python3
# ruff: noqa: RUF001
"""Freeze the reviewed local adaptive successor; no model or scientific computation."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import sys
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from quantos.application.adaptive_execution import quote_expression  # noqa: E402
from quantos.application.adaptive_store import read, save  # noqa: E402
from quantos.application.autonomous_execution import (  # noqa: E402
    build_autonomous_execution_bindings,
)
from quantos.application.discovery_baselines import baseline_expression_space  # noqa: E402
from quantos.application.enumeration import structural_expression_hash  # noqa: E402
from quantos.application.provenance import capture_code_provenance  # noqa: E402
from quantos.artifacts.store import sha256_file  # noqa: E402
from quantos.contracts.adaptive import AdaptiveResearchSpec  # noqa: E402
from quantos.contracts.base import canonical_json_bytes, sha256_bytes  # noqa: E402
from quantos.contracts.discovery import DiscoveryBatch, SequentialDiscoveryBatch  # noqa: E402
from quantos.contracts.qlib_view import QlibViewManifest  # noqa: E402
from quantos.contracts.snapshot import DataSnapshotManifest  # noqa: E402
from quantos.infrastructure.hosted_storage import StorageGuard, StoragePolicy  # noqa: E402


def prepare(recipe_path: Path, output: Path, expected_commit: str):
    recipe = json.loads(read(recipe_path))
    code = capture_code_provenance(ROOT)
    if code.commit_hash != expected_commit:
        raise ValueError("package source commit differs")
    pins = []
    for pin in recipe["source_pins"]:
        if sha256_file(Path(pin["path"])) != pin["sha256"]:
            raise ValueError("retained source pin differs")
        pins.append(pin)
    batches = []
    for path in recipe["batches"]:
        raw = read(Path(path))
        parsed = json.loads(raw)
        batch = (
            SequentialDiscoveryBatch.model_validate_json(raw).batch
            if parsed["schema_version"] == "discovery-sequential-batch/v2"
            else DiscoveryBatch.model_validate_json(raw)
        )
        if batch.canonical_bytes() != (
            canonical_json_bytes(parsed["batch"]) if "batch" in parsed else raw
        ):
            raise ValueError("historical batch must be canonical")
        batches.append(batch)
    design = batches[0].design
    snapshot = DataSnapshotManifest.model_validate_json(
        read(Path(recipe["snapshot_path"]) / "manifest.json", 16 << 20)
    )
    view = QlibViewManifest.model_validate_json(
        read(Path(recipe["qlib_view_path"]) / "manifest.json", 16 << 20)
    )
    if (snapshot.snapshot_hash, view.view_hash, view.source_snapshot_hash) != (
        design.snapshot_hash,
        design.qlib_view_hash,
        design.snapshot_hash,
    ):
        raise ValueError("snapshot/view manifests differ from inherited scientific inputs")
    bindings = build_autonomous_execution_bindings(
        snapshot=snapshot,
        qlib_view=view,
        research_policy=design.research_policy,
        validation_policy=design.validation_policy,
        authoring=design.authoring,
        cost_policy=design.cost_policy,
        backtest_policy=design.backtest_policy,
        code_commit_hash=code.commit_hash,
        lockfile_hash=code.lockfile_hash,
    )
    design = type(design).model_validate(
        {
            **design.model_dump(mode="python"),
            "bindings": bindings.model_dump(mode="python"),
            "research_question": recipe["research_question"],
            "exposure_history": (
                *design.exposure_history,
                (
                    "Adaptive successor consumes previous scientific summaries and every new "
                    "result for later design; no independent confirmation or adaptive "
                    "multiple-testing correction is claimed."
                ),
            ),
        }
    )
    initial = tuple(
        sorted(
            {
                structural_expression_hash(m.expression)
                for batch in batches
                for m in batch.mappings
                if m.expression is not None
            }
        )
    )
    # Explicit spec is new authority. No old balance, launch count or authorization is copied.
    spec = AdaptiveResearchSpec(
        task_id=recipe["task_id"],
        design=design,
        limits={
            "sdk_decisions": 2,
            "new_candidates": 2,
            "scientific_executions": 2,
            "compute_units": 1,
            "wall_seconds": 10800,
            "storage_growth_bytes": 5 << 30,
        },
        sdk=recipe["sdk"],
        workspace=str(ROOT),
        snapshot_path=recipe["snapshot_path"],
        qlib_view_path=recipe["qlib_view_path"],
        output_root=recipe["output_root"],
        sdk_cwd=str(Path(recipe["output_root"]) / "empty-sdk-cwd"),
        initial_structural_hashes=initial,
        context=recipe["context"],
        context_source_hashes=tuple(sorted(recipe["context_source_hashes"])),
    )
    quotes = Counter(quote_expression(spec, e) for e in baseline_expression_space(spec.design))
    units = max(quotes) * spec.limits.scientific_executions
    spec = spec.model_copy(
        update={
            "limits": spec.limits.model_copy(update={"compute_units": units}),
            "design": type(design).model_validate(
                {**design.model_dump(mode="python"), "max_compute_units": units}
            ),
        }
    )
    spec = AdaptiveResearchSpec.model_validate(spec.model_dump(mode="python"))
    policy_path = Path(recipe["storage_policy"])
    policy = json.loads(read(policy_path))
    for name in ("evidence_root", "scratch_root", "host_volume", "vhd_file"):
        policy[name] = Path(policy[name])
    guard = StorageGuard(StoragePolicy(**policy))
    capacity = guard.check(spec.limits.storage_growth_bytes)
    lease_fd = os.open(
        guard.policy.evidence_root / "storage-control/lease.lock", os.O_RDWR | os.O_NOFOLLOW
    )
    try:
        try:
            fcntl.flock(lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            concurrent_reservations = 0
        except BlockingIOError:
            concurrent_reservations = "ACTIVE_OR_UNKNOWN"
    finally:
        os.close(lease_fd)
    old_env = json.loads(read(Path(recipe["environment_original"])))
    distribution_versions = {name: version(name) for name in old_env["selected_distributions"]}
    # Reuse validated installation identity; rehash metadata/RECORD/binary originals only.
    for distribution in old_env["selected_distributions"].values():
        for pin in distribution["metadata"]:
            if sha256_file(Path(pin["path"])) != pin["sha256"]:
                raise ValueError("retained environment original differs")
            pins.append(pin)
    for path in (
        Path(recipe["python"]).resolve(),
        ROOT / "uv.lock",
        policy_path,
        Path(recipe["snapshot_path"]) / "manifest.json",
        Path(recipe["qlib_view_path"]) / "manifest.json",
        recipe_path,
        Path(recipe["environment_original"]),
    ):
        path = Path(path)
        pins.append({"path": str(path), "sha256": sha256_file(path)})
    output.mkdir(parents=True, exist_ok=False)
    save(output / "spec.json", spec)
    from quantos.application.adaptive_store import AdaptiveStore

    AdaptiveStore(spec).initialize()
    Path(spec.sdk_cwd).mkdir(parents=True, exist_ok=True)
    pythonpath = ":".join(
        [str(ROOT / "src"), str(ROOT), recipe["sdk_overlay"], recipe["site_packages"]]
    )
    launcher = (
        "#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\nsys.path[:0]="
        + repr(pythonpath.split(":"))
        + (
            "\nfrom quantos.application.adaptive_package import package_main\nraise "
            "SystemExit(package_main(Path("
        )
        + repr(str(output))
        + "),sys.argv[1:]))\n"
    )
    save(output / "launch.py", launcher.encode())
    pins.append({"path": str(output / "launch.py"), "sha256": sha256_bytes(launcher.encode())})
    proposal = {
        "schema_version": "adaptive-combination-proposal/v1",
        "status": "PROPOSED_NOT_AUTHORIZED",
        "commit": code.commit_hash,
        "task_hash": spec.content_hash,
        "spec_path": str(output / "spec.json"),
        "output_root": spec.output_root,
        "python": recipe["python"],
        "pythonpath": pythonpath,
        "profile": spec.sdk.model_dump(mode="json"),
        "limits": spec.limits.model_dump(mode="json"),
        "policy_quote": {
            "finite_structures": sum(quotes.values()),
            "units_per_structure_counts": {str(k): v for k, v in sorted(quotes.items())},
            "per_execution_cap": max(quotes),
            "parent_new_compute_units": units,
            "historical_allowance_transferred": 0,
            "source": (
                "quote_autonomous_workload over actual frozen grammar and ValidationPolicy;"
                " policy units are not seconds, tokens or money"
            ),
        },
        "wall_seconds": spec.limits.wall_seconds,
        "max_operator_recovery_operations": 2,
        "resources": {
            "growth_bytes": spec.limits.storage_growth_bytes,
            "components_bytes": {
                "two_complete_science_envelopes": 3 << 30,
                "sdk_metadata_checkpoints": 512 << 20,
                "result_verification_export_receipts": 512 << 20,
                "failure_safe_finish_margin": 1 << 30,
            },
            "basis": (
                "555-structure price grammar, at most 2 singleton full chains, 17-18 policy"
                " units each; 1.5 GiB per complete science envelope conservatively exceeds "
                "prior bounded two-run retained aggregate 1.394 GB and B2 0.5 GiB/envelope "
                "estimate; no prediction-comparison stage or dataset copies"
            ),
            "input_copies_bytes": 0,
            "workers": 1,
            "concurrent_guard_reservations_at_prepare": concurrent_reservations,
            "outside_guard_reservations": "UNAVAILABLE_NO_EXTRA_WORKERS_REQUESTED",
            "host_volume": str(guard.policy.host_volume),
            "vhd_file": str(guard.policy.vhd_file),
            "exclusive_existing_storage_lease_required": True,
            "capacity_at_prepare": capacity,
            "physical_host_floor_bytes": guard.policy.host_reserve_bytes,
            "linux_floor_bytes": guard.policy.linux_reserve_bytes,
            "scratch_hard_quota_bytes": guard.policy.scratch_quota_bytes,
            "reservation_held_awaiting_approval": False,
        },
        "egress": {
            "destination": (
                "Existing OpenAI Codex account endpoint only; apps=false; shell/MCP/tools disabled"
            ),
            "included": [
                "bounded research question/context (<=8000 characters)",
                "explicit source identity hashes and prior exposed structural hashes",
                "safe AST proposal and rationale",
                "verified own-task gate reason enums/scalar metrics/receipt references",
                "runtime/usage protocol metadata",
            ],
            "excluded": [
                "credential contents",
                "raw Parquet/Qlib bins",
                "full private repository/ledger",
                "sealed confirmation data",
            ],
        },
        "usage_observation_limits_each": {
            "input_count": spec.sdk.max_input_tokens,
            "output_count": spec.sdk.max_output_tokens,
            "provider_billing_hard_cap": False,
        },
        "activation": (
            "One fresh start within 24 hours of exact approval; 10800s original total "
            "wall deadline. No extension on restart. Source/dependency changes need new"
            " package."
        ),
        "recovery": (
            "Same task and remaining original deadline only: complete saved SDK capture"
            " may submit; complete saved outcome may publish receipt/settle; UNKNOWN "
            "never reissues; STARTED lacking complete verified result stops. Science "
            "restart count 0. Receipt-only reconciliation may run after task expiry "
            "with 900s management cap; no new SDK/science."
        ),
        "acceptance": (
            "OFFLINE_IMPLEMENTED_SIMULATED_ONLY; real new AST plus execution plus "
            "feedback-informed decision still unproven. First STOP is valid but leaves "
            "generation unproven; later STOP proves only observed stop branch, not "
            "revision branch."
        ),
        "current_permissions": {
            "sdk_calls": 0,
            "scientific_executions": 0,
            "new_policy_units": 0,
            "egress": False,
            "push": False,
            "deployment": False,
        },
    }
    save(output / "proposed-combination.json", proposal)
    pins.append({"path": str(output / "spec.json"), "sha256": spec.content_hash})
    manifest = {
        "schema_version": "adaptive-release-manifest/v1",
        "commit": code.commit_hash,
        "workspace": str(ROOT),
        "lockfile_sha256": code.lockfile_hash,
        "host": socket.gethostname(),
        "uid": os.getuid(),
        "python": recipe["python"],
        "pythonpath": pythonpath,
        "distribution_versions": distribution_versions,
        "spec_path": str(output / "spec.json"),
        "task_hash": spec.content_hash,
        "output_root": spec.output_root,
        "proposal_sha256": sha256_bytes(read(output / "proposed-combination.json")),
        "storage_policy": {"path": str(policy_path), "sha256": sha256_file(policy_path)},
        "readonly_inputs": [spec.snapshot_path, spec.qlib_view_path],
        "pins": list({p["path"]: p for p in pins}.values()),
        "created_at": datetime.now(UTC),
        "status": "OFFLINE_PACKAGE_NOT_AUTHORIZED",
        "qualification": "NOT_QUALIFIED",
    }
    save(output / "release-manifest.json", manifest)
    save(
        output / "preparation.json",
        {
            "schema_version": "adaptive-package-preparation/v1",
            "task_hash": spec.content_hash,
            "commit": code.commit_hash,
            "real_sdk_calls": 0,
            "scientific_executions": 0,
            "capacity": capacity,
            "quote_distribution": {str(k): v for k, v in sorted(quotes.items())},
            "source_scope": (
                "small original/manifests/installation metadata only; full data "
                "verification deferred to existing science adapter before execution"
            ),
            "created_at": datetime.now(UTC),
        },
    )
    launch_command = f"{recipe['python']} -B {output / 'launch.py'}"
    approval_text = (
        "我批准此固定包：最多SDK2次、新候选2个、科学2次、36个新policy units，"
        "原始deadline3小时、增长5GiB，包内OpenAI外发范围；"
        "SDK自动重试、UNKNOWN重发、科学restart、sealed均0；"
        "同任务至多2次受限恢复管理操作，禁止扩大额度。"
    )
    startup = f"""请在 /home/zjw/quant-research-os 运行我已批准的这一个具体包。
先读 AGENTS.md、实施约定、{ROOT / "docs/guides/bounded-adaptive-research-v1.md"}，
再核对 {output / "release-manifest.json"} 和 {output / "proposed-combination.json"}。
固定开发提交：{code.commit_hash}
父任务哈希：{spec.content_hash}
提案SHA256：{manifest["proposal_sha256"]}
清单SHA256：{sha256_bytes(read(output / "release-manifest.json"))}
实际输出根：{spec.output_root}
Python：{recipe["python"]}
SDK/runtime 0.162.1，gpt-6.1-sol / medium，apps=false，单worker。
本消息的具体授权是：{approval_text}
只向现有OpenAI Codex账户端点发送包内有限问题/历史结构/来源hash、安全AST、
自身科学反馈gate原因码与scalar metrics；不外发凭证、Parquet/Qlib原数据、完整仓库或其他任务ledger。
输入/输出每次观测上界50000/4096，不将其声称为远端精确计费硬上限。

按顺序执行（无需手填任何hash）：
{launch_command} --verify
{launch_command} --authorize '{approval_text}'
{launch_command} --run-approved

一次启动后自动推进，普通进度不逐轮询问。模型可以首次STOP或反馈后STOP，不为展示流程强迫生成。
不要改源码、升级/uv sync、执行旧launcher、采集、部署或推送。不要为了科学PASS改变政策或追加机会。
如中断，先检查 operator/operations/SDK/科学job的独立退出与完整原件。
完整capture可补提交；完整outcome可补receipt/结算；UNKNOWN不得重发，STARTED不完整不得重算。
同一任务、原始deadline与原余额内，且证据明确支持时最多两次管理恢复：
{launch_command} --resume-approved
或仅对账：
{launch_command} --reconcile-approved
恢复不新增SDK/科学机会，不修改旧失败/退出，不凭锁消失推断已完成。

交付原始SDK输入/响应/结构、实际科学退出/Validation/receipt、真实反馈后的动作、
机会分母、consumed/reserved预算、最终停止理由、guard cleanup及未证明分支。
工程接受与科学REJECT/FAILED分开；没有实际新候选/反馈后决策的分支继续标缺证。
本提示词只有用户明确批准并在运行会话发送后才是运行指令，离线保存它不构成授权。
"""
    save(output / "startup-prompt.txt", startup.encode())
    runbook = f"""# 本机最小真实运行包

状态：PROPOSED_NOT_AUTHORIZED。新commit {code.commit_hash}；新task {spec.content_hash}。
本机只读共享原snapshot/view，不复制数据。全量数据核验在正式运行首次SDK前由既有验证器执行，
同operation复用；准备不声称已取得新组合资格。

离线核对：`{launch_command} --verify`。
批准后直接复制 [完整会话提示词](startup-prompt.txt)，其中已填好全部hash、实际环境、路径和命令。
每个包只有一次首次启动，最多两次受限resume/reconcile；SDK自动retry与科学restart始终0。
最晚在批准后24小时首次启动；任务总原期限10800秒，绝不在恢复时延长；过期只对账管理上限900秒。
科学按候选实际17/18 units预留，父cap36；报错和非法响应同样占SDK机会。

资源：新任务完整增长5GiB（科学3GiB、SDK/metadata 0.5GiB、结果核验/receipt 0.5GiB、
失败留证/安全收尾1GiB），单worker，无大型输入副本。沿用现有守卫与独占host lease，
当前宿主余量、物理卷/VHD、floor与scratch硬quota在提案和preparation原件中；启动必须刷新，
若另有并发reservation或容量不足则停止，不删证据腾空间。

实际运行输出：{spec.output_root}。
operator/operation-* 是父进程真实wait退出，operations/ 是controller自身观察；
children/*/job/process-exit.json 是科学namespace独立退出，child-exit不代替父wait；
sdk/* 是原始capture、来源fact、用量与SDK host退出。
objects/events/checkpoints/reports是不可变父任务链。
`feedback_verification=RETAINED_PROJECTION_REVERIFY_REQUIRED` 的只读status不是重新科学验证。
科学REJECT有效保留；FAILED保持NOT_EVALUATED；不得退款UNKNOWN或盲目重跑。

初次STOP保留停止证据，但新生成路径仍未证明；第二次STOP不证明修订路径。
本包不授予P14d-C、盈利、独立sealed、长期质量或跨宿主安装资格。
当前源码和实际环境pins、完整外发范围见release-manifest.json/proposed-combination.json。
"""
    save(output / "runbook.md", runbook.encode())
    return manifest, proposal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    manifest, _ = prepare(args.recipe, args.output, args.expected_commit)
    print(
        json.dumps(
            {
                "task_hash": manifest["task_hash"],
                "commit": manifest["commit"],
                "package": str(args.output),
                "status": "PROPOSED_NOT_AUTHORIZED",
            }
        )
    )


if __name__ == "__main__":
    main()
