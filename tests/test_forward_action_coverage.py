"""Source inventory joins reject missing or conflicting prospective event evidence."""

import copy
from datetime import UTC, datetime

import pandas as pd
import pytest

from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence_acquisition import EvidenceCollectionSpec
from quantos.data.forward_action_coverage import assess_actions
from quantos.data.forward_actions import EVENT_FIELDS, KEY_FIELDS


@pytest.fixture
def sources(tmp_path):
    def save(name, value):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else canonical_json_bytes(value))
        return {"path": name, "sha256": sha256_file(path)}

    received = datetime(2024, 1, 5, tzinfo=UTC)
    pd.DataFrame({"instrument_id": ["600000.SH"]}).to_parquet(tmp_path / "members.parquet")
    vendor = {"columns": [*KEY_FIELDS, *EVENT_FIELDS, "imp_ann_date"], "data": []}
    spec = {
        "schema_version": "forward-action-inputs/v1",
        "fresh_account_start": "2024-01-08",
        "snapshot_end_date": "2024-01-05",
        "announcement_start_date": "2024-01-04",
        "membership": {
            "path": "members.parquet",
            "sha256": sha256_file(tmp_path / "members.parquet"),
        },
        "dividends": [
            {
                "instrument_id": "600000.SH",
                "source": save("dividends.json", vendor),
                "receipt": save("dividends-receipt.json", {"received_at": received}),
            }
        ],
        "announcement_inventories": [],
        "documents": {},
    }
    pages = {}
    for venue in ("SSE", "SZSE"):
        collection = EvidenceCollectionSpec(
            collection_id="synthetic-source-join",
            venues=(venue,),
            start_date="2024-01-04",
            end_date="2024-01-05",
            page_size=50,
        )
        if venue == "SSE":
            page = {
                "pageHelp": {"pageNo": 1, "total": 1, "pageCount": 1},
                "result": [
                    [
                        {
                            "ORG_BULLETIN_ID": "sse1",
                            "SECURITY_CODE": "600000",
                            "URL": "/fixture.pdf",
                            "SSEDATE": "2024-01-05",
                            "TITLE": "董事会决议公告",
                        }
                    ]
                ],
            }
        else:
            page = {
                "announceCount": 1,
                "data": [
                    {
                        "id": "szse1",
                        "secCode": ["000002"],
                        "title": "董事会决议公告",
                        "attachPath": "/fixture.pdf",
                        "publishTime": "2024-01-05 12:00:00",
                    }
                ],
            }
        pages[venue] = page
        page_ref = save(venue + "/page.json", page)
        page_ref["receipt"] = save(
            venue + "/receipt.json",
            {"received_at": received, "http_status": 200, "sha256": page_ref["sha256"]},
        )
        spec["announcement_inventories"].append(
            {
                "venue": venue,
                "spec": save(venue + "/spec.json", collection.canonical_payload()),
                "pages": [page_ref],
            }
        )

    def refresh(*, rows=(), title=None, pdf=True):
        updated = copy.deepcopy(spec)
        vendor["data"] = [[row.get(column) for column in vendor["columns"]] for row in rows]
        updated["dividends"][0]["source"] = save("dividends.json", vendor)
        if title is not None:
            pages["SSE"]["result"][0][0]["TITLE"] = title
            page_ref = save("SSE/page.json", pages["SSE"])
            page_ref["receipt"] = save(
                "SSE/receipt.json",
                {"received_at": received, "http_status": 200, "sha256": page_ref["sha256"]},
            )
            updated["announcement_inventories"][0]["pages"] = [page_ref]
            if pdf:
                raw = b"synthetic document; extraction tested separately"
                updated["documents"]["sse1"] = {
                    "pdf": save("document.pdf", raw),
                    "receipt": save(
                        "document-receipt.json",
                        {
                            "received_at": received,
                            "http_status": 200,
                            "url": "https://big5.sse.com.cn/site/cht/www.sse.com.cn/fixture.pdf",
                            "source_sha256": sha256_bytes(raw),
                        },
                    ),
                }
        return updated

    return tmp_path, spec, save, refresh


def dividend(**updates):
    return {
        **dict.fromkeys(EVENT_FIELDS),
        "ts_code": "600000.SH",
        "end_date": "20231231",
        "ann_date": "20240105",
        "imp_ann_date": "20240105",
        "div_proc": "实施",
        "cash_div_tax": 0.1,
        "record_date": "20240108",
        "ex_date": "20240109",
        "pay_date": "20240109",
        **updates,
    }


