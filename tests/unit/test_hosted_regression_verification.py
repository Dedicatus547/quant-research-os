"""CI metric tampering fails closed; component reports never grant qualification."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from quantos.infrastructure.hosted_regression_verification import verify_regression_reports
from quantos.infrastructure.hosted_verification import HostedQualificationError


def _reports() -> tuple[bytes, bytes]:
    root = ET.Element(
        "coverage",
        {
            "lines-valid": "20",
            "lines-covered": "18",
            "branches-valid": "20",
            "branches-covered": "16",
            "line-rate": "0.9",
            "branch-rate": "0.8",
        },
    )
    packages = ET.SubElement(root, "packages")
    classes = ET.SubElement(ET.SubElement(packages, "package"), "classes")
    cls = ET.SubElement(classes, "class", {"filename": "src/quantos/example.py"})
    lines = ET.SubElement(cls, "lines")
    for number in range(1, 21):
        values = {"number": str(number), "hits": str(int(number <= 18))}
        if number <= 10:
            values.update(
                branch="true", **{"condition-coverage": "100% (2/2)" if number <= 8 else "0% (0/2)"}
            )
        ET.SubElement(lines, "line", values)
    suites = ET.Element("testsuites")
    suite = ET.SubElement(
        suites,
        "testsuite",
        {
            "tests": "1",
            "failures": "0",
            "errors": "0",
            "skipped": "0",
        },
    )
    ET.SubElement(suite, "testcase", {"name": "offline-regression"})
    return ET.tostring(root), ET.tostring(suites)


def test_exact_combined_85_percent_and_native_comments_are_accepted() -> None:
    coverage, junit = _reports()
    verify_regression_reports(b"<!-- coverage.py generated report -->" + coverage, junit)


@pytest.mark.parametrize(
    "field,value",
    (
        ("lines-valid", "21"),
        ("lines-covered", "19"),
        ("branches-valid", "0"),
        ("branches-covered", "21"),
        ("lines-covered", "-1"),
        ("lines-valid", "NaN"),
        ("line-rate", "1"),
        ("branch-rate", "-0.8"),
        ("line-rate", "NaN"),
    ),
)
def test_modified_coverage_totals_are_rejected(field: str, value: str) -> None:
    coverage, junit = _reports()
    root = ET.fromstring(coverage)
    root.set(field, value)
    with pytest.raises(HostedQualificationError):
        verify_regression_reports(ET.tostring(root), junit)


@pytest.mark.parametrize(
    "kind",
    (
        "below-gate",
        "missing-class",
        "duplicate-class",
        "escaped-file",
        "missing-line",
        "negative-hits",
        "duplicate-line",
        "zero-line",
        "missing-branches",
        "invalid-branches",
        "missing-count",
        "invalid-xml",
        "doctype",
        "entity",
    ),
)
def test_line_and_branch_evidence_cannot_be_replaced_by_a_pass_total(kind: str) -> None:
    coverage, junit = _reports()
    root = ET.fromstring(coverage)
    classes = root.find("./packages/package/classes")
    assert classes is not None
    cls = classes[0]
    lines = cls.find("lines")
    assert lines is not None
    if kind == "below-gate":
        root.set("lines-covered", "17")
        root.set("line-rate", "0.85")
        lines[17].set("hits", "0")
    elif kind == "missing-class":
        classes.remove(cls)
    elif kind == "duplicate-class":
        classes.append(ET.fromstring(ET.tostring(cls)))
    elif kind == "escaped-file":
        cls.set("filename", "src/quantos/../outside.py")
    elif kind == "missing-line":
        lines.remove(lines[-1])
    elif kind == "negative-hits":
        lines[0].set("hits", "-1")
    elif kind == "duplicate-line":
        lines[1].set("number", "1")
    elif kind == "zero-line":
        lines[0].set("number", "0")
    elif kind == "missing-branches":
        lines[0].attrib.pop("condition-coverage")
    elif kind == "invalid-branches":
        lines[0].set("condition-coverage", "100% (3/2)")
    elif kind == "missing-count":
        root.attrib.pop("lines-valid")
    coverage = ET.tostring(root)
    if kind == "invalid-xml":
        coverage = b"<coverage>"
    elif kind == "doctype":
        coverage = b'<!DOCTYPE coverage SYSTEM "file:///outside">' + coverage
    elif kind == "entity":
        coverage = b'<!ENTITY file SYSTEM "file:///outside">' + coverage
    with pytest.raises(HostedQualificationError):
        verify_regression_reports(coverage, junit)


@pytest.mark.parametrize(
    "kind",
    (
        "failure-count",
        "error-count",
        "skip-count",
        "empty",
        "missing-case",
        "extra-case",
        "hidden-failure",
        "hidden-error",
        "hidden-skip",
        "second-suite",
        "missing-count",
        "invalid-count",
        "invalid-xml",
        "wrong-schema",
    ),
)
def test_pytest_individual_results_and_denominator_are_mandatory(kind: str) -> None:
    coverage, junit = _reports()
    suites = ET.fromstring(junit)
    suite = suites[0]
    if kind in {"failure-count", "error-count", "skip-count"}:
        suite.set(
            {"failure-count": "failures", "error-count": "errors", "skip-count": "skipped"}[kind],
            "1",
        )
    elif kind == "empty":
        suite.set("tests", "0")
        suite.remove(suite[0])
    elif kind == "missing-case":
        suite.remove(suite[0])
    elif kind == "extra-case":
        ET.SubElement(suite, "testcase")
    elif kind.startswith("hidden-"):
        ET.SubElement(
            suite[0],
            {"hidden-failure": "failure", "hidden-error": "error", "hidden-skip": "skipped"}[kind],
        )
    elif kind == "second-suite":
        ET.SubElement(suites, "testsuite")
    elif kind == "missing-count":
        suite.attrib.pop("failures")
    elif kind == "invalid-count":
        suite.set("tests", "NaN")
    elif kind == "wrong-schema":
        suites.tag = "producer-pass"
    junit = ET.tostring(suites) if kind != "invalid-xml" else b"<testsuites>"
    with pytest.raises(HostedQualificationError):
        verify_regression_reports(coverage, junit)
