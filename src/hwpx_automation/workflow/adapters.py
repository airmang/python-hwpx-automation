# SPDX-License-Identifier: Apache-2.0
"""Typed family adapters for the high-level workflow service."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from hwpx_automation.document_state import document_revision

from .models import WorkFamily, WorkflowRecord
from .policy import ActionRequest, PolicyViolation


class AdapterAbstention(RuntimeError):
    """The typed request is unsupported or incomplete and needs human review."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class WorkflowAdapter:
    family: WorkFamily

    def recon_action(self, record: WorkflowRecord) -> ActionRequest:
        raise NotImplementedError

    def execution_action(self, record: WorkflowRecord) -> ActionRequest | None:
        raise NotImplementedError

    def prepare_execution(self, record: WorkflowRecord) -> None:
        return None

    def verification_actions(self, record: WorkflowRecord) -> tuple[ActionRequest, ...]:
        """Return the mandatory, read-only quality gates for this family."""

        return ()

    def execution_evidence_ok(self, record: WorkflowRecord, result: Any) -> bool:
        return isinstance(result, Mapping) and result.get("ok") is not False

    def verification_ok(self, record: WorkflowRecord, results: tuple[Any, ...]) -> bool:
        """Fail closed when a mandatory verifier is absent or explicitly fails."""

        actions = self.verification_actions(record)
        if len(results) != len(actions):
            return False
        for result in results:
            if not isinstance(result, Mapping):
                return False
            if result.get("ok") is False or result.get("pass") is False:
                return False
        return True

    def recon_ok(self, result: Any) -> bool:
        return not isinstance(result, Mapping) or result.get("ok", True) is not False


class ReadExtractAdapter(WorkflowAdapter):
    _TOOLS = {
        "text": "get_document_text",
        "info": "get_document_info",
        "outline": "get_document_outline",
        "map": "get_document_map",
        # The workflow reads a local source path, so it needs the filename-based
        # exporters. hwpx_to_markdown/hwpx_extract_json take a base64 payload or a
        # URL and reject ``filename`` (issue #197).
        "markdown": "document_to_markdown",
        "json": "document_extract_json",
    }

    def recon_action(self, record: WorkflowRecord) -> ActionRequest:
        if not record.work_order.source_path:
            raise AdapterAbstention("SOURCE_REQUIRED", "read/extract requires a source document")
        operation = str(record.work_order.parameters.get("operation", "info"))
        tool = self._TOOLS.get(operation)
        if tool is None:
            raise AdapterAbstention("UNSUPPORTED_READ_OPERATION", f"unsupported read operation: {operation}")
        arguments = dict(record.work_order.parameters.get("arguments") or {})
        arguments.setdefault("filename", record.work_order.source_path)
        return ActionRequest(tool_name=tool, arguments=arguments)

    def execution_action(self, record: WorkflowRecord) -> ActionRequest | None:
        return None


class TransactionalEditAdapter(WorkflowAdapter):
    def recon_action(self, record: WorkflowRecord) -> ActionRequest:
        return ActionRequest(tool_name="get_document_info", arguments={"filename": record.work_order.source_path})

    def prepare_execution(self, record: WorkflowRecord) -> None:
        source = Path(record.work_order.source_path or "")
        output = Path(record.work_order.output_path or "")
        if output.exists():
            if document_revision(output) != record.work_order.expected_revision:
                raise PolicyViolation("OUTPUT_ALREADY_EXISTS", "workflow output exists with unrelated content")
            return
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)

    def execution_action(self, record: WorkflowRecord) -> ActionRequest:
        operations = record.work_order.parameters.get("operations")
        if not isinstance(operations, list):
            raise AdapterAbstention("OPERATIONS_REQUIRED", "transactional edit requires an operations array")
        output = record.work_order.output_path
        return ActionRequest(
            tool_name="apply_edits",
            arguments={
                "filename": output,
                "operations": operations,
                "dry_run": False,
                "expected_revision": record.work_order.expected_revision,
                "idempotency_key": f"{record.work_order.idempotency_key}:apply",
            },
            destructive=True,
        )

    def verification_actions(self, record: WorkflowRecord) -> tuple[ActionRequest, ...]:
        return (
            ActionRequest(
                tool_name="doc_diff",
                arguments={
                    "old_filename": record.work_order.source_path,
                    "new_filename": record.work_order.output_path,
                },
            ),
        )

    def execution_evidence_ok(self, record: WorkflowRecord, result: Any) -> bool:
        return (
            super().execution_evidence_ok(record, result)
            and isinstance(result.get("semanticDiff"), Mapping)
        )


