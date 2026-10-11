"""Pure presentation of retrospective discovery comparison reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast


def _display(value: object) -> str:
    return "unavailable" if value is None else str(value)


def render_discovery_report(report: dict[str, object]) -> str:
    """Render the T6 report fields without recalculating or interpreting metrics."""

    lines = [
        f"Discovery report: {_display(report.get('schema_version'))}",
        f"Batch: {_display(report.get('batch_hash'))}",
        f"Primary metric: {_display(report.get('primary_metric'))}",
        f"Direction: {_display(report.get('direction'))}",
        f"Interpretation: {_display(report.get('interpretation'))}",
        f"Original generation batch: {_display(report.get('original_generation_batch_hash'))}",
        f"Original generation design: {_display(report.get('original_generation_design_hash'))}",
        f"Original generation code: {_display(report.get('original_generation_code_identity'))}",
        f"Actual evaluation code: {_display(report.get('actual_evaluation_code_identity'))}",
        f"Evaluation identity: {_display(report.get('evaluation_identity'))}",
        f"Evaluation declaration: {_display(report.get('evaluation_declaration'))}",
        "",
        "Evaluation origin:",
    ]
    evaluation = report.get("evaluation", {})
    if isinstance(evaluation, Mapping) and evaluation:
        for key, value in cast(Mapping[str, object], evaluation).items():
            lines.append(f"  {key}: {_display(value)}")
    else:
        lines.append("  unavailable")
    lines.append(
        "  actual_evaluation_bindings: " + _display(report.get("actual_evaluation_bindings"))
    )
    lines.extend(("", "Rows:"))
    row_fields = (
        "method",
        "reservation_hash",
        "status",
        "reason",
        "subtask_hash",
        "generation_provenance",
        "execution_status",
        "execution_outcome",
        "execution_reason",
        "prediction_analyzable",
        "prediction_reason",
        "purge_evidence_status",
        "model_data_splits_hash",
        "effective_train_end",
        "effective_validation_end",
        "purge_limitations",
        "primary_value",
        "original_verdict",
        "validation_pass",
        "p14c_selectable",
    )
    rows = report.get("rows", ())
    if isinstance(rows, (tuple, list)):
        for index, row in enumerate(cast(tuple[object, ...] | list[object], rows), start=1):
            lines.append(f"  [{index}]")
            if isinstance(row, Mapping):
                mapping = cast(Mapping[str, object], row)
                lines.extend(f"    {field}: {_display(mapping.get(field))}" for field in row_fields)
            else:
                lines.append("    row: unavailable")
    else:
        lines.append("  unavailable")

    lines.extend(("", "Methods:"))
    methods = report.get("methods", ())
    if isinstance(methods, (tuple, list)):
        for method in cast(tuple[object, ...] | list[object], methods):
            lines.append(f"  {_display(method)}")
    elif isinstance(methods, Mapping):
        for name, facts in cast(Mapping[str, object], methods).items():
            lines.append(f"  {name}: {_display(facts)}")
    else:
        lines.append("  unavailable")

    lines.extend(("", "Costs:"))
    costs = report.get("costs", {})
    if isinstance(costs, Mapping) and costs:
        cost_mapping = cast(Mapping[str, object], costs)
        for key in sorted(cost_mapping):
            lines.append(f"  {key}: {_display(cost_mapping[key])}")
    else:
        lines.append("  unavailable")

    lines.extend(("", "Limitations:"))
    limitations = report.get("limitations", ())
    if isinstance(limitations, (tuple, list)) and limitations:
        lines.extend(
            f"  - {_display(item)}" for item in cast(tuple[object, ...] | list[object], limitations)
        )
    else:
        lines.append("  unavailable")
    return "\n".join(lines)
