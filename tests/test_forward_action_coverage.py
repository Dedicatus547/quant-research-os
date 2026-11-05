"""Source inventory joins reject missing or conflicting prospective event evidence."""

import copy
import json
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


@pytest.mark.parametrize("attack", [None, "missing", "duplicate", "receipt", "contradiction"])
def test_empty_official_interval_requires_exactly_one_consistent_original(sources, attack):
    root, spec, save, _ = sources
    for inventory in spec["announcement_inventories"]:
        venue = inventory["venue"]
        page = (
            {"pageHelp": {"pageNo": 1, "total": 0, "pageCount": 0}, "result": []}
            if venue == "SSE"
            else {"announceCount": 0, "data": []}
        )
        if attack == "contradiction" and venue == "SSE":
            page["result"] = json.loads((root / "SSE/page.json").read_bytes())["result"]
        ref = save(venue + "/empty.json", page)
        ref["receipt"] = save(
            venue + "/empty-receipt.json",
            {
                "received_at": datetime(2024, 1, 5, tzinfo=UTC),
                "http_status": 200,
                "sha256": "a" * 64 if attack == "receipt" else ref["sha256"],
            },
        )
        inventory["pages"] = [] if attack == "missing" else [ref]
        if attack == "duplicate":
            inventory["pages"].append(ref)
    if attack is None:
        result = assess_actions(root, spec)
        assert result["announcement_counts"] == {"SSE": 0, "SZSE": 0}
        assert result["status"] == "SUPPORTED_IN_DECLARED_SOURCE_SCOPE"
        assert result["pool_announcements"] == 0
    else:
        with pytest.raises(ValueError, match=r"(incomplete|receipt differs|total differs)"):
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


@pytest.mark.parametrize("issuer_is_party", [False, True])
def test_subsidiary_merger_requires_exact_exchange_parties(sources, monkeypatch, issuer_is_party):
    from quantos.research import merger_entitlement_sources as merger

    root, _, save, refresh = sources
    title = (
        "国联民生证券股份有限公司关于全资子公司民生证券参与"
        "国联期货换股吸收合并民生期货暨关联交易的公告"
    )
    spec = refresh(title=title)
    pd.DataFrame({"instrument_id": ["601456.SH"]}).to_parquet(root / "members.parquet")
    spec["membership"]["sha256"] = sha256_file(root / "members.parquet")
    spec["dividends"][0]["instrument_id"] = "601456.SH"
    page = json.loads((root / "SSE/page.json").read_bytes())
    page["result"][0][0]["SECURITY_CODE"] = "601456"
    ref = save("SSE/page.json", page)
    receipt = json.loads((root / "SSE/receipt.json").read_bytes())
    receipt["sha256"] = ref["sha256"]
    ref["receipt"] = save("SSE/receipt.json", receipt)
    spec["announcement_inventories"][0]["pages"] = [ref]
    raw = b"%PDF-synthetic-party-fixture"
    spec["documents"]["sse1"]["pdf"] = save("document.pdf", raw)
    receipt = json.loads((root / "document-receipt.json").read_bytes())
    receipt["source_sha256"] = sha256_bytes(raw)
    spec["documents"]["sse1"]["receipt"] = save("document-receipt.json", receipt)
    text = (
        "证券代码:601456 公告编号:2026-060号\n"
        "甲方(吸收合并方/存续方):国联期货股份有限公司\n"
        "乙方(被吸收合并方/解散方):民生期货有限公司\n"
        "丙方(乙方股东/换股股份取得方):民生证券股份有限公司\n"
        "由甲方向乙方唯一股东丙方发行股份作为合并对价\n"
        "公司全资子公司民生证券将所持民生期货100%股权转换为国联期货52.57%股份"
    )
    if issuer_is_party:
        text = text.replace(
            "甲方(吸收合并方/存续方):国联期货", "甲方(吸收合并方/存续方):国联民生证券"
        )
    monkeypatch.setattr(merger, "_pdf_pages", lambda _: (text,))
    if issuer_is_party:
        with pytest.raises(ValueError, match="source clause"):
            assess_actions(root, spec)
    else:
        result = assess_actions(root, spec)
        assert result["status"] == "SUPPORTED_IN_DECLARED_SOURCE_SCOPE"
        assert result["classified"] == [
            {"source_id": "sse1", "classification": "SUBSIDIARY_MERGER_NO_LISTED_SHARE_EXCHANGE"}
        ]