class KnownTemplateFillAdapter(WorkflowAdapter):
    @staticmethod
    def _coordinate_operations(record: WorkflowRecord) -> list[dict[str, Any]] | None:
        if record.work_order.parameters.get("mode") != "coordinate_table":
            return None
        raw = record.work_order.parameters.get("operations")
        if not isinstance(raw, list) or not raw:
            raise AdapterAbstention(
                "FROZEN_FILL_OPERATIONS_REQUIRED",
                "coordinate-table fill requires frozen fill_cell operations",
            )
        operations: list[dict[str, Any]] = []
        coordinates: set[tuple[int, int, int]] = set()
        for value in raw:
            if not isinstance(value, Mapping) or set(value) != {
                "op",
                "table_index",
                "row",
                "col",
                "text",
            }:
                raise AdapterAbstention(
                    "FROZEN_FILL_OPERATIONS_REQUIRED",
                    "coordinate-table fill accepts exact fill_cell operations only",
                )
            operation = dict(value)
            indices = tuple(operation[key] for key in ("table_index", "row", "col"))
            if (
                operation["op"] != "fill_cell"
                or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in indices)
                or not isinstance(operation["text"], str)
                or not operation["text"]
                or len(operation["text"]) > 4_096
                or indices in coordinates
            ):
                raise AdapterAbstention(
                    "FROZEN_FILL_OPERATIONS_REQUIRED",
                    "coordinate-table fill operation is invalid",
                )
            coordinates.add(indices)
            operations.append(operation)
        return operations

    def _required(self, record: WorkflowRecord) -> tuple[Any, dict[str, Any]]:
        baseline = record.work_order.parameters.get("baseline")
        content = record.work_order.parameters.get("content")
        if baseline is None or not isinstance(content, dict):
            raise AdapterAbstention("TEMPLATE_INPUT_REQUIRED", "baseline and typed content are required")
        return baseline, content

    def recon_action(self, record: WorkflowRecord) -> ActionRequest:
        if self._coordinate_operations(record) is not None:
            return ActionRequest(
                tool_name="scan_form_guidance",
                arguments={"filename": record.work_order.source_path},
            )
        baseline, content = self._required(record)
        return ActionRequest(
            tool_name="analyze_template_formfit",
            arguments={
                "source_filename": record.work_order.source_path,
                "baseline": baseline,
                "content": content,
                "destination_filename": record.work_order.output_path,
            },
        )

    def execution_action(self, record: WorkflowRecord) -> ActionRequest:
        coordinate_operations = self._coordinate_operations(record)
        if coordinate_operations is not None:
            return ActionRequest(
                tool_name="apply_table_ops",
                arguments={
                    "filename": record.work_order.source_path,
                    "ops": coordinate_operations,
                    "output": record.work_order.output_path,
                    "dry_run": False,
                    "render_check": "off",
                },
                destructive=True,
            )
        baseline, content = self._required(record)
        return ActionRequest(
            tool_name="apply_template_formfit",
            arguments={
                "source_filename": record.work_order.source_path,
                "baseline": baseline,
                "content": content,
                "destination_filename": record.work_order.output_path,
                "confirm": True,
            },
            destructive=True,
        )

    def verification_actions(self, record: WorkflowRecord) -> tuple[ActionRequest, ...]:
        return (
            ActionRequest(
                tool_name="inspect_fill_residue",
                arguments={
                    "filename": record.work_order.output_path,
                    "blank_path": record.work_order.source_path,
                },
            ),
            ActionRequest(
                tool_name="verify_form_fill",
                arguments={
                    "filename": record.work_order.output_path,
                    "before_path": record.work_order.source_path,
                    "require": False,
                },
            ),
        )

    def verification_ok(self, record: WorkflowRecord, results: tuple[Any, ...]) -> bool:
        return len(results) == 2 and all(
            isinstance(result, Mapping) and result.get("ok") is True for result in results
        )


