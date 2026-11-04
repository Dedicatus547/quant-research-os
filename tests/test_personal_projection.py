"""Bounded display through the original service verifier; no scientific execution."""

from __future__ import annotations

import json

import pytest

from quantos.application.personal_projection import PersonalResearchProjection
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from test_personal_cash_service import _cash_setup
from test_personal_lifecycle_service import _request, _setup
from test_personal_research import request, service


def test_capability_page_is_bounded_and_preserves_original_catalog(tmp_path):
    app = service(tmp_path)
    projection = PersonalResearchProjection(app)
    original = app.capabilities()
    summary = projection.capabilities(limit=1)
    assert summary["total"] == 1
    assert summary["datasets"][0]["content_hash"] == app.catalog["fixture"].manifest.content_hash
    assert summary["datasets"][0]["source"] == "synthetic"
    assert summary["next_offset"] is None
    assert summary["readiness"]["real_market_execution_default"] == "DENIED"
    assert projection.capabilities(offset=1)["datasets"] == []
    assert app.capabilities() == original
    assert len(json.dumps(summary)) < 4000


@pytest.mark.parametrize("offset,limit", [(-1, 1), (0, 0), (0, 101)])
def test_summary_page_limits_reject_before_reading(tmp_path, offset, limit):
    projection = PersonalResearchProjection(service(tmp_path))
    with pytest.raises(ValueError, match="offset"):
        projection.capabilities(offset, limit)
    with pytest.raises(ValueError, match="offset"):
        projection.boundary_page("absent", "main", offset, limit)


def test_missing_results_retain_denominator_null_and_original_contract(tmp_path, monkeypatch):
    app, _, _, _ = _setup(tmp_path, monkeypatch)
    task = app.prepare(_request())["task_id"]
    projection = PersonalResearchProjection(app)
    original = app.results(task)
    summary = projection.results(task)
    assert len(summary["rows"]) == summary["planned_denominator"] == 7
    assert summary["succeeded_denominator"] == summary["reused_denominator"] == 0
    assert all(row["metrics"] is None for row in summary["rows"])
    assert all(row["boundary_count"] is None for row in summary["rows"])
    assert summary["validation_verdict"] == "NOT_EVALUATED"
    page = projection.boundary_page(task, "main")
    assert page["total"] is None
    assert page["observability"] == "NOT_OBSERVED"
    assert page["entries"] == []
    assert app.results(task) == original
    with pytest.raises(ValueError, match="denominator"):
        projection.boundary_page(task, "invented")
    with pytest.raises(ValueError, match="not bound"):
        projection.boundary_read(task, "main", "0" * 64)


def _boundary_execution(app, task):
    def execute(prepared, root, cancelled):
        directory = root / "main"
        directory.mkdir()
        files = {}
        boundaries = []
        for index, text in enumerate(("原生边界" * 4000, '{"status":"STOP"}')):
            filename = f"boundaries/{index}.json"
            path = directory / filename
            path.parent.mkdir(exist_ok=True)
            atomic_write_bytes(path, text.encode())
            digest = sha256_file(path)
            files[filename] = digest
            boundaries.append({"file": filename, "sha256": digest})
        receipt = {
            "candidate_id": "main",
            "prepared_hash": prepared.content_hash,
            "run_status": "FAILED",
            "metrics": None,
            "files": files,
            "boundary_receipts": boundaries,
        }
        atomic_write_bytes(directory / "receipt.json", canonical_json_bytes(receipt))
        return {
            "prepared_hash": prepared.content_hash,
            "run_status": "FAILED",
            "receipts": [
                {
                    "candidate_id": "main",
                    "receipt_hash": sha256_file(directory / "receipt.json"),
                }
            ],
        }

    app._authorizer = lambda item: "synthetic fixture only"
    app._executor = execute
    assert app.execute(task)["state"] == "FAILED"


