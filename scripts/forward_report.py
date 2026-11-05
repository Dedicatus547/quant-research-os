"""Read a frozen campaign through existing status APIs; never acquire or advance."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from quantos.application.forward_campaign import SHANGHAI, core_for, read_ref, registry
from quantos.application.personal_shadow import PersonalShadowService
from quantos.artifacts.store import confined_regular_file, sha256_file, verify_file
from quantos.contracts.personal_strategy import PersonalExecutionPolicy, PersonalStrategy
from quantos.research.personal_session import NativePersonalSession, UnknownNativeStep


class ReadOnlySession(NativePersonalSession):
    """Reuse native verification/decoding, disabling constructor and recovery writes."""

    def __init__(
        self, root: Path, *, strategy: Any, policy: Any, runtime_hash: str, benchmark: str
    ) -> None:
        self.root = root.absolute()
        self.strategy, self.policy = strategy, policy
        self.runtime_hash, self.benchmark = runtime_hash, benchmark
        self.identity = {
            "schema_version": "personal-native-session/v1",
            "strategy_hash": strategy.content_hash,
            "policy_hash": policy.content_hash,
            "runtime_hash": runtime_hash,
            "benchmark": benchmark,
        }
        # Unlike the native writer constructor, absence cannot create session.json.
        if self._read_json("session.json") != self.identity:
            raise ValueError("native session dependencies changed")

    def _reconcile(self, path: Path) -> None:
        raise UnknownNativeStep("report never publishes or recovers an unfinished native step")


class ReadOnlyShadow(PersonalShadowService):
    def _session(self, shadow_id: str, plan: dict[str, Any]) -> ReadOnlySession:
        if plan["runtime_hash"] != self.runtime_hash:
            raise PermissionError("native account runtime differs")
        return ReadOnlySession(
            self.root / "shadow-accounts" / shadow_id / "native",
            strategy=PersonalStrategy.model_validate(plan["strategy"]),
            policy=PersonalExecutionPolicy.model_validate(plan["policy"]),
            runtime_hash=self.runtime_hash,
            benchmark=plan["benchmark"],
        )


def shadow_status(product: Any, shadow_id: str) -> dict[str, Any]:
    service = product.shadow
    plan = service._plan(shadow_id)
    if plan["runtime_hash"] != service.runtime_hash:
        raise PermissionError("native account runtime differs")
    root = service.root / "shadow-accounts" / shadow_id
    native = root / "native"
    if native.is_symlink():
        raise ValueError("native session root must not be a symlink")
    if not native.exists():
        return {
            "state": "STOPPED" if (root / "stop.json").exists() else "NOT_STARTED",
            "native": {
                "completed_sessions": 0,
                "last_execution_date": None,
                "checkpoint_hash": None,
            },
            "native_cash_cny": None,
            "native_latest_report": None,
            "holdings_count": 0,
        }
    confined_regular_file(native, "session.json")
    reader = ReadOnlyShadow(service.root, service.observations, runtime_hash=service.runtime_hash)
    return reader.status(shadow_id)


def scheduled_rows(plan: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """A missing terminal record is never treated as success or refunded budget."""
    if now.tzinfo is None:
        raise ValueError("report clock requires a timezone")
    rows = []
    root = Path(plan["root"]) / "scheduled-jobs"
    for phase, days in (("acquire", plan["acquisition_dates"]), ("observe", plan["signal_dates"])):
        for day in days:
            due_day = date.fromisoformat(day) + timedelta(days=phase == "observe")
            due = datetime.combine(
                due_day, time(22, 30) if phase == "acquire" else time(0, 1), SHANGHAI
            )
            job = root / f"{day}-{phase}"
            row: dict[str, Any] = {
                "day": day,
                "phase": phase,
                "due_at": due.isoformat(),
                "state": "DUE_WITHOUT_RECORD" if due <= now else "WAITING",
                "wall_seconds": None,
                "evidence": [],
            }
            for name in ("intent", "result", "failure"):
                path = job / f"{name}.json"
                if not path.exists():
                    continue
                ref = {"path": str(path), "sha256": sha256_file(path)}
                value = read_ref(ref)
                if value.get("day") != day or value.get("phase") != phase:
                    raise ValueError("scheduler record belongs to a different job")
                row["evidence"].append(ref)
                if name == "intent":
                    row["state"] = "IN_PROGRESS_OR_UNKNOWN"
                elif name == "result":
                    if value.get("state") != "COMPLETED":
                        raise ValueError("scheduler result is not completed")
                    row["state"] = "COMPLETED"
                    row["wall_seconds"] = value["wall_seconds"]
                else:
                    row["state"] = "STOPPED"
                    row["error_type"] = value.get("error_type")
                    row["wall_seconds"] = value.get("wall_seconds")
            wall = row["wall_seconds"]
            if wall is not None and (
                type(wall) not in (int, float) or not math.isfinite(wall) or wall < 0
            ):
                raise ValueError("invalid scheduler wall charge")
            rows.append(row)
    return sorted(rows, key=lambda row: (row["due_at"], row["phase"]))


def collect(plan_path: Path, expected_hash: str) -> dict[str, Any]:
    plan = read_ref({"path": str(plan_path), "sha256": expected_hash})
    now = datetime.now(UTC)
    for name, digest in plan["source_hashes"].items():
        verify_file(Path(plan["repo_root"]) / name, digest)
    read_ref(plan["approval"])
    rows = scheduled_rows(plan, now)
    # Only a contiguous, explicitly linked registry prefix can select server configuration.
    selected = plan["initial_date"]
    gap = False
    for day in plan["acquisition_dates"]:
        exists = (Path(plan["root"]) / "registry" / f"{day}.json").exists()
        if exists and gap:
            raise ValueError("campaign registry has a gap")
        if exists:
            selected = day
        else:
            gap = True
    state = registry(plan, selected)
    acquired = read_ref(state["acquisition_result"])
    arms = []
    issues = [
        f"{r['day']} {r['phase']}: {r['state']}"
        for r in rows
        if r["state"] not in {"WAITING", "COMPLETED"}
    ]
    stop = Path(plan["root"]) / "campaign-stop.json"
    if stop.exists():
        issues.append("campaign STOP exists; reconcile retained evidence before any continuation")
    for arm in plan["arms"]:
        product = core_for(plan, state, arm)
        observations = product.observations.status(arm["observation_id"], limit=100)
        records = list(observations["records"])
        offset = observations["next_offset"]
        while offset is not None:
            page = product.observations.status(arm["observation_id"], offset=offset, limit=100)
            if page["record_count"] != observations["record_count"]:
                raise RuntimeError("observations changed during report; collect a new report")
            records.extend(page["records"])
            offset = page["next_offset"]
        shadow = shadow_status(product, arm["shadow_id"])
        scopes = product.scope_status()
        forward = scopes["forward"]
        if observations["unknown_attempts"] or shadow["state"] == "UNKNOWN":
            issues.append(arm["name"] + ": unresolved operation; never infer success")
        if observations["state"] == "STOPPED" or shadow["state"] == "STOPPED":
            issues.append(arm["name"] + ": stopped")
        if forward is None or forward["state"] != "OPEN" or forward["remaining_limits"]["pending"]:
            issues.append(arm["name"] + ": inspect scope state and outstanding reservations")
        native = shadow["native"]
        arms.append(
            {
                "name": arm["name"],
                "observation_id": arm["observation_id"],
                "shadow_id": arm["shadow_id"],
                "configuration": state["configs"][arm["name"]],
                "observation_status": observations["state"],
                "observation_record_count": observations["record_count"],
                "record_status_counts": dict(Counter(r["status"] for r in records)),
                "after_the_fact_records": sum(bool(r.get("after_the_fact")) for r in records),
                "unknown_attempts": observations["unknown_attempts"],
                "records": records,
                "native_status": shadow["state"],
                "completed_sessions": native["completed_sessions"],
                "last_execution_date": native["last_execution_date"],
                "checkpoint_hash": native["checkpoint_hash"],
                "native_cash_cny": shadow["native_cash_cny"],
                "native_latest_report": shadow["native_latest_report"],
                "holdings_count": shadow["holdings_count"],
                "scope": forward,
            }
        )
    # Scheduler elapsed time and native scope charges overlap: never add both together.
    known_wall = plan["initial_wall_charge_seconds"] + sum(
        r["wall_seconds"] for r in rows if r["wall_seconds"] is not None
    )
    unknown_wall = any(r["state"] == "IN_PROGRESS_OR_UNKNOWN" for r in rows)
    jobs_root = Path(plan["root"]) / "scheduled-jobs"
    expected_jobs = {f"{r['day']}-{r['phase']}" for r in rows}
    unexpected_jobs = (
        sorted(p.name for p in jobs_root.iterdir() if p.name not in expected_jobs)
        if jobs_root.exists()
        else []
    )
    if unexpected_jobs:
        unknown_wall = True
        issues.append(
            "unexpected scheduler entries require inspection: " + ", ".join(unexpected_jobs)
        )
    pending = [r for r in rows if r["state"] == "WAITING"]
    return {
        "schema_version": "forward-operator-report/v1",
        "generated_at": now.isoformat(),
        "authority": "DERIVED_READ_ONLY_VIEW; not execution permission or scientific acceptance",
        "plan": {"path": str(plan_path), "sha256": expected_hash},
        "state": "ATTENTION_REQUIRED" if issues else "WAITING" if pending else "FINISHED_SCHEDULE",
        "issues": issues,
        "source_pins_verified": len(plan["source_hashes"]),
        "registered_through": selected,
        "registered_acquisition": state["acquisition_result"],
        "action_source_status": acquired["assessment"]["status"],
        "source_scope": plan["source_scope"],
        "scientific_status": plan["scientific_status"],
        "next_scheduled": pending[0] if pending else None,
        "scheduler_state_counts": dict(Counter(r["state"] for r in rows)),
        "scheduler_jobs": rows,
        "arms": arms,
        "budget": {
            "global_wall_seconds": plan["global_wall_seconds"],
            "known_scheduler_wall_charge_seconds": known_wall,
            "unresolved_scheduler_wall": unknown_wall,
            "remaining_wall_seconds": None
            if unknown_wall
            else max(0, plan["global_wall_seconds"] - known_wall),
            "complete_growth_limit_bytes": plan["complete_growth_bytes"],
            "current_complete_growth_bytes": None,
            "note": "Scope reservations are not usage. Global growth requires the host guard.",
        },
        "limits": [
            "Status APIs verify chains; market-data qualification is not repeated.",
            "Collection is sequential, not a cross-service atomic snapshot; use generated_at.",
            "Scheduler evidence does not prove a live timer; inspect systemd separately.",
            "Missing account metrics remain null; no future prices or reconstructed account PnL.",
        ],
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 前瞻运行报告",
        "",
        f"读取时间: {report['generated_at']}",
        "",
        f"运行状态: {report['state']}; 科学状态: {report['scientific_status']}。",
        f"已注册行情截至 {report['registered_through']}; "
        f"来源状态: {report['action_source_status']}。",
        "",
        "| 组别 | 信号记录 | 原生完成日 | 最近执行日 | 现金(元) |",
        "| --- | ---: | ---: | --- | ---: |",
    ]

    def display(value: Any) -> str:
        return "未产生/未知" if value is None else str(value).replace("|", "\\|").replace("\n", " ")

    for arm in report["arms"]:
        lines.append(
            "| "
            + " | ".join(
                display(arm[k])
                for k in (
                    "name",
                    "observation_record_count",
                    "completed_sessions",
                    "last_execution_date",
                    "native_cash_cny",
                )
            )
            + " |"
        )
    upcoming = report["next_scheduled"]
    if upcoming:
        lines += [
            "",
            f"下一计划: {upcoming['due_at']}, {upcoming['phase']}, 对应 {upcoming['day']}。",
        ]
    lines += ["", "## 需要关注", ""] + (
        ["- " + item for item in report["issues"]] or ["未发现状态异常; 定时器是否在线需另行查看。"]
    )
    lines += ["", "## 原生账户报告", "", "以下直接展示 Qlib 状态返回的最近报告; 空值表示尚无结果。"]
    for arm in report["arms"]:
        lines += [
            "",
            f"### {arm['name']}",
            "",
            "```json",
            json.dumps(arm["native_latest_report"], ensure_ascii=False, indent=2),
            "```",
        ]
    lines += [
        "",
        "## 预算与证据范围",
        "",
        "```json",
        json.dumps(report["budget"], ensure_ascii=False, indent=2),
        "```",
        "",
        "完整状态、逐日任务、信号及检查点引用见同目录 report.json。",
        "本页是读取时点的派生视图, 不授予执行权限, 不替代冻结研究判据。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    plan_path, output = args.plan.resolve(), args.output_dir.resolve()
    plan = read_ref({"path": str(plan_path), "sha256": args.sha256})
    protected = [
        Path(plan["root"]).resolve(),
        *(Path(a["product_root"]).resolve() for a in plan["arms"]),
    ]
    if any(output.is_relative_to(path) for path in protected):
        parser.error("reports must be outside campaign and product authority directories")
    output.mkdir(parents=True, exist_ok=False)
    report = collect(plan_path, args.sha256)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (output / "report.md").write_text(markdown(report))
    print(json.dumps({"state": report["state"], "report": str(output / "report.md")}))


if __name__ == "__main__":
    main()