class UnknownFormFillAdapter(WorkflowAdapter):
    def recon_action(self, record: WorkflowRecord) -> ActionRequest:
        return ActionRequest(tool_name="scan_form_guidance", arguments={"filename": record.work_order.source_path})

    def execution_action(self, record: WorkflowRecord) -> ActionRequest:
        operation_kind = str(record.work_order.parameters.get("operationKind", "table"))
        tools = {"table": "apply_table_ops", "body": "apply_body_ops"}
        tool = tools.get(operation_kind)
        operations = record.work_order.parameters.get("operations")
        if tool is None or not isinstance(operations, list):
            raise AdapterAbstention(
                "FORM_OPERATIONS_REQUIRED",
                "unknown-form fill requires operationKind=table|body and an operations array",
            )
        arguments = {
            "filename": record.work_order.source_path,
            "ops": operations,
            "output": record.work_order.output_path,
            "dry_run": False,
        }
        if tool == "apply_table_ops":
            arguments["render_check"] = "off"
        return ActionRequest(tool_name=tool, arguments=arguments, destructive=True)

    def verification_actions(self, record: WorkflowRecord) -> tuple[ActionRequest, ...]:
        return (
            ActionRequest(
                tool_name="inspect_fill_residue",
                arguments={
                    "filename": record.work_order.output_path,
                    "blank_path": record.work_order.source_path,
                },
            ),
            ActionRequest(
                tool_name="verify_form_fill",
                arguments={
                    "filename": record.work_order.output_path,
                    "before_path": record.work_order.source_path,
                    "require": False,
                },
            ),
        )

    def verification_ok(self, record: WorkflowRecord, results: tuple[Any, ...]) -> bool:
        return len(results) == 2 and all(
            isinstance(result, Mapping) and result.get("ok") is True for result in results
        )


class StructuralTableEditAdapter(WorkflowAdapter):
    """Apply one frozen row clone plus coordinate fills through ToolSpec."""

    @staticmethod
    def _operations(record: WorkflowRecord) -> list[dict[str, Any]]:
        raw = record.work_order.parameters.get("operations")
        if not isinstance(raw, list) or len(raw) < 2:
            raise AdapterAbstention(
                "STRUCTURAL_OPERATIONS_REQUIRED",
                "structural table edit requires a row clone and frozen fills",
            )
        operations = [dict(value) for value in raw if isinstance(value, Mapping)]
        if len(operations) != len(raw):
            raise AdapterAbstention(
                "STRUCTURAL_OPERATIONS_REQUIRED", "structural operations are invalid"
            )
        clone = operations[0]
        if (
            set(clone) != {"op", "table_index", "ref_row", "count"}
            or clone.get("op") != "insert_row_by_clone"
            or clone.get("count") != 1
            or any(
                isinstance(clone.get(key), bool)
                or not isinstance(clone.get(key), int)
                or clone.get(key) < 0
                for key in ("table_index", "ref_row")
            )
        ):
            raise AdapterAbstention(
                "STRUCTURAL_OPERATIONS_REQUIRED", "row clone operation is invalid"
            )
        target_row = clone["ref_row"] + 1
        columns: set[int] = set()
        for fill in operations[1:]:
            if (
                set(fill) != {"op", "table_index", "row", "col", "text"}
                or fill.get("op") != "fill_cell"
                or fill.get("table_index") != clone["table_index"]
                or fill.get("row") != target_row
                or isinstance(fill.get("col"), bool)
                or not isinstance(fill.get("col"), int)
                or fill["col"] < 0
                or fill["col"] in columns
                or not isinstance(fill.get("text"), str)
                or not fill["text"]
                or len(fill["text"]) > 4_096
            ):
                raise AdapterAbstention(
                    "STRUCTURAL_OPERATIONS_REQUIRED",
                    "frozen structural fill operation is invalid",
                )
            columns.add(fill["col"])
        return operations

    def recon_action(self, record: WorkflowRecord) -> ActionRequest:
        self._operations(record)
        return ActionRequest(
            tool_name="scan_form_guidance",
            arguments={"filename": record.work_order.source_path},
        )

    def execution_action(self, record: WorkflowRecord) -> ActionRequest:
        return ActionRequest(
            tool_name="apply_table_ops",
            arguments={
                "filename": record.work_order.source_path,
                "ops": self._operations(record),
                "output": record.work_order.output_path,
                "dry_run": False,
                "render_check": "off",
            },
            destructive=True,
        )

    def verification_actions(self, record: WorkflowRecord) -> tuple[ActionRequest, ...]:
        return (
            ActionRequest(
                tool_name="doc_diff",
                arguments={
                    "old_filename": record.work_order.source_path,
                    "new_filename": record.work_order.output_path,
                },
            ),
        )


