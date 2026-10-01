"""Trusted management capture of an external Codex host; not a QuantOS LLM backend."""

from __future__ import annotations

import json
import os
import selectors
import signal
import stat
import subprocess
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes_at,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import (
    HostedAgentRequest,
    HostedAgentResponse,
    HostedCampaignSpec,
    parse_hosted_contract,
)
from quantos.contracts.hosted_deployment import (
    HostedDeploymentProfile,
    HostedInstallInventory,
    HostedLauncherConfiguration,
    HostedLauncherRecord,
    HostedMountObservation,
    HostedProjectionFact,
)
from quantos.infrastructure.hosted_deployment import (
    HostedNamespacePaths,
    KnownValueGuard,
    namespace_command,
    source_seccomp_filter,
    verify_install,
    verify_projection_fact,
)
from quantos.security import SecretArtifactRejected, validate_secret_free

EXTRACTION_RULE_BYTES = canonical_json_bytes(
    {
        "schema_version": "hosted-extraction-rule/v1",
        "rule": "codex-jsonl-single-final/v1",
        "success_exit": 0,
        "completed_turns": 1,
        "completed_agent_messages": 1,
        "proposal_encoding": "UNMODIFIED_AGENT_MESSAGE_TEXT_UTF8",
        "tool_events": "REJECTED",
        "malformed_or_duplicate_json_keys": "REJECTED",
    }
)

MOUNT_PROBE_CODE = """
import hashlib,json,os,stat
files=[]
for name in sorted(os.listdir('/projection')):
    if len(name)!=64 or any(c not in '0123456789abcdef' for c in name):
        raise SystemExit(3)
    fd=os.open('/projection/'+name,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        meta=os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1:
            raise SystemExit(4)
        digest=hashlib.sha256()
        while True:
            chunk=os.read(fd,65536)
            if not chunk: break
            digest.update(chunk)
        files.append([name,digest.hexdigest(),meta.st_size,stat.S_IMODE(meta.st_mode)])
    finally: os.close(fd)
print(json.dumps({'files':files,'projection_readonly':bool(os.statvfs('/projection').f_flag&os.ST_RDONLY),
                  'install_readonly':bool(os.statvfs('/install').f_flag&os.ST_RDONLY),
                  'channel_readonly':bool(os.statvfs('/channel').f_flag&os.ST_RDONLY),
                  'proc_empty':not os.listdir('/proc'),'uid':os.getuid(),'gid':os.getgid()},
                 sort_keys=True,separators=(',',':')))
""".strip()


