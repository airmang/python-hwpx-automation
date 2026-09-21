# SPDX-License-Identifier: Apache-2.0
"""Typed MCP adapter for the canonical mixed-anchor form-fill transaction.

The adapter deliberately does not edit HWPX packages.  It validates the public
wire model, resolves workspace paths, and delegates planning and execution to
the canonical ``hwpx_automation.office.agent`` mixed-form compiler/executor.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
import secrets
import stat
import zipfile
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, TypeAlias

from hwpx_automation.office.agent import (
    MIXED_FORM_COMPILED_PLAN_SCHEMA,
    MIXED_FORM_PLAN_SCHEMA,
    HwpxAgentDocument,
    apply_mixed_form_plan,
    plan_mixed_form_fill,
    validate_mixed_form_plan,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .execution_lock import PUBLIC_MUTATION_LOCK
from .office.agent._batch_publication import GuardedSavePipeline
from .office.rendering import resolve_hancom_backend
from .storage import build_hwpx_open_safety_report
from .utils.helpers import resolve_path
from .workspace import (
    WorkspaceMissingParentGuard,
    WorkspaceOutputGuard,
    WorkspacePathError,
    WorkspaceResolver,
)


FORM_VERIFICATION_RECEIPT_SCHEMA = "hwpx.form-verification-receipt/v1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class NativeFieldTarget(_StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "oneOf": [
                {
                    "required": ["fieldId"],
                    "properties": {
                        "fieldId": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                        },
                    },
                    "not": {"required": ["name"]},
                },
                {
                    "required": ["name"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                        },
                    },
                    "not": {"required": ["fieldId"]},
                },
            ]
        },
    )

    kind: Literal["nativeField"]
    field_id: str | None = Field(
        default=None,
        alias="fieldId",
        min_length=1,
        max_length=4096,
    )
    name: str | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def _one_selector(self) -> NativeFieldTarget:
        if (
            "field_id" in self.model_fields_set and self.field_id is None
        ) or ("name" in self.model_fields_set and self.name is None):
            raise ValueError("nativeField selector keys cannot be null")
        if (self.field_id is None) == (self.name is None):
            raise ValueError("nativeField requires exactly one of fieldId or name")
        return self


class LabelCellAnchor(_StrictModel):
    label: str = Field(min_length=1, max_length=4096)
    direction: Literal["right", "left", "below", "above"]


class LabelCellTarget(_StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "oneOf": [
                {
                    "required": ["tableAnchor"],
                    "properties": {
                        "tableAnchor": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                        },
                    },
                    "not": {"required": ["tableIndex"]},
                },
                {
                    "required": ["tableIndex"],
                    "properties": {
                        "tableIndex": {"type": "integer", "minimum": 0},
                    },
                    "not": {"required": ["tableAnchor"]},
                },
            ]
        },
    )

    kind: Literal["labelCell"]
    section_path: str = Field(
        alias="sectionPath",
        pattern=r"^/section\[[1-9][0-9]*\]$",
    )
    table_anchor: str | None = Field(
        default=None,
        alias="tableAnchor",
        min_length=1,
        max_length=4096,
    )
    table_index: int | None = Field(default=None, alias="tableIndex", ge=0)
    cell_anchor: LabelCellAnchor = Field(alias="cellAnchor")

    @model_validator(mode="after")
    def _one_table_selector(self) -> LabelCellTarget:
        if (
            "table_anchor" in self.model_fields_set and self.table_anchor is None
        ) or ("table_index" in self.model_fields_set and self.table_index is None):
            raise ValueError("labelCell selector keys cannot be null")
        if (self.table_anchor is None) == (self.table_index is None):
            raise ValueError("labelCell requires exactly one of tableAnchor or tableIndex")
        return self


class CanonicalPathTarget(_StrictModel):
    kind: Literal["canonicalPath"]
    path: str = Field(min_length=1)


class BodyAnchorTarget(_StrictModel):
    kind: Literal["bodyAnchor"]
    section_path: str = Field(
        alias="sectionPath",
        pattern=r"^/section\[[1-9][0-9]*\]$",
    )
    anchor: str = Field(min_length=1, max_length=4096)
    expected_count: Literal[1] = Field(alias="expectedCount")


MixedFormTarget: TypeAlias = Annotated[
    NativeFieldTarget | LabelCellTarget | CanonicalPathTarget | BodyAnchorTarget,
    Field(discriminator="kind"),
]


class MixedFormOperation(_StrictModel):
    operation_id: str = Field(
        alias="operationId",
        pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$",
    )
    target: MixedFormTarget
    value: str = Field(max_length=4096)


class MixedFormQuality(_StrictModel):
    # The core schema permits omission but rejects an explicitly supplied
    # JSON null for each option. A non-null annotation with a None default
    # preserves that presence-sensitive wire contract in Pydantic.
    mode: Literal["transparent", "strict"] = None
    render_check: Literal["off", "auto", "required"] = Field(
        default=None,
        alias="renderCheck",
    )
    xsd_mode: Literal["off", "lint"] = Field(default=None, alias="xsdMode")
    overflow_policy: Literal["fail", "warn", "truncate"] = Field(
        default=None,
        alias="overflowPolicy",
    )
    layout_lint: Literal["off", "warn", "strict"] = Field(
        default=None,
        alias="layoutLint",
    )
    preserve_unmodified_parts: bool = Field(
        default=None,
        alias="preserveUnmodifiedParts",
    )
    require_reference_integrity: bool = Field(
        default=None,
        alias="requireReferenceIntegrity",
    )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: Any,
        handler: Any,
    ) -> dict[str, Any]:
        schema = handler(core_schema)
        for option in schema.get("properties", {}).values():
            if isinstance(option, dict):
                # None means "omitted" to the Pydantic runtime but is not a
                # valid explicit value. Do not advertise that internal default
                # as a JSON value the frozen core schema would reject.
                option.pop("default", None)
        return schema


VerificationRequirement: TypeAlias = Literal[
    "package",
    "reopen",
    "openSafety",
    "semanticDiff",
    "bytePreservation",
    "domain",
    "realHancom",
]
QualityInput: TypeAlias = Literal["transparent", "strict"] | MixedFormQuality | None


class MixedFormPlanInput(_StrictModel):
    """Strict public ``hwpx.mixed-form-plan/v1`` request."""

    schema_version: Literal["hwpx.mixed-form-plan/v1"] = Field(alias="schemaVersion")
    source: str = Field(min_length=1)
    output: str = Field(min_length=1)
    expected_revision: str | None = Field(
        alias="expectedRevision",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    idempotency_key: str | None = Field(
        alias="idempotencyKey",
        min_length=1,
        max_length=128,
    )
    dry_run: bool = Field(alias="dryRun")
    overwrite: bool
    quality: QualityInput
    verification_requirements: list[VerificationRequirement] = Field(
        alias="verificationRequirements",
        json_schema_extra={"uniqueItems": True},
    )
    operations: list[MixedFormOperation] = Field(min_length=1, max_length=100)

    @field_validator("verification_requirements")
    @classmethod
    def _unique_verification_requirements(
        cls,
        value: list[VerificationRequirement],
    ) -> list[VerificationRequirement]:
        if len(value) != len(set(value)):
            raise ValueError("verificationRequirements must contain unique items")
        return value


class _FilenameRef(_StrictModel):
    filename: str = Field(min_length=1)


class _OutputRef(_FilenameRef):
    overwrite: bool


class _TextSetProperties(_StrictModel):
    text: str = Field(max_length=4096)


class _ValueSetProperties(_StrictModel):
    value: str = Field(max_length=4096)


class _CompiledSetCommand(_StrictModel):
    command_id: str = Field(
        alias="commandId",
        pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$",
    )
    op: Literal["set"]
    path: str = Field(min_length=1)
    properties: _TextSetProperties | _ValueSetProperties


class _CompiledBatch(_StrictModel):
    schema_version: Literal["hwpx.agent-batch/v1"] = Field(alias="schemaVersion")
    input: _FilenameRef
    output: _OutputRef
    commands: list[_CompiledSetCommand] = Field(min_length=1, max_length=100)
    expected_revision: str = Field(
        alias="expectedRevision",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    idempotency_key: str | None = Field(
        alias="idempotencyKey",
        min_length=1,
        max_length=128,
    )
    dry_run: bool = Field(alias="dryRun")
    quality: QualityInput
    verification_requirements: list[VerificationRequirement] = Field(
        alias="verificationRequirements",
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("verification_requirements")
    @classmethod
    def _unique_verification_requirements(
        cls,
        value: list[VerificationRequirement],
    ) -> list[VerificationRequirement]:
        if len(value) != len(set(value)):
            raise ValueError("verificationRequirements must contain unique items")
        return value


class MixedFormResolution(_StrictModel):
    operation_id: str = Field(
        alias="operationId",
        pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$",
    )
    locator_kind: Literal["nativeField", "labelCell", "canonicalPath", "bodyAnchor"] = Field(
        alias="locatorKind"
    )
    path: str = Field(min_length=1)
    node_kind: Literal["paragraph", "run", "cell", "form-field"] = Field(alias="nodeKind")
    stability: Literal["native", "derived", "positional"]
    section: int | None = Field(ge=1)
    table_index: int | None = Field(alias="tableIndex", ge=0)
    logical_row: int | None = Field(alias="logicalRow", ge=0)
    logical_column: int | None = Field(alias="logicalColumn", ge=0)
    physical_row: int | None = Field(alias="physicalRow", ge=0)
    physical_column: int | None = Field(alias="physicalColumn", ge=0)


class MixedFormCompiledPlanInput(_StrictModel):
    """Detached, revision-bound plan returned by ``analyze_form_fill``."""

    schema_version: Literal["hwpx.mixed-form-compiled-plan/v1"] = Field(
        alias="schemaVersion"
    )
    input_revision: str = Field(
        alias="inputRevision",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    request_hash: str = Field(
        alias="requestHash",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    resolutions: list[MixedFormResolution] = Field(min_length=1, max_length=100)
    batch: _CompiledBatch
    plan_hash: str = Field(
        alias="planHash",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )


class _ReceiptPlanSummary(_StrictModel):
    schema_version: Literal["hwpx.mixed-form-compiled-plan/v1"] = Field(
        alias="schemaVersion"
    )
    plan_hash: str = Field(alias="planHash", pattern=r"^sha256:[0-9a-f]{64}$")
    request_hash: str = Field(alias="requestHash", pattern=r"^sha256:[0-9a-f]{64}$")
    input_revision: str = Field(alias="inputRevision", pattern=r"^sha256:[0-9a-f]{64}$")


class _ReceiptFile(_StrictModel):
    filename: str
    revision: str | None


class _ReceiptOutput(_ReceiptFile):
    exists: bool
    expected_revision: str | None = Field(alias="expectedRevision")
    revision_matched: bool | None = Field(alias="revisionMatched")


class _ReceiptValueVerification(_StrictModel):
    ok: bool | None
    status: Literal["checked", "deferred"]
    matched_count: int = Field(alias="matchedCount", ge=0)
    check_count: int = Field(alias="checkCount", ge=0)
    checks: list[dict[str, Any]]


class FormVerificationReceipt(_StrictModel):
    """Closed top-level public receipt envelope for form mutations/verifiers."""

    schema_version: Literal["hwpx.form-verification-receipt/v1"] = Field(
        alias="schemaVersion"
    )
    phase: Literal["apply", "verify", "domain-apply"]
    status: Literal[
        "committed",
        "dry-run",
        "failed",
        "replayed",
        "rolled-back",
        "structurally-verified",
        "verified",
    ]
    ok: bool
    dry_run: bool = Field(alias="dryRun")
    committed: bool
    rolled_back: bool = Field(alias="rolledBack")
    plan: _ReceiptPlanSummary | None
    source: _ReceiptFile
    output: _ReceiptOutput
    source_preservation: dict[str, Any] = Field(alias="sourcePreservation")
    resolutions: list[dict[str, Any]]
    expected_targets: list[dict[str, Any]] = Field(alias="expectedTargets")
    value_verification: _ReceiptValueVerification = Field(alias="valueVerification")
    package: dict[str, Any]
    reopen: dict[str, Any]
    open_safety: dict[str, Any] = Field(alias="openSafety")
    semantic_diff: dict[str, Any] = Field(alias="semanticDiff")
    member_diff: dict[str, Any] = Field(alias="memberDiff")
    byte_preservation: dict[str, Any] = Field(alias="bytePreservation")
    idempotency: dict[str, Any]
    save_pipeline: dict[str, Any] = Field(alias="savePipeline")
    domain: dict[str, Any]
    real_hancom: dict[str, Any] = Field(alias="realHancom")
    error: dict[str, Any] | None
    rollback_preservation: dict[str, Any] | None = Field(
        default=None, alias="rollbackPreservation"
    )
    operation: str | None = None


MixedFormApplyInput: TypeAlias = Annotated[
    MixedFormPlanInput | MixedFormCompiledPlanInput,
    Field(discriminator="schema_version"),
]


_PUBLIC_PLAN_ADAPTER = TypeAdapter(MixedFormPlanInput)
_APPLY_PLAN_ADAPTER = TypeAdapter(MixedFormApplyInput)
_IDEMPOTENCY_STORE: dict[str, Any] = {}
_IDEMPOTENCY_LOCK = PUBLIC_MUTATION_LOCK
# Test-only failure seam.  It is intentionally absent from every MCP model.
_fault_injector_for_tests: Any = None
_SECTION_PATH = re.compile(r"^/section\[([1-9][0-9]*)\](?:/|$)")
_FAILURE_RECOVERY_PREFIX = ".hwpx-mixed-form-recovery"


def _publish_exact_failure_recovery(
    workspace: WorkspaceResolver,
    output: Path,
    data: bytes,
    *,
    mode: int | None,
    max_candidates: int = 64,
) -> WorkspaceOutputGuard:
    """Publish one random, bounded preimage sidecar without overwriting aliases."""

    parent = output.parent.resolve(strict=True)
    output_hash = hashlib.sha256(output.name.encode("utf-8")).hexdigest()[:12]
    for _ in range(max_candidates):
        candidate = parent / (
            f"{_FAILURE_RECOVERY_PREFIX}-{output_hash}-{secrets.token_hex(16)}"
        )
        if os.path.lexists(candidate):
            continue
        try:
            guard = workspace.capture_output(candidate, create_parents=False)
        except WorkspacePathError:
            if os.path.lexists(candidate):
                continue
            raise
        if guard.path != candidate:
            if os.path.lexists(candidate):
                continue
            raise WorkspacePathError(
                "mixed-form recovery path changed before publication",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            )
        if guard.target_existed:
            continue
        try:
            publication = workspace.atomic_publish_bytes(
                guard,
                data,
                mode=mode,
            )
            if workspace.read_guarded_bytes(publication) != data:
                raise RuntimeError(
                    "mixed-form recovery sidecar differs from the output preimage"
                )
        except (
            WorkspacePathError,
            FileNotFoundError,
            FileExistsError,
            RuntimeError,
        ):
            # A publish may have replaced the name and then lost its final
            # ownership claim to an external replacement or deletion. Never
            # reuse that name; retain the immutable preimage in a fresh random
            # candidate instead.
            continue
        except OSError:
            # Capacity and permission failures are not namespace races. Fail
            # closed before the document output can be mutated.
            raise
        return publication
    raise RuntimeError(
        f"no available random recovery sidecar for {output.name}"
    )


@dataclass(slots=True)
class _FailurePreimagePreserver:
    """Reserve, retain, and guardedly release an output preimage sidecar."""

    workspace: WorkspaceResolver
    output: Path
    data: bytes | None
    mode: int | None
    publication: WorkspaceOutputGuard | None = None

    def reserve(self) -> WorkspaceOutputGuard | None:
        if self.data is None:
            return None
        if self.publication is not None:
            try:
                if self.workspace.read_guarded_bytes(self.publication) == self.data:
                    return self.publication
            except (OSError, RuntimeError):
                self.publication = None
        self.publication = _publish_exact_failure_recovery(
            self.workspace,
            self.output,
            self.data,
            mode=self.mode,
        )
        return self.publication

    def preserve(self) -> WorkspaceOutputGuard | None:
        return self.reserve()

    def cleanup_after_success(self) -> bool:
        if self.publication is None:
            return True
        publication = self.publication
        try:
            if self.workspace.read_guarded_bytes(publication) != self.data:
                return False
            self.workspace.remove_output(publication)
        except (OSError, RuntimeError):
            return False
        self.publication = None
        return True


class _WorkspaceSavePipeline(GuardedSavePipeline):
    """Run the core quality gate but publish through an identity-bound path."""

    def __init__(
        self,
        resolver: WorkspaceResolver,
        precondition: WorkspaceOutputGuard | WorkspaceMissingParentGuard,
        failure_preimage: _FailurePreimagePreserver,
    ) -> None:
        super().__init__(oracle_factory=resolve_hancom_backend)
        self._workspace_resolver = resolver
        self._workspace_precondition = precondition
        self._failure_preimage = failure_preimage
        self.publication: WorkspaceOutputGuard | None = None

    def _publish(
        self,
        data: bytes,
        output_path: str | os.PathLike[str] | None,
        output_stream: Any | None,
    ) -> str | None:
        if output_stream is not None:
            return super()._publish(data, output_path, output_stream)
        if output_path is None:
            return None
        target = Path(output_path).resolve(strict=False)
        if target != self._workspace_precondition.path:
            raise RuntimeError("quality pipeline attempted an unauthorized output path")
        self._failure_preimage.reserve()
        guard = self._workspace_resolver.materialize_output_guard(
            self._workspace_precondition
        )
        try:
            self.publication = self._workspace_resolver.atomic_publish_bytes(
                guard,
                data,
            )
        except BaseException:
            self._failure_preimage.preserve()
            self._workspace_resolver.cleanup_owned_parent_directories(guard)
            raise
        return str(target)


def _payload(value: BaseModel | dict[str, Any], *, apply: bool) -> dict[str, Any]:
    adapter = _APPLY_PLAN_ADAPTER if apply else _PUBLIC_PLAN_ADAPTER
    parsed = adapter.validate_python(value)
    if not isinstance(parsed, BaseModel):  # pragma: no cover - union invariant
        raise TypeError("mixed-form plan did not validate to a typed model")
    payload = parsed.model_dump(by_alias=True, exclude_none=False)
    # Nullable fields at the plan/batch level are required by the frozen core
    # schema. Selector and quality optionals, however, are presence-sensitive.
    if payload["schemaVersion"] == MIXED_FORM_PLAN_SCHEMA:
        for operation in payload["operations"]:
            target = operation["target"]
            for name in ("fieldId", "name", "tableAnchor", "tableIndex"):
                if target.get(name) is None:
                    target.pop(name, None)
    quality = payload.get("quality")
    if isinstance(quality, dict):
        payload["quality"] = {name: item for name, item in quality.items() if item is not None}
    batch_quality = payload.get("batch", {}).get("quality")
    if isinstance(batch_quality, dict):
        payload["batch"]["quality"] = {
            name: item for name, item in batch_quality.items() if item is not None
        }
    return payload


def _authorize_public_plan(payload: dict[str, Any]) -> dict[str, Any]:
    authorized = copy.deepcopy(payload)
    authorized["source"] = resolve_path(str(payload["source"]))
    authorized["output"] = resolve_path(str(payload["output"]))
    return authorized


def _authorize_compiled_plan(payload: dict[str, Any]) -> tuple[Path, Path]:
    batch = payload["batch"]
    # Resolution is itself the workspace authorization check.  Keep the bytes
    # hash-protected compiled payload untouched after checking it.
    source_text = str(batch["input"]["filename"])
    output_text = str(batch["output"]["filename"])
    source = Path(resolve_path(source_text))
    output = Path(resolve_path(output_text))
    # A detached plan cannot be rewritten after its planHash is frozen. Reject
    # relative/non-canonical coordinates whose runtime interpretation could
    # differ from the workspace resolver used for authorization.
    for raw, resolved, name in (
        (source_text, source, "batch.input.filename"),
        (output_text, output, "batch.output.filename"),
    ):
        raw_path = Path(raw).expanduser()
        if not raw_path.is_absolute() or raw_path != resolved:
            raise ValueError(
                f"compiled mixed-form {name} must be an authorized canonical absolute path; "
                "run analyze_form_fill again"
            )
    return source, output


def _revision_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class _PathSnapshot:
    path: Path
    existed: bool
    data: bytes | None
    mode: int | None
    device: int | None
    inode: int | None
    guard: WorkspaceOutputGuard | None
    missing_guard: WorkspaceMissingParentGuard | None
    missing_parent_anchor: Path | None
    missing_parent_device: int | None
    missing_parent_inode: int | None
    missing_parent_parts: tuple[str, ...]


def _capture_path_snapshot(
    path: Path,
    *,
    create_parents: bool = False,
) -> _PathSnapshot:
    """Capture bytes and metadata through one workspace-bound file identity."""

    workspace = WorkspaceResolver.from_environment()
    guard = workspace.capture_output(path, create_parents=create_parents)
    data = workspace.read_guarded_bytes(guard) if guard.target_existed else None
    return _PathSnapshot(
        path=guard.path,
        existed=guard.target_existed,
        data=data,
        mode=guard.target_mode,
        device=guard.target_device,
        inode=guard.target_inode,
        guard=guard,
        missing_guard=None,
        missing_parent_anchor=None,
        missing_parent_device=None,
        missing_parent_inode=None,
        missing_parent_parts=(),
    )


def _capture_optional_path_snapshot(path: Path) -> _PathSnapshot:
    """Capture a path while treating a missing parent as an absent output.

    Read-only analysis and dry-run calls must not create output directories just
    to prove that the output does not exist.  A ``None`` guard records that no
    parent descriptor could be captured; a later comparison still observes any
    directory or file that appeared in the meantime.
    """

    workspace = WorkspaceResolver.from_environment()
    precondition = workspace.capture_output_precondition(path)
    if isinstance(precondition, WorkspaceOutputGuard):
        data = (
            workspace.read_guarded_bytes(precondition)
            if precondition.target_existed
            else None
        )
        return _PathSnapshot(
            path=precondition.path,
            existed=precondition.target_existed,
            data=data,
            mode=precondition.target_mode,
            device=precondition.target_device,
            inode=precondition.target_inode,
            guard=precondition,
            missing_guard=None,
            missing_parent_anchor=None,
            missing_parent_device=None,
            missing_parent_inode=None,
            missing_parent_parts=(),
        )
    return _PathSnapshot(
        path=precondition.path,
        existed=False,
        data=None,
        mode=None,
        device=None,
        inode=None,
        guard=None,
        missing_guard=precondition,
        missing_parent_anchor=precondition.anchor,
        missing_parent_device=precondition.anchor_device,
        missing_parent_inode=precondition.anchor_inode,
        missing_parent_parts=precondition.missing_parts,
    )


def _snapshots_match(
    observed: _PathSnapshot,
    expected: _PathSnapshot,
    *,
    identity: bool = True,
) -> bool:
    if observed.existed != expected.existed:
        return False
    if not expected.existed:
        if expected.guard is not None and observed.guard is not None:
            return bool(
                observed.path == expected.path
                and observed.guard.root == expected.guard.root
                and observed.guard.root_device == expected.guard.root_device
                and observed.guard.root_inode == expected.guard.root_inode
                and observed.guard.parent_device == expected.guard.parent_device
                and observed.guard.parent_inode == expected.guard.parent_inode
            )
        if (
            expected.guard is None
            and observed.guard is None
            and expected.missing_guard is not None
            and observed.missing_guard is not None
        ):
            return bool(
                observed.path == expected.path
                and observed.missing_guard.root == expected.missing_guard.root
                and observed.missing_guard.root_device
                == expected.missing_guard.root_device
                and observed.missing_guard.root_inode
                == expected.missing_guard.root_inode
                and observed.missing_parent_anchor
                == expected.missing_parent_anchor
                and observed.missing_parent_device
                == expected.missing_parent_device
                and observed.missing_parent_inode == expected.missing_parent_inode
                and observed.missing_parent_parts == expected.missing_parent_parts
            )
        return False
    return bool(
        observed.path == expected.path
        and observed.guard is not None
        and expected.guard is not None
        and observed.guard.root == expected.guard.root
        and observed.guard.root_device == expected.guard.root_device
        and observed.guard.root_inode == expected.guard.root_inode
        and observed.guard.parent_device == expected.guard.parent_device
        and observed.guard.parent_inode == expected.guard.parent_inode
        and observed.data == expected.data
        and observed.mode == expected.mode
        and (
            not identity
            or (
                observed.device == expected.device
                and observed.inode == expected.inode
            )
        )
    )


def _snapshot_matches_publication(
    observed: _PathSnapshot,
    publication: WorkspaceOutputGuard | None,
) -> bool:
    return bool(
        publication is not None
        and observed.existed
        and observed.guard is not None
        and observed.path == publication.path
        and observed.guard.root == publication.root
        and observed.guard.root_device == publication.root_device
        and observed.guard.root_inode == publication.root_inode
        and observed.guard.parent_device == publication.parent_device
        and observed.guard.parent_inode == publication.parent_inode
        and observed.device == publication.target_device
        and observed.inode == publication.target_inode
        and observed.mode == publication.target_mode
        and observed.guard.target_digest == publication.target_digest
    )


def _snapshot_path(path: Path) -> tuple[bool, bytes | None]:
    """Read existence and bytes as one observation."""

    snapshot = _capture_optional_path_snapshot(path)
    return snapshot.existed, snapshot.data


def _member_diff(
    before: bytes,
    after: bytes,
    *,
    allowed_changed_members: set[str] | None = None,
) -> dict[str, Any]:
    try:
        with (
            zipfile.ZipFile(BytesIO(before)) as old_zip,
            zipfile.ZipFile(BytesIO(after)) as new_zip,
        ):
            old_infos: dict[str, list[zipfile.ZipInfo]] = {}
            new_infos: dict[str, list[zipfile.ZipInfo]] = {}
            for info in old_zip.infolist():
                old_infos.setdefault(info.filename, []).append(info)
            for info in new_zip.infolist():
                new_infos.setdefault(info.filename, []).append(info)
            old_counts = Counter(info.filename for info in old_zip.infolist())
            new_counts = Counter(info.filename for info in new_zip.infolist())
            old_names = set(old_counts)
            new_names = set(new_counts)
            shared = sorted(old_names & new_names)
            changed = [
                name
                for name in shared
                if old_counts[name] == 1
                and new_counts[name] == 1
                and old_zip.read(old_infos[name][0]) != new_zip.read(new_infos[name][0])
            ]
            added = sorted(new_names - old_names)
            removed = sorted(old_names - new_names)
            duplicate_before = sorted(
                name for name, count in old_counts.items() if count > 1
            )
            duplicate_after = sorted(
                name for name, count in new_counts.items() if count > 1
            )
            multiplicity_changed = sorted(
                name
                for name in old_names | new_names
                if old_counts[name] != new_counts[name]
            )
            allowed = (
                sorted(allowed_changed_members)
                if allowed_changed_members is not None
                else None
            )
            unexpected = (
                sorted(set(changed) - allowed_changed_members)
                if allowed_changed_members is not None
                else []
            )
            preservation_ok = (
                not added
                and not removed
                and not unexpected
                and not duplicate_before
                and not duplicate_after
                and not multiplicity_changed
                if allowed_changed_members is not None
                else None
            )
            return {
                "ok": preservation_ok,
                "status": (
                    "verified"
                    if preservation_ok is True
                    else "violated"
                    if preservation_ok is False
                    else "diff-only"
                ),
                "diffComputed": True,
                "changedMembers": changed,
                "allowedChangedMembers": allowed,
                "unexpectedChangedMembers": unexpected,
                "addedMembers": added,
                "removedMembers": removed,
                "duplicateMembersBefore": duplicate_before,
                "duplicateMembersAfter": duplicate_after,
                "multiplicityChangedMembers": multiplicity_changed,
                "unchangedMemberCount": len(shared) - len(changed),
                "beforeMemberCount": sum(old_counts.values()),
                "afterMemberCount": sum(new_counts.values()),
            }
    except (OSError, zipfile.BadZipFile) as exc:
        return {
            "ok": False,
            "status": "unavailable",
            "diffComputed": False,
            "errorCode": type(exc).__name__,
        }


def _not_produced(reason: str = "not-produced") -> dict[str, Any]:
    return {"ok": None, "status": reason}


def _expected_values(compiled: dict[str, Any]) -> list[dict[str, Any]]:
    expected: list[dict[str, Any]] = []
    commands = compiled["batch"]["commands"]
    for resolution, command in zip(compiled["resolutions"], commands, strict=True):
        properties = command["properties"]
        property_name = "value" if "value" in properties else "text"
        expected.append(
            {
                "operationId": resolution["operationId"],
                "locatorKind": resolution["locatorKind"],
                "path": resolution["path"],
                "nodeKind": resolution["nodeKind"],
                "property": property_name,
                "value": properties[property_name],
            }
        )
    return expected


def _public_expected_targets(
    expected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return receipt-safe target metadata without user-provided values."""

    keys = ("operationId", "locatorKind", "path", "nodeKind", "property")
    return [{key: item[key] for key in keys if key in item} for item in expected]


