"""One simulated STOP exercises shared capture validation and its read-only boundary."""

import json

import pytest
from test_adaptive_history import recipe  # noqa: F401
from test_adaptive_runtime import Science, case  # noqa: F401

from quantos.application.adaptive_runtime import AdaptiveRuntime
from quantos.application.adaptive_sdk import AdaptiveSdkProducer
from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.contracts.adaptive import AdaptiveDecisionRequest


def test_verified_capture_never_republishes(case, monkeypatch):  # noqa: F811
    import quantos.application.adaptive_sdk as module

    spec, producer, science, harness, _ = case
    harness.actions = [None]
    runtime = AdaptiveRuntime(spec, producer, science)
    runtime.run()
    event = next(e for e in runtime.store.events() if e.kind == "DECISION_RESERVED")
    request = runtime.store.get(event.reference_hash, AdaptiveDecisionRequest)
    directory = producer.directory(request)
    before = {str(p): sha256_file(p) for p in directory.iterdir() if p.is_file()}
    monkeypatch.setattr(
        module, "save", lambda *a: pytest.fail("read-only verifier attempted write")
    )
    decision, _ = producer.verify_capture(request)
    assert decision.action == "STOP"
    assert len(harness.calls) == 1
    assert before == {str(p): sha256_file(p) for p in directory.iterdir() if p.is_file()}
    (directory / "response.json").unlink()
    with pytest.raises((FileNotFoundError, ArtifactIntegrityError)):
        producer.verify_capture(request)
    assert not (directory / "response.json").exists()


def test_projected_context_is_exact_actual_model_input(case, recipe):  # noqa: F811
    from test_adaptive_history import project_history
    from test_adaptive_runtime import Harness

    context, _ = project_history(recipe)
    spec, _, _, _, _ = case
    spec = spec.model_copy(
        update={"context": context, "context_source_hashes": tuple(recipe["context_source_hashes"])}
    )
    harness = Harness(spec, [None])
    runtime = AdaptiveRuntime(spec, AdaptiveSdkProducer(spec, harness), Science())
    runtime.run()
    actual = json.loads(harness.calls[0].prompt.split("Context:\n", 1)[1])
    assert actual["context"] == context
