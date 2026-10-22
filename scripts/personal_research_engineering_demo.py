"""Run one bounded synthetic Qlib rehearsal, or read its durable completed outputs.

No market acquisition, real-market execution, nested SDK or simulation service is started.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

from quantos.application.personal_research import PersonalDatasetBinding, PersonalResearchService
from quantos.artifacts.store import atomic_write_bytes, regular_tree_files, sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_research import PersonalDatasetManifest
from quantos.integrations.qlib import verify_official_qlib_tools

REPO = Path(__file__).resolve().parents[1]


def request(key="test"):
    return {
        "idempotency_key": key,
        "brief": "A股主板日频短线趋势, 同花顺板块, 公告辅助分析",
        "proposal": {"session_id": "engineering-fixture", "model_claim": None},
        "dataset_id": "fixture",
        "benchmark": "SH000985",
    }


def panel():
    days = pd.bdate_range("2024-01-02", periods=45)
    rows = []
    for instrument, offset in (("SH000985", 0), ("SH600001", 1), ("SH600002", 2), ("SZ000001", 3)):
        for index, day in enumerate(days):
            close = (10 + offset) * (1.008 + offset * 0.001) ** index
            if instrument == "SH600001" and index >= 32:
                close *= 0.94 ** (index - 31)
            rows.append(
                {
                    "trade_date": day.date(),
                    "qlib_id": instrument,
                    "close": close,
                    "volume": 100000 * 1.10**index,
                    "is_mainboard": instrument != "SH000985",
                    "is_st": False,
                    "sector_momentum_5": 0.03 if instrument != "SH000985" else np.nan,
                    "available_at": day.tz_localize("Asia/Shanghai") + pd.Timedelta(hours=16),
                }
            )
    return pd.DataFrame(rows)


def build_native_fixture(root: Path) -> PersonalDatasetBinding:
    """Tiny immutable canonical synthetic panel -> official Qlib dump_bin cache."""
    root.mkdir(parents=True, exist_ok=True)
    data = panel()
    source = root / "csv"
    source.mkdir(exist_ok=True)
    for instrument, rows in data.groupby("qlib_id"):
        frame = rows[["trade_date", "close", "volume"]].rename(columns={"trade_date": "date"})
        frame["open"] = frame["close"] * 0.999
        frame["high"] = frame["close"] * 1.005
        frame["low"] = frame["close"] * 0.995
        frame["factor"] = 1.0
        frame["change"] = frame["close"].pct_change().fillna(0)
        frame["limit_buy"] = 0.0
        frame["limit_sell"] = 0.0
        frame["is_st"] = 0.0
        atomic_write_bytes(source / f"{instrument}.csv", frame.to_csv(index=False).encode())
    panel_path = root / "canonical-panel.parquet"
    if panel_path.exists():
        pd.testing.assert_frame_equal(pd.read_parquet(panel_path), data)
    else:
        stream = BytesIO()
        data.to_parquet(stream, index=False)
        atomic_write_bytes(panel_path, stream.getvalue())
    tools = verify_official_qlib_tools(REPO / ".tools" / "qlib-0.9.7")
    provider = root / "provider"
    command = [
        sys.executable,
        str(tools.dump_bin),
        "dump_all",
        "--data_path",
        str(source),
        "--qlib_dir",
        str(provider),
        "--date_field_name",
        "date",
        "--max_workers",
        "1",
        "--include_fields",
        "open,high,low,close,volume,factor,change,limit_buy,limit_sell,is_st",
    ]
    if (root / "dump-exit.json").exists():
        completed_dump = json.loads((root / "dump-exit.json").read_bytes())
        if (
            completed_dump["exit_code"] != 0
            or completed_dump["dump_bin_sha256"] != tools.dump_bin_sha256
            or completed_dump["official_commit"] != tools.commit
        ):
            raise ValueError("completed dump dependency is not reusable")
    else:
        with (root / "official-dump.log").open("xb") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
        atomic_write_bytes(
            root / "dump-exit.json",
            canonical_json_bytes(
                {
                    "exit_code": result.returncode,
                    "official_commit": tools.commit,
                    "dump_bin_sha256": tools.dump_bin_sha256,
                }
            ),
        )
        if result.returncode != 0:
            raise RuntimeError("official dump failed; do not reissue automatically")
    if not (root / "health-exit.json").exists():
        probe = (
            "import runpy,sys,json; C=runpy.run_path(sys.argv[1])['DataHealthChecker']; "
            "c=C(csv_path=sys.argv[2]); "
            "r={n:getattr(c,n)() is None for n in "
            "('check_missing_data','check_large_step_changes','check_required"
            "_columns','check_missing_factor')}; "
            "print(json.dumps(r)); sys.exit(0 if all(r.values()) else 1)"
        )
        with (root / "official-health.log").open("xb") as log:
            health = subprocess.run(
                [sys.executable, "-c", probe, str(tools.check_data_health), str(source)],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        atomic_write_bytes(
            root / "health-exit.json",
            canonical_json_bytes(
                {
                    "exit_code": health.returncode,
                    "check_data_health_sha256": tools.health_check_sha256,
                }
            ),
        )
    completed_health = json.loads((root / "health-exit.json").read_bytes())
    if (
        completed_health["exit_code"] != 0
        or completed_health["check_data_health_sha256"] != tools.health_check_sha256
    ):
        raise RuntimeError("official health checks did not pass")
    hashes = {
        path.relative_to(provider).as_posix(): sha256_file(path)
        for path in regular_tree_files(provider)
    }
    snapshot_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "canonical_panel": sha256_file(panel_path),
                "synthetic_source": {path.name: sha256_file(path) for path in source.iterdir()},
            }
        )
    )
    pit_path = root / "pit-evidence.json"
    atomic_write_bytes(
        pit_path,
        canonical_json_bytes(
            {
                "kind": "synthetic",
                "snapshot_hash": snapshot_hash,
                "panel_sha256": sha256_file(panel_path),
                "scope": "synthetic fixture membership; no claim of actual full-market coverage",
            }
        ),
    )
    bound_manifest = PersonalDatasetManifest(
        dataset_id="fixture",
        kind="synthetic",
        snapshot_hash=snapshot_hash,
        qlib_view_hash=sha256_bytes(canonical_json_bytes(hashes)),
        panel_sha256=sha256_file(panel_path),
        pit_evidence_hash=sha256_file(pit_path),
        start_date=date(2024, 2, 1),
        end_date=date(2024, 2, 16),
        all_mainboard_pit=True,
        ths_historical_membership=True,
        tradability_verified=True,
        source_vintage="synthetic",
        exposure="synthetic",
        benchmarks=("SH000985",),
        qlib_files=hashes,
    )
    atomic_write_bytes(root / "dataset-manifest.json", bound_manifest.canonical_bytes())
    return PersonalDatasetBinding(bound_manifest, provider, panel_path, pit_path)


def load_demo_service(root: Path, *, authorize_synthetic: bool = False) -> PersonalResearchService:
    """Explicit server fixture catalog; no authorization is inferred from tool parameters."""
    root = root.absolute()
    item = PersonalDatasetManifest.model_validate_json(
        (root / "input/dataset-manifest.json").read_bytes()
    )
    binding = PersonalDatasetBinding(
        item,
        root / "input/provider",
        root / "input/canonical-panel.parquet",
        root / "input/pit-evidence.json",
    )

    def authorizer(prepared):
        if prepared.dataset_manifest != item or item.kind != "synthetic":
            return None
        return "development-synthetic-only:" + prepared.content_hash

    return PersonalResearchService(
        root / "authority",
        REPO,
        catalog={item.dataset_id: binding},
        execution_authorizer=authorizer if authorize_synthetic else None,
    )


def freeze_producer_sources(app: PersonalResearchService, root: Path, expected_hash: str) -> None:
    """Retain the exact files bound by prepare before invoking any native execution."""
    from importlib.metadata import distribution

    manifest = app.dependency_manifest()
    if sha256_bytes(canonical_json_bytes(manifest)) != expected_hash:
        raise ValueError("producer changed between prepare and source freeze")
    destination = root / "producer-source"
    native = distribution("pyqlib")
    for logical, digest in manifest["sources"].items():
        source = (
            Path(native.locate_file(logical)) if logical.startswith("qlib/") else REPO / logical
        )
        encoded = source.read_bytes()
        if sha256_bytes(encoded) != digest:
            raise ValueError("producer changed during source freeze")
        atomic_write_bytes(destination / logical, encoded)
    atomic_write_bytes(destination / "dependency-manifest.json", canonical_json_bytes(manifest))
    atomic_write_bytes(destination / "preparation-script.py", Path(__file__).read_bytes())
    atomic_write_bytes(
        destination / "source-freeze.json",
        canonical_json_bytes(
            {
                "code_hash": expected_hash,
                "dependency_manifest_hash": sha256_bytes(canonical_json_bytes(manifest)),
                "preparation_script_hash": sha256_file(Path(__file__)),
                "frozen_before_execution": True,
            }
        ),
    )


def run_demo(root: Path) -> dict:
    root = root.absolute()
    # An existing fixture is reused read-only. Unknown/failed parent runs are never reissued.
    if (root / "prepared.json").exists():
        app = load_demo_service(root)
        task_id = json.loads((root / "prepared.json").read_bytes())["task_id"]
        return app.results(task_id)
    root.mkdir(parents=True, exist_ok=True)
    build_native_fixture(root / "input")
    app = load_demo_service(root, authorize_synthetic=True)
    configured = request("native")
    configured["profile"] = {"top_k": 2, "max_weight": 0.5}
    prepared = app.prepare(configured)
    atomic_write_bytes(root / "prepared.json", canonical_json_bytes(prepared))
    freeze_producer_sources(app, root, prepared["code_hash"])
    outcome = app.execute(prepared["task_id"])
    atomic_write_bytes(root / "status.json", canonical_json_bytes(outcome))
    result = app.results(prepared["task_id"])
    atomic_write_bytes(root / "results.json", canonical_json_bytes(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    arguments = parser.parse_args()
    result = run_demo(arguments.root)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "task_id",
                    "state",
                    "planned_denominator",
                    "succeeded_denominator",
                    "validation_verdict",
                )
            }
        )
    )
    return 0 if result["state"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