def _public_value_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip expected/actual document content from durable receipts."""

    public: list[dict[str, Any]] = []
    keys = ("operationId", "locatorKind", "path", "nodeKind", "property", "ok")
    for check in checks:
        item = {key: check[key] for key in keys if key in check}
        if check.get("errorCode"):
            item["errorCode"] = check["errorCode"]
        public.append(item)
    return public


def _public_error(error: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep stable failure metadata while excluding paths and document values."""

    if not isinstance(error, dict):
        return None
    keys = ("code", "recoverability", "target")
    return _receipt_safe({key: error[key] for key in keys if key in error})


def _public_source_preservation(report: dict[str, Any]) -> dict[str, Any]:
    public = copy.deepcopy(report)
    filename = public.get("filename")
    if isinstance(filename, str):
        public["filename"] = Path(filename).name
    return public


def _receipt_safe(value: Any) -> Any:
    """Recursively remove absolute filesystem coordinates from receipts."""

    if isinstance(value, dict):
        return {str(key): _receipt_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_receipt_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_receipt_safe(item) for item in value]
    if isinstance(value, str) and not value.startswith("/section["):
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            return candidate.name
    return value


def _public_apply_response(response: dict[str, Any]) -> dict[str, Any]:
    """Keep transactional evidence while removing document content echoes."""

    public = copy.deepcopy(response)
    if "error" in public:
        public["error"] = _public_error(public.get("error"))
    command_results: list[dict[str, Any]] = []
    for raw in public.get("commandResults", []):
        if not isinstance(raw, dict):
            continue
        item = {
            key: copy.deepcopy(raw[key])
            for key in (
                "commandId",
                "op",
                "ok",
                "path",
                "parentPath",
            )
            if key in raw
        }
        warnings = raw.get("warnings")
        item["warningCount"] = len(warnings) if isinstance(warnings, list) else 0
        changed = raw.get("changedProperties")
        item["changedPropertyNames"] = (
            sorted(str(name) for name in changed) if isinstance(changed, dict) else []
        )
        identities = raw.get("generatedIdentities")
        item["generatedIdentityCount"] = (
            len(identities) if isinstance(identities, list) else 0
        )
        command_results.append(item)
    if "commandResults" in public:
        public["commandResults"] = command_results

    semantic = public.get("semanticDiff")
    if isinstance(semantic, dict):
        changes: list[dict[str, Any]] = []
        for raw in semantic.get("changes", []):
            if not isinstance(raw, dict):
                continue
            item = {
                key: copy.deepcopy(raw[key])
                for key in ("commandId", "op", "beforePath", "afterPath")
                if key in raw
            }
            changed = raw.get("changedProperties")
            item["changedPropertyNames"] = (
                sorted(str(name) for name in changed)
                if isinstance(changed, dict)
                else []
            )
            changes.append(item)
        public["semanticDiff"] = {
            key: copy.deepcopy(semantic[key])
            for key in (
                "schemaVersion",
                "inputRevision",
                "candidateRevision",
            )
            if key in semantic
        }
        public["semanticDiff"].update(
            {
                "changeCount": len(changes),
                "changes": changes,
                "identityChangeCount": len(semantic.get("identityMap", [])),
            }
        )
    safe = _receipt_safe(public)
    if not isinstance(safe, dict):  # pragma: no cover - object invariant
        raise TypeError("public mixed-form response must remain an object")
    return safe