def test_boundary_pages_and_unicode_spans_are_complete_bounded_and_hash_bound(
    tmp_path, monkeypatch
):
    app, _, _, _ = _setup(tmp_path, monkeypatch)
    task = app.prepare(_request())["task_id"]
    _boundary_execution(app, task)
    projection = PersonalResearchProjection(app)
    first = projection.boundary_page(task, "main", limit=1)
    second = projection.boundary_page(task, "main", offset=first["next_offset"], limit=1)
    assert first["total"] == 2
    assert first["observability"] == "RETAINED"
    assert len(first["entries"]) == len(second["entries"]) == 1
    assert second["next_offset"] is None
    digest = first["entries"][0]["sha256"]
    chunks = []
    start = 0
    while True:
        span = projection.boundary_read(task, "main", digest, start=start, max_chars=3001)
        assert len(span["text"]) <= 3001
        chunks.append(span["text"])
        if span["next_start"] is None:
            break
        start = span["next_start"]
    assert sha256_bytes("".join(chunks).encode()) == digest
    assert projection.results(task)["rows"][0]["boundary_count"] == 2
    assert projection.results(task)["rows"][0]["metrics"] is None


@pytest.mark.parametrize("start,max_chars", [(-1, 1), (0, 0), (0, 32001)])
def test_boundary_span_limits_reject_before_reading(tmp_path, start, max_chars):
    projection = PersonalResearchProjection(service(tmp_path))
    with pytest.raises(ValueError, match="max_chars"):
        projection.boundary_read("absent", "main", "0" * 64, start, max_chars)


@pytest.mark.parametrize("attack", ["receipt", "export", "outcome"])
def test_every_display_uses_the_full_original_integrity_path(tmp_path, monkeypatch, attack):
    app, _, _, _ = _setup(tmp_path, monkeypatch)
    task = app.prepare(_request())["task_id"]
    _boundary_execution(app, task)
    projection = PersonalResearchProjection(app)
    digest = projection.boundary_page(task, "main")["entries"][0]["sha256"]
    execution = app.root / "tasks" / task / "execution"
    targets = {
        "receipt": execution / "main/receipt.json",
        "export": execution / "main/boundaries/0.json",
        "outcome": execution / "outcome.json",
    }
    targets[attack].write_bytes(b"tampered")
    for read in (
        lambda: app.results(task),
        lambda: projection.results(task),
        lambda: projection.boundary_page(task, "main"),
        lambda: projection.boundary_read(task, "main", digest),
    ):
        with pytest.raises(ArtifactIntegrityError):
            read()


def test_classic_origin_keeps_original_identity_and_failure_propagates(tmp_path, monkeypatch):
    from quantos.research import hs300_cash_runtime

    app, _, _, _, payload = _cash_setup(tmp_path, monkeypatch)
    # The cash fixture supplies an injected origin verifier; exercise projection
    # routing to that retained root and its refusal when the verifier later fails.
    (tmp_path / "original.json").write_bytes(b"fixture origin receipt")
    boundary = tmp_path / "origin-boundary.json"
    boundary.write_text('{"native_status":"RETAINED"}')
    digest = sha256_file(boundary)
    monkeypatch.setattr(
        hs300_cash_runtime,
        "verify_classic_origin",
        lambda *args: {
            "candidate_id": "classic",
            "run_status": "SUCCEEDED",
            "metrics": {"return": 0.01},
            "boundary_receipts": [{"file": boundary.name, "sha256": digest}],
        },
    )
    task = app.prepare(payload)["task_id"]
    prepared = app._prepared(task)
    origin = prepared.origin_reuse[0]

    def execute(item, output, cancelled):
        return {
            "prepared_hash": item.content_hash,
            "run_status": "FAILED",
            "receipts": [],
            "origin_reuse": [{"candidate_id": "classic", "origin_hash": origin.content_hash}],
        }

    app._authorizer = lambda item: "synthetic fixture only"
    app._executor = execute
    app.execute(task)
    projection = PersonalResearchProjection(app)
    summary = projection.results(task)
    classic = summary["rows"][1]
    assert classic["run_status"] == "REUSED_ORIGIN"
    assert classic["origin_reuse"]["content_hash"] == origin.content_hash
    assert classic["origin_reuse"]["receipt"] == origin.receipt.model_dump(mode="json")
    assert summary["reused_denominator"] == 1
    assert summary["planned_denominator"] == len(summary["rows"]) == 7
    assert classic["metrics"]["net_total_return"] is None
    assert not (app.root / "tasks" / task / "execution/classic").exists()
    retained = projection.boundary_read(task, "classic", digest)
    assert retained["text"] == boundary.read_text()
    assert retained["sha256"] == digest

    def changed(*args):
        raise ArtifactIntegrityError("original changed")

    monkeypatch.setattr(hs300_cash_runtime, "verify_classic_origin", changed)
    with pytest.raises(ArtifactIntegrityError, match="original changed"):
        projection.results(task)
    with pytest.raises(ArtifactIntegrityError, match="original changed"):
        projection.boundary_page(task, "classic")