def test_complete_declared_inventory_does_not_claim_universal_absence(sources):
    root, spec, _, _ = sources
    result = assess_actions(root, spec)
    assert result["status"] == "SUPPORTED_IN_DECLARED_SOURCE_SCOPE"
    assert result["announcement_counts"] == {"SSE": 1, "SZSE": 1}
    assert result["member_count"] == result["pool_announcements"] == 1
    assert "SOURCE_SCOPED_NOT_UNIVERSAL_ABSENCE_PROOF" in result["limitations"]
    (root / "SSE/page.json").write_bytes(b"revised")
    with pytest.raises(ValueError, match="original changed"):
        assess_actions(root, spec)


@pytest.mark.parametrize(
    "rows,reason",
    [
        ([dividend()], "FUTURE_EVENT_OFFICIAL_TERMS_NOT_MATCHED"),
        ([dividend(stk_div=0.1)], "FUTURE_STOCK_DISTRIBUTION"),
        ([dividend(pay_date=None)], "INCOMPLETE_FUTURE_EVENT_DATES"),
        ([dividend(div_proc="预案", stk_div=0.1)], "UNRESOLVED_STOCK_PROPOSAL"),
        ([dividend(), dividend(cash_div_tax=0.2)], "IMPLEMENTED_EVENT_FIELDS_CONFLICT"),
    ],
)
def test_future_event_never_passes_on_vendor_records_alone(sources, rows, reason):
    root, _, _, refresh = sources
    result = assess_actions(root, refresh(rows=rows))
    assert result["status"] == "UNSUPPORTED_OR_UNKNOWN"
    assert reason in {row["reason"] for row in result["unresolved"]}


@pytest.mark.parametrize(
    "title,pdf,reason",
    [
        ("吸收合并实施公告", False, "ACTION_ORIGINAL_MISSING"),
        ("吸收合并实施公告", True, "OTHER_ACTION_REQUIRES_SOURCE_RULE"),
    ],
)
def test_new_action_requires_its_original_and_a_supported_rule(sources, title, pdf, reason):
    root, _, _, refresh = sources
    result = assess_actions(root, refresh(title=title, pdf=pdf))
    assert result["unresolved"] == [
        {"source_id": "sse1", **({"instrument_id": "600000.SH"} if pdf else {}), "reason": reason}
    ]


def test_explicit_cash_terms_must_match_vendor_dates_and_amount(sources, monkeypatch):
    root, _, _, refresh = sources
    fact = {
        "instrument_id": "600000.SH",
        "record_date": "2024-01-08",
        "ex_date": "2024-01-09",
        "scheduled_depository_pay_date": "2024-01-09",
        "cash_div_tax": "0.1",
    }
    monkeypatch.setattr(
        "quantos.data.forward_action_coverage.derive_sse_cash_notice", lambda raw, code: fact
    )
    spec = refresh(rows=[dividend()], title="权益分派实施公告")
    result = assess_actions(root, spec)
    assert result["status"] == "SUPPORTED_IN_DECLARED_SOURCE_SCOPE"
    assert result["classified"][0]["classification"] == "ORDINARY_CASH_VENDOR_FACTOR_ONLY"
    fact["cash_div_tax"] = "0.2"
    result = assess_actions(root, spec)
    assert result["status"] == "UNSUPPORTED_OR_UNKNOWN"
    assert "CASH_NOTICE_AMBIGUOUS_OR_DISAGREES" in {row["reason"] for row in result["unresolved"]}


@pytest.mark.parametrize(
    "change", ["gap", "missing_venue", "page_count", "receipt", "future_receipt"]
)
def test_inventory_gaps_and_receipt_mismatches_reject(sources, change):
    root, spec, save, _ = sources
    first = spec["announcement_inventories"][0]
    if change == "gap":
        import json

        data = json.loads((root / first["spec"]["path"]).read_bytes())
        data["start_date"] = "2024-01-05"
        first["spec"] = save("changed-spec.json", data)
    elif change == "missing_venue":
        spec["announcement_inventories"].pop()
    elif change == "page_count":
        first["pages"].append(copy.deepcopy(first["pages"][0]))
    else:
        receipt = {
            "received_at": datetime(2099 if change == "future_receipt" else 2024, 1, 5, tzinfo=UTC),
            "http_status": 200,
            "sha256": "f" * 64,
        }
        first["pages"][0]["receipt"] = save("changed-receipt.json", receipt)
    with pytest.raises(ValueError):
        assess_actions(root, spec)
