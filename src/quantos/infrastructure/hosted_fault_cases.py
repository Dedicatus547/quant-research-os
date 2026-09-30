"""Finite management fault windows; research requests cannot select them."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HostedFaultWindow:
    action: str
    operation_kind: str | None
    point: str
    occurrence: int = 1
    native_execution: bool = False


PROTOCOL_FAULT_WINDOWS = {
    f"{action}-{point}-{number}": HostedFaultWindow(action, kind, point, number)
    for action, kind, publications in (
        ("register", "REGISTER", 3),
        ("issue", "ISSUE", 4),
        ("submit", "SUBMIT", 5),
        ("reject", "SUBMIT", 2),
        ("cancel", "TERMINATE", 1),
        ("expire", "TERMINATE", 1),
    )
    for point, number in (
        ("intent_published", 1),
        *(("artifact_published", index) for index in range(1, publications + 1)),
        ("completion_published", 1),
    )
}

# These use the existing native schema-invalid proposal admission. Execution
# windows below use a separate frozen valid-candidate fixture.
ADMISSION_FAULT_WINDOWS = {
    f"business-{point}": HostedFaultWindow(
        "start" if point in ("research_initial", "request_checkpoint") else "resume",
        None,
        point,
    )
    for point in (
        "research_initial",
        "request_checkpoint",
        "prepared",
        "completed_intent",
        "trial_event",
        "ledger",
        "step_completed",
    )
}

EXECUTION_FAULT_WINDOWS = {
    f"execution-{point}": HostedFaultWindow("execute_campaign", None, point, native_execution=True)
    for point in (
        "prepared",
        "started",
        "execution_receipt",
        "completed_intent",
        "trial_event",
        "ledger",
        "step_completed",
        "selection_ledger",
        "final_report",
    )
}

HOSTED_FAULT_WINDOWS = {
    **PROTOCOL_FAULT_WINDOWS,
    **ADMISSION_FAULT_WINDOWS,
    **EXECUTION_FAULT_WINDOWS,
}
FAULT_SNAPSHOT_PHASES = ("before", "crashed", "recovered", "after")