def test_legacy_prepared_summary_retains_old_contract(tmp_path):
    app = service(tmp_path)
    task = app.prepare(request())["task_id"]
    full = app.results(task)
    summary = PersonalResearchProjection(app).results(task)
    assert summary["planned_denominator"] == full["planned_denominator"] == 7
    assert summary["comparison_sha256"] is None
    assert app.results(task) == full


def _strategy_projection_fixture(tmp_path):
    """Recorded schema fixtures exercise verification; confer no native-run proof."""
    from quantos.contracts.personal_strategy import PersonalStrategy, PreparedStrategyStudy
    from test_personal_scope import prepared

    app = service(tmp_path)

    def task(key, candidates):
        data = prepared(key).model_dump(mode="json")
        base = data["request"]["candidates"][0]
        data["request"]["candidates"] = []
        data["strategy_hashes"] = {}
        for i, candidate in enumerate(candidates):
            spec = {**base["strategy"]}
            if candidate not in {"reuse"} and len(candidates) > 1:
                spec["top_k"] = i + 1
            data["request"]["candidates"].append(
                {
                    **base,
                    "candidate_id": candidate,
                    "role": "main" if i == 0 else "control",
                    "strategy": spec,
                }
            )
            data["strategy_hashes"][candidate] = PersonalStrategy.model_validate(spec).content_hash
        item = PreparedStrategyStudy.model_validate(data)
        app._persist_prepared(item)
        return item

    metrics = {
        "sessions": 2,
        "net_total_return": -0.01,
        "benchmark_total_return": 0.02,
        "total_cost_cny": 123.4,
        "total_turnover": 0.3,
        "mean_risk_exposure": 0.4,
        "actual_exposure": {"minimum": 0.2, "mean": 0.4, "maximum": 0.6},
        "order_count": 2,
    }

    def publish(item, states, *, origin=None):
        refs = []
        for candidate_id, state in states.items():
            directory = app.root / "tasks" / item.content_hash / "execution" / candidate_id
            files = {}
            if state == "SUCCEEDED":
                for day in ("2024-01-03", "2024-01-04"):
                    relative = f"native/targets/{day}.json"
                    path = directory / relative
                    atomic_write_bytes(
                        path,
                        canonical_json_bytes(
                            {"execution_date": day, "orders_generated": [], "note": "单位用例"}
                        ),
                    )
                    files[relative] = sha256_file(path)
                path = directory / "native/other.json"
                atomic_write_bytes(path, b"{}")
                files["native/other.json"] = sha256_file(path)
            receipt = {
                "prepared_hash": item.content_hash,
                "candidate_id": candidate_id,
                "strategy_hash": item.strategy_hashes[candidate_id],
                "policy_hash": item.policy_hash,
                "dataset_hash": item.dataset_hash,
                "account_identity": "a" * 64,
                "signal_artifact_hash": "b" * 64,
                "validation_verdict": "NOT_EVALUATED",
                "run_status": state,
                "metrics": None if state == "FAILED" else metrics,
                "files": files,
                **({"origin": origin} if state == "REUSED_ORIGIN" else {}),
            }
            path = directory / "receipt.json"
            atomic_write_bytes(path, canonical_json_bytes(receipt))
            refs.append({"candidate_id": candidate_id, "receipt_sha256": sha256_file(path)})
        directory = app.root / "tasks" / item.content_hash / "execution"
        atomic_write_bytes(directory / "outcome.json", canonical_json_bytes({"receipts": refs}))
        app._append(
            item.content_hash,
            "FAILED" if "FAILED" in states.values() else "SUCCEEDED",
            {"outcome_hash": sha256_file(directory / "outcome.json")},
        )

    original = task("original", ["main"])
    publish(original, {"main": "SUCCEEDED"})
    source = app.results(original.content_hash)["rows"][0]
    origin = {
        "task_id": original.content_hash,
        "candidate_id": "main",
        "receipt_sha256": source["receipt_sha256"],
        "account_identity": source["account_identity"],
    }
    current = task("current", ["main", "reuse", "untouched", "completed"])
    publish(
        current,
        {"main": "FAILED", "reuse": "REUSED_ORIGIN", "completed": "SUCCEEDED"},
        origin=origin,
    )
    return app, current.content_hash, original.content_hash, origin


