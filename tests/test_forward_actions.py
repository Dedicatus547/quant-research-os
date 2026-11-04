import pytest

from quantos.data.forward_actions import (
    EVENT_FIELDS,
    compare_dividend_variants,
    derive_szse_cash_notice,
)


def test_implemented_metadata_agreement_does_not_choose_a_vintage():
    row = dict.fromkeys(EVENT_FIELDS)
    row.update(
        ts_code="600000.SH",
        end_date="20251231",
        ann_date="20260401",
        div_proc="实施",
        cash_div_tax=1.0,
        ex_date="20260601",
        base_date="20260520",
    )
    report = compare_dividend_variants([row, {**row, "base_date": "20260521"}])
    assert (
        report["groups"][0]["classification"] == "IMPLEMENTED_EVENT_FIELDS_AGREE_METADATA_DIFFERS"
    )
    assert report["groups"][0]["versions_ordered"] is False
    assert report["coverage_granted"] is False
    assert report["raw_failure_reclassified"] is False


def test_implemented_economic_conflict_remains_a_conflict():
    row = dict.fromkeys(EVENT_FIELDS)
    row.update(
        ts_code="600000.SH",
        end_date="20251231",
        ann_date="20260401",
        div_proc="实施",
        cash_div_tax=1.0,
    )
    report = compare_dividend_variants([row, {**row, "cash_div_tax": 2.0}])
    assert report["groups"][0]["classification"] == "IMPLEMENTED_EVENT_FIELDS_CONFLICT"
    assert report["groups"][0]["event_fields_agree"] is False


@pytest.fixture
def notice(monkeypatch):
    from quantos.research.merger_entitlement_sources import _Document

    text = (
        "证券代码:002241权益分派实施公告不送红股,不以公积金转增股本"
        "每10股派1.500000元人民币现金(含税;扣税后每10股派1.35元;"
        "每10股除权除息参考现金1.480664元"
        "股权登记日为:2026年11月3日;除权除息日为:2026年11月4日。"
        "现金红利将于2026年11月4日通过股东托管证券公司(或其他托管机构)"
        "直接划入其资金账户"
    )
    monkeypatch.setattr(
        _Document, "read", classmethod(lambda cls, raw: cls("a" * 64, (text,), text))
    )
    return text, _Document


def test_cash_notice_keeps_gross_terms_separate_from_reference_and_receipt(notice):
    report = derive_szse_cash_notice(b"fixture", "002241.SZ")
    assert report["cash_div_tax"] == "0.15"
    assert report["record_date"] == "2026-11-03"
    assert report["scheduled_depository_pay_date"] == "2026-11-04"
    assert report["coverage_granted"] is False
    assert report["payment_observed"] is False
    with pytest.raises(ValueError, match="headers disagree"):
        derive_szse_cash_notice(b"fixture", "002142.SZ")


@pytest.mark.parametrize(
    "extra",
    ["每10股派2元人民币现金(含税", "股权登记日为:2026年11月2日", "每10股送红股2股"],
)
def test_cash_notice_rejects_conflicting_explicit_terms(notice, monkeypatch, extra):
    text, document = notice
    text += extra
    monkeypatch.setattr(
        document, "read", classmethod(lambda cls, raw: cls("a" * 64, (text,), text))
    )
    with pytest.raises(ValueError, match=r"ambiguous|conflicting stock"):
        derive_szse_cash_notice(b"fixture", "002241.SZ")
