import json
from pathlib import Path

from typer.testing import CliRunner

from quantos.application import build_doctor_report
from quantos.cli import app


def test_doctor_never_contains_token_value(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    secret = "never-print-this-token"
    monkeypatch.setenv("TUSHARE_TOKEN", secret)

    report = build_doctor_report(tmp_path)
    encoded = report.model_dump_json()

    assert report.tushare_token_configured
    assert secret not in encoded


def test_tushare_probe_reports_missing_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    result = CliRunner().invoke(app, ["tushare", "probe"])

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "TUSHARE_TOKEN_MISSING"
