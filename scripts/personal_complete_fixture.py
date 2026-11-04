"""Small HS300-shaped engineering data; never fetch or execute market data."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from quantos.application.personal_research import PersonalDatasetBinding
from quantos.artifacts.store import atomic_write_bytes, regular_tree_files, sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_research import HS300DatasetManifest
from quantos.integrations.qlib import verify_official_qlib_tools

REPO = Path(__file__).resolve().parents[1]


def build_fixture(root: Path) -> PersonalDatasetBinding:
    root = root.absolute()
    root.mkdir(parents=True, exist_ok=True)
    if (root / "dataset-manifest.json").exists():
        manifest = HS300DatasetManifest.model_validate_json(
            (root / "dataset-manifest.json").read_bytes()
        )
        from quantos.research.personal_signal import verified_panel

        if (
            manifest.kind != "synthetic"
            or json.loads((root / "dump-exit.json").read_bytes())["actual_exit_code"] != 0
            or json.loads((root / "health-exit.json").read_bytes())["actual_exit_code"] != 0
            or manifest.snapshot_hash
            != sha256_bytes(
                canonical_json_bytes(
                    {
                        "canonical_panel": sha256_file(root / "panel.parquet"),
                        "generator": sha256_file(root / "generator.py"),
                    }
                )
            )
        ):
            raise ValueError("retained synthetic source/proof differs")
        verified_panel(
            PersonalDatasetBinding(
                manifest, root / "provider", root / "panel.parquet", root / "pit.json"
            )
        )
        return PersonalDatasetBinding(
            manifest, root / "provider", root / "panel.parquet", root / "pit.json"
        )
    days = pd.bdate_range("2024-01-02", periods=40)
    rows = []
    for c, code in enumerate(("SH000300", "SH600001", "SH600002", "SZ300001")):
        for i, day in enumerate(days):
            close = 10 + c + i * (0.03 + c * 0.03)
            if code == "SH600002" and i >= 25:
                close -= (i - 24) * 0.20
            volume = 3000.0 * 1.5 ** abs(i - 29)
            row = {
                "trade_date": day.date(),
                "qlib_id": code,
                "open": close * 0.998,
                "high": close * 1.005,
                "low": close * 0.995,
                "close": close,
                "volume": volume,
                "amount_cny": 15_000_000.0 * (1 + c * 0.1 + i * 0.04),
                "adjustment_factor": 1.0,
                "is_member": c != 0,
                "is_st": code == "SH600001" and i == 30,
                "is_suspended": False,
                "available_at": day.tz_localize("Asia/Shanghai") + pd.Timedelta(hours=16),
            }
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame.to_parquet(root / "panel.parquet", index=False)
    source = root / "csv"
    source.mkdir()
    for code, part in frame.groupby("qlib_id"):
        csv = part[["trade_date", "open", "high", "low", "close", "volume", "amount_cny"]].rename(
            columns={"trade_date": "date"}
        )
        csv["factor"] = 1.0
        csv["change"] = csv.close.pct_change().fillna(0)
        csv["limit_buy"] = 0.0
        csv["limit_sell"] = 0.0
        csv["is_st"] = part.is_st.astype(float).values
        csv.to_csv(source / f"{code}.csv", index=False)
    tools = verify_official_qlib_tools(REPO / ".tools/qlib-0.9.7")
    command = [
        sys.executable,
        str(tools.dump_bin),
        "dump_all",
        "--data_path",
        str(source),
        "--qlib_dir",
        str(root / "provider"),
        "--date_field_name",
        "date",
        "--max_workers",
        "1",
        "--include_fields",
        "open,high,low,close,volume,amount_cny,factor,change,limit_buy,limit_sell,is_st",
    ]
    with (root / "official-dump.log").open("xb") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
    atomic_write_bytes(
        root / "dump-exit.json",
        canonical_json_bytes(
            {
                "actual_exit_code": result.returncode,
                "command": command,
                "official_commit": tools.commit,
                "dump_bin_sha256": tools.dump_bin_sha256,
            }
        ),
    )
    if result.returncode != 0:
        raise RuntimeError("synthetic dump failed; preserve attempt")
    probe = (
        "import runpy,sys,json; C=runpy.run_path(sys.argv[1])['DataHealthChecker']; "
        "c=C(csv_path=sys.argv[2]); "
        "r={n:getattr(c,n)() is None for n in "
        "('check_missing_data','check_large_step_changes','check_required_columns',"
        "'check_missing_factor')}; "
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
                "actual_exit_code": health.returncode,
                "check_data_health_sha256": tools.health_check_sha256,
            }
        ),
    )
    if health.returncode != 0:
        raise RuntimeError("synthetic health check failed; preserve attempt")
    hashes = {
        p.relative_to(root / "provider").as_posix(): sha256_file(p)
        for p in regular_tree_files(root / "provider")
    }
    snapshot_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "canonical_panel": sha256_file(root / "panel.parquet"),
                "generator": sha256_file(Path(__file__)),
            }
        )
    )
    atomic_write_bytes(root / "generator.py", Path(__file__).read_bytes())
    atomic_write_bytes(
        root / "pit.json",
        canonical_json_bytes(
            {
                "kind": "synthetic",
                "snapshot_hash": snapshot_hash,
                "panel_sha256": sha256_file(root / "panel.parquet"),
                "scope": "engineered historical membership/status clocks",
            }
        ),
    )
    manifest = HS300DatasetManifest(
        dataset_id="hs300-complete-synthetic-01",
        kind="synthetic",
        snapshot_hash=snapshot_hash,
        qlib_view_hash=sha256_bytes(canonical_json_bytes(hashes)),
        panel_sha256=sha256_file(root / "panel.parquet"),
        pit_evidence_hash=sha256_file(root / "pit.json"),
        start_date=days[24].date(),
        end_date=days[-1].date(),
        warmup_start=days[0].date(),
        market_source="SYNTHETIC_FIXTURE",
        source_vintage="synthetic",
        exposure="synthetic",
        qlib_files=hashes,
        snapshot_manifest_sha256=snapshot_hash,
        view_manifest_sha256=sha256_bytes(canonical_json_bytes(hashes)),
    )
    atomic_write_bytes(root / "dataset-manifest.json", manifest.canonical_bytes())
    return PersonalDatasetBinding(
        manifest, root / "provider", root / "panel.parquet", root / "pit.json"
    )


if __name__ == "__main__":
    print(json.dumps(build_fixture(Path(sys.argv[1])).manifest.model_dump(mode="json")))