def _section_member_paths(source_bytes: bytes) -> tuple[str, ...]:
    """Return manifest-spine section parts in logical document order."""

    with HwpxAgentDocument.open(source_bytes) as document:
        return tuple(str(section.part_name) for section in document.document.sections)


def _allowed_plan_members(
    compiled: dict[str, Any],
    source_bytes: bytes,
) -> set[str]:
    """Map logical section coordinates to manifest-spine member names."""

    section_paths = _section_member_paths(source_bytes)
    allowed: set[str] = set()
    for resolution in compiled.get("resolutions", []):
        section = resolution.get("section")
        if not isinstance(section, int) or section < 1:
            match = _SECTION_PATH.match(str(resolution.get("path", "")))
            section = int(match.group(1)) if match is not None else None
        if isinstance(section, int) and section >= 1:
            try:
                allowed.add(section_paths[section - 1])
            except IndexError as exc:
                raise ValueError(
                    f"compiled mixed-form plan references missing logical section {section}"
                ) from exc
    if not allowed:
        raise ValueError("compiled mixed-form plan has no authorized section members")
    return allowed


def _assess_declared_member_diff(
    report: dict[str, Any] | None,
    *,
    allowed_changed_members: set[str],
) -> dict[str, Any]:
    """Apply preservation semantics to a core candidate-only diff report."""

    if not isinstance(report, dict):
        return {
            "ok": False,
            "status": "not-produced",
            "diffComputed": False,
            "allowedChangedMembers": sorted(allowed_changed_members),
        }
    assessed = copy.deepcopy(report)
    readable = bool(report.get("ok"))
    changed = {str(name) for name in report.get("changedMembers", [])}
    added = sorted(str(name) for name in report.get("addedMembers", []))
    removed = sorted(str(name) for name in report.get("removedMembers", []))
    unexpected = sorted(changed - allowed_changed_members)
    ok = readable and not added and not removed and not unexpected
    assessed.update(
        {
            "ok": ok,
            "status": "verified" if ok else "violated",
            "diffComputed": True,
            "allowedChangedMembers": sorted(allowed_changed_members),
            "unexpectedChangedMembers": unexpected,
            "addedMembers": added,
            "removedMembers": removed,
        }
    )
    return assessed