def probe_projection_mount(
    paths: HostedNamespacePaths,
    *,
    request: HostedAgentRequest,
    profile: HostedDeploymentProfile,
    projection: HostedInstallInventory,
    seccomp_fd: int,
) -> HostedMountObservation:
    """Observed inside the exact host mount/proc/seccomp recipe before model launch."""
    os.lseek(seccomp_fd, 0, os.SEEK_SET)
    argv = namespace_command(
        "host",
        paths,
        ("/install/python-seeded", "-c", MOUNT_PROBE_CODE),
        seccomp_fd=seccomp_fd,
        mount_policy_hash=profile.mount_policy_hash,
    )
    result = subprocess.run(
        argv, pass_fds=(seccomp_fd,), capture_output=True, timeout=10, env={"PATH": "/usr/bin:/bin"}
    )
    if result.returncode != 0 or len(result.stdout) > 1_048_576:
        raise ArtifactIntegrityError("pre-launch mounted projection probe failed")
    try:
        parsed: object = json.loads(result.stdout.decode("utf-8"), object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ArtifactIntegrityError("pre-launch mounted projection probe invalid") from error
    if not isinstance(parsed, dict):
        raise ArtifactIntegrityError("pre-launch mounted projection probe invalid")
    observed = cast(dict[str, object], parsed)
    files = observed.get("files")
    expected = [
        [entry.relative_path, entry.bytes_hash, entry.size_bytes, entry.mode]
        for entry in projection.files
    ]
    if files != expected or any(
        observed.get(key) is not True
        for key in ("projection_readonly", "install_readonly", "channel_readonly", "proc_empty")
    ):
        raise ArtifactIntegrityError("pre-launch mounted projection or readonly boundary changed")
    return HostedMountObservation(
        request_hash=request.content_hash,
        deployment_profile_hash=profile.content_hash,
        projection_inventory_hash=projection.content_hash,
        observed_uid=cast(int, observed["uid"]),
        observed_gid=cast(int, observed["gid"]),
    )


def scan_cli_capture(data: bytes, *, guard: KnownValueGuard) -> None:
    """All raw bytes are checked before storing; typed usage gets only its narrow adaptation."""
    guard(data)
    for line in data.splitlines():
        try:
            value: object = json.loads(
                line.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_invalid_number
            )
        except (ValueError, UnicodeError, RecursionError):
            text = line.decode("utf-8", errors="strict")
            for offset in range(0, len(text), 60000):
                validate_secret_free(
                    text[max(0, offset - 4096) : offset + 60000], file_name="hosted-cli-text.txt"
                )
        else:
            if isinstance(value, dict):
                _safe_event(cast(dict[str, object], value))
            else:
                validate_secret_free(value, file_name="hosted-cli-value.json")


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise ValueError("duplicate CLI event key")
        result[key] = value
    return result


def _invalid_number(_: str) -> object:
    raise ValueError("nonfinite CLI event number")


def _safe_event(event: dict[str, object]) -> None:
    # The only scanner adaptation is the official turn.completed usage object.
    # Unknown token-bearing fields and all message/tool text retain normal checks.
    safe = dict(event)
    if event.get("type") == "turn.completed" and "usage" in event:
        usage = event["usage"]
        if not isinstance(usage, dict):
            raise ValueError("CLI usage schema invalid")
        counts = cast(dict[str, object], usage)
        if not set(counts).issubset(
            {"input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"}
        ):
            raise ValueError("CLI usage contains unknown fields")
        if any(type(x) is not int or x < 0 for x in counts.values()):
            raise ValueError("CLI usage must contain nonnegative integer counts")
        safe["usage"] = {key.replace("tokens", "count"): value for key, value in counts.items()}
    validate_secret_free(safe, file_name="hosted-cli-event.json")


def extract_proposal(
    output: bytes,
    configuration: HostedLauncherConfiguration,
    *,
    guard: KnownValueGuard,
) -> tuple[bytes, str | None]:
    """Fixed single-turn rule, before any persistence; no stripping or manual replacement."""
    if len(output) > configuration.output_byte_cap:
        raise ValueError("CLI output limit")
    guard(output)
    messages: list[str] = []
    started = completed = thread_started = 0
    model: str | None = None
    for line in output.splitlines():
        if not line:
            raise ValueError("empty CLI event line")
        event_value: object = json.loads(
            line.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_invalid_number
        )
        if not isinstance(event_value, dict):
            raise ValueError("CLI event object required")
        event = cast(dict[str, object], event_value)
        _safe_event(event)
        kind = event.get("type")
        if kind == "thread.started":
            if thread_started or started:
                raise ValueError("CLI thread order invalid")
            thread_started += 1
        elif kind == "turn.started":
            if thread_started != 1 or started or completed:
                raise ValueError("CLI turn order invalid")
            started += 1
        elif kind == "turn.completed":
            if started != 1 or completed:
                raise ValueError("CLI completion order invalid")
            completed += 1
        elif kind in ("item.started", "item.updated", "item.completed"):
            if started != 1 or completed:
                raise ValueError("CLI item order invalid")
            item = event.get("item")
            if not isinstance(item, dict):
                raise ValueError("CLI item object required")
            typed = cast(dict[str, object], item)
            if typed.get("type") not in ("agent_message", "reasoning"):
                raise ValueError("tool event forbidden for fixed proposal-only profile")
            if kind == "item.completed" and typed.get("type") == "agent_message":
                text = typed.get("text")
                if not isinstance(text, str):
                    raise ValueError("CLI agent text required")
                messages.append(text)
        else:
            raise ValueError("unknown or failed CLI event")
        # Only CLI event metadata, never a model's message claiming its own identity.
        if kind in ("thread.started", "turn.started") and "model" in event:
            observed = event["model"]
            if not isinstance(observed, str) or len(observed) > 200:
                raise ValueError("CLI model identity invalid")
            if model is not None and model != observed:
                raise ValueError("CLI model identity conflict")
            model = observed
    if (started, completed, thread_started, len(messages)) != (1, 1, 1, 1):
        raise ValueError("CLI source does not contain one completed genuine turn")
    proposal = messages[0].encode("utf-8")
    if not proposal or len(proposal) > configuration.proposal_byte_cap:
        raise ValueError("CLI proposal byte limit")
    guard(proposal)
    if model is not None and model != configuration.model:
        raise ValueError("CLI requested and observed model disagree")
    return proposal, model


def hosted_prompt(request: HostedAgentRequest) -> bytes:
    return (
        b"Produce exactly one final JSON proposal using this frozen request. "
        b"Use only the listed candidate options and supplied context. "
        b"Do not invoke tools. Output only the proposal JSON, with no commentary.\n"
        + request.canonical_bytes()
    )


def register_model_auth_memory(fd: int, guard: KnownValueGuard) -> None:
    """Register every bounded auth string in memory before CLI output can be saved."""
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > 65_536:
        raise ArtifactIntegrityError("model auth memory descriptor has invalid size")
    raw = os.pread(fd, 65_537, 0)
    if len(raw) != metadata.st_size:
        raise ArtifactIntegrityError("model auth memory descriptor changed")
    try:
        document: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ArtifactIntegrityError("model auth memory descriptor is invalid") from error
    registered = 0

    def visit(value: object, depth: int) -> None:
        nonlocal registered
        if depth > 16:
            raise ArtifactIntegrityError("model auth memory descriptor is too deep")
        if isinstance(value, str):
            encoded = value.encode("utf-8")
            if len(encoded) >= 16:
                guard.register_value(encoded)
                registered += 1
        elif isinstance(value, dict):
            for child in cast(dict[str, object], value).values():
                visit(child, depth + 1)
        elif isinstance(value, list):
            for child in cast(list[object], value):
                visit(child, depth + 1)

    visit(document, 0)
    if registered == 0:
        raise ArtifactIntegrityError("model auth memory descriptor has no registered values")


class TrustedLauncherEvidenceStore:
    """Management namespace owns this root; response references confer no write/read authority."""

    def __init__(self, root: Path, guard: KnownValueGuard) -> None:
        self.root = root
        self.guard = guard
        with opened_directory(root, create=True):
            pass

    def publish_bytes(self, data: bytes) -> str:
        self.guard(data)
        digest = sha256_bytes(data)
        with opened_directory(self.root) as fd:
            atomic_write_bytes_at(fd, digest, data)
        return digest

    def publish_record(self, record: HostedLauncherRecord) -> str:
        validate_secret_free(
            record.model_dump(mode="json"), file_name="hosted-launcher-record.json"
        )
        return self.publish_bytes(record.canonical_bytes())

    def read_bytes(self, digest: str, *, max_bytes: int) -> bytes:
        if len(digest) != 64 or any(x not in "0123456789abcdef" for x in digest):
            raise ArtifactIntegrityError("source reference must be SHA-256")
        with opened_directory(self.root) as fd:
            data = read_regular_bytes_at(fd, digest, max_bytes=max_bytes)
        if sha256_bytes(data) != digest:
            raise ArtifactIntegrityError("trusted source bytes changed")
        self.guard(data)
        return data

    def verify_response_source(
        self,
        response: HostedAgentResponse,
        *,
        request: HostedAgentRequest,
        spec: HostedCampaignSpec,
        profile: HostedDeploymentProfile,
        initial_inventory: HostedInstallInventory,
        projection_root: Path,
        configuration: HostedLauncherConfiguration,
    ) -> HostedLauncherRecord:
        matching: list[HostedLauncherRecord] = []
        for digest in response.host_observation.external_evidence_hashes:
            record = parse_hosted_contract(
                self.read_bytes(digest, max_bytes=65_536), HostedLauncherRecord, max_bytes=65_536
            )
            fact = parse_hosted_contract(
                self.read_bytes(record.projection_fact_hash, max_bytes=65_536),
                HostedProjectionFact,
                max_bytes=65_536,
            )
            if (
                record.projection_fact_hash != fact.content_hash
                or record.host_instance != fact.host_instance
                or record.projection_inventory_hash != fact.projection_inventory_hash
            ):
                raise ArtifactIntegrityError("launcher record is not bound to pre-launch fact")
            verify_projection_fact(
                fact,
                request=request,
                spec=spec,
                profile=profile,
                initial_inventory=initial_inventory,
                projection_root=projection_root,
            )
            mount = parse_hosted_contract(
                self.read_bytes(record.isolation_observation_hash, max_bytes=65_536),
                HostedMountObservation,
                max_bytes=65_536,
            )
            if (
                mount.content_hash != record.isolation_observation_hash
                or mount.request_hash != request.content_hash
                or mount.deployment_profile_hash != profile.content_hash
                or mount.projection_inventory_hash != fact.projection_inventory_hash
            ):
                raise ArtifactIntegrityError("launcher mount observation binding invalid")
            if (
                record.request_hash != request.content_hash
                or record.outcome != "CAPTURED"
                or record.deployment_profile_hash != profile.content_hash
                or record.executable_hash != profile.cli_binary_hash
                or record.configuration_hash != configuration.content_hash
                or record.configuration_hash != profile.model_configuration_hash
                or record.proposal_hash != response.proposal_hash
                or record.raw_output_hash is None
                or record.prompt_hash != sha256_bytes(hosted_prompt(request))
                or not record.raw_output_complete
            ):
                raise ArtifactIntegrityError("external launcher binding invalid")
            output = self.read_bytes(
                record.raw_output_hash, max_bytes=configuration.output_byte_cap
            )
            proposal, model = extract_proposal(output, configuration, guard=self.guard)
            if (
                proposal != response.proposal_json.encode("utf-8")
                or model != record.actual_model_identifier
            ):
                raise ArtifactIntegrityError("external launcher proposal source differs")
            reported = response.host_observation.reported_model_identifier
            if reported is not None and reported != (model or configuration.model):
                raise ArtifactIntegrityError("host reported model conflicts with launcher source")
            effort = response.host_observation.reported_reasoning_effort
            if effort is not None and effort != configuration.reasoning_effort:
                raise ArtifactIntegrityError("host reported effort conflicts with launcher source")
            matching.append(record)
        if len(matching) != 1:
            raise ArtifactIntegrityError("one trusted external launcher source required")
        return matching[0]


def _capture_process(
    argv: tuple[str, ...],
    *,
    pass_fds: tuple[int, ...],
    configuration: HostedLauncherConfiguration,
    input_bytes: bytes,
) -> tuple[int | None, bytes, bytes, str]:
    """Read both direct pipes into bounded memory, terminate group at timeout/byte cap."""
    output = bytearray()
    diagnostic = bytearray()
    outcome = "CAPTURED"
    with subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        pass_fds=pass_fds,
        env={"PATH": "/usr/bin:/bin"},
        start_new_session=True,
    ) as process:
        assert (
            process.stdin is not None and process.stdout is not None and process.stderr is not None
        )
        deadline = time.monotonic() + configuration.runtime_timeout_seconds
        input_offset = 0
        os.set_blocking(process.stdin.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE, "prompt")
            selector.register(process.stdout, selectors.EVENT_READ, output)
            selector.register(process.stderr, selectors.EVENT_READ, diagnostic)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    outcome = "TIMED_OUT"
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    break
                for key, _ in selector.select(
                    timeout=min(0.2, max(0, deadline - time.monotonic()))
                ):
                    if key.data == "prompt":
                        try:
                            written = os.write(
                                key.fd, input_bytes[input_offset : input_offset + 16_384]
                            )
                        except BrokenPipeError:
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                            continue
                        input_offset += written
                        if input_offset == len(input_bytes):
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                        continue
                    data = os.read(key.fd, 65_536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    target = cast(bytearray, key.data)
                    remaining = configuration.output_byte_cap + 1 - len(output) - len(diagnostic)
                    target.extend(data[: max(0, remaining)])
                    if len(output) + len(diagnostic) > configuration.output_byte_cap:
                        outcome = "OUTPUT_LIMIT"
                        with suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGKILL)
                        break
                if outcome != "CAPTURED":
                    break
        exit_code = process.wait(timeout=5)
    return exit_code, bytes(output), bytes(diagnostic), outcome