def test_strategy_summary_retains_all_states_metrics_identities_and_full_denominator(tmp_path):
    app, task, _, origin = _strategy_projection_fixture(tmp_path)
    full = app.results(task)
    summary = PersonalResearchProjection(app).results(task)
    assert summary["schema_version"] == "personal-research-result-summary/v2"
    assert summary["planned_denominator"] == len(summary["rows"]) == 4
    assert summary["attempted_denominator"] == 3
    assert summary["succeeded_denominator"] == summary["reused_denominator"] == 1
    assert [row["run_status"] for row in summary["rows"]] == [
        "FAILED",
        "REUSED_ORIGIN",
        "NOT_RUN",
        "SUCCEEDED",
    ]
    assert summary["rows"][0]["metrics"] is summary["rows"][2]["metrics"] is None
    assert summary["rows"][2]["receipt_sha256"] is None
    reused = summary["rows"][1]
    assert reused["origin"] == origin
    assert reused["detail_source"]["receipt_sha256"] == origin["receipt_sha256"]
    assert reused["account_identity"] == origin["account_identity"]
    assert reused["metrics"]["net_total_return"] == -0.01
    assert reused["metrics"]["total_cost_cny"] == 123.4
    assert reused["metrics"]["actual_exposure"] == full["rows"][1]["metrics"]["actual_exposure"]
    assert reused["hypothesis"] == "fixture"
    assert summary["validation_verdict"] == "NOT_EVALUATED"
    assert all(row["validation_verdict"] == "NOT_EVALUATED" for row in summary["rows"])
    assert app.results(task) == full


def test_strategy_trace_pagination_and_spans_route_to_original_receipt(tmp_path):
    app, task, source_task, origin = _strategy_projection_fixture(tmp_path)
    projection = PersonalResearchProjection(app)
    first = projection.boundary_page(task, "reuse", limit=1)
    second = projection.boundary_page(task, "reuse", offset=first["next_offset"], limit=1)
    assert first["total"] == 2 and len(first["entries"]) == len(second["entries"]) == 1
    assert second["next_offset"] is None
    assert first["source_task_id"] == source_task
    assert first["source_candidate_id"] == "main"
    assert first["source_receipt_sha256"] == origin["receipt_sha256"]
    assert first["origin"] == origin
    assert first["read_hash_parameter"] == "boundary_sha256"
    entry = first["entries"][0]
    pieces, start = [], 0
    while True:
        span = projection.boundary_read(task, "reuse", entry["sha256"], start, 17)
        assert span["source_task_id"] == source_task and len(span["text"]) <= 17
        pieces.append(span["text"])
        if span["next_start"] is None:
            break
        start = span["next_start"]
    assert sha256_bytes("".join(pieces).encode()) == entry["sha256"]
    assert json.loads("".join(pieces))["orders_generated"] == []
    source_directory = app.root / "tasks" / source_task / "execution/main"
    other_digest = sha256_file(source_directory / "native/other.json")
    for digest in ("0" * 64, other_digest):
        with pytest.raises(ValueError, match="not bound"):
            projection.boundary_read(task, "reuse", digest)
    assert projection.boundary_page(task, "reuse", offset=100)["entries"] == []
    assert projection.boundary_page(task, "untouched")["total"] is None
    assert projection.boundary_page(task, "main")["total"] == 0
    with pytest.raises(ValueError, match="denominator"):
        projection.boundary_page(task, "invented")


@pytest.mark.parametrize("attack", ["outcome", "receipt", "source-receipt", "source-trace"])
def test_strategy_display_revalidates_local_and_reused_originals_without_cached_pass(
    tmp_path, attack
):
    app, task, source_task, _ = _strategy_projection_fixture(tmp_path)
    projection = PersonalResearchProjection(app)
    entry = projection.boundary_page(task, "reuse")["entries"][0]
    projection.results(task)
    local = app.root / "tasks" / task / "execution"
    source = app.root / "tasks" / source_task / "execution/main"
    path = {
        "outcome": local / "outcome.json",
        "receipt": local / "reuse/receipt.json",
        "source-receipt": source / "receipt.json",
        "source-trace": source / entry["file"],
    }[attack]
    path.write_bytes(b"tampered")
    for read in (
        lambda: projection.results(task),
        lambda: projection.boundary_page(task, "reuse"),
        lambda: projection.boundary_read(task, "reuse", entry["sha256"]),
    ):
        with pytest.raises(ArtifactIntegrityError):
            read()
