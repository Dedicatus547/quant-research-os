"""Adjusted source/quote joins on synthetic originals; never market qualification."""

import struct
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hs300_adjusted import (
    AdjustedUnitFactBundle,
    AdjustedUnitPolicy,
    FixedNativeQuoteBinding,
    HS300AdjustedDatasetManifest,
)
from quantos.contracts.hs300_lifecycle import LifecycleSourceArtifact, UnsupportedAccountEvent
from quantos.research import hs300_adjusted_runtime as runtime


@pytest.fixture
def bound(tmp_path, monkeypatch):
    days = (date(2025, 2, 6), date(2025, 3, 3))
    calendar = tmp_path / "calendars/day.txt"
    calendar.parent.mkdir()
    calendar.write_text("\n".join(map(str, days)) + "\n")
    quotes = {}
    for field in runtime._QUOTE_FIELDS:
        path = tmp_path / f"features/sh600837/{field}.day.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(struct.pack("<fff", 0, float("nan"), float("nan")))
        quotes[path.relative_to(tmp_path).as_posix()] = sha256_file(path)
    quote = FixedNativeQuoteBinding(
        qlib_view_hash="a" * 64,
        calendar_sha256=sha256_file(calendar),
        quote_files=quotes,
        sessions_by_instrument={"600837.SH": days},
    )
    sources = []
    for doc in ("109", "146"):
        path = tmp_path / (doc + ".html")
        path.write_text(
            "<!doctype html><html><style>hidden</style><script>hidden</script>分红再投 复权</html>"
        )
        sources.append(
            LifecycleSourceArtifact(
                source_id=doc,
                kind="OFFICIAL_COMPANY",
                logical_path=path.name,
                sha256=sha256_file(path),
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                url="https://tushare.pro/document/2?doc_id=" + doc,
            )
        )
    issuer = tmp_path / "issuer.bin"
    issuer.write_bytes(b"synthetic parsed-notice boundary input")
    sources.append(
        LifecycleSourceArtifact(
            source_id="issuer",
            kind="OFFICIAL_COMPANY",
            logical_path=issuer.name,
            sha256=sha256_file(issuer),
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    dividend = {
        "record_date": "2023-07-27",
        "ex_date": "2023-07-28",
        "pay_date": "2023-07-28",
        "cash_div_tax": "0.21",
    }
    merger = {
        "record_date": "2025-03-03",
        "ratio": "0.62",
        "issuer_instrument_id": "601211.SH",
        "registration_basis": "CLOSE_REGISTERED_OLD_SHARES",
        "fractional_rule": "INTEGER_SHARES_REMAINDER_RANK_RANDOM_TIES",
    }
    facts = AdjustedUnitFactBundle(
        official_sources=tuple(sources),
        vendor_semantics_source_ids=("109", "146"),
        dividends=(
            {
                **dividend,
                "instrument_id": "600837.SH",
                "source_id": "issuer",
                "source_rule_sha256": sha256_bytes(canonical_json_bytes(dividend)),
            },
        ),
        mergers=(
            {
                **merger,
                "instrument_id": "600837.SH",
                "source_id": "issuer",
                "source_rule_sha256": sha256_bytes(canonical_json_bytes(merger)),
                "boundary_date": days[0],
                "event_ids": ("merger",),
            },
        ),
    )
    facts_path = tmp_path / "facts.json"
    facts_path.write_bytes(facts.canonical_bytes())
    # Contract construction and lower-level cash/PDF/lifecycle verification have
    # separate tests. Here their interfaces are isolated to exercise the joins.
    manifest = HS300AdjustedDatasetManifest.model_construct(
        adjusted_facts=facts,
        adjusted_unit_policy_hash=AdjustedUnitPolicy().content_hash,
        adjusted_runtime_source_hashes={"synthetic-runtime": "b" * 64},
        future_quote_binding=quote,
        lifecycle_manifest_hash="c" * 64,
        qlib_view_hash=quote.qlib_view_hash,
        qlib_files={**quotes, "calendars/day.txt": quote.calendar_sha256},
        end_date=days[-1],
    )
    binding = SimpleNamespace(
        manifest=manifest,
        provider_root=tmp_path,
        adjusted_facts_path=facts_path,
        lifecycle_path=tmp_path / "lifecycle.json",
    )
    events = [
        UnsupportedAccountEvent(
            event_id="merger",
            instrument_id="600837.SH",
            boundary_date=days[0],
            event_type="MERGER_EXCHANGE",
            source_ids=("issuer",),
        )
    ]
    checked = []
    monkeypatch.setattr(runtime, "verify_hs300_cash_binding", lambda value: checked.append(value))
    monkeypatch.setattr(
        runtime, "adjusted_native_runtime_identity", lambda: {"synthetic-runtime": "b" * 64}
    )
    monkeypatch.setattr(
        runtime, "load_lifecycle_facts", lambda *args: SimpleNamespace(events=events)
    )

    def derive(raw, code, result):
        assert raw == issuer.read_bytes() and code == "600837.SH"
        return result

    monkeypatch.setattr(
        runtime, "derive_dividend_rule", lambda raw, code: derive(raw, code, dividend)
    )
    monkeypatch.setattr(runtime, "derive_merger_rule", lambda raw, code: derive(raw, code, merger))
    return SimpleNamespace(
        root=tmp_path,
        binding=binding,
        manifest=manifest,
        facts=facts,
        quote=quote,
        events=events,
        dividend=dividend,
        merger=merger,
        checked=checked,
    )


def test_bound_empty_quote_window_is_verified_without_inventing_native_rights(bound):
    runtime.verify_hs300_adjusted_binding(bound.binding)
    assert bound.checked == [bound.binding]
    calendar, bins = runtime._read_fixed_bins(bound.root, bound.quote)
    assert calendar == list(bound.quote.sessions_by_instrument["600837.SH"])
    assert runtime._bin_value(bins, "600837.SH", "close", -1) is None
    assert runtime._bin_value(bins, "600837.SH", "close", len(calendar)) is None


@pytest.mark.parametrize(
    "attack,match",
    [
        ("type", "explicit successor"),
        ("policy", "policy differs"),
        ("runtime", "runtime differs"),
        ("path", "original is missing"),
        ("facts", "facts or semantics"),
        ("source", "source original"),
        ("dividend", "dividend terms"),
        ("merger", "merger terms"),
        ("event", "different native event"),
        ("boundary", "initial hard boundary"),
        ("view", "view or security"),
        ("fields", "quote-field"),
        ("sessions", "future sessions"),
        ("close", "usable close"),
    ],
)
def test_adjusted_binding_rejects_changed_terms_events_or_quotes(bound, attack, match):
    binding, manifest = bound.binding, bound.manifest
    changes = {}
    if attack == "type":
        binding.manifest = None
    elif attack == "policy":
        changes["adjusted_unit_policy_hash"] = "d" * 64
    elif attack == "runtime":
        changes["adjusted_runtime_source_hashes"] = {"changed": "d" * 64}
    elif attack == "path":
        binding.adjusted_facts_path = None
    elif attack == "facts":
        changes["adjusted_facts"] = bound.facts.model_copy(update={"source_vintage": "changed"})
    elif attack == "source":
        (bound.root / "109.html").write_text("changed")
    elif attack == "dividend":
        bound.dividend["cash_div_tax"] = "0.22"
    elif attack == "merger":
        bound.merger["ratio"] = "0.63"
    elif attack == "event":
        bound.events.clear()
    elif attack == "boundary":
        bound.events[0] = bound.events[0].model_copy(update={"boundary_date": date(2025, 2, 7)})
    elif attack == "view":
        changes["qlib_view_hash"] = "d" * 64
    elif attack == "fields":
        changes["future_quote_binding"] = bound.quote.model_copy(update={"quote_files": {}})
    elif attack == "sessions":
        changes["future_quote_binding"] = bound.quote.model_copy(
            update={"sessions_by_instrument": {"600837.SH": (date(2025, 2, 6),)}}
        )
    else:
        path = bound.root / "features/sh600837/close.day.bin"
        path.write_bytes(struct.pack("<fff", 0, 10, 10))
        quotes = {**bound.quote.quote_files, "features/sh600837/close.day.bin": sha256_file(path)}
        changes.update(
            future_quote_binding=bound.quote.model_copy(update={"quote_files": quotes}),
            qlib_files={**manifest.qlib_files, **quotes},
        )
    if changes:
        binding.manifest = manifest.model_copy(update=changes)
    with pytest.raises(ValueError, match=match):
        runtime.verify_hs300_adjusted_binding(binding)
    assert bound.checked == [binding]


@pytest.mark.parametrize("attack", ["url", "kind", "non_html", "hidden", "duplicate_document"])
def test_vendor_convention_must_be_visible_in_two_distinct_official_originals(bound, attack):
    facts = bound.facts
    sources = list(facts.official_sources)
    originals = {s.source_id: (bound.root / s.logical_path).read_bytes() for s in sources}
    if attack == "url":
        sources[0] = sources[0].model_copy(
            update={"url": "https://example.invalid/document/2?doc_id=109"}
        )
    elif attack == "kind":
        sources[0] = sources[0].model_copy(update={"kind": "DERIVATION_SPEC"})
    elif attack == "duplicate_document":
        sources[0] = sources[0].model_copy(update={"url": sources[1].url})
    elif attack == "non_html":
        originals["109"] = b"not an HTML original"
    else:
        originals["109"] = (
            "<html><script>分红再投 复权</script><style>分红再投 复权</style></html>".encode()
        )
    facts = facts.model_copy(update={"official_sources": tuple(sources)})
    with pytest.raises(ValueError, match=r"(official|original HTML|convention)"):
        runtime._verify_vendor_semantics_sources(facts, originals)


@pytest.mark.parametrize(
    "attack",
    [
        "calendar_hash",
        "calendar_order",
        "bin_hash",
        "short",
        "unaligned",
        "negative",
        "fraction",
        "range",
    ],
)
def test_fixed_quote_binary_cannot_change_or_escape_calendar(bound, attack):
    quote = bound.quote
    calendar = bound.root / "calendars/day.txt"
    path = bound.root / "features/sh600837/close.day.bin"
    if attack.startswith("calendar"):
        calendar.write_text("2025-03-03\n2025-02-06\n")
        if attack == "calendar_order":
            quote = quote.model_copy(update={"calendar_sha256": sha256_file(calendar)})
    else:
        raw = {
            "bin_hash": b"changed",
            "short": b"",
            "unaligned": b"12345",
            "negative": struct.pack("<ff", -1, 1),
            "fraction": struct.pack("<ff", 0.5, 1),
            "range": struct.pack("<ff", 2, 1),
        }[attack]
        path.write_bytes(raw)
        if attack != "bin_hash":
            quote = quote.model_copy(
                update={
                    "quote_files": {
                        **quote.quote_files,
                        "features/sh600837/close.day.bin": sha256_file(path),
                    }
                }
            )
    with pytest.raises(ValueError, match="fixed native"):
        runtime._read_fixed_bins(bound.root, quote)