class TrustedCodexLauncher:
    def __init__(
        self,
        paths: HostedNamespacePaths,
        profile: HostedDeploymentProfile,
        install: HostedInstallInventory,
        configuration: HostedLauncherConfiguration,
        evidence: TrustedLauncherEvidenceStore,
    ) -> None:
        self.paths, self.profile, self.install = paths, profile, install
        self.configuration, self.evidence = configuration, evidence
        if (
            profile.install_inventory_hash != install.content_hash
            or profile.model_configuration_hash != configuration.content_hash
            or profile.extraction_rule_hash != sha256_bytes(EXTRACTION_RULE_BYTES)
        ):
            raise ArtifactIntegrityError("launcher frozen configuration binding invalid")
        executable = next((x for x in install.files if x.relative_path == "codex"), None)
        if executable is None or executable.bytes_hash != profile.cli_binary_hash:
            raise ArtifactIntegrityError("launcher executable is not the bound frozen binary")

    def capture(
        self,
        request: HostedAgentRequest,
        spec: HostedCampaignSpec,
        projection: HostedInstallInventory,
        initial_inventory: HostedInstallInventory,
        *,
        projection_fact_hash: str,
        host_instance: str,
        model_auth_memory_fd: int | None = None,
    ) -> tuple[HostedLauncherRecord, bytes | None]:
        """Manager owns capture; CLI receives no channel capability or authority descriptor."""
        if model_auth_memory_fd is not None:
            register_model_auth_memory(model_auth_memory_fd, self.evidence.guard)
        verify_install(self.paths.install, self.install)
        verify_install(self.paths.projection, projection)
        fact = parse_hosted_contract(
            self.evidence.read_bytes(projection_fact_hash, max_bytes=65_536),
            HostedProjectionFact,
            max_bytes=65_536,
        )
        if fact.content_hash != projection_fact_hash or fact.host_instance != host_instance:
            raise ArtifactIntegrityError("launcher has no matching trusted pre-launch fact")
        verify_projection_fact(
            fact,
            request=request,
            spec=spec,
            profile=self.profile,
            initial_inventory=initial_inventory,
            projection_root=self.paths.projection,
        )
        if projection.content_hash != fact.projection_inventory_hash:
            raise ArtifactIntegrityError("launcher actual mount differs from pre-launch fact")
        if {x.relative_path for x in projection.files} != {
            *request.projection_object_hashes,
            request.content_hash,
        }:
            raise ArtifactIntegrityError("launcher projection differs from request allowlist")
        if self.profile.content_hash not in request.input_hashes:
            raise ArtifactIntegrityError("launcher request is not bound to deployment profile")
        if request.proposal_schema_hash not in {item.relative_path for item in projection.files}:
            raise ArtifactIntegrityError("launcher schema is not in the frozen projection")
        prompt = hosted_prompt(request)
        self.evidence.guard(prompt)
        if len(prompt) > request.max_request_bytes + 4096:
            raise ValueError("launcher prompt byte cap")
        seccomp_fd, bpf = source_seccomp_filter()
        if sha256_bytes(bpf) != self.profile.seccomp_bpf_hash:
            os.close(seccomp_fd)
            raise ArtifactIntegrityError("launcher source filter changed")
        mount = probe_projection_mount(
            self.paths,
            request=request,
            profile=self.profile,
            projection=projection,
            seccomp_fd=seccomp_fd,
        )
        isolation_observation_hash = self.evidence.publish_bytes(mount.canonical_bytes())
        os.lseek(seccomp_fd, 0, os.SEEK_SET)
        command = (
            "/install/codex",
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--model",
            self.configuration.model,
            "-c",
            f'model_reasoning_effort="{self.configuration.reasoning_effort}"',
            "--sandbox",
            "read-only",
            "--output-schema",
            "/projection/" + request.proposal_schema_hash,
            "-",
        )
        argv = namespace_command(
            "host",
            self.paths,
            command,
            seccomp_fd=seccomp_fd,
            mount_policy_hash=self.profile.mount_policy_hash,
        )
        descriptors = (seccomp_fd,)
        if model_auth_memory_fd is not None:
            # bwrap copies the caller's private memory fd into tmpfs; no disk auth copy.
            # The outer controller must include auth's known values in its guard.
            index = argv.index("/install/codex")
            argv = (
                *argv[:index],
                "--ro-bind-data",
                str(model_auth_memory_fd),
                "/tmp/codex/auth.json",
                *argv[index:],
            )
            descriptors = (*descriptors, model_auth_memory_fd)
        started = datetime.now(UTC)
        try:
            try:
                exit_code, output, diagnostic, outcome = _capture_process(
                    argv, pass_fds=descriptors, configuration=self.configuration, input_bytes=prompt
                )
            except (OSError, subprocess.TimeoutExpired):
                exit_code, output, diagnostic, outcome = None, b"", b"", "REJECTED"
        finally:
            os.close(seccomp_fd)
        terminated = datetime.now(UTC)
        proposal: bytes | None = None
        model: str | None = None
        output_hash = diagnostic_hash = None
        reason = "CLI_EVENT_CAPTURED"
        raw_complete = outcome not in ("OUTPUT_LIMIT", "TIMED_OUT")
        try:
            scan_cli_capture(output, guard=self.evidence.guard)
            scan_cli_capture(diagnostic, guard=self.evidence.guard)
            output_hash = self.evidence.publish_bytes(output)
            diagnostic_hash = self.evidence.publish_bytes(diagnostic)
            if outcome == "CAPTURED" and exit_code == 0:
                proposal, model = extract_proposal(
                    output, self.configuration, guard=self.evidence.guard
                )
            else:
                reason = "CLI_PROCESS_NOT_COMPLETED"
                if outcome == "CAPTURED":
                    outcome = "REJECTED"
        except (ValueError, UnicodeError, RecursionError, SecretArtifactRejected):
            outcome, reason = "REJECTED", "CLI_OUTPUT_UNSAFE_OR_SOURCE_INVALID"
            proposal = None
        record = HostedLauncherRecord(
            deployment_profile_hash=self.profile.content_hash,
            host_instance=host_instance,
            request_hash=request.content_hash,
            projection_inventory_hash=projection.content_hash,
            projection_fact_hash=projection_fact_hash,
            executable_hash=self.profile.cli_binary_hash,
            executable_version=self.profile.cli_version,
            configuration_hash=self.configuration.content_hash,
            argv_hash=sha256_bytes(canonical_json_bytes(command)),
            prompt_hash=sha256_bytes(prompt),
            isolation_observation_hash=isolation_observation_hash,
            raw_output_hash=output_hash,
            raw_output_complete=raw_complete,
            diagnostic_output_hash=diagnostic_hash,
            proposal_hash=sha256_bytes(proposal) if proposal else None,
            proposal_bytes=len(proposal) if proposal else 0,
            actual_model_identifier=model,
            started_at=started,
            terminated_at=terminated,
            exit_code=exit_code,
            outcome=cast("LauncherOutcome", outcome),
            reason=reason,
            unavailable_reasons=(
                "HOST_INTERNAL_USAGE_UNAVAILABLE",
                "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
                "MODEL_IDENTIFIER_NOT_IMMUTABLE",
                "PROVIDER_INTERNAL_TRANSCRIPT_UNAVAILABLE",
                *(("MODEL_IDENTITY_NOT_EXPOSED_BY_CLI",) if model is None else ()),
            ),
        )
        self.evidence.publish_record(record)
        return record, proposal


from typing import Literal  # noqa: E402

LauncherOutcome = Literal["CAPTURED", "REJECTED", "TIMED_OUT", "OUTPUT_LIMIT"]