def _path_mode(path: Path) -> int | None:
    try:
        return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
    except OSError:
        return None


def _open_safety_snapshot(data: bytes) -> dict[str, Any]:
    """Validate immutable bytes so one receipt never combines two path states."""

    return build_hwpx_open_safety_report(data)


def validate_form_verification_receipt(
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Validate and normalize the closed receipt envelope before publication."""

    return FormVerificationReceipt.model_validate(receipt).model_dump(
        by_alias=True,
        exclude_none=False,
    )


def _source_preservation_snapshot(
    source: Path,
    *,
    expected_revision: str | None,
    before: bytes,
    after: bytes | None,
) -> dict[str, Any]:
    """Build preservation evidence from one immutable post-operation read."""

    before_revision = _revision_bytes(before)
    actual_revision = _revision_bytes(after) if after is not None else None
    expected_matches_before = (
        expected_revision is None or before_revision == expected_revision
    )
    preserved = bool(
        actual_revision == before_revision and expected_matches_before
    )
    return {
        "ok": preserved,
        "filename": str(source),
        "expectedRevision": expected_revision,
        "beforeRevision": before_revision,
        "actualRevision": actual_revision,
        "expectedMatchedBefore": expected_matches_before,
        "preserved": preserved,
    }


def _unified_receipt(
    *,
    phase: Literal["apply", "verify", "domain-apply"],
    ok: bool,
    source: Path,
    output: Path,
    dry_run: bool,
    rolled_back: bool,
    source_preservation: dict[str, Any],
    plan: dict[str, Any] | None = None,
    core_verification: dict[str, Any] | None = None,
    member_diff: dict[str, Any] | None = None,
    value_checks: list[dict[str, Any]] | None = None,
    output_revision: str | None = None,
    output_exists: bool | None = None,
    expected_output_revision: str | None = None,
    error: dict[str, Any] | None = None,
    domain: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verification = copy.deepcopy(core_verification or {})
    idempotency = verification.get("idempotency")
    replayed = bool(isinstance(idempotency, dict) and idempotency.get("replayed"))
    if ok and dry_run:
        status = "dry-run"
    elif ok and replayed:
        status = "replayed"
    elif ok and phase == "verify":
        real_hancom = verification.get("realHancom")
        visually_verified = bool(
            isinstance(real_hancom, dict)
            and real_hancom.get("ok")
            and real_hancom.get("renderChecked") is True
        )
        revision_bound = (
            expected_output_revision is not None
            and expected_output_revision == output_revision
        )
        status = (
            "verified"
            if visually_verified and revision_bound
            else "structurally-verified"
        )
    elif ok:
        status = "committed"
    elif rolled_back:
        status = "rolled-back"
    else:
        status = "failed"
    observed_output_exists = output.exists() if output_exists is None else output_exists
    open_safety = copy.deepcopy(verification.get("openSafety"))
    if not isinstance(open_safety, dict):
        open_safety = _not_produced("dry-run" if dry_run else "not-produced")
    byte_preservation = copy.deepcopy(
        member_diff or verification.get("bytePreservation") or _not_produced()
    )
    plan_summary = None
    resolutions: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    if plan is not None:
        plan_summary = {
            "schemaVersion": plan["schemaVersion"],
            "planHash": plan["planHash"],
            "requestHash": plan["requestHash"],
            "inputRevision": plan["inputRevision"],
        }
        resolutions = copy.deepcopy(plan["resolutions"])
        expected = _public_expected_targets(_expected_values(plan))
    checks = _public_value_checks(copy.deepcopy(value_checks or []))
    values_ok: bool | None = None
    if checks:
        values_ok = all(bool(item.get("ok")) for item in checks)
    receipt = {
        "schemaVersion": FORM_VERIFICATION_RECEIPT_SCHEMA,
        "phase": phase,
        "status": status,
        "ok": ok,
        "dryRun": dry_run,
        "committed": bool(ok and not dry_run and phase != "verify" and not replayed),
        "rolledBack": rolled_back,
        "plan": plan_summary,
        "source": {
            "filename": source.name,
            "revision": source_preservation.get("actualRevision"),
        },
        "output": {
            "filename": output.name,
            "exists": observed_output_exists,
            "revision": output_revision,
            "expectedRevision": expected_output_revision,
            "revisionMatched": (
                output_revision == expected_output_revision
                if expected_output_revision is not None
                else None
            ),
        },
        "sourcePreservation": _public_source_preservation(source_preservation),
        "resolutions": resolutions,
        "expectedTargets": expected,
        "valueVerification": {
            "ok": values_ok,
            "status": "checked" if checks else "deferred",
            "matchedCount": sum(bool(item.get("ok")) for item in checks),
            "checkCount": len(checks),
            "checks": checks,
        },
        "package": _receipt_safe(
            copy.deepcopy(verification.get("package") or _not_produced())
        ),
        "reopen": _receipt_safe(
            copy.deepcopy(verification.get("reopen") or _not_produced())
        ),
        "openSafety": _receipt_safe(open_safety),
        "semanticDiff": _receipt_safe(
            copy.deepcopy(verification.get("semanticDiff") or _not_produced())
        ),
        "memberDiff": _receipt_safe(byte_preservation),
        # Compatibility key retained for callers already reading the core name.
        "bytePreservation": _receipt_safe(copy.deepcopy(byte_preservation)),
        "idempotency": _receipt_safe(
            copy.deepcopy(verification.get("idempotency") or _not_produced())
        ),
        "savePipeline": _receipt_safe(
            copy.deepcopy(verification.get("savePipeline") or _not_produced())
        ),
        "domain": _receipt_safe(
            copy.deepcopy(domain or verification.get("domain") or _not_produced())
        ),
        "realHancom": _receipt_safe(
            copy.deepcopy(
                verification.get("realHancom") or _not_produced("not-requested")
            )
        ),
        "error": _public_error(error),
    }
    return validate_form_verification_receipt(receipt)


def analyze_mixed_form_plan(
    plan: MixedFormPlanInput | dict[str, Any],
) -> dict[str, Any]:
    """Compile a public plan without copying, saving, or mutating either path."""

    request = _authorize_public_plan(_payload(plan, apply=False))
    source = Path(request["source"])
    source_snapshot = _capture_path_snapshot(source)
    if source_snapshot.data is None:
        raise FileNotFoundError(source)
    before = source_snapshot.data
    output = Path(request["output"])
    output_snapshot = _capture_optional_path_snapshot(output)

    compiled = plan_mixed_form_fill(request).to_dict()
    open_safety = _open_safety_snapshot(before)
    source_unchanged = _snapshots_match(
        _capture_path_snapshot(source),
        source_snapshot,
    )
    output_unchanged = _snapshots_match(
        _capture_optional_path_snapshot(output),
        output_snapshot,
    )
    if not source_unchanged or not output_unchanged:  # pragma: no cover - race/invariant
        raise RuntimeError("mixed-form analysis mutated an input or output file")
    detached = copy.deepcopy(compiled)
    return {
        "schemaVersion": "hwpx.mixed-form-analysis/v1",
        "mutated": False,
        "source": {
            "filename": str(source),
            "revision": detached["inputRevision"],
            "unchangedAfterAnalysis": True,
        },
        "output": {
            "filename": str(output),
            "unchangedAfterAnalysis": True,
        },
        "compiledPlan": detached,
        "planHash": detached["planHash"],
        "requestHash": detached["requestHash"],
        "resolutions": copy.deepcopy(detached["resolutions"]),
        "openSafety": open_safety,
        "nextTool": "apply_form_fill",
    }


def apply_canonical_mixed_form_plan(
    plan: MixedFormApplyInput | dict[str, Any],
) -> dict[str, Any]:
    """Apply one plan while serializing adapter verification and rollback."""

    with _IDEMPOTENCY_LOCK:
        return _apply_canonical_mixed_form_plan_locked(plan)


def _forget_fresh_idempotency(
    compiled: dict[str, Any],
    *,
    fresh: bool,
) -> None:
    if not fresh:
        return
    key = compiled["batch"].get("idempotencyKey")
    if isinstance(key, str):
        _IDEMPOTENCY_STORE.pop(key, None)


def _restore_owned_candidate(
    *,
    output: Path,
    output_existed: bool,
    output_before: bytes | None,
    output_mode_before: int | None,
    candidate_bytes: bytes | None,
    claimed_revision: str | None,
    fresh: bool,
    publication: WorkspaceOutputGuard | None = None,
    failure_preimage: _FailurePreimagePreserver | None = None,
) -> bool:
    """Restore only a candidate represented by an exact publication token."""

    if failure_preimage is not None:
        failure_preimage.preserve()
    if publication is not None:
        workspace = WorkspaceResolver.from_environment()
        try:
            if output_existed:
                if output_before is None:  # pragma: no cover - snapshot invariant
                    return False
                workspace.atomic_publish_bytes(
                    publication,
                    output_before,
                    mode=output_mode_before,
                )
            else:
                workspace.remove_output(publication)
        except (OSError, RuntimeError):
            return False
        if not output_existed:
            return workspace.cleanup_owned_parent_directories(publication)
        return True

    # Every canonical commit is required to publish through
    # ``_WorkspaceSavePipeline``. Bytes alone are not an ownership claim: an
    # external writer can replace the path with identical contents. Without the
    # publication token, fail closed and preserve the live path.
    return False


def _apply_canonical_mixed_form_plan_locked(
    plan: MixedFormApplyInput | dict[str, Any],
) -> dict[str, Any]:
    """Apply and bind every public claim to one immutable output candidate."""

    payload = _payload(plan, apply=True)
    if payload["schemaVersion"] == MIXED_FORM_PLAN_SCHEMA:
        compiled = plan_mixed_form_fill(_authorize_public_plan(payload)).to_dict()
    elif payload["schemaVersion"] == MIXED_FORM_COMPILED_PLAN_SCHEMA:
        _authorize_compiled_plan(payload)
        compiled = payload
    else:  # pragma: no cover - discriminated union guard
        raise ValueError("unsupported mixed-form plan schema")

    compiled = validate_mixed_form_plan(compiled).to_dict()
    source, output = _authorize_compiled_plan(compiled)
    source_snapshot = _capture_path_snapshot(source)
    if source_snapshot.data is None:  # pragma: no cover - compiled plan invariant
        raise FileNotFoundError(source)
    source_before = source_snapshot.data
    dry_run = bool(compiled["batch"]["dryRun"])
    save_pipeline: _WorkspaceSavePipeline | None = None
    output_snapshot = _capture_optional_path_snapshot(output)
    output_existed = output_snapshot.existed
    output_before = output_snapshot.data
    output_mode_before = output_snapshot.mode
    workspace = WorkspaceResolver.from_environment()
    failure_preimage = _FailurePreimagePreserver(
        workspace=workspace,
        output=output_snapshot.path,
        data=output_before if output_existed else None,
        mode=output_mode_before,
    )
    if not dry_run:
        output_precondition = (
            output_snapshot.guard or output_snapshot.missing_guard
        )
        if output_precondition is None:  # pragma: no cover - snapshot invariant
            raise RuntimeError("canonical output precondition is unavailable")
        save_pipeline = _WorkspaceSavePipeline(
            workspace,
            output_precondition,
            failure_preimage,
        )
    fresh = False
    claimed_revision: str | None = None
    publication: WorkspaceOutputGuard | None = None
    candidate_existed = False
    candidate_bytes: bytes | None = None
    try:
        result = apply_mixed_form_plan(
            compiled,
            idempotency_store=_IDEMPOTENCY_STORE,
            fault_injector=_fault_injector_for_tests,
            save_pipeline=save_pipeline,
        )
        response = result.to_dict()
        core_verification = copy.deepcopy(response.get("verificationReport", {}))
        idempotency = core_verification.get("idempotency")
        replayed = bool(
            isinstance(idempotency, dict) and idempotency.get("replayed") is True
        )
        fresh = bool(
            response.get("ok")
            and isinstance(idempotency, dict)
            and idempotency.get("replayed") is False
        )
        claimed_revision = (
            response.get("documentRevision")
            if isinstance(response.get("documentRevision"), str)
            else None
        )
        if claimed_revision is None and isinstance(
            core_verification.get("candidateRevision"),
            str,
        ):
            claimed_revision = core_verification["candidateRevision"]
        publication = save_pipeline.publication if save_pipeline is not None else None
        candidate_snapshot = _capture_optional_path_snapshot(output)
        candidate_existed = candidate_snapshot.existed
        candidate_bytes = candidate_snapshot.data
        return _finalize_canonical_apply(
            compiled=compiled,
            source=source,
            output=output,
            source_snapshot_before=source_snapshot,
            output_snapshot_before=output_snapshot,
            candidate_snapshot=candidate_snapshot,
            source_before=source_before,
            output_existed=output_existed,
            output_before=output_before,
            output_mode_before=output_mode_before,
            candidate_existed=candidate_existed,
            candidate_bytes=candidate_bytes,
            response=response,
            core_verification=core_verification,
            claimed_revision=claimed_revision,
            replayed=replayed,
            fresh=fresh,
            publication=publication,
            failure_preimage=failure_preimage,
        )
    except BaseException:
        if publication is None and save_pipeline is not None:
            publication = save_pipeline.publication
        failure_preimage.preserve()
        _forget_fresh_idempotency(
            compiled,
            fresh=bool(fresh or publication is not None),
        )
        _restore_owned_candidate(
            output=output,
            output_existed=output_existed,
            output_before=output_before,
            output_mode_before=output_mode_before,
            candidate_bytes=candidate_bytes,
            claimed_revision=claimed_revision,
            fresh=fresh,
            publication=publication,
            failure_preimage=failure_preimage,
        )
        raise


def _finalize_canonical_apply(
    *,
    compiled: dict[str, Any],
    source: Path,
    output: Path,
    source_snapshot_before: _PathSnapshot,
    output_snapshot_before: _PathSnapshot,
    candidate_snapshot: _PathSnapshot,
    source_before: bytes,
    output_existed: bool,
    output_before: bytes | None,
    output_mode_before: int | None,
    candidate_existed: bool,
    candidate_bytes: bytes | None,
    response: dict[str, Any],
    core_verification: dict[str, Any],
    claimed_revision: str | None,
    replayed: bool,
    fresh: bool,
    publication: WorkspaceOutputGuard | None,
    failure_preimage: _FailurePreimagePreserver,
) -> dict[str, Any]:
    """Finalize a core result without combining evidence from different bytes."""

    dry_run = bool(compiled["batch"]["dryRun"])
    response["dryRun"] = dry_run
    observed_source_snapshot = _capture_optional_path_snapshot(source)
    source_exists = observed_source_snapshot.existed
    source_after = observed_source_snapshot.data
    source_report = _source_preservation_snapshot(
        source,
        expected_revision=compiled["inputRevision"],
        before=source_before,
        after=source_after if source_exists else None,
    )
    if not _snapshots_match(observed_source_snapshot, source_snapshot_before):
        source_report.update(
            {
                "ok": False,
                "preserved": False,
                "identityPreserved": False,
            }
        )
    candidate_revision = (
        _revision_bytes(candidate_bytes) if candidate_bytes is not None else None
    )
    allowed_members = _allowed_plan_members(compiled, source_before)
    verification = copy.deepcopy(core_verification)
    response_ok = bool(response.get("ok")) and bool(source_report["ok"])
    missing_fresh_publication = bool(
        (response_ok or core_verification.get("publication", {}).get("ownershipMissing"))
        and not dry_run
        and not replayed
        and publication is None
    )
    rolled_back = bool(response.get("rolledBack"))
    final_exists = candidate_existed
    final_bytes = candidate_bytes

    if not source_report["ok"]:
        response_ok = False
        response["error"] = {
            "code": "source_revision_mismatch",
            "recoverability": "retryable",
            "target": "batch.input.filename",
        }
        _forget_fresh_idempotency(compiled, fresh=fresh)
        rolled_back = _restore_owned_candidate(
            output=output,
            output_existed=output_existed,
            output_before=output_before,
            output_mode_before=output_mode_before,
            candidate_bytes=candidate_bytes,
            claimed_revision=claimed_revision,
            fresh=fresh,
            publication=publication,
            failure_preimage=failure_preimage,
        )
        final_exists, final_bytes = _snapshot_path(output)
    elif missing_fresh_publication:
        response_ok = False
        _forget_fresh_idempotency(compiled, fresh=fresh)
        failure_preimage.preserve()
        response["error"] = {
            "code": "materialized_output_changed",
            "recoverability": "retryable",
            "target": "batch.output.filename",
        }
    elif not response_ok:
        _forget_fresh_idempotency(compiled, fresh=fresh)
        restored = _restore_owned_candidate(
            output=output,
            output_existed=output_existed,
            output_before=output_before,
            output_mode_before=output_mode_before,
            candidate_bytes=candidate_bytes,
            claimed_revision=claimed_revision,
            fresh=fresh,
            publication=publication,
            failure_preimage=failure_preimage,
        )
        final_exists, final_bytes = _snapshot_path(output)
        prestate_preserved = bool(
            final_exists == output_existed
            and (
                not output_existed
                or (
                    final_bytes == output_before
                    and _path_mode(output) == output_mode_before
                )
            )
        )
        rolled_back = bool(prestate_preserved and (restored or rolled_back))
    elif dry_run:
        output_preserved = bool(
            candidate_existed == output_existed
            and (
                not output_existed
                or (
                    candidate_bytes == output_before
                    and _path_mode(output) == output_mode_before
                )
            )
        )
        if not output_preserved:
            response_ok = False
            response["error"] = {
                "code": "dry_run_mutated",
                "recoverability": "terminal",
                "target": "batch.output.filename",
            }
            _forget_fresh_idempotency(compiled, fresh=fresh)
            rolled_back = _restore_owned_candidate(
                output=output,
                output_existed=output_existed,
                output_before=output_before,
                output_mode_before=output_mode_before,
                candidate_bytes=candidate_bytes,
                claimed_revision=claimed_revision,
                fresh=False,
                publication=publication,
                failure_preimage=failure_preimage,
            )
            final_exists, final_bytes = _snapshot_path(output)
    elif response_ok:
        revision_matches = bool(
            candidate_bytes is not None and claimed_revision == candidate_revision
        )
        if candidate_bytes is None:
            open_safety = {"ok": False, "status": "output-unavailable"}
            member_diff = {
                "ok": False,
                "status": "output-unavailable",
                "diffComputed": False,
            }
        else:
            open_safety = _open_safety_snapshot(candidate_bytes)
            member_diff = _member_diff(
                source_before,
                candidate_bytes,
                allowed_changed_members=allowed_members,
            )
        verification.update(
            {
                "package": copy.deepcopy(
                    open_safety.get("validatePackage") or _not_produced()
                ),
                "reopen": copy.deepcopy(
                    open_safety.get("reopen") or _not_produced()
                ),
                "openSafety": open_safety,
                "bytePreservation": member_diff,
            }
        )
        if not (
            revision_matches and open_safety.get("ok") and member_diff.get("ok")
        ):
            response_ok = False
            _forget_fresh_idempotency(compiled, fresh=fresh)
            rolled_back = _restore_owned_candidate(
                output=output,
                output_existed=output_existed,
                output_before=output_before,
                output_mode_before=output_mode_before,
                candidate_bytes=candidate_bytes,
                claimed_revision=claimed_revision,
                fresh=fresh and revision_matches,
                publication=publication,
                failure_preimage=failure_preimage,
            )
            response["error"] = {
                "code": (
                    "idempotency_output_mismatch"
                    if replayed
                    else "materialized_output_verification_failed"
                    if rolled_back
                    else "materialized_output_changed"
                ),
                "recoverability": "terminal" if rolled_back else "retryable",
                "target": "batch.output.filename",
            }
            final_exists, final_bytes = _snapshot_path(output)

    if dry_run and response_ok:
        receipt_members = _assess_declared_member_diff(
            verification.get("bytePreservation"),
            allowed_changed_members=allowed_members,
        )
    elif response_ok:
        receipt_members = copy.deepcopy(
            verification.get("bytePreservation") or _not_produced()
        )
    else:
        receipt_members = _not_produced(
            "rolled-back" if rolled_back else "not-committed"
        )

    def assemble_public(
        *,
        ok: bool,
        source_evidence: dict[str, Any],
        observed_exists: bool,
        observed_bytes: bytes | None,
        receipt_verification: dict[str, Any],
        member_evidence: dict[str, Any],
        path_prestate_preserved: bool = True,
    ) -> dict[str, Any]:
        response["ok"] = ok
        response["rolledBack"] = rolled_back
        response["documentRevision"] = claimed_revision if ok else None
        if ok:
            response.pop("error", None)
        observed_revision = (
            None
            if dry_run and ok
            else _revision_bytes(observed_bytes)
            if observed_bytes is not None
            else None
        )
        rollback_preserved = bool(
            path_prestate_preserved
            and
            observed_exists == output_existed
            and (
                not output_existed
                or (
                    observed_bytes == output_before
                    and _path_mode(output) == output_mode_before
                )
            )
        )
        if not ok:
            reason = "rolled-back" if rolled_back else "not-committed"
            receipt_verification = copy.deepcopy(receipt_verification)
            receipt_verification.update(
                {
                    "package": _not_produced(reason),
                    "reopen": _not_produced(reason),
                    "openSafety": _not_produced(reason),
                    "bytePreservation": member_evidence,
                }
            )
        receipt = _unified_receipt(
            phase="apply",
            ok=ok,
            source=source,
            output=output,
            dry_run=dry_run,
            rolled_back=rolled_back,
            source_preservation=source_evidence,
            plan=compiled,
            core_verification=receipt_verification,
            member_diff=member_evidence,
            output_revision=observed_revision,
            output_exists=observed_exists,
            expected_output_revision=(claimed_revision if ok and not dry_run else None),
            error=response.get("error"),
        )
        receipt["rollbackPreservation"] = {
            "required": bool(
                rolled_back
                or dry_run
                or (not ok and publication is not None)
            ),
            "outputExistedBefore": output_existed,
            "preserved": rollback_preserved,
        }
        receipt = validate_form_verification_receipt(receipt)
        response["verificationReport"] = receipt_verification
        response.update(
            {
                "planHash": compiled["planHash"],
                "requestHash": compiled["requestHash"],
                "resolutions": copy.deepcopy(compiled["resolutions"]),
                "verificationReceipt": receipt,
                "openSafety": copy.deepcopy(receipt["openSafety"]),
            }
        )
        return _public_apply_response(response)

    public = assemble_public(
        ok=response_ok,
        source_evidence=source_report,
        observed_exists=final_exists,
        observed_bytes=final_bytes,
        receipt_verification=verification,
        member_evidence=receipt_members,
    )
    observed_source = _capture_optional_path_snapshot(source)
    observed_output = _capture_optional_path_snapshot(output)
    source_matches = _snapshots_match(observed_source, source_snapshot_before)
    if not response_ok:
        failure_preimage.preserve()
        final_source_report = _source_preservation_snapshot(
            source,
            expected_revision=compiled["inputRevision"],
            before=source_before,
            after=observed_source.data if observed_source.existed else None,
        )
        if not source_matches:
            final_source_report.update(
                {
                    "ok": False,
                    "preserved": False,
                    "identityPreserved": False,
                }
            )
            response["error"] = {
                "code": "source_revision_mismatch",
                "recoverability": "retryable",
                "target": "batch.input.filename",
            }
        return assemble_public(
            ok=False,
            source_evidence=final_source_report,
            observed_exists=observed_output.existed,
            observed_bytes=observed_output.data,
            receipt_verification=verification,
            member_evidence=receipt_members,
            path_prestate_preserved=_snapshots_match(
                observed_output,
                output_snapshot_before,
                identity=False,
            ),
        )

    if dry_run:
        output_matches = _snapshots_match(
            observed_output,
            output_snapshot_before,
        )
    elif publication is not None:
        output_matches = _snapshot_matches_publication(
            observed_output,
            publication,
        )
    else:
        output_matches = _snapshots_match(observed_output, candidate_snapshot)
    success_cleanup_failed = False
    if source_matches and output_matches:
        if dry_run:
            return public
        if failure_preimage.cleanup_after_success():
            observed_source = _capture_optional_path_snapshot(source)
            observed_output = _capture_optional_path_snapshot(output)
            source_matches = _snapshots_match(
                observed_source,
                source_snapshot_before,
            )
            output_matches = (
                _snapshot_matches_publication(observed_output, publication)
                if publication is not None
                else _snapshots_match(observed_output, candidate_snapshot)
            )
            if source_matches and output_matches:
                return public
        else:
            success_cleanup_failed = True

    _forget_fresh_idempotency(compiled, fresh=fresh)
    failure_preimage.preserve()
    if not source_matches:
        response["error"] = {
            "code": "source_revision_mismatch",
            "recoverability": "retryable",
            "target": "batch.input.filename",
        }
        rolled_back = _restore_owned_candidate(
            output=output,
            output_existed=output_existed,
            output_before=output_before,
            output_mode_before=output_mode_before,
            candidate_bytes=candidate_bytes,
            claimed_revision=claimed_revision,
            fresh=fresh and not dry_run,
            publication=publication,
            failure_preimage=failure_preimage,
        )
    else:
        response["error"] = {
            "code": "materialized_output_changed",
            "recoverability": "retryable",
            "target": "batch.output.filename",
        }
        rolled_back = (
            _restore_owned_candidate(
                output=output,
                output_existed=output_existed,
                output_before=output_before,
                output_mode_before=output_mode_before,
                candidate_bytes=candidate_bytes,
                claimed_revision=claimed_revision,
                fresh=fresh and not dry_run,
                publication=publication,
                failure_preimage=failure_preimage,
            )
            if success_cleanup_failed and output_matches
            else False
        )
    final_output_snapshot = _capture_optional_path_snapshot(output)
    final_exists = final_output_snapshot.existed
    final_bytes = final_output_snapshot.data
    source_exists, source_after = _snapshot_path(source)
    source_report = _source_preservation_snapshot(
        source,
        expected_revision=compiled["inputRevision"],
        before=source_before,
        after=source_after if source_exists else None,
    )
    if not source_matches:
        source_report.update(
            {
                "ok": False,
                "preserved": False,
                "identityPreserved": False,
            }
        )
    return assemble_public(
        ok=False,
        source_evidence=source_report,
        observed_exists=final_exists,
        observed_bytes=final_bytes,
        receipt_verification=verification,
        member_evidence=_not_produced(
            "rolled-back" if rolled_back else "output-changed"
        ),
        path_prestate_preserved=_snapshots_match(
            final_output_snapshot,
            output_snapshot_before,
            identity=False,
        ),
    )


def verify_canonical_mixed_form_plan(
    plan: MixedFormCompiledPlanInput | dict[str, Any],
    *,
    require: bool = False,
    expected_output_revision: str | None = None,
    render_verifier: Callable[[str, str, bool], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify one compiled plan while excluding in-process public writers."""

    with _IDEMPOTENCY_LOCK:
        return _verify_canonical_mixed_form_plan_locked(
            plan,
            require=require,
            expected_output_revision=expected_output_revision,
            render_verifier=render_verifier,
        )


def _verify_canonical_mixed_form_plan_locked(
    plan: MixedFormCompiledPlanInput | dict[str, Any],
    *,
    require: bool = False,
    expected_output_revision: str | None = None,
    render_verifier: Callable[[str, str, bool], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify one compiled plan against immutable source/output snapshots."""

    payload = _payload(plan, apply=True)
    if payload["schemaVersion"] != MIXED_FORM_COMPILED_PLAN_SCHEMA:
        raise ValueError("verify_form_fill requires hwpx.mixed-form-compiled-plan/v1")
    compiled = validate_mixed_form_plan(payload).to_dict()
    source, output = _authorize_compiled_plan(compiled)
    source_snapshot = _capture_path_snapshot(source)
    if source_snapshot.data is None:  # pragma: no cover - validated plan invariant
        raise FileNotFoundError(source)
    source_bytes = source_snapshot.data
    checks: list[dict[str, Any]] = []
    output_bytes: bytes | None = None
    output_error_code: str | None = None
    output_snapshot_before = _capture_optional_path_snapshot(output)
    try:
        if output_snapshot_before.data is None:
            raise FileNotFoundError(output)
        output_bytes = output_snapshot_before.data
        with HwpxAgentDocument.open(output_bytes) as document:
            for expected in _expected_values(compiled):
                try:
                    record = document.resolve_record(expected["path"])
                    actual = record.summary.get(expected["property"])
                    checks.append(
                        {
                            **copy.deepcopy(expected),
                            "ok": actual == expected["value"],
                        }
                    )
                except Exception as exc:
                    checks.append(
                        {
                            **copy.deepcopy(expected),
                            "ok": False,
                            "errorCode": type(exc).__name__,
                        }
                    )
    except Exception as exc:
        output_error_code = type(exc).__name__

    if output_bytes is not None:
        open_safety = _open_safety_snapshot(output_bytes)
        member_diff = _member_diff(
            source_bytes,
            output_bytes,
            allowed_changed_members=_allowed_plan_members(compiled, source_bytes),
        )
        core_verification = {
            "package": copy.deepcopy(
                open_safety.get("validatePackage") or _not_produced()
            ),
            "reopen": copy.deepcopy(open_safety.get("reopen") or _not_produced()),
            "openSafety": open_safety,
            "semanticDiff": {
                "ok": all(bool(item.get("ok")) for item in checks),
                "verifiedTargetCount": len(checks),
            },
            "bytePreservation": member_diff,
        }
    else:
        open_safety = {
            "ok": False,
            "status": "output-unavailable",
            "errorCode": output_error_code,
        }
        member_diff = {
            "ok": False,
            "status": "output-unavailable",
            "errorCode": output_error_code,
        }
        core_verification = {
            "openSafety": open_safety,
            "bytePreservation": member_diff,
        }

    real_hancom = _not_produced("not-requested")
    if render_verifier is not None and (require or output_bytes is not None):
        snapshot_cleanup_failed = False
        try:
            if output_bytes is None:
                raise FileNotFoundError("verification output is unavailable")
            workspace = WorkspaceResolver.from_environment()
            snapshot_token = secrets.token_hex(16)
            output_render_snapshot = (
                workspace.primary_root
                / f".hwpx-verify-{snapshot_token}-output.hwpx"
            )
            source_render_snapshot = (
                workspace.primary_root
                / f".hwpx-verify-{snapshot_token}-source.hwpx"
            )
            snapshot_publications: list[WorkspaceOutputGuard] = []
            try:
                for snapshot_path, snapshot_bytes in (
                    (output_render_snapshot, output_bytes),
                    (source_render_snapshot, source_bytes),
                ):
                    snapshot_guard = workspace.capture_output(
                        snapshot_path,
                        create_parents=False,
                    )
                    if snapshot_guard.target_existed:
                        raise RuntimeError("verification snapshot name collision")
                    snapshot_publications.append(
                        workspace.atomic_publish_bytes(
                            snapshot_guard,
                            snapshot_bytes,
                            mode=0o400,
                        )
                    )
                real_hancom = render_verifier(
                    str(output_render_snapshot),
                    str(source_render_snapshot),
                    require,
                )
            finally:
                for publication in reversed(snapshot_publications):
                    try:
                        workspace.remove_output(publication)
                    except (OSError, RuntimeError):
                        snapshot_cleanup_failed = True
                        # A verifier may chmod or rewrite the same inode. It is
                        # still our snapshot, so recapture that exact identity
                        # and remove it. Never delete a replacement inode.
                        try:
                            current = workspace.capture_output(
                                publication.path,
                                create_parents=False,
                            )
                            if (
                                current.target_existed
                                and current.target_device
                                == publication.target_device
                                and current.target_inode
                                == publication.target_inode
                            ):
                                workspace.remove_output(current)
                        except (OSError, RuntimeError):
                            pass
            if snapshot_cleanup_failed:
                real_hancom = {
                    "ok": False,
                    "status": "failed",
                    "renderChecked": False,
                    "errorCode": "verification_snapshot_cleanup_failed",
                }
        except Exception as exc:
            real_hancom = (
                {
                    "ok": False,
                    "status": "failed",
                    "renderChecked": False,
                    "errorCode": "verification_snapshot_cleanup_failed",
                }
                if snapshot_cleanup_failed
                else {
                    "ok": False if require else None,
                    "status": "failed" if require else "unavailable",
                    "renderChecked": False,
                    "errorCode": type(exc).__name__,
                }
            )
    if (
        not require
        and real_hancom.get("renderChecked") is not True
        and real_hancom.get("status") != "failed"
    ):
        # Optional visual verification is advisory. A fully installed visual
        # stack can report ``ok=false`` when the external Hancom oracle itself
        # is unavailable, while a base install raises and reaches the explicit
        # unavailable branch above. Normalize both environments to the same
        # honest unverified state; only observed render failures or internal
        # snapshot-cleanup failures may fail structural verification.
        real_hancom = {
            **real_hancom,
            "ok": None,
            "status": "unavailable",
            "renderChecked": False,
        }
    core_verification["realHancom"] = real_hancom
    values_ok = bool(checks) and all(bool(item.get("ok")) for item in checks)
    render_observed = real_hancom.get("renderChecked") is True
    render_failed = bool(
        (render_observed and real_hancom.get("ok") is False)
        or real_hancom.get("status") == "failed"
    )
    render_ok = (
        bool(real_hancom.get("ok"))
        if render_observed
        else not require and not render_failed
    )
    output_revision = (
        _revision_bytes(output_bytes) if output_bytes is not None else None
    )
    revision_ok = (
        output_revision == expected_output_revision
        if expected_output_revision is not None
        else True
    )
    source_exists, source_after = _snapshot_path(source)
    if not source_exists:
        source_after = None
    source_report = _source_preservation_snapshot(
        source,
        expected_revision=compiled["inputRevision"],
        before=source_bytes,
        after=source_after,
    )
    ok = bool(
        source_report["ok"]
        and output_bytes is not None
        and open_safety.get("ok")
        and member_diff.get("ok")
        and values_ok
        and render_ok
        and revision_ok
    )
    receipt = _unified_receipt(
        phase="verify",
        ok=ok,
        source=source,
        output=output,
        dry_run=False,
        rolled_back=False,
        source_preservation=source_report,
        plan=compiled,
        core_verification=core_verification,
        member_diff=member_diff,
        value_checks=checks,
        output_revision=output_revision,
        output_exists=output_bytes is not None,
        expected_output_revision=expected_output_revision,
        error=(
            None
            if ok
            else {
                "code": "verification_failed",
                "recoverability": "retryable",
                "target": "batch.output.filename",
            }
        ),
    )
    observed_source = _capture_optional_path_snapshot(source)
    observed_output = _capture_optional_path_snapshot(output)
    source_matches = _snapshots_match(observed_source, source_snapshot)
    output_matches = _snapshots_match(observed_output, output_snapshot_before)
    if source_matches and output_matches:
        return receipt

    output_exists, current_output = _snapshot_path(output)
    source_exists, current_source = _snapshot_path(source)
    source_report = _source_preservation_snapshot(
        source,
        expected_revision=compiled["inputRevision"],
        before=source_bytes,
        after=current_source if source_exists else None,
    )
    if not source_matches:
        source_report.update(
            {
                "ok": False,
                "preserved": False,
                "identityPreserved": False,
            }
        )
    changed_target = "batch.input.filename" if not source_matches else "batch.output.filename"
    changed_code = "source_revision_mismatch" if not source_matches else "materialized_output_changed"
    unavailable = _not_produced("verification-input-changed")
    failure_verification = copy.deepcopy(core_verification)
    failure_verification.update(
        {
            "package": unavailable,
            "reopen": unavailable,
            "openSafety": unavailable,
            "bytePreservation": unavailable,
            "semanticDiff": unavailable,
            "realHancom": _not_produced("verification-input-changed"),
        }
    )
    return _unified_receipt(
        phase="verify",
        ok=False,
        source=source,
        output=output,
        dry_run=False,
        rolled_back=False,
        source_preservation=source_report,
        plan=compiled,
        core_verification=failure_verification,
        member_diff=unavailable,
        value_checks=[],
        output_revision=(
            _revision_bytes(current_output) if current_output is not None else None
        ),
        output_exists=output_exists,
        expected_output_revision=expected_output_revision,
        error={
            "code": changed_code,
            "recoverability": "retryable",
            "target": changed_target,
        },
    )


def _specialized_allowed_members(source_bytes: bytes) -> set[str]:
    """Allow only document body/header XML parts for specialized text edits."""

    with HwpxAgentDocument.open(source_bytes) as document:
        members = {str(section.part_name) for section in document.document.sections}
        members.update(
            str(header.part_name)
            for header in getattr(document.document.parts, "headers", ())
        )
    if not members:
        raise ValueError("specialized form operation has no editable document members")
    return members


def attach_common_form_receipt(
    result: dict[str, Any],
    *,
    operation: str,
    source: Path,
    output: Path,
    source_before: bytes,
    source_after: bytes | None = None,
    output_exists: bool | None = None,
    output_bytes: bytes | None = None,
    output_existed_before: bool | None = None,
    output_before: bytes | None = None,
    output_mode_before: int | None = None,
    output_mode_after: int | None = None,
    source_snapshot_preserved: bool | None = None,
    output_snapshot_preserved: bool | None = None,
    allowed_changed_members: set[str] | None = None,
    dry_run: bool = False,
    rolled_back: bool = False,
    rollback_required: bool = False,
) -> dict[str, Any]:
    """Attach snapshot-bound evidence to a specialized mutation result."""

    payload = copy.deepcopy(result)
    payload.pop("_workspacePublication", None)
    source_is_output = source.resolve(strict=False) == output.resolve(strict=False)
    if source_after is None:
        source_exists, source_after = _snapshot_path(source)
        if not source_exists:
            source_after = None
    if output_exists is None:
        output_exists, output_bytes = _snapshot_path(output)
    if allowed_changed_members is None:
        allowed_changed_members = _specialized_allowed_members(source_before)
    target_bytes = None if dry_run else output_bytes

    if source_is_output and not dry_run:
        source_report = {
            "ok": None,
            "filename": str(source),
            "expectedRevision": _revision_bytes(source_before),
            "actualRevision": (
                _revision_bytes(source_after) if source_after is not None else None
            ),
            "preserved": None,
            "status": "in-place-specialized-operation",
        }
    else:
        source_report = _source_preservation_snapshot(
            source,
            expected_revision=_revision_bytes(source_before),
            before=source_before,
            after=source_after,
        )
        if source_snapshot_preserved is False:
            source_report.update(
                {
                    "ok": False,
                    "preserved": False,
                    "status": "source-identity-or-mode-changed",
                }
            )

    if dry_run:
        member_diff = _not_produced("dry-run")
    elif target_bytes is not None:
        member_diff = _member_diff(
            source_before,
            target_bytes,
            allowed_changed_members=allowed_changed_members,
        )
        if member_diff.get("diffComputed"):
            declared = payload.get("changedParts")
            declared_members = (
                sorted(str(item) for item in declared)
                if isinstance(declared, list)
                and all(isinstance(item, str) for item in declared)
                else None
            )
            observed_members = sorted(
                str(item) for item in member_diff.get("changedMembers", [])
            )
            member_diff["declaredChangedMembers"] = declared_members
            member_diff["declaredMatchesObserved"] = (
                declared_members == observed_members
                if declared_members is not None
                else False
            )
            # Correct legacy result payloads from independent final-byte evidence.
            payload["changedParts"] = observed_members
    else:
        member_diff = _not_produced("output-unavailable")

    # Normalize every public specialized response, including early/explicit
    # failures, to the same typed top-level envelope advertised by FastMCP.
    payload.setdefault("dryRun", dry_run)
    payload.setdefault("outputPath", str(output))
    payload.setdefault("changedParts", [])
    if not dry_run and member_diff.get("diffComputed") is not True:
        payload["changedParts"] = []
    payload.setdefault(
        "byteIdentical",
        bool(target_bytes is not None and target_bytes == source_before),
    )
    payload.setdefault("skipped", [])
    if not dry_run:
        payload["byteIdentical"] = bool(
            target_bytes is not None and target_bytes == source_before
        )
    if operation == "apply_table_ops":
        payload.setdefault("applied", [])
        payload.setdefault("zipMethod", "unavailable")
        payload.setdefault("transcript", None)
    elif operation == "apply_body_ops":
        payload.setdefault("transcript", [])
    elif operation == "apply_evalplan_fill":
        payload.setdefault("transcript", [])
        payload.setdefault("expectedSkeleton", None)
        payload.setdefault("contentReport", {})
        payload.setdefault("rubricNeedsReview", 0)
        payload.setdefault("needsReviewNotes", [])

    open_safety = (
        _not_produced("dry-run-candidate-not-materialized")
        if dry_run
        else _open_safety_snapshot(target_bytes)
        if target_bytes is not None
        else _not_produced("output-unavailable")
    )
    verification = copy.deepcopy(payload.get("verificationReport") or {})
    verification.update(
        {
            "openSafety": open_safety,
            "package": copy.deepcopy(
                open_safety.get("validatePackage") or _not_produced()
            ),
            "reopen": copy.deepcopy(open_safety.get("reopen") or _not_produced()),
            "bytePreservation": member_diff,
        }
    )
    if dry_run:
        verification["candidateStatus"] = "not-materialized"
    payload["openSafety"] = copy.deepcopy(open_safety)
    payload["verificationReport"] = copy.deepcopy(verification)
    explicit_ok = payload.get("ok")
    source_ok = True if source_is_output else source_report.get("ok") is True
    evidence_ok = bool(
        dry_run
        or (
            target_bytes is not None
            and open_safety.get("ok") is True
            and member_diff.get("ok") is True
        )
    )
    receipt_ok = bool(
        not rolled_back and explicit_ok is not False and source_ok and evidence_ok
    )
    domain = {
        "ok": receipt_ok,
        "operation": operation,
        "status": (
            "rolled-back"
            if rolled_back
            else "specialized-semantics-preserved"
            if receipt_ok
            else "specialized-verification-failed"
        ),
    }
    receipt = _unified_receipt(
        phase="domain-apply",
        ok=receipt_ok,
        source=source,
        output=output,
        dry_run=dry_run,
        rolled_back=rolled_back,
        source_preservation=source_report,
        core_verification=verification,
        member_diff=member_diff,
        output_revision=(
            _revision_bytes(output_bytes) if output_bytes is not None else None
        ),
        output_exists=bool(output_exists),
        error=payload.get("error"),
        domain=domain,
    )
    receipt["operation"] = operation
    if output_existed_before is not None:
        rollback_required = bool(rollback_required or rolled_back or dry_run)
        rollback_preserved = bool(
            output_snapshot_preserved is not False
            and
            output_exists == output_existed_before
            and (
                not output_existed_before
                or (
                    output_bytes == output_before
                    and output_mode_after == output_mode_before
                )
            )
        )
        receipt["rollbackPreservation"] = {
            "required": rollback_required,
            "outputExistedBefore": output_existed_before,
            "preserved": rollback_preserved if rollback_required else None,
        }
    receipt = validate_form_verification_receipt(receipt)
    payload["ok"] = receipt_ok
    payload["rolledBack"] = rolled_back
    if not receipt["committed"]:
        payload["documentRevision"] = None
    payload["verificationReceipt"] = receipt
    payload.setdefault("compatibility", {})
    payload["compatibility"].update(
        {
            "status": domain["status"],
            "canonicalReceipt": FORM_VERIFICATION_RECEIPT_SCHEMA,
        }
    )
    return payload


def run_specialized_form_operation(
    *,
    operation: str,
    source: Path,
    output: Path,
    dry_run: bool,
    execute: Callable[[], dict[str, Any]] | None = None,
    execute_with_guard: Callable[
        [
            WorkspaceOutputGuard | WorkspaceMissingParentGuard,
            Callable[[WorkspaceOutputGuard], None],
        ],
        dict[str, Any],
    ]
    | None = None,
) -> dict[str, Any]:
    """Serialize specialized verification and rollback with canonical writes."""

    if (execute is None) == (execute_with_guard is None):
        raise ValueError("provide exactly one specialized execution callback")
    with _IDEMPOTENCY_LOCK:
        same_path = source.resolve(strict=False) == output.resolve(strict=False)
        source_before = _capture_path_snapshot(source)
        if not source_before.existed or source_before.data is None:
            raise FileNotFoundError(source)
        output_before = (
            source_before
            if same_path
            else _capture_optional_path_snapshot(output)
        )
        return _run_specialized_form_operation_locked(
            operation=operation,
            source=source,
            output=output,
            source_before=source_before,
            output_before=output_before,
            dry_run=dry_run,
            execute=execute,
            execute_with_guard=execute_with_guard,
        )


def _run_specialized_form_operation_locked(
    *,
    operation: str,
    source: Path,
    output: Path,
    source_before: _PathSnapshot,
    output_before: _PathSnapshot,
    dry_run: bool,
    execute: Callable[[], dict[str, Any]] | None,
    execute_with_guard: Callable[
        [
            WorkspaceOutputGuard | WorkspaceMissingParentGuard,
            Callable[[WorkspaceOutputGuard], None],
        ],
        dict[str, Any],
    ]
    | None,
) -> dict[str, Any]:
    """Execute a specialized write and roll back only its exact publication."""

    same_path = source.resolve(strict=False) == output.resolve(strict=False)
    source_bytes = source_before.data
    if source_bytes is None:  # pragma: no cover - required source invariant
        raise FileNotFoundError(source)
    allowed_members = _specialized_allowed_members(source_bytes)
    workspace = WorkspaceResolver.from_environment()
    failure_preimage = _FailurePreimagePreserver(
        workspace=workspace,
        output=output_before.path,
        data=output_before.data if output_before.existed else None,
        mode=output_before.mode,
    )
    rollback_attempted = False

    def snapshots() -> tuple[_PathSnapshot, _PathSnapshot]:
        source_snapshot = _capture_path_snapshot(source)
        output_snapshot = (
            source_snapshot
            if same_path
            else _capture_optional_path_snapshot(output)
        )
        return source_snapshot, output_snapshot

    def restore_publication(publication: WorkspaceOutputGuard | None) -> bool:
        nonlocal rollback_attempted
        failure_preimage.preserve()
        if publication is None:
            return False
        rollback_attempted = True
        try:
            if output_before.existed:
                if output_before.data is None:  # pragma: no cover - invariant
                    return False
                workspace.atomic_publish_bytes(
                    publication,
                    output_before.data,
                    mode=output_before.mode,
                )
            else:
                workspace.remove_output(publication)
        except (OSError, RuntimeError):
            return False
        if not output_before.existed:
            return workspace.cleanup_owned_parent_directories(publication)
        return True

    def attach(
        raw: dict[str, Any],
        source_snapshot: _PathSnapshot,
        output_snapshot: _PathSnapshot,
        *,
        rolled_back: bool = False,
    ) -> dict[str, Any]:
        source_preserved = (
            True
            if same_path and not dry_run
            else _snapshots_match(source_snapshot, source_before)
        )
        return attach_common_form_receipt(
            raw,
            operation=operation,
            source=source,
            output=output,
            source_before=source_bytes,
            source_after=source_snapshot.data,
            output_exists=output_snapshot.existed,
            output_bytes=output_snapshot.data,
            output_existed_before=output_before.existed,
            output_before=output_before.data,
            output_mode_before=output_before.mode,
            output_mode_after=output_snapshot.mode,
            source_snapshot_preserved=source_preserved,
            output_snapshot_preserved=_snapshots_match(
                output_snapshot,
                output_before,
                identity=not rolled_back,
            ),
            allowed_changed_members=allowed_members,
            dry_run=dry_run,
            rolled_back=rolled_back,
            rollback_required=rollback_attempted,
        )

    recorded_publication: WorkspaceOutputGuard | None = None

    def record_publication(publication: WorkspaceOutputGuard) -> None:
        nonlocal recorded_publication
        if publication.path != output_before.path:
            raise RuntimeError("specialized writer published an unexpected output path")
        if recorded_publication is not None:
            raise RuntimeError("specialized writer published more than one candidate")
        recorded_publication = publication

    try:
        output_precondition = output_before.guard or output_before.missing_guard
        if output_precondition is None:  # pragma: no cover - snapshot invariant
            raise RuntimeError("specialized output precondition is unavailable")
        if not dry_run:
            failure_preimage.reserve()
        result = (
            execute_with_guard(output_precondition, record_publication)
            if execute_with_guard is not None
            else execute()
            if execute is not None
            else None
        )
    except BaseException:
        failure_preimage.preserve()
        restore_publication(recorded_publication)
        raise
    if not isinstance(result, dict):
        failure_preimage.preserve()
        restore_publication(recorded_publication)
        raise TypeError(f"{operation} returned a non-object result")

    publication_value = result.pop("_workspacePublication", None)
    publication = recorded_publication
    if publication is None:
        publication = (
            publication_value
            if isinstance(publication_value, WorkspaceOutputGuard)
            and publication_value.path == output_before.path
            else None
        )
    try:
        candidate_source, candidate_output = snapshots()
    except BaseException:
        failure_preimage.preserve()
        restore_publication(publication)
        raise
    source_preserved = _snapshots_match(candidate_source, source_before)
    output_preserved = _snapshots_match(candidate_output, output_before)
    candidate_owned = _snapshot_matches_publication(candidate_output, publication)
    source_mutated = (dry_run or not same_path) and not source_preserved
    dry_run_mutated = dry_run and not (source_preserved and output_preserved)
    unowned_output = bool(
        not dry_run
        and not output_preserved
        and not candidate_owned
    )
    explicit_failure = result.get("ok") is False

    if explicit_failure or source_mutated or dry_run_mutated or unowned_output:
        failure_preimage.preserve()
        restored = restore_publication(publication if candidate_owned else None)
        final_source, final_output = snapshots()
        failed = copy.deepcopy(result)
        failed["ok"] = False
        if dry_run_mutated:
            failed["error"] = {
                "code": "dry_run_mutated",
                "recoverability": "terminal",
                "target": "output",
            }
        elif source_mutated:
            failed["error"] = {
                "code": "source_mutated",
                "recoverability": "retryable",
                "target": "source",
            }
        elif unowned_output:
            failed["error"] = {
                "code": "specialized_output_changed",
                "recoverability": "retryable",
                "target": "output",
            }
        rolled_back = bool(
            restored
            and _snapshots_match(final_output, output_before, identity=False)
        )
        return attach(
            failed,
            final_source,
            final_output,
            rolled_back=rolled_back,
        )

    try:
        attached = attach(result, candidate_source, candidate_output)
    except BaseException:
        failure_preimage.preserve()
        restore_publication(publication if candidate_owned else None)
        raise

    try:
        final_source, final_output = snapshots()
    except BaseException:
        failure_preimage.preserve()
        restore_publication(publication if candidate_owned else None)
        raise
    source_matches = (
        _snapshot_matches_publication(final_source, publication)
        if same_path and publication is not None
        else _snapshots_match(final_source, source_before)
    )
    output_matches = (
        _snapshot_matches_publication(final_output, publication)
        if publication is not None
        else _snapshots_match(final_output, output_before)
    )
    if not source_matches or not output_matches:
        failure_preimage.preserve()
        restored = restore_publication(
            publication
            if output_matches and publication is not None
            else None
        )
        final_source, final_output = snapshots()
        failed = copy.deepcopy(result)
        failed["ok"] = False
        failed["error"] = {
            "code": (
                "source_mutated" if not source_matches else "specialized_output_changed"
            ),
            "recoverability": "retryable",
            "target": "source" if not source_matches else "output",
        }
        rolled_back = bool(
            restored
            and _snapshots_match(final_output, output_before, identity=False)
        )
        return attach(
            failed,
            final_source,
            final_output,
            rolled_back=rolled_back,
        )

    if not dry_run and not attached["verificationReceipt"]["ok"]:
        failure_preimage.preserve()
        restored = restore_publication(publication if output_matches else None)
        final_source, final_output = snapshots()
        failed = copy.deepcopy(result)
        failed["ok"] = False
        failed["error"] = {
            "code": (
                "specialized_verification_failed"
                if restored
                else "specialized_output_changed"
            ),
            "recoverability": "terminal" if restored else "retryable",
            "target": "output",
        }
        rolled_back = bool(
            restored
            and _snapshots_match(final_output, output_before, identity=False)
        )
        return attach(
            failed,
            final_source,
            final_output,
            rolled_back=rolled_back,
        )
    if dry_run:
        return attached

    cleanup_ok = failure_preimage.cleanup_after_success()
    try:
        final_source, final_output = snapshots()
    except BaseException:
        failure_preimage.preserve()
        restore_publication(publication if output_matches else None)
        raise
    source_matches = (
        _snapshot_matches_publication(final_source, publication)
        if same_path and publication is not None
        else _snapshots_match(final_source, source_before)
    )
    output_matches = (
        _snapshot_matches_publication(final_output, publication)
        if publication is not None
        else _snapshots_match(final_output, output_before)
    )
    if cleanup_ok and source_matches and output_matches:
        return attached

    failure_preimage.preserve()
    restored = restore_publication(
        publication if output_matches and publication is not None else None
    )
    final_source, final_output = snapshots()
    failed = copy.deepcopy(result)
    failed["ok"] = False
    failed["error"] = {
        "code": (
            "source_mutated" if not source_matches else "specialized_output_changed"
        ),
        "recoverability": "retryable",
        "target": "source" if not source_matches else "output",
    }
    rolled_back = bool(
        restored
        and _snapshots_match(final_output, output_before, identity=False)
    )
    return attach(
        failed,
        final_source,
        final_output,
        rolled_back=rolled_back,
    )


__all__ = [
    "BodyAnchorTarget",
    "CanonicalPathTarget",
    "LabelCellTarget",
    "MixedFormApplyInput",
    "MixedFormCompiledPlanInput",
    "MixedFormOperation",
    "MixedFormPlanInput",
    "MixedFormResolution",
    "MixedFormTarget",
    "NativeFieldTarget",
    "FORM_VERIFICATION_RECEIPT_SCHEMA",
    "FormVerificationReceipt",
    "analyze_mixed_form_plan",
    "apply_canonical_mixed_form_plan",
    "attach_common_form_receipt",
    "run_specialized_form_operation",
    "validate_form_verification_receipt",
    "verify_canonical_mixed_form_plan",
]