class TypedAuthoringAdapter(WorkflowAdapter):
    def _plan(self, record: WorkflowRecord) -> dict[str, Any]:
        plan = record.work_order.parameters.get("documentPlan")
        if not isinstance(plan, dict):
            raise AdapterAbstention("DOCUMENT_PLAN_REQUIRED", "typed authoring requires documentPlan")
        return plan

    def recon_action(self, record: WorkflowRecord) -> ActionRequest:
        return ActionRequest(tool_name="validate_document_plan", arguments={"document_plan": self._plan(record)})

    def recon_ok(self, result: Any) -> bool:
        return isinstance(result, Mapping) and bool(result.get("ok", result.get("can_create", False)))

    def prepare_execution(self, record: WorkflowRecord) -> None:
        output = Path(record.work_order.output_path or "")
        if output.exists():
            raise PolicyViolation("OUTPUT_ALREADY_EXISTS", "typed authoring will not overwrite an existing output")
        output.parent.mkdir(parents=True, exist_ok=True)

    def execution_action(self, record: WorkflowRecord) -> ActionRequest:
        return ActionRequest(
            tool_name="create_document_from_plan",
            arguments={
                "filename": record.work_order.output_path,
                "document_plan": self._plan(record),
                "verify_render": False,
            },
            destructive=True,
        )

    def verification_actions(self, record: WorkflowRecord) -> tuple[ActionRequest, ...]:
        actions = [
            ActionRequest(
                tool_name="inspect_document_authoring_quality",
                arguments={
                    "filename": record.work_order.output_path,
                    "document_plan": self._plan(record),
                    "quality_profile": record.work_order.parameters.get("qualityProfile"),
                },
            )
        ]
        metadata = self._plan(record).get("metadata")
        document_type = metadata.get("document_type") if isinstance(metadata, Mapping) else None
        if document_type in {"gongmun", "official", "official_document", "공문"}:
            actions.append(
                ActionRequest(
                    tool_name="inspect_official_document_style",
                    arguments={"filename": record.work_order.output_path},
                )
            )
        return tuple(actions)

    def verification_ok(self, record: WorkflowRecord, results: tuple[Any, ...]) -> bool:
        actions = self.verification_actions(record)
        if len(results) != len(actions) or not results:
            return False
        quality = results[0]
        if not isinstance(quality, Mapping) or quality.get("pass") is not True:
            return False
        return all(
            isinstance(result, Mapping) and result.get("ok") is True
            for result in results[1:]
        )


class MustAbstainAdapter(WorkflowAdapter):
    """A durable, no-tool family for an expected safety abstention."""

    def recon_action(self, record: WorkflowRecord) -> ActionRequest:
        raise AdapterAbstention(
            "UNSUPPORTED_INTENT",
            "must-abstain work orders never dispatch document tools",
        )

    def execution_action(self, record: WorkflowRecord) -> None:
        return None


ADAPTERS: dict[WorkFamily, WorkflowAdapter] = {
    WorkFamily.READ_EXTRACT: ReadExtractAdapter(WorkFamily.READ_EXTRACT),
    WorkFamily.TRANSACTIONAL_EDIT: TransactionalEditAdapter(WorkFamily.TRANSACTIONAL_EDIT),
    WorkFamily.KNOWN_TEMPLATE_FILL: KnownTemplateFillAdapter(WorkFamily.KNOWN_TEMPLATE_FILL),
    WorkFamily.UNKNOWN_FORM_FILL: UnknownFormFillAdapter(WorkFamily.UNKNOWN_FORM_FILL),
    WorkFamily.STRUCTURAL_TABLE_EDIT: StructuralTableEditAdapter(
        WorkFamily.STRUCTURAL_TABLE_EDIT
    ),
    WorkFamily.TYPED_AUTHORING: TypedAuthoringAdapter(WorkFamily.TYPED_AUTHORING),
    WorkFamily.MUST_ABSTAIN: MustAbstainAdapter(WorkFamily.MUST_ABSTAIN),
}


__all__ = ["ADAPTERS", "AdapterAbstention", "WorkflowAdapter"]
