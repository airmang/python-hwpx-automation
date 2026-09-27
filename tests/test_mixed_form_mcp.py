# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import io
import json
import os
import threading
import zipfile
from pathlib import Path
from typing import Any

import mcp.types as mcp_types
import pytest
from jsonschema import Draft202012Validator
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import TypeAdapter, ValidationError

import hwpx_automation.mixed_form as mixed_form_adapter
import hwpx_automation.server as server
import hwpx_automation.workspace as workspace_module
from hwpx import HwpxDocument, validate_editor_open_safety
from hwpx_automation.office.agent import (
    AgentContractError,
    HwpxAgentDocument,
    mixed_form_json_schemas,
)
from hwpx.oxml.namespaces import HP
from hwpx_automation.tool_contract import bound_tool_registry
from hwpx_automation.mixed_form import (
    FORM_VERIFICATION_RECEIPT_SCHEMA,
    FormVerificationReceipt,
    MixedFormCompiledPlanInput,
    MixedFormPlanInput,
)
from hwpx_automation.form_output_models import ApplyTableOpsOutput


def _append(parent: Any, tag: str, attrs: dict[str, str] | None = None) -> Any:
    child = parent.makeelement(tag, attrs or {})
    parent.append(child)
    return child


def _add_native_field(document: HwpxDocument, *, field_id: str = "240021") -> None:
    paragraph = document.add_paragraph("사업명: ")
    paragraph.element.set("id", str(int(field_id) - 1))
    begin_run = _append(paragraph.element, f"{HP}run", {"charPrIDRef": "0"})
    control = _append(
        begin_run, f"{HP}ctrl", {"type": "FORM", "id": "ctrl-" + field_id}
    )
    field = _append(
        control,
        f"{HP}fieldBegin",
        {
            "id": field_id,
            "fieldid": field_id,
            "type": "CLICK_HERE",
            "name": "사업명",
            "prompt": "사업명",
            "editable": "true",
        },
    )
    params = _append(field, f"{HP}parameters", {"count": "2"})
    _append(params, f"{HP}stringParam", {"name": "FieldName"}).text = "사업명"
    _append(params, f"{HP}stringParam", {"name": "Instruction"}).text = "사업명"
    value_run = _append(paragraph.element, f"{HP}run", {"charPrIDRef": "0"})
    _append(value_run, f"{HP}t").text = "여기를 누르세요"
    end_run = _append(paragraph.element, f"{HP}run", {"charPrIDRef": "0"})
    end_control = _append(end_run, f"{HP}ctrl")
    _append(end_control, f"{HP}fieldEnd", {"beginIDRef": field_id, "fieldid": field_id})
    paragraph.section.mark_dirty()


def _build_fixture(
    path: Path,
    *,
    split_body_anchor: bool = False,
    duplicate_body_anchor: bool = False,
    duplicate_native_field: bool = False,
) -> None:
    with HwpxDocument.new() as document:
        title = document.sections[0].paragraphs[0]
        title.element.set("id", "240010")
        title.text = "S-079 혼합 양식 기준 문서"
        _add_native_field(document)
        if duplicate_native_field:
            _add_native_field(document, field_id="240023")

        table_paragraph = document.add_paragraph("담당 부서")
        table_paragraph.element.set("id", "240030")
        table = table_paragraph.add_table(2, 2)
        table.element.set("id", "240031")
        table.rows[0].cells[0].text = "사업명"
        table.rows[0].cells[1].text = ""
        table.rows[1].cells[0].text = "담당 부서"
        table.rows[1].cells[1].text = ""

        body = document.add_paragraph("", include_run=False)
        body.element.set("id", "240040")
        if split_body_anchor:
            body.add_run("담당자: {{담")
            body.add_run("당자}}")
        else:
            body.add_run("담당자: {{담당자}}")
        if duplicate_body_anchor:
            document.add_paragraph("비상 담당자: {{담당자}}")

        purpose = document.add_paragraph("행사 목적: 여기를 입력하세요")
        purpose.element.set("id", "240050")
        document.save_to_path(path)


def _revision(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _failure_recoveries(output: Path) -> list[Path]:
    output_hash = hashlib.sha256(output.name.encode("utf-8")).hexdigest()[:12]
    return sorted(
        output.parent.glob(f".hwpx-mixed-form-recovery-{output_hash}-*"),
        key=lambda path: path.name,
    )


def _rewrite_package(
    data: bytes,
    *,
    replacements: dict[str, bytes] | None = None,
    renames: dict[str, str] | None = None,
) -> bytes:
    replacements = replacements or {}
    renames = renames or {}
    target = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(target, "w") as output,
    ):
        for info in source.infolist():
            payload = replacements.get(info.filename, source.read(info))
            copied = copy.copy(info)
            copied.filename = renames.get(info.filename, info.filename)
            output.writestr(copied, payload)
    return target.getvalue()


def _plan(
    source: Path,
    output: Path,
    *,
    dry_run: bool = False,
    key: str | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": "hwpx.mixed-form-plan/v1",
        "source": str(source),
        "output": str(output),
        "expectedRevision": _revision(source),
        "idempotencyKey": key,
        "dryRun": dry_run,
        "overwrite": True,
        "quality": "transparent",
        "verificationRequirements": [
            "package",
            "reopen",
            "openSafety",
            "semanticDiff",
            "bytePreservation",
        ],
        "operations": [
            {
                "operationId": "native-project",
                "target": {"kind": "nativeField", "fieldId": "240021"},
                "value": "AI 수업 나눔의 날",
            },
            {
                "operationId": "label-department",
                "target": {
                    "kind": "labelCell",
                    "sectionPath": "/section[1]",
                    "tableAnchor": "담당 부서",
                    "cellAnchor": {"label": "담당 부서", "direction": "right"},
                },
                "value": "교육연구부",
            },
            {
                "operationId": "canonical-purpose",
                "target": {
                    "kind": "canonicalPath",
                    "path": '/section[1]/paragraph[@id="240050"]',
                },
                "value": "행사 목적: 교내 AI 활용 사례 공유",
            },
            {
                "operationId": "body-owner",
                "target": {
                    "kind": "bodyAnchor",
                    "sectionPath": "/section[1]",
                    "anchor": "{{담당자}}",
                    "expectedCount": 1,
                },
                "value": "김서현",
            },
        ],
    }


def _single(plan: dict[str, Any], operation_id: str) -> dict[str, Any]:
    selected = copy.deepcopy(plan)
    selected["operations"] = [
        operation
        for operation in selected["operations"]
        if operation["operationId"] == operation_id
    ]
    return selected


def _compiled_plan_payload() -> dict[str, Any]:
    revision = "sha256:" + "0" * 64
    return {
        "schemaVersion": "hwpx.mixed-form-compiled-plan/v1",
        "inputRevision": revision,
        "requestHash": revision,
        "resolutions": [
            {
                "operationId": "operation-1",
                "locatorKind": "canonicalPath",
                "path": "/section[1]/paragraph[1]",
                "nodeKind": "paragraph",
                "stability": "positional",
                "section": 1,
                "tableIndex": None,
                "logicalRow": None,
                "logicalColumn": None,
                "physicalRow": None,
                "physicalColumn": None,
            }
        ],
        "batch": {
            "schemaVersion": "hwpx.agent-batch/v1",
            "input": {"filename": "source.hwpx"},
            "output": {"filename": "output.hwpx", "overwrite": True},
            "commands": [
                {
                    "commandId": "operation-1",
                    "op": "set",
                    "path": "/section[1]/paragraph[1]",
                    "properties": {"text": "value"},
                }
            ],
            "expectedRevision": revision,
            "idempotencyKey": None,
            "dryRun": True,
            "quality": None,
            "verificationRequirements": ["package"],
        },
        "planHash": revision,
    }


def test_tool_schemas_are_discriminated_and_closed() -> None:
    bound = bound_tool_registry().by_name()
    analyze = bound["analyze_form_fill"].input_schema
    apply = bound["apply_form_fill"].input_schema
    assert analyze["additionalProperties"] is False
    assert apply["additionalProperties"] is False
    assert len(analyze["oneOf"]) == 2
    assert len(apply["oneOf"]) == 2
    assert analyze["properties"]["plan"]["$ref"].endswith("MixedFormPlanInput")
    assert (
        apply["properties"]["plan"]["discriminator"]["propertyName"] == "schemaVersion"
    )
    assert set(apply["properties"]["plan"]["discriminator"]["mapping"]) == {
        "hwpx.mixed-form-plan/v1",
        "hwpx.mixed-form-compiled-plan/v1",
    }
    defs = apply["$defs"]
    for name in (
        "MixedFormPlanInput",
        "MixedFormCompiledPlanInput",
        "NativeFieldTarget",
        "LabelCellTarget",
        "CanonicalPathTarget",
        "BodyAnchorTarget",
    ):
        assert defs[name]["additionalProperties"] is False
    target = defs["MixedFormOperation"]["properties"]["target"]
    assert target["discriminator"]["propertyName"] == "kind"
    assert set(target["discriminator"]["mapping"]) == {
        "nativeField",
        "labelCell",
        "canonicalPath",
        "bodyAnchor",
    }
    assert len(defs["NativeFieldTarget"]["oneOf"]) == 2
    assert len(defs["LabelCellTarget"]["oneOf"]) == 2


def test_public_mixed_form_constraints_match_frozen_core_schema() -> None:
    core = mixed_form_json_schemas()
    core_plan = core["plan"]
    core_compiled = core["compiledPlan"]
    mcp_plan = MixedFormPlanInput.model_json_schema(by_alias=True)
    mcp_compiled = MixedFormCompiledPlanInput.model_json_schema(by_alias=True)

    plan_defs = mcp_plan["$defs"]

    def string_max_length(schema: dict[str, Any]) -> int:
        if "maxLength" in schema:
            return int(schema["maxLength"])
        return int(
            next(
                branch["maxLength"]
                for branch in schema["anyOf"]
                if branch.get("type") == "string"
            )
        )

    assert (
        string_max_length(plan_defs["NativeFieldTarget"]["properties"]["fieldId"])
        == 4096
    )
    assert (
        string_max_length(plan_defs["NativeFieldTarget"]["properties"]["name"]) == 4096
    )
    assert (
        string_max_length(plan_defs["LabelCellTarget"]["properties"]["tableAnchor"])
        == 4096
    )
    assert plan_defs["LabelCellAnchor"]["properties"]["label"]["maxLength"] == 4096
    assert plan_defs["BodyAnchorTarget"]["properties"]["anchor"]["maxLength"] == 4096
    assert plan_defs["MixedFormOperation"]["properties"]["value"]["maxLength"] == 4096
    core_targets = core_plan["properties"]["operations"]["items"]["properties"][
        "target"
    ]["oneOf"]
    assert {
        target["properties"][selector]["maxLength"]
        for target, selector in (
            (core_targets[0], "fieldId"),
            (core_targets[1], "name"),
            (core_targets[2], "tableAnchor"),
            (core_targets[5], "anchor"),
        )
    } == {4096}
    assert (
        core_plan["$defs"]["requiredCellAnchor"]["properties"]["label"]["maxLength"]
        == 4096
    )
    assert (
        core_plan["properties"]["operations"]["items"]["properties"]["value"][
            "maxLength"
        ]
        == 4096
    )

    assert mcp_plan["properties"]["verificationRequirements"]["uniqueItems"] is True
    assert core_plan["properties"]["verificationRequirements"]["uniqueItems"] is True
    compiled_batch = mcp_compiled["$defs"]["_CompiledBatch"]
    assert (
        compiled_batch["properties"]["verificationRequirements"]["uniqueItems"] is True
    )
    assert (
        core_compiled["properties"]["batch"]["properties"]["verificationRequirements"][
            "uniqueItems"
        ]
        is True
    )

    resolution = mcp_compiled["$defs"]["MixedFormResolution"]["properties"]
    core_resolution = core_compiled["properties"]["resolutions"]["items"]["properties"]
    assert (
        resolution["operationId"]["pattern"]
        == core_resolution["operationId"]["pattern"]
    )
    assert resolution["path"]["minLength"] == core_resolution["path"]["minLength"]
    for field, minimum in (
        ("section", 1),
        ("tableIndex", 0),
        ("logicalRow", 0),
        ("logicalColumn", 0),
        ("physicalRow", 0),
        ("physicalColumn", 0),
    ):
        integer_schema = next(
            branch
            for branch in resolution[field]["anyOf"]
            if branch.get("type") == "integer"
        )
        assert integer_schema["minimum"] == core_resolution[field]["minimum"] == minimum

    core_quality = next(
        branch
        for branch in core_plan["properties"]["quality"]["oneOf"]
        if branch.get("type") == "object"
    )
    mcp_quality = plan_defs["MixedFormQuality"]
    for field in core_quality["properties"]:
        assert "default" not in mcp_quality["properties"][field]
        assert "null" not in json.dumps(mcp_quality["properties"][field])

    compiled_defs = mcp_compiled["$defs"]
    assert (
        compiled_defs["_TextSetProperties"]["properties"]["text"]["maxLength"] == 4096
    )
    assert (
        compiled_defs["_ValueSetProperties"]["properties"]["value"]["maxLength"] == 4096
    )


def test_public_mixed_form_constraints_reject_invalid_runtime_values(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    plan = _plan(source, output)

    duplicate_requirements = copy.deepcopy(plan)
    duplicate_requirements["verificationRequirements"] = ["package", "package"]
    with pytest.raises(ValidationError, match="unique items"):
        MixedFormPlanInput.model_validate(duplicate_requirements)

    for option in (
        "mode",
        "renderCheck",
        "xsdMode",
        "overflowPolicy",
        "layoutLint",
        "preserveUnmodifiedParts",
        "requireReferenceIntegrity",
    ):
        explicit_null = copy.deepcopy(plan)
        explicit_null["quality"] = {option: None}
        with pytest.raises(ValidationError):
            MixedFormPlanInput.model_validate(explicit_null)

    overlong = copy.deepcopy(plan)
    overlong["operations"][0]["value"] = "x" * 4097
    with pytest.raises(ValidationError):
        MixedFormPlanInput.model_validate(overlong)

    compiled = _compiled_plan_payload()
    duplicate_compiled = copy.deepcopy(compiled)
    duplicate_compiled["batch"]["verificationRequirements"] = [
        "package",
        "package",
    ]
    with pytest.raises(ValidationError, match="unique items"):
        MixedFormCompiledPlanInput.model_validate(duplicate_compiled)

    overlong_compiled = copy.deepcopy(compiled)
    overlong_compiled["batch"]["commands"][0]["properties"]["text"] = "x" * 4097
    with pytest.raises(ValidationError):
        MixedFormCompiledPlanInput.model_validate(overlong_compiled)

    invalid_resolution_values = {
        "operationId": "1-invalid",
        "path": "",
        "section": 0,
        "tableIndex": -1,
        "logicalRow": -1,
        "logicalColumn": -1,
        "physicalRow": -1,
        "physicalColumn": -1,
    }
    for field, invalid in invalid_resolution_values.items():
        invalid_compiled = copy.deepcopy(compiled)
        invalid_compiled["resolutions"][0][field] = invalid
        with pytest.raises(ValidationError):
            MixedFormCompiledPlanInput.model_validate(invalid_compiled)


def test_specialized_dry_run_validates_through_live_fastmcp(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "missing" / "nested" / "output.hwpx"
    _build_fixture(source)

    _, structured = asyncio.run(
        server.mcp.call_tool(
            "apply_table_ops",
            {
                "filename": str(source),
                "ops": [],
                "output": str(output),
                "dry_run": True,
            },
        )
    )

    assert structured["ok"] is True
    assert structured["dryRun"] is True
    assert structured["verificationReceipt"]["dryRun"] is True
    assert not output.parent.exists()
    ApplyTableOpsOutput.model_validate(structured)


def test_analysis_and_canonical_dry_run_accept_missing_output_parent(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "new" / "deep" / "output.hwpx"
    _build_fixture(source)

    analysis = server.analyze_form_fill(plan=_plan(source, output))

    assert analysis["mutated"] is False
    assert analysis["output"]["unchangedAfterAnalysis"] is True
    assert not output.parent.exists()

    dry = server.apply_form_fill(
        plan=_plan(source, output, dry_run=True, key="missing-parent-dry-run")
    )

    assert dry["ok"] is True
    assert dry["dryRun"] is True
    assert dry["verificationReceipt"]["status"] == "dry-run"
    assert not output.parent.exists()


def test_canonical_dry_run_fails_if_missing_parent_chain_is_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "new" / "deep" / "output.hwpx"
    _build_fixture(source)
    original_apply = mixed_form_adapter.apply_mixed_form_plan

    def create_parent_then_apply(*args: Any, **kwargs: Any) -> Any:
        output.parent.parent.mkdir()
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(
        mixed_form_adapter,
        "apply_mixed_form_plan",
        create_parent_then_apply,
    )
    result = server.apply_form_fill(
        plan=_plan(source, output, dry_run=True, key="dry-run-parent-mutation")
    )

    assert result["ok"] is False
    assert result["rolledBack"] is False
    assert result["error"]["code"] == "materialized_output_changed"
    assert result["verificationReceipt"]["rollbackPreservation"]["preserved"] is False
    assert output.parent.parent.is_dir()
    assert not output.exists()


def test_specialized_dry_run_fails_if_missing_parent_chain_is_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "new" / "deep" / "output.hwpx"
    _build_fixture(source)
    original_apply = server._OPS.apply_table_ops

    def create_parent_then_apply(*args: Any, **kwargs: Any) -> dict[str, Any]:
        output.parent.parent.mkdir()
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(server._OPS, "apply_table_ops", create_parent_then_apply)
    result = server.apply_table_ops(
        str(source),
        [],
        output=str(output),
        dry_run=True,
    )

    assert result["ok"] is False
    assert result["rolledBack"] is False
    assert result["error"]["code"] == "dry_run_mutated"
    assert result["verificationReceipt"]["rollbackPreservation"]["preserved"] is False
    assert output.parent.parent.is_dir()
    assert not output.exists()


def test_strict_plan_rejects_unknown_keys_and_selector_xor(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    adapter = TypeAdapter(MixedFormPlanInput)
    schema = adapter.json_schema(by_alias=True)
    validator = Draft202012Validator(schema)

    unknown = _plan(source, output)
    unknown["unexpected"] = True
    assert list(validator.iter_errors(unknown))
    with pytest.raises(ValidationError):
        server.analyze_form_fill(plan=unknown)

    missing_native = _single(_plan(source, output), "native-project")
    missing_native["operations"][0]["target"] = {"kind": "nativeField"}
    assert list(validator.iter_errors(missing_native))
    with pytest.raises(ValidationError):
        server.analyze_form_fill(plan=missing_native)

    both_native = _single(_plan(source, output), "native-project")
    both_native["operations"][0]["target"] = {
        "kind": "nativeField",
        "fieldId": "240021",
        "name": "사업명",
    }
    assert list(validator.iter_errors(both_native))
    with pytest.raises(ValidationError):
        server.analyze_form_fill(plan=both_native)

    null_native = _single(_plan(source, output), "native-project")
    null_native["operations"][0]["target"] = {
        "kind": "nativeField",
        "fieldId": None,
    }
    assert list(validator.iter_errors(null_native))
    null_native_with_name = _single(_plan(source, output), "native-project")
    null_native_with_name["operations"][0]["target"] = {
        "kind": "nativeField",
        "fieldId": None,
        "name": "사업명",
    }
    assert list(validator.iter_errors(null_native_with_name))
    with pytest.raises(ValidationError):
        server.analyze_form_fill(plan=null_native_with_name)

    both_table = _single(_plan(source, output), "label-department")
    both_table["operations"][0]["target"]["tableIndex"] = 0
    assert list(validator.iter_errors(both_table))
    with pytest.raises(ValidationError):
        server.analyze_form_fill(plan=both_table)

    null_table = _single(_plan(source, output), "label-department")
    null_table["operations"][0]["target"]["tableAnchor"] = None
    assert list(validator.iter_errors(null_table))
    null_table_with_index = _single(_plan(source, output), "label-department")
    null_table_with_index["operations"][0]["target"].update(
        {"tableAnchor": None, "tableIndex": 0}
    )
    assert list(validator.iter_errors(null_table_with_index))
    with pytest.raises(ValidationError):
        server.analyze_form_fill(plan=null_table_with_index)

    with pytest.raises(ValueError, match="cannot be combined"):
        server.analyze_form_fill(
            source_filename=str(source), plan=_plan(source, output)
        )


def test_mode_schemas_reject_mixed_canonical_and_legacy_arguments(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    plan = _plan(source, output)
    bound = bound_tool_registry().by_name()
    analyze_validator = Draft202012Validator(bound["analyze_form_fill"].input_schema)
    apply_validator = Draft202012Validator(bound["apply_form_fill"].input_schema)

    analyze_call = {"plan": plan}
    assert analyze_validator.is_valid(analyze_call)
    analyze_call["source_filename"] = str(source)
    assert not analyze_validator.is_valid(analyze_call)

    apply_call = {"plan": plan}
    assert apply_validator.is_valid(apply_call)
    assert not apply_validator.is_valid({"plan": plan, "confirm": False})
    with pytest.raises(ValueError, match="cannot be combined"):
        server.apply_form_fill(plan=plan, confirm=False)
    apply_call["plan_id"] = "legacy-plan"
    assert not apply_validator.is_valid(apply_call)

    compiled = server.analyze_form_fill(plan=plan)["compiledPlan"]
    verify_validator = Draft202012Validator(bound["verify_form_fill"].input_schema)
    verify_call = {"plan": compiled}
    assert verify_validator.is_valid(verify_call)
    verify_call["filename"] = str(output)
    assert not verify_validator.is_valid(verify_call)


def test_analyze_and_apply_four_targets_with_receipt_and_member_preservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    source_before = source.read_bytes()

    analysis = server.analyze_form_fill(
        plan=_plan(source, output, key="mcp-four-targets")
    )
    assert analysis["schemaVersion"] == "hwpx.mixed-form-analysis/v1"
    assert analysis["mutated"] is False
    assert analysis["openSafety"]["ok"] is True
    assert source.read_bytes() == source_before
    assert not output.exists()
    compiled = analysis["compiledPlan"]
    assert compiled["schemaVersion"] == "hwpx.mixed-form-compiled-plan/v1"
    assert compiled["planHash"] == analysis["planHash"]
    assert [item["locatorKind"] for item in analysis["resolutions"]] == [
        "nativeField",
        "labelCell",
        "canonicalPath",
        "bodyAnchor",
    ]

    result = server.apply_form_fill(plan=compiled)
    assert result["ok"] is True
    assert result["rolledBack"] is False
    assert result["openSafety"]["ok"] is True
    assert result["verificationReceipt"]["reopen"]["ok"] is True
    assert result["verificationReceipt"]["bytePreservation"]["ok"] is True
    assert (
        result["verificationReceipt"]["schemaVersion"]
        == FORM_VERIFICATION_RECEIPT_SCHEMA
    )
    assert result["verificationReceipt"]["status"] == "committed"
    assert result["verificationReceipt"]["plan"]["planHash"] == compiled["planHash"]
    assert result["verificationReceipt"]["sourcePreservation"]["ok"] is True
    assert FormVerificationReceipt.model_json_schema()["additionalProperties"] is False
    invalid_receipt = copy.deepcopy(result["verificationReceipt"])
    invalid_receipt["unexpected"] = True
    with pytest.raises(ValidationError):
        FormVerificationReceipt.model_validate(invalid_receipt)
    serialized_receipt = json.dumps(
        result["verificationReceipt"], ensure_ascii=False, sort_keys=True
    )
    serialized_apply = json.dumps(result, ensure_ascii=False, sort_keys=True)
    for private_value in (
        "AI 수업 나눔의 날",
        "교육연구부",
        "교내 AI 활용 사례 공유",
        "김서현",
    ):
        assert private_value not in serialized_receipt
        assert private_value not in serialized_apply
    assert str(tmp_path) not in serialized_receipt
    assert str(tmp_path) not in serialized_apply
    assert result["verificationReceipt"]["expectedTargets"]
    assert "expectedValues" not in result["verificationReceipt"]
    assert validate_editor_open_safety(output).ok
    assert source.read_bytes() == source_before

    changed = set(result["verificationReceipt"]["bytePreservation"]["changedMembers"])
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(output) as after:
        common = set(before.namelist()) & set(after.namelist())
        assert all(before.read(name) == after.read(name) for name in common - changed)
    with HwpxDocument.open(output) as document:
        assert document.fields.all[0].value == "AI 수업 나눔의 날"
    with HwpxAgentDocument.open(output) as agent:
        purpose = agent.resolve_record('/section[1]/paragraph[@id="240050"]')
        owner = agent.resolve_record('/section[1]/paragraph[@id="240040"]')
        assert purpose.summary["text"] == "행사 목적: 교내 AI 활용 사례 공유"
        assert owner.summary["text"] == "담당자: 김서현"

    deferred_render = {
        "renderChecked": False,
        "ok": True,
        "warnings": ["oracle unavailable"],
        "errors": [],
    }
    monkeypatch.setattr(
        server._OPS,
        "verify_form_fill",
        lambda *args, **kwargs: copy.deepcopy(deferred_render),
    )
    verified = server.verify_form_fill(plan=compiled)
    assert verified["schemaVersion"] == FORM_VERIFICATION_RECEIPT_SCHEMA
    assert verified["phase"] == "verify"
    assert verified["ok"] is True
    assert verified["plan"]["planHash"] == compiled["planHash"]
    assert verified["sourcePreservation"]["ok"] is True
    assert verified["memberDiff"]["ok"] is True
    assert verified["valueVerification"]["ok"] is True
    assert len(verified["valueVerification"]["checks"]) == 4
    assert verified["status"] == "structurally-verified"
    assert all(
        "value" not in item and "actual" not in item
        for item in verified["valueVerification"]["checks"]
    )

    revision_bound = server.verify_form_fill(
        plan=compiled,
        expected_output_revision=result["documentRevision"],
    )
    assert revision_bound["ok"] is True
    assert revision_bound["output"]["revisionMatched"] is True
    stale_revision = server.verify_form_fill(
        plan=compiled,
        expected_output_revision="sha256:" + "0" * 64,
    )
    assert stale_revision["ok"] is False
    assert stale_revision["output"]["revisionMatched"] is False

    def unavailable_render(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("oracle transport unavailable")

    monkeypatch.setattr(server._OPS, "verify_form_fill", unavailable_render)
    honestly_deferred = server.verify_form_fill(plan=compiled)
    assert honestly_deferred["ok"] is True
    assert honestly_deferred["status"] == "structurally-verified"
    assert honestly_deferred["realHancom"]["status"] == "unavailable"

    monkeypatch.setattr(
        server._OPS,
        "verify_form_fill",
        lambda *args, **kwargs: {
            "renderChecked": False,
            "ok": False,
            "overflowDetected": False,
            "overlapDetected": False,
            "pageCountChanged": None,
            "warnings": [],
            "errors": [
                "RENDER_ORACLE_UNAVAILABLE: external Hancom oracle unavailable"
            ],
        },
    )
    installed_visual_degrade = server.verify_form_fill(plan=compiled)
    assert installed_visual_degrade["ok"] is True
    assert installed_visual_degrade["status"] == "structurally-verified"
    assert installed_visual_degrade["realHancom"]["renderChecked"] is False
    assert installed_visual_degrade["realHancom"]["ok"] is None
    assert installed_visual_degrade["realHancom"]["status"] == "unavailable"
    assert installed_visual_degrade["realHancom"]["errors"]

    monkeypatch.setattr(
        server._OPS,
        "verify_form_fill",
        lambda *args, **kwargs: {
            "renderChecked": True,
            "ok": False,
            "overflowDetected": True,
            "errors": ["overflow"],
        },
    )
    observed_render_failure = server.verify_form_fill(plan=compiled)
    assert observed_render_failure["ok"] is False
    assert observed_render_failure["status"] == "failed"
    monkeypatch.setattr(
        server._OPS,
        "verify_form_fill",
        lambda *args, **kwargs: copy.deepcopy(deferred_render),
    )

    server.fill_form_field(str(output), "변조값", field_id="240021")
    tampered = server.verify_form_fill(plan=compiled)
    assert tampered["ok"] is False
    assert tampered["valueVerification"]["ok"] is False
    assert any(
        item["operationId"] == "native-project" and not item["ok"]
        for item in tampered["valueVerification"]["checks"]
    )
    with zipfile.ZipFile(output, "a") as package:
        package.writestr("unexpected-member.bin", b"unexpected")
    unrelated = server.verify_form_fill(plan=compiled)
    assert unrelated["ok"] is False
    assert unrelated["memberDiff"]["ok"] is False
    assert unrelated["memberDiff"]["addedMembers"] == ["unexpected-member.bin"]


def test_dry_run_rollback_replay_and_key_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    _build_fixture(source)

    dry_output = tmp_path / "dry.hwpx"
    dry = server.apply_form_fill(plan=_plan(source, dry_output, dry_run=True))
    assert dry["ok"] is True and dry["dryRun"] is True
    assert not dry_output.exists()
    assert dry["verificationReceipt"]["status"] == "dry-run"
    assert dry["verificationReceipt"]["sourcePreservation"]["ok"] is True

    failed_output = tmp_path / "failed.hwpx"
    failed_output.write_bytes(b"existing destination")

    def fail_after_second(stage: str, index: int | None) -> None:
        if stage == "after_command" and index == 1:
            raise RuntimeError("injected MCP mixed-form failure")

    monkeypatch.setattr(
        mixed_form_adapter, "_fault_injector_for_tests", fail_after_second
    )
    failed = server.apply_form_fill(plan=_plan(source, failed_output))
    assert failed["ok"] is False and failed["rolledBack"] is True
    assert failed_output.read_bytes() == b"existing destination"
    assert failed["verificationReceipt"]["status"] == "rolled-back"
    assert failed["verificationReceipt"]["rollbackPreservation"]["preserved"] is True
    monkeypatch.setattr(mixed_form_adapter, "_fault_injector_for_tests", None)

    replay_output = tmp_path / "replay.hwpx"
    request = _plan(source, replay_output, key="mcp-replay-key")
    first = server.apply_form_fill(plan=request)
    replay = server.apply_form_fill(plan=request)
    assert first["ok"] is True and replay["ok"] is True
    assert replay["verificationReceipt"]["idempotency"]["replayed"] is True
    assert replay["verificationReceipt"]["status"] == "replayed"
    assert replay["verificationReceipt"]["committed"] is False

    with zipfile.ZipFile(replay_output, "a") as package:
        package.writestr("external-change.bin", b"do-not-overwrite")
    externally_changed = replay_output.read_bytes()
    changed_replay = server.apply_form_fill(plan=request)
    assert changed_replay["ok"] is False
    assert changed_replay["error"]["code"] == "idempotency_output_mismatch"
    assert replay_output.read_bytes() == externally_changed

    replay_output.unlink()
    missing_replay = server.apply_form_fill(plan=request)
    assert missing_replay["ok"] is False
    assert missing_replay["error"]["code"] == "idempotency_output_mismatch"
    assert missing_replay["verificationReceipt"]["status"] == "failed"
    assert missing_replay["verificationReceipt"]["output"]["exists"] is False

    source_replay_output = tmp_path / "source-replay.hwpx"
    source_request = _plan(
        source,
        source_replay_output,
        key="mcp-source-replay-key",
    )
    source_compiled = server.analyze_form_fill(plan=source_request)["compiledPlan"]
    assert server.apply_form_fill(plan=source_compiled)["ok"] is True
    source_before_tamper = source.read_bytes()
    with zipfile.ZipFile(source, "a") as package:
        package.writestr("external-source-change.bin", b"do-not-restore")
    changed_source_bytes = source.read_bytes()
    source_replay = server.apply_form_fill(plan=source_compiled)
    assert source_replay["ok"] is False
    assert source_replay["error"]["code"] == "source_revision_mismatch"
    assert source.read_bytes() == changed_source_bytes
    source.write_bytes(source_before_tamper)

    conflict_request = copy.deepcopy(request)
    conflict_request["operations"][0]["value"] = "다른 사업명"
    conflict = server.apply_form_fill(plan=conflict_request)
    assert conflict["ok"] is False
    assert conflict["error"]["code"] == "idempotency_conflict"


def test_post_publish_verification_rolls_back_only_the_exact_core_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    output.write_bytes(b"prior-destination")
    prior = output.read_bytes()
    original_diff = mixed_form_adapter._member_diff

    def reject_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        report = original_diff(*args, **kwargs)
        report.update(
            {
                "ok": False,
                "status": "violated",
                "unexpectedChangedMembers": ["settings.xml"],
            }
        )
        return report

    monkeypatch.setattr(mixed_form_adapter, "_member_diff", reject_candidate)
    rejected = server.apply_form_fill(
        plan=_plan(source, output, key="post-verify-rollback")
    )
    assert rejected["ok"] is False
    assert rejected["rolledBack"] is True
    assert rejected["error"]["code"] == "materialized_output_verification_failed"
    assert output.read_bytes() == prior

    monkeypatch.setattr(mixed_form_adapter, "_member_diff", original_diff)
    original_apply = mixed_form_adapter.apply_mixed_form_plan

    def concurrent_change(*args: Any, **kwargs: Any) -> Any:
        result = original_apply(*args, **kwargs)
        output.write_bytes(b"external-concurrent-change")
        return result

    monkeypatch.setattr(
        mixed_form_adapter,
        "apply_mixed_form_plan",
        concurrent_change,
    )
    changed = server.apply_form_fill(
        plan=_plan(source, output, key="post-verify-concurrent")
    )
    assert changed["ok"] is False
    assert changed["rolledBack"] is False
    assert changed["error"]["code"] == "materialized_output_changed"
    assert output.read_bytes() == b"external-concurrent-change"


def test_canonical_dry_run_preserves_unowned_and_adapter_restores_owned_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    candidate_path = tmp_path / "candidate.hwpx"
    dry_output = tmp_path / "dry.hwpx"
    _build_fixture(source)
    candidate = server.apply_form_fill(plan=_plan(source, candidate_path))
    assert candidate["ok"] is True
    candidate_bytes = candidate_path.read_bytes()
    original_apply = mixed_form_adapter.apply_mixed_form_plan

    def mutating_dry_run(*args: Any, **kwargs: Any) -> Any:
        result = original_apply(*args, **kwargs)
        dry_output.write_bytes(candidate_bytes)
        return result

    monkeypatch.setattr(
        mixed_form_adapter,
        "apply_mixed_form_plan",
        mutating_dry_run,
    )
    dry = server.apply_form_fill(
        plan=_plan(source, dry_output, dry_run=True, key="canonical-dry-mutation")
    )
    assert dry["ok"] is False
    assert dry["rolledBack"] is False
    assert dry["error"]["code"] == "dry_run_mutated"
    assert dry["documentRevision"] is None
    assert dry["verificationReceipt"]["output"]["expectedRevision"] is None
    assert dry_output.read_bytes() == candidate_bytes
    assert "canonical-dry-mutation" not in mixed_form_adapter._IDEMPOTENCY_STORE

    monkeypatch.setattr(mixed_form_adapter, "apply_mixed_form_plan", original_apply)
    existing = tmp_path / "existing.hwpx"
    existing.write_bytes(b"preexisting-destination")
    before = existing.read_bytes()

    def adapter_failure(data: bytes) -> dict[str, Any]:
        raise RuntimeError("adapter open-safety failed")

    monkeypatch.setattr(mixed_form_adapter, "_open_safety_snapshot", adapter_failure)
    with pytest.raises(RuntimeError, match="adapter open-safety failed"):
        server.apply_form_fill(
            plan=_plan(source, existing, key="canonical-adapter-exception")
        )
    assert existing.read_bytes() == before
    assert "canonical-adapter-exception" not in mixed_form_adapter._IDEMPOTENCY_STORE


def test_canonical_final_cas_never_overwrites_external_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    original_safety = mixed_form_adapter._open_safety_snapshot

    def swap_live_output(data: bytes) -> dict[str, Any]:
        output.write_bytes(b"external-concurrent-output")
        return original_safety(data)

    monkeypatch.setattr(
        mixed_form_adapter,
        "_open_safety_snapshot",
        swap_live_output,
    )
    changed = server.apply_form_fill(
        plan=_plan(source, output, key="canonical-final-cas")
    )
    assert changed["ok"] is False
    assert changed["rolledBack"] is False
    assert changed["documentRevision"] is None
    assert changed["error"]["code"] == "materialized_output_changed"
    assert output.read_bytes() == b"external-concurrent-output"
    assert "canonical-final-cas" not in mixed_form_adapter._IDEMPOTENCY_STORE


def test_canonical_final_receipt_rejects_same_bytes_output_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    replacement = tmp_path / "replacement.hwpx"
    _build_fixture(source)
    original_receipt = mixed_form_adapter._unified_receipt
    replaced = False

    def replace_after_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal replaced
        receipt = original_receipt(*args, **kwargs)
        if kwargs.get("phase") == "apply" and not replaced and receipt["ok"]:
            replaced = True
            replacement.write_bytes(output.read_bytes())
            replacement.chmod(output.stat().st_mode & 0o777)
            os.replace(replacement, output)
        return receipt

    monkeypatch.setattr(
        mixed_form_adapter,
        "_unified_receipt",
        replace_after_receipt,
    )
    result = server.apply_form_fill(
        plan=_plan(source, output, key="canonical-same-bytes-output-race")
    )

    assert replaced is True
    assert result["ok"] is False
    assert result["rolledBack"] is False
    assert result["error"]["code"] == "materialized_output_changed"
    assert output.exists()
    assert result["verificationReceipt"]["output"]["revision"] == _revision(output)
    assert "canonical-same-bytes-output-race" not in mixed_form_adapter._IDEMPOTENCY_STORE


def test_canonical_final_receipt_rejects_same_bytes_source_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    replacement = tmp_path / "replacement-source.hwpx"
    _build_fixture(source)
    original_inode = source.stat().st_ino
    original_receipt = mixed_form_adapter._unified_receipt
    replaced = False

    def replace_after_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal replaced
        receipt = original_receipt(*args, **kwargs)
        if kwargs.get("phase") == "apply" and not replaced and receipt["ok"]:
            replaced = True
            replacement.write_bytes(source.read_bytes())
            replacement.chmod(source.stat().st_mode & 0o777)
            os.replace(replacement, source)
        return receipt

    monkeypatch.setattr(
        mixed_form_adapter,
        "_unified_receipt",
        replace_after_receipt,
    )
    result = server.apply_form_fill(
        plan=_plan(source, output, key="canonical-same-bytes-source-race")
    )

    assert replaced is True
    assert source.stat().st_ino != original_inode
    assert result["ok"] is False
    assert result["rolledBack"] is True
    assert result["error"]["code"] == "source_revision_mismatch"
    assert result["verificationReceipt"]["sourcePreservation"]["ok"] is False
    assert not output.exists()
    assert "canonical-same-bytes-source-race" not in mixed_form_adapter._IDEMPOTENCY_STORE


def test_verify_rejects_same_bytes_output_replacement_during_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    replacement = tmp_path / "replacement.hwpx"
    _build_fixture(source)
    analysis = server.analyze_form_fill(plan=_plan(source, output))
    compiled = analysis["compiledPlan"]
    applied = server.apply_form_fill(plan=compiled)
    assert applied["ok"] is True
    original_receipt = mixed_form_adapter._unified_receipt
    replaced = False

    def replace_after_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal replaced
        receipt = original_receipt(*args, **kwargs)
        if kwargs.get("phase") == "verify" and not replaced:
            replaced = True
            replacement.write_bytes(output.read_bytes())
            replacement.chmod(output.stat().st_mode & 0o777)
            os.replace(replacement, output)
        return receipt

    monkeypatch.setattr(
        mixed_form_adapter,
        "_unified_receipt",
        replace_after_receipt,
    )
    verified = server.verify_form_fill(
        plan=compiled,
        expected_output_revision=applied["documentRevision"],
    )

    assert replaced is True
    assert verified["ok"] is False
    assert verified["error"]["code"] == "materialized_output_changed"
    assert verified["output"]["revision"] == _revision(output)


def test_canonical_source_race_preserves_external_source_and_cleans_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    original_apply = mixed_form_adapter.apply_mixed_form_plan

    def mutate_source_after_publish(*args: Any, **kwargs: Any) -> Any:
        result = original_apply(*args, **kwargs)
        source.write_bytes(b"external-source-change")
        return result

    monkeypatch.setattr(
        mixed_form_adapter,
        "apply_mixed_form_plan",
        mutate_source_after_publish,
    )
    result = server.apply_form_fill(
        plan=_plan(source, output, key="canonical-source-race")
    )
    assert result["ok"] is False
    assert result["rolledBack"] is True
    assert result["documentRevision"] is None
    assert result["verificationReceipt"]["output"]["expectedRevision"] is None
    assert result["error"]["code"] == "source_revision_mismatch"
    assert source.read_bytes() == b"external-source-change"
    assert not output.exists()
    assert "canonical-source-race" not in mixed_form_adapter._IDEMPOTENCY_STORE


def test_compiled_paths_are_authorized_canonical_and_writes_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    with pytest.raises(AgentContractError, match="output"):
        server.analyze_form_fill(plan=_plan(source, source))

    compiled = server.analyze_form_fill(plan=_plan(source, output))["compiledPlan"]
    relative = copy.deepcopy(compiled)
    relative["batch"]["input"]["filename"] = source.name
    with pytest.raises(ValueError, match="canonical absolute path"):
        server.apply_form_fill(plan=relative)

    def blocked() -> None:
        raise RuntimeError("capability skew")

    monkeypatch.setattr(server.quality_contract, "assert_write_capability", blocked)
    with pytest.raises(RuntimeError, match="capability skew"):
        server.apply_form_fill(plan=compiled)
    assert not output.exists()


def test_single_native_plan_derives_allowed_section_member(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    request = _single(_plan(source, output), "native-project")
    compiled = server.analyze_form_fill(plan=request)["compiledPlan"]

    result = server.apply_form_fill(plan=compiled)

    assert result["ok"] is True
    assert result["verificationReceipt"]["memberDiff"]["ok"] is True
    assert result["verificationReceipt"]["memberDiff"]["allowedChangedMembers"] == [
        "Contents/section0.xml"
    ]


def test_allowed_members_follow_manifest_spine_not_section_filename_convention(
    tmp_path: Path,
) -> None:
    source = tmp_path / "renamed-section.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    with zipfile.ZipFile(source) as package:
        content = package.read("Contents/content.hpf").replace(
            b"Contents/section0.xml",
            b"Contents/section7.xml",
        )
    source.write_bytes(
        _rewrite_package(
            source.read_bytes(),
            replacements={"Contents/content.hpf": content},
            renames={"Contents/section0.xml": "Contents/section7.xml"},
        )
    )
    assert validate_editor_open_safety(source).ok

    request = _single(_plan(source, output), "native-project")
    result = server.apply_form_fill(plan=request)

    assert result["ok"] is True
    assert result["verificationReceipt"]["memberDiff"]["allowedChangedMembers"] == [
        "Contents/section7.xml"
    ]
    assert result["verificationReceipt"]["memberDiff"]["changedMembers"] == [
        "Contents/section7.xml"
    ]


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
    reason="descriptor-anchored publication is POSIX-only",
)
def test_canonical_apply_cleans_parent_swap_during_guarded_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    parent = root / "results"
    parent.mkdir(parents=True)
    outside.mkdir()
    source = root / "source.hwpx"
    output = parent / "output.hwpx"
    _build_fixture(source)
    monkeypatch.delenv("HWPX_AUTOMATION_WORKSPACE_ROOTS", raising=False)
    monkeypatch.setenv("HWPX_MCP_WORKSPACE_ROOTS", str(root))
    compiled = server.analyze_form_fill(plan=_plan(source, output))["compiledPlan"]
    real_link = workspace_module.os.link
    attacked = False

    def swap_parent_at_publish(src, dst, *args, **kwargs):
        nonlocal attacked
        if (
            not attacked
            and os.fspath(src).endswith(".tmp")
            and os.fspath(dst) == "output.hwpx"
        ):
            attacked = True
            parent.rename(outside / "escaped")
            parent.mkdir()
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(workspace_module.os, "link", swap_parent_at_publish)

    result = server.apply_form_fill(plan=compiled)

    assert result["ok"] is False
    assert attacked is True
    assert not output.exists()
    assert not (outside / "escaped/output.hwpx").exists()


def test_member_diff_rejects_duplicate_zip_entries(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    _build_fixture(source)
    before = source.read_bytes()
    duplicate = io.BytesIO(before)
    with zipfile.ZipFile(io.BytesIO(before)) as package:
        section = package.read("Contents/section0.xml")
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(duplicate, "a") as package:
            package.writestr("Contents/section0.xml", section)

    report = mixed_form_adapter._member_diff(
        before,
        duplicate.getvalue(),
        allowed_changed_members={"Contents/section0.xml"},
    )

    assert report["ok"] is False
    assert report["duplicateMembersAfter"] == ["Contents/section0.xml"]
    assert report["multiplicityChangedMembers"] == ["Contents/section0.xml"]
    assert report["afterMemberCount"] == report["beforeMemberCount"] + 1


def test_verify_uses_snapshot_paths_and_rejects_live_path_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    compiled = server.analyze_form_fill(plan=_plan(source, output))["compiledPlan"]
    applied = server.apply_form_fill(plan=compiled)
    assert applied["ok"] is True
    filled_bytes = output.read_bytes()
    seen_paths: list[tuple[Path, Path]] = []

    def snapshot_renderer(after: str, before: str, require: bool) -> dict[str, Any]:
        after_path = Path(after)
        before_path = Path(before)
        seen_paths.append((after_path, before_path))
        assert after_path != output and before_path != source
        assert after_path.read_bytes() == filled_bytes
        assert before_path.read_bytes() == source.read_bytes()
        return {"ok": True, "renderChecked": True}

    monkeypatch.setattr(server._OPS, "verify_form_fill", snapshot_renderer)
    verified = server.verify_form_fill(
        plan=compiled,
        require=True,
        expected_output_revision=applied["documentRevision"],
    )
    assert verified["ok"] is True
    assert verified["status"] == "verified"
    assert seen_paths
    workspace_root = workspace_module.WorkspaceResolver.from_environment().primary_root
    for after_snapshot, before_snapshot in seen_paths:
        assert workspace_root in after_snapshot.parents
        assert workspace_root in before_snapshot.parents
        assert not after_snapshot.exists()
        assert not before_snapshot.exists()

    monkeypatch.setattr(
        server._OPS,
        "verify_form_fill",
        lambda *args, **kwargs: {"ok": True},
    )
    structural = server.verify_form_fill(
        plan=compiled,
        expected_output_revision=applied["documentRevision"],
    )
    assert structural["ok"] is True
    assert structural["status"] == "structurally-verified"
    required_without_observation = server.verify_form_fill(
        plan=compiled,
        require=True,
        expected_output_revision=applied["documentRevision"],
    )
    assert required_without_observation["ok"] is False

    original_safety = mixed_form_adapter._open_safety_snapshot

    def change_live_output(data: bytes) -> dict[str, Any]:
        output.write_bytes(source.read_bytes())
        return original_safety(data)

    monkeypatch.setattr(
        mixed_form_adapter,
        "_open_safety_snapshot",
        change_live_output,
    )
    changed = server.verify_form_fill(
        plan=compiled,
        expected_output_revision=applied["documentRevision"],
    )
    assert changed["ok"] is False
    assert changed["error"]["code"] == "materialized_output_changed"
    assert output.read_bytes() == source.read_bytes()


def test_verify_fails_closed_and_cleans_mutated_render_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    compiled = server.analyze_form_fill(plan=_plan(source, output))["compiledPlan"]
    applied = server.apply_form_fill(plan=compiled)
    assert applied["ok"] is True

    def mutate_snapshot(after: str, before: str, require: bool) -> dict[str, Any]:
        del before, require
        snapshot = Path(after)
        payload = snapshot.read_bytes()
        snapshot.chmod(0o600)
        snapshot.write_bytes(payload)
        return {"ok": True, "renderChecked": True}

    monkeypatch.setattr(server._OPS, "verify_form_fill", mutate_snapshot)
    verified = server.verify_form_fill(
        plan=compiled,
        expected_output_revision=applied["documentRevision"],
    )

    assert verified["ok"] is False
    assert verified["realHancom"]["status"] == "failed"
    assert (
        verified["realHancom"]["errorCode"]
        == "verification_snapshot_cleanup_failed"
    )
    workspace_root = workspace_module.WorkspaceResolver.from_environment().primary_root
    assert list(workspace_root.glob(".hwpx-verify-*.hwpx")) == []


def test_canonical_verify_serializes_with_public_mutation_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    compiled = server.analyze_form_fill(plan=_plan(source, output))["compiledPlan"]
    applied = server.apply_form_fill(plan=compiled)
    assert applied["ok"] is True

    call_ready = threading.Event()
    start_call = threading.Event()
    call_attempted = threading.Event()
    verify_entered = threading.Event()
    verify_finished = threading.Event()
    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []
    original_payload = mixed_form_adapter._payload

    def observed_payload(*args: Any, **kwargs: Any) -> dict[str, Any]:
        verify_entered.set()
        return original_payload(*args, **kwargs)

    def run_verify() -> None:
        call_ready.set()
        start_call.wait()
        call_attempted.set()
        try:
            results.append(
                mixed_form_adapter.verify_canonical_mixed_form_plan(compiled)
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            verify_finished.set()

    monkeypatch.setattr(mixed_form_adapter, "_payload", observed_payload)
    worker = threading.Thread(target=run_verify, daemon=True)
    with mixed_form_adapter.PUBLIC_MUTATION_LOCK:
        worker.start()
        assert call_ready.wait(timeout=1.0)
        start_call.set()
        assert call_attempted.wait(timeout=1.0)
        entered_while_writer_locked = verify_entered.wait(timeout=0.5)
        finished_while_writer_locked = verify_finished.is_set()

    worker.join(timeout=5.0)

    assert entered_while_writer_locked is False
    assert finished_while_writer_locked is False
    assert worker.is_alive() is False
    assert errors == []
    assert results and results[0]["ok"] is True


def test_specialized_required_render_failures_restore_destinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    review = tmp_path / "review.md"
    _build_fixture(source)
    _build_fixture(output)
    review.write_text("# synthetic", encoding="utf-8")
    source_before = source.read_bytes()
    output_before = output.read_bytes()

    def table_partial(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("required render failed")

    monkeypatch.setattr(server._OPS, "apply_table_ops", table_partial)
    with pytest.raises(RuntimeError, match="required render failed"):
        server.apply_table_ops(
            str(source),
            [],
            output=str(output),
            render_check="required",
        )
    assert source.read_bytes() == source_before
    assert output.read_bytes() == output_before

    def table_false(*args: Any, **kwargs: Any) -> dict[str, Any]:
        publication = (
            workspace_module.WorkspaceResolver.from_environment().atomic_publish_bytes(
                kwargs["output_guard"],
                b"partial-false-output",
            )
        )
        return {
            "ok": False,
            "changedParts": ["Contents/section0.xml"],
            "_workspacePublication": publication,
        }

    monkeypatch.setattr(server._OPS, "apply_table_ops", table_false)
    failed = server.apply_table_ops(str(source), [], output=str(output))
    assert failed["ok"] is False
    assert failed["rolledBack"] is True
    assert failed["verificationReceipt"]["status"] == "rolled-back"
    assert failed["verificationReceipt"]["rollbackPreservation"] == {
        "required": True,
        "outputExistedBefore": True,
        "preserved": True,
    }
    assert failed["compatibility"]["status"] == "rolled-back"
    assert output.read_bytes() == output_before

    source_identity = source.stat()
    output_identity = output.stat()

    def table_false_without_mutation(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": False, "changedParts": []}

    monkeypatch.setattr(server._OPS, "apply_table_ops", table_false_without_mutation)
    unchanged_failure = server.apply_table_ops(str(source), [], output=str(output))
    assert unchanged_failure["ok"] is False
    assert unchanged_failure["rolledBack"] is False
    assert unchanged_failure["verificationReceipt"]["rollbackPreservation"] == {
        "required": False,
        "outputExistedBefore": True,
        "preserved": None,
    }
    ApplyTableOpsOutput.model_validate(unchanged_failure)
    assert source.stat().st_ino == source_identity.st_ino
    assert source.stat().st_mode == source_identity.st_mode
    assert output.stat().st_ino == output_identity.st_ino
    assert output.stat().st_mode == output_identity.st_mode

    def evalplan_partial(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("required evalplan render failed")

    monkeypatch.setattr(server._OPS, "apply_evalplan_fill", evalplan_partial)
    with pytest.raises(RuntimeError, match="required evalplan render failed"):
        server.apply_evalplan_fill(
            str(source),
            str(review),
            render_check="required",
        )
    assert source.read_bytes() == source_before


def test_specialized_dry_run_mutations_and_post_publish_exceptions_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    source_before = source.read_bytes()

    def mutate_separate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        output.write_bytes(source_before)
        return {"ok": True, "changedParts": []}

    monkeypatch.setattr(server._OPS, "apply_table_ops", mutate_separate)
    separate = server.apply_table_ops(
        str(source),
        [],
        output=str(output),
        dry_run=True,
    )
    assert separate["ok"] is False
    assert separate["rolledBack"] is False
    assert separate["error"]["code"] == "dry_run_mutated"
    assert separate["verificationReceipt"]["error"]["code"] == "dry_run_mutated"
    assert output.read_bytes() == source_before
    assert source.read_bytes() == source_before
    output.unlink()

    def mutate_in_place(*args: Any, **kwargs: Any) -> dict[str, Any]:
        source.write_bytes(b"partial-dry-run-source")
        return {"ok": True, "changedParts": []}

    monkeypatch.setattr(server._OPS, "apply_table_ops", mutate_in_place)
    in_place = server.apply_table_ops(str(source), [], dry_run=True)
    assert in_place["ok"] is False
    assert in_place["rolledBack"] is False
    assert source.read_bytes() == b"partial-dry-run-source"
    source.write_bytes(source_before)

    output.write_bytes(b"preexisting-specialized-output")
    output_before = output.read_bytes()

    def publish_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        publication = (
            workspace_module.WorkspaceResolver.from_environment().atomic_publish_bytes(
                kwargs["output_guard"],
                source_before,
            )
        )
        return {
            "ok": True,
            "changedParts": [],
            "_workspacePublication": publication,
        }

    monkeypatch.setattr(server._OPS, "apply_table_ops", publish_candidate)
    monkeypatch.setattr(
        mixed_form_adapter,
        "_open_safety_snapshot",
        lambda data: (_ for _ in ()).throw(RuntimeError("receipt adapter failed")),
    )
    with pytest.raises(RuntimeError, match="receipt adapter failed"):
        server.apply_table_ops(str(source), [], output=str(output))
    assert output.read_bytes() == output_before
    assert source.read_bytes() == source_before


def test_specialized_allowlist_is_independent_and_snapshot_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    source_bytes = source.read_bytes()
    with zipfile.ZipFile(source) as package:
        preview = package.read("Preview/PrvText.txt")
        section = package.read("Contents/section0.xml")
        header = package.read("Contents/header.xml")

    unrelated = _rewrite_package(
        source_bytes,
        replacements={"Preview/PrvText.txt": preview + b" unrelated"},
    )

    def publish_unrelated(*args: Any, **kwargs: Any) -> dict[str, Any]:
        publication = (
            workspace_module.WorkspaceResolver.from_environment().atomic_publish_bytes(
                kwargs["output_guard"],
                unrelated,
            )
        )
        return {
            "ok": True,
            "changedParts": ["Preview/PrvText.txt"],
            "documentRevision": "sha256:" + hashlib.sha256(unrelated).hexdigest(),
            "_workspacePublication": publication,
        }

    monkeypatch.setattr(server._OPS, "apply_table_ops", publish_unrelated)
    rejected = server.apply_table_ops(str(source), [], output=str(output))
    assert rejected["ok"] is False
    assert rejected["rolledBack"] is True
    assert rejected["documentRevision"] is None
    assert rejected["error"]["code"] == "specialized_verification_failed"
    assert rejected["verificationReceipt"]["error"]["code"] == (
        "specialized_verification_failed"
    )
    assert not output.exists()

    legitimate = _rewrite_package(
        source_bytes,
        replacements={
            "Contents/section0.xml": section + b"\n",
            "Contents/header.xml": header + b"\n",
        },
    )

    def publish_body_header(*args: Any, **kwargs: Any) -> dict[str, Any]:
        publication = (
            workspace_module.WorkspaceResolver.from_environment().atomic_publish_bytes(
                kwargs["output_guard"],
                legitimate,
            )
        )
        # Legacy executors under-report the header mutation; the adapter must
        # derive the actual changed set from source/candidate bytes.
        return {
            "ok": True,
            "changedParts": ["Contents/section0.xml"],
            "_workspacePublication": publication,
        }

    monkeypatch.setattr(server._OPS, "apply_table_ops", publish_body_header)
    accepted = server.apply_table_ops(str(source), [], output=str(output))
    assert accepted["ok"] is True
    assert accepted["changedParts"] == [
        "Contents/header.xml",
        "Contents/section0.xml",
    ]
    assert accepted["verificationReceipt"]["memberDiff"]["ok"] is True
    assert (
        accepted["verificationReceipt"]["memberDiff"]["declaredMatchesObserved"]
        is False
    )

    original_safety = mixed_form_adapter._open_safety_snapshot

    def swap_during_receipt(data: bytes) -> dict[str, Any]:
        output.write_bytes(source_bytes)
        return original_safety(data)

    monkeypatch.setattr(
        mixed_form_adapter,
        "_open_safety_snapshot",
        swap_during_receipt,
    )
    changed = server.apply_table_ops(str(source), [], output=str(output))
    assert changed["ok"] is False
    assert changed["rolledBack"] is False
    assert changed["error"]["code"] == "specialized_output_changed"
    assert output.read_bytes() == source_bytes


def test_zero_multiple_and_cross_run_targets_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    _build_fixture(source)
    missing = _single(_plan(source, tmp_path / "missing.hwpx"), "body-owner")
    missing["operations"][0]["target"]["anchor"] = "{{없는값}}"
    with pytest.raises(AgentContractError, match="not found") as absent:
        server.analyze_form_fill(plan=missing)
    assert absent.value.code == "not_found"

    duplicate = tmp_path / "duplicate.hwpx"
    _build_fixture(duplicate, duplicate_native_field=True)
    duplicate_plan = _single(
        _plan(duplicate, tmp_path / "duplicate-out.hwpx"),
        "native-project",
    )
    duplicate_plan["operations"][0]["target"] = {
        "kind": "nativeField",
        "name": "사업명",
    }
    with pytest.raises(AgentContractError) as ambiguous:
        server.analyze_form_fill(plan=duplicate_plan)
    assert ambiguous.value.code == "ambiguous_target"

    split = tmp_path / "split.hwpx"
    _build_fixture(split, split_body_anchor=True)
    with pytest.raises(AgentContractError, match="run boundaries") as cross_run:
        server.analyze_form_fill(
            plan=_single(_plan(split, tmp_path / "split-out.hwpx"), "body-owner")
        )
    assert cross_run.value.code == "unsupported_content"


def test_duplicate_native_field_protocol_preserves_ambiguous_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "duplicate.hwpx"
    output = tmp_path / "duplicate-out.hwpx"
    _build_fixture(source, duplicate_native_field=True)
    source_before = source.read_bytes()
    duplicate_plan = _single(_plan(source, output), "native-project")
    duplicate_plan["operations"][0]["target"] = {
        "kind": "nativeField",
        "name": "사업명",
    }

    async def call() -> mcp_types.ErrorData:
        async with create_connected_server_and_client_session(server.mcp) as client:
            health = await client.call_tool("mcp_server_health", {})
            assert health.isError is False
            with pytest.raises(McpError) as captured:
                await client.call_tool(
                    "analyze_form_fill",
                    {"plan": duplicate_plan},
                )
            return captured.value.error

    error = asyncio.run(call())

    assert error.code == -32000
    assert error.data["errorCode"] == "ambiguous_target"
    assert error.data["tool"] == "analyze_form_fill"
    assert error.data["error"]["schemaVersion"] == "hwpx.mcp-error/v1"
    assert error.data["error"]["code"] == "ambiguous_target"
    assert error.data["error"]["category"] == "document"
    encoded = json.dumps(error.data, ensure_ascii=False)
    for private_detail in (
        str(source),
        str(output),
        "사업명",
        "AI 수업 나눔의 날",
        "native form-field locator matched 2 fields",
    ):
        assert private_detail not in encoded
    assert "arguments" not in error.data
    assert source.read_bytes() == source_before
    assert not output.exists()


def test_legacy_formfill_is_marked_and_evalplan_exam_remain_separate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy.hwpx"
    output = tmp_path / "legacy-out.hwpx"
    _build_fixture(source)
    legacy = server.analyze_form_fill(
        str(source),
        input_json={
            "schemaVersion": "hwpx.formfill.v1",
            "fields": [{"label": "담당 부서", "value": "교육연구부"}],
        },
        destination_filename=str(output),
    )
    assert legacy["compatibility"]["schemaVersion"] == "hwpx.formfill.v1"
    assert callable(server.apply_evalplan_fill)
    assert callable(server.compose_exam)

    tree = ast.parse(Path(mixed_form_adapter.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )
    assert not any(
        name == "hwpx.exam" or name.startswith("hwpx.exam.") for name in imported
    )
    assert (
        "exam"
        not in str(
            bound_tool_registry().by_name()["analyze_form_fill"].input_schema
        ).casefold()
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode preservation assertion")
def test_canonical_core_failure_after_publish_restores_exact_prestate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    _build_fixture(source)
    output.write_bytes(b"preexisting-invalid-output")
    output.chmod(0o640)
    output_before = output.read_bytes()

    def publish_then_fail(
        self: mixed_form_adapter._WorkspaceSavePipeline,
        data: bytes,
        **kwargs: Any,
    ) -> Any:
        self._publish(
            data,
            kwargs.get("output_path"),
            kwargs.get("output_stream"),
        )
        raise RuntimeError("core failed after publication")

    monkeypatch.setattr(
        mixed_form_adapter._WorkspaceSavePipeline,
        "run",
        publish_then_fail,
    )

    result = server.apply_form_fill(plan=_plan(source, output))

    assert result["ok"] is False
    assert result["rolledBack"] is True
    assert result["documentRevision"] is None
    assert output.read_bytes() == output_before
    assert output.stat().st_mode & 0o777 == 0o640
    receipt = result["verificationReceipt"]
    assert receipt["committed"] is False
    assert receipt["status"] == "rolled-back"
    assert receipt["output"]["revision"] == _revision(output)
    assert receipt["output"]["expectedRevision"] is None
    assert receipt["rollbackPreservation"]["preserved"] is True
    assert receipt["openSafety"] == {"ok": None, "status": "rolled-back"}


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode preservation assertion")
def test_canonical_uncaught_adapter_exception_after_publish_restores_prestate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    _build_fixture(source)
    output.write_bytes(b"preexisting-invalid-output")
    output.chmod(0o640)
    output_before = output.read_bytes()
    original_apply = mixed_form_adapter.apply_mixed_form_plan

    def apply_then_raise(*args: Any, **kwargs: Any) -> Any:
        original_apply(*args, **kwargs)
        raise RuntimeError("adapter raised after core publication")

    monkeypatch.setattr(
        mixed_form_adapter,
        "apply_mixed_form_plan",
        apply_then_raise,
    )
    with pytest.raises(RuntimeError, match="after core publication"):
        server.apply_form_fill(
            plan=_plan(source, output, key="canonical-uncaught-after-publish")
        )

    assert output.read_bytes() == output_before
    assert output.stat().st_mode & 0o777 == 0o640
    assert "canonical-uncaught-after-publish" not in mixed_form_adapter._IDEMPOTENCY_STORE


def test_canonical_publish_claim_loss_preserves_preimage_without_overwriting_external(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    external = tmp_path / "external.hwpx"
    deterministic_recovery = output.with_name(
        output.name + ".mixed-form-recovery"
    )
    _build_fixture(source)
    output_before = b"canonical-output-before"
    external_bytes = b"canonical-external-winner"
    deterministic_bytes = b"external-deterministic-recovery"
    output.write_bytes(output_before)
    deterministic_recovery.write_bytes(deterministic_bytes)
    original_publish = workspace_module.WorkspaceResolver.atomic_publish_bytes
    raced = False
    recovery_attempts = 0

    def publish_then_external_replace_and_raise(
        self: workspace_module.WorkspaceResolver,
        guard: workspace_module.WorkspaceOutputGuard,
        data: bytes,
        *,
        mode: int | None = None,
    ) -> workspace_module.WorkspaceOutputGuard:
        nonlocal raced, recovery_attempts
        publication = original_publish(self, guard, data, mode=mode)
        if guard.path.name.startswith(".hwpx-mixed-form-recovery-"):
            recovery_attempts += 1
            if recovery_attempts == 1:
                self.remove_output(publication)
                raise workspace_module.WorkspacePathError(
                    "simulated recovery publication claim loss",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_target_changed",
                )
        if guard.path == output and not raced:
            raced = True
            external.write_bytes(external_bytes)
            external.replace(output)
            raise workspace_module.WorkspacePathError(
                "simulated final publication claim loss",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            )
        return publication

    monkeypatch.setattr(
        workspace_module.WorkspaceResolver,
        "atomic_publish_bytes",
        publish_then_external_replace_and_raise,
    )

    result = server.apply_form_fill(plan=_plan(source, output))

    assert raced is True
    assert recovery_attempts == 2
    assert result["ok"] is False
    assert output.read_bytes() == external_bytes
    assert deterministic_recovery.read_bytes() == deterministic_bytes
    recoveries = _failure_recoveries(output)
    assert len(recoveries) == 1
    assert recoveries[0].read_bytes() == output_before


def test_canonical_recovery_reservation_failure_prevents_output_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    _build_fixture(source)
    output_before = b"canonical-reservation-before"
    output.write_bytes(output_before)
    output_hash = hashlib.sha256(output.name.encode("utf-8")).hexdigest()[:12]
    fixed_token = "a" * 32
    occupied_recovery = output.parent / (
        f".hwpx-mixed-form-recovery-{output_hash}-{fixed_token}"
    )
    occupied_bytes = b"external-random-recovery"
    occupied_recovery.write_bytes(occupied_bytes)
    original_publish = workspace_module.WorkspaceResolver.atomic_publish_bytes
    target_publish_attempted = False

    def track_target_publish(
        self: workspace_module.WorkspaceResolver,
        guard: workspace_module.WorkspaceOutputGuard,
        data: bytes,
        *,
        mode: int | None = None,
    ) -> workspace_module.WorkspaceOutputGuard:
        nonlocal target_publish_attempted
        if guard.path == output:
            target_publish_attempted = True
        return original_publish(self, guard, data, mode=mode)

    monkeypatch.setattr(
        mixed_form_adapter.secrets,
        "token_hex",
        lambda size: "a" * (size * 2),
    )
    monkeypatch.setattr(
        workspace_module.WorkspaceResolver,
        "atomic_publish_bytes",
        track_target_publish,
    )

    with pytest.raises(
        RuntimeError,
        match="no available random recovery sidecar",
    ):
        server.apply_form_fill(plan=_plan(source, output))

    assert target_publish_attempted is False
    assert output.read_bytes() == output_before
    assert occupied_recovery.read_bytes() == occupied_bytes
    assert _failure_recoveries(output) == [occupied_recovery]


def test_canonical_rollback_claim_loss_keeps_external_and_recovery_preimage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    external = tmp_path / "external.hwpx"
    _build_fixture(source)
    output_before = b"canonical-rollback-before"
    external_bytes = b"canonical-rollback-external-winner"
    output.write_bytes(output_before)
    original_publish = workspace_module.WorkspaceResolver.atomic_publish_bytes
    original_diff = mixed_form_adapter._member_diff
    target_publications = 0

    def reject_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        report = original_diff(*args, **kwargs)
        report["ok"] = False
        return report

    def lose_claim_after_rollback_publish(
        self: workspace_module.WorkspaceResolver,
        guard: workspace_module.WorkspaceOutputGuard,
        data: bytes,
        *,
        mode: int | None = None,
    ) -> workspace_module.WorkspaceOutputGuard:
        nonlocal target_publications
        publication = original_publish(self, guard, data, mode=mode)
        if guard.path == output:
            target_publications += 1
            if target_publications == 2:
                external.write_bytes(external_bytes)
                external.replace(output)
                raise workspace_module.WorkspacePathError(
                    "simulated rollback publication claim loss",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_target_changed",
                )
        return publication

    monkeypatch.setattr(mixed_form_adapter, "_member_diff", reject_candidate)
    monkeypatch.setattr(
        workspace_module.WorkspaceResolver,
        "atomic_publish_bytes",
        lose_claim_after_rollback_publish,
    )

    result = server.apply_form_fill(plan=_plan(source, output))

    assert target_publications == 2
    assert result["ok"] is False
    assert result["rolledBack"] is False
    assert output.read_bytes() == external_bytes
    recoveries = _failure_recoveries(output)
    assert len(recoveries) == 1
    assert recoveries[0].read_bytes() == output_before


def test_canonical_post_cleanup_claim_loss_recreates_random_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    external = tmp_path / "external.hwpx"
    _build_fixture(source)
    output_before = b"canonical-post-cleanup-before"
    external_bytes = b"canonical-post-cleanup-external"
    output.write_bytes(output_before)
    original_cleanup = (
        mixed_form_adapter._FailurePreimagePreserver.cleanup_after_success
    )
    raced = False

    def cleanup_then_replace_output(
        self: mixed_form_adapter._FailurePreimagePreserver,
    ) -> bool:
        nonlocal raced
        cleaned = original_cleanup(self)
        if self.output == output and cleaned and not raced:
            raced = True
            external.write_bytes(external_bytes)
            external.replace(output)
        return cleaned

    monkeypatch.setattr(
        mixed_form_adapter._FailurePreimagePreserver,
        "cleanup_after_success",
        cleanup_then_replace_output,
    )

    result = server.apply_form_fill(plan=_plan(source, output))

    assert raced is True
    assert result["ok"] is False
    assert result["error"]["code"] == "materialized_output_changed"
    assert output.read_bytes() == external_bytes
    recoveries = _failure_recoveries(output)
    assert len(recoveries) == 1
    assert recoveries[0].read_bytes() == output_before
    assert len(recoveries[0].name.encode("utf-8")) < 128


def test_specialized_snapshot_exception_after_publish_restores_prestate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    _build_fixture(source)
    output.write_bytes(b"preexisting-specialized-output")
    output_before = output.read_bytes()
    original_capture = mixed_form_adapter._capture_path_snapshot
    published = False

    def publish_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal published
        publication = server._OPS.storage.atomic_publish_bytes(
            kwargs["output_guard"],
            source.read_bytes(),
        )
        kwargs["publication_sink"](publication)
        published = True
        return {"ok": True, "changedParts": []}

    def fail_post_publish_source_snapshot(
        path: Path,
        *,
        create_parents: bool = False,
    ) -> Any:
        if published and Path(path) == source:
            raise RuntimeError("post-publication snapshot failed")
        return original_capture(path, create_parents=create_parents)

    monkeypatch.setattr(server._OPS, "apply_table_ops", publish_candidate)
    monkeypatch.setattr(
        mixed_form_adapter,
        "_capture_path_snapshot",
        fail_post_publish_source_snapshot,
    )

    with pytest.raises(RuntimeError, match="post-publication snapshot failed"):
        server.apply_table_ops(str(source), [], output=str(output))

    assert output.read_bytes() == output_before


def test_specialized_non_object_result_after_publish_restores_prestate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    _build_fixture(source)
    output.write_bytes(b"preexisting-specialized-output")
    output_before = output.read_bytes()

    def publish_then_return_non_object(*args: Any, **kwargs: Any) -> Any:
        publication = server._OPS.storage.atomic_publish_bytes(
            kwargs["output_guard"],
            source.read_bytes(),
        )
        kwargs["publication_sink"](publication)
        return None

    monkeypatch.setattr(
        server._OPS,
        "apply_table_ops",
        publish_then_return_non_object,
    )

    with pytest.raises(TypeError, match="non-object result"):
        server.apply_table_ops(str(source), [], output=str(output))

    assert output.read_bytes() == output_before


def test_specialized_publish_claim_loss_preserves_preimage_and_external_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    external = tmp_path / "external.hwpx"
    _build_fixture(source)
    output_before = b"specialized-output-before"
    external_bytes = b"specialized-external-winner"
    output.write_bytes(output_before)
    original_publish = workspace_module.WorkspaceResolver.atomic_publish_bytes
    raced = False

    def publish_then_external_replace_and_raise(
        self: workspace_module.WorkspaceResolver,
        guard: workspace_module.WorkspaceOutputGuard,
        data: bytes,
        *,
        mode: int | None = None,
    ) -> workspace_module.WorkspaceOutputGuard:
        nonlocal raced
        publication = original_publish(self, guard, data, mode=mode)
        if guard.path == output and not raced:
            raced = True
            external.write_bytes(external_bytes)
            external.replace(output)
            raise workspace_module.WorkspacePathError(
                "simulated specialized final claim loss",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            )
        return publication

    monkeypatch.setattr(
        workspace_module.WorkspaceResolver,
        "atomic_publish_bytes",
        publish_then_external_replace_and_raise,
    )

    with pytest.raises(
        workspace_module.WorkspacePathError,
        match="simulated specialized final claim loss",
    ):
        server.apply_table_ops(str(source), [], output=str(output))

    assert raced is True
    assert output.read_bytes() == external_bytes
    recoveries = _failure_recoveries(output)
    assert len(recoveries) == 1
    assert recoveries[0].read_bytes() == output_before


def test_specialized_recovery_reservation_failure_prevents_callback_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    _build_fixture(source)
    output_before = b"specialized-reservation-before"
    output.write_bytes(output_before)
    callback_called = False

    def fail_recovery_reservation(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("simulated specialized recovery reservation failure")

    def unexpected_callback(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal callback_called
        callback_called = True
        output.write_bytes(b"unexpected-mutation")
        return {"ok": True, "changedParts": []}

    monkeypatch.setattr(
        mixed_form_adapter,
        "_publish_exact_failure_recovery",
        fail_recovery_reservation,
    )
    monkeypatch.setattr(server._OPS, "apply_table_ops", unexpected_callback)

    with pytest.raises(
        RuntimeError,
        match="simulated specialized recovery reservation failure",
    ):
        server.apply_table_ops(str(source), [], output=str(output))

    assert callback_called is False
    assert output.read_bytes() == output_before
    assert _failure_recoveries(output) == []


def test_specialized_unowned_candidate_preserves_preimage_and_external_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    external = tmp_path / "external.hwpx"
    _build_fixture(source)
    output_before = b"specialized-unowned-before"
    external_bytes = b"specialized-unowned-external-winner"
    output.write_bytes(output_before)

    def publish_then_lose_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        publication = (
            workspace_module.WorkspaceResolver.from_environment().atomic_publish_bytes(
                kwargs["output_guard"],
                source.read_bytes(),
            )
        )
        kwargs["publication_sink"](publication)
        external.write_bytes(external_bytes)
        external.replace(output)
        return {"ok": True, "changedParts": []}

    monkeypatch.setattr(server._OPS, "apply_table_ops", publish_then_lose_candidate)

    result = server.apply_table_ops(str(source), [], output=str(output))

    assert result["ok"] is False
    assert result["error"]["code"] == "specialized_output_changed"
    assert output.read_bytes() == external_bytes
    recoveries = _failure_recoveries(output)
    assert len(recoveries) == 1
    assert recoveries[0].read_bytes() == output_before


def test_specialized_post_cleanup_claim_loss_recreates_random_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    external = tmp_path / "external.hwpx"
    _build_fixture(source)
    output_before = b"specialized-post-cleanup-before"
    external_bytes = b"specialized-post-cleanup-external"
    output.write_bytes(output_before)
    original_cleanup = (
        mixed_form_adapter._FailurePreimagePreserver.cleanup_after_success
    )
    raced = False

    def cleanup_then_replace_output(
        self: mixed_form_adapter._FailurePreimagePreserver,
    ) -> bool:
        nonlocal raced
        cleaned = original_cleanup(self)
        if self.output == output and cleaned and not raced:
            raced = True
            external.write_bytes(external_bytes)
            external.replace(output)
        return cleaned

    monkeypatch.setattr(
        mixed_form_adapter._FailurePreimagePreserver,
        "cleanup_after_success",
        cleanup_then_replace_output,
    )

    result = server.apply_table_ops(str(source), [], output=str(output))

    assert raced is True
    assert result["ok"] is False
    assert result["error"]["code"] == "specialized_output_changed"
    assert output.read_bytes() == external_bytes
    recoveries = _failure_recoveries(output)
    assert len(recoveries) == 1
    assert recoveries[0].read_bytes() == output_before
    assert len(recoveries[0].name.encode("utf-8")) < 128


def test_specialized_rollback_claim_loss_keeps_external_and_recovery_preimage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    external = tmp_path / "external.hwpx"
    _build_fixture(source)
    output_before = b"specialized-rollback-before"
    external_bytes = b"specialized-rollback-external-winner"
    output.write_bytes(output_before)
    original_publish = workspace_module.WorkspaceResolver.atomic_publish_bytes
    target_publications = 0

    def publish_then_report_failure(*args: Any, **kwargs: Any) -> dict[str, Any]:
        publication = (
            workspace_module.WorkspaceResolver.from_environment().atomic_publish_bytes(
                kwargs["output_guard"],
                source.read_bytes(),
            )
        )
        kwargs["publication_sink"](publication)
        return {"ok": False, "changedParts": []}

    def lose_claim_after_rollback_publish(
        self: workspace_module.WorkspaceResolver,
        guard: workspace_module.WorkspaceOutputGuard,
        data: bytes,
        *,
        mode: int | None = None,
    ) -> workspace_module.WorkspaceOutputGuard:
        nonlocal target_publications
        publication = original_publish(self, guard, data, mode=mode)
        if guard.path == output:
            target_publications += 1
            if target_publications == 2:
                external.write_bytes(external_bytes)
                external.replace(output)
                raise workspace_module.WorkspacePathError(
                    "simulated specialized rollback claim loss",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_target_changed",
                )
        return publication

    monkeypatch.setattr(server._OPS, "apply_table_ops", publish_then_report_failure)
    monkeypatch.setattr(
        workspace_module.WorkspaceResolver,
        "atomic_publish_bytes",
        lose_claim_after_rollback_publish,
    )

    result = server.apply_table_ops(str(source), [], output=str(output))

    assert target_publications == 2
    assert result["ok"] is False
    assert result["rolledBack"] is False
    assert output.read_bytes() == external_bytes
    recoveries = _failure_recoveries(output)
    assert len(recoveries) == 1
    assert recoveries[0].read_bytes() == output_before


def test_successful_mixed_form_mutations_do_not_create_recovery_sidecars(
    tmp_path: Path,
) -> None:
    canonical_source = tmp_path / "canonical-source.hwpx"
    canonical_output = tmp_path / "canonical-output.hwpx"
    specialized_source = tmp_path / "specialized-source.hwpx"
    specialized_output = tmp_path / "specialized-output.hwpx"
    _build_fixture(canonical_source)
    _build_fixture(specialized_source)
    canonical_output.write_bytes(b"canonical-before")
    specialized_output.write_bytes(b"specialized-before")

    canonical = server.apply_form_fill(
        plan=_plan(canonical_source, canonical_output)
    )
    specialized = server.apply_table_ops(
        str(specialized_source),
        [],
        output=str(specialized_output),
    )

    assert canonical["ok"] is True
    assert specialized["ok"] is True
    assert _failure_recoveries(canonical_output) == []
    assert _failure_recoveries(specialized_output) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX inode/mode assertion")
def test_specialized_same_bytes_external_replacement_is_unowned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    replacement = tmp_path / "external-replacement.hwpx"
    _build_fixture(source)
    output.write_bytes(source.read_bytes())
    output.chmod(0o640)
    original_inode = output.stat().st_ino
    external_inode: int | None = None

    def replace_with_same_bytes(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal external_inode
        replacement.write_bytes(output.read_bytes())
        replacement.chmod(0o777)
        external_inode = replacement.stat().st_ino
        replacement.replace(output)
        return {"ok": True, "changedParts": []}

    monkeypatch.setattr(server._OPS, "apply_table_ops", replace_with_same_bytes)

    result = server.apply_table_ops(str(source), [], output=str(output))

    assert result["ok"] is False
    assert result["rolledBack"] is False
    assert result["error"]["code"] == "specialized_output_changed"
    assert output.read_bytes() == source.read_bytes()
    assert output.stat().st_ino == external_inode
    assert output.stat().st_ino != original_inode
    assert output.stat().st_mode & 0o777 == 0o777
    assert result["verificationReceipt"]["committed"] is False


def test_specialized_source_race_restores_only_owned_distinct_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "existing.hwpx"
    _build_fixture(source)
    source_before = source.read_bytes()
    output.write_bytes(b"preexisting-specialized-output")
    output_before = output.read_bytes()
    external_source = b"external-source-owner"

    def publish_then_change_source(*args: Any, **kwargs: Any) -> dict[str, Any]:
        publication = (
            workspace_module.WorkspaceResolver.from_environment().atomic_publish_bytes(
                kwargs["output_guard"],
                source_before,
            )
        )
        source.write_bytes(external_source)
        return {
            "ok": True,
            "changedParts": [],
            "_workspacePublication": publication,
        }

    monkeypatch.setattr(server._OPS, "apply_table_ops", publish_then_change_source)

    result = server.apply_table_ops(str(source), [], output=str(output))

    assert result["ok"] is False
    assert result["rolledBack"] is True
    assert result["error"]["code"] == "source_mutated"
    assert source.read_bytes() == external_source
    assert output.read_bytes() == output_before
    assert result["verificationReceipt"]["sourcePreservation"]["ok"] is False
    assert result["verificationReceipt"]["rollbackPreservation"] == {
        "required": True,
        "outputExistedBefore": True,
        "preserved": True,
    }


def test_specialized_rollback_evidence_describes_final_invalid_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "invalid-existing.hwpx"
    _build_fixture(source)
    source_bytes = source.read_bytes()
    output.write_bytes(b"not-an-hwpx-package")
    output_before = output.read_bytes()

    def publish_then_reject(*args: Any, **kwargs: Any) -> dict[str, Any]:
        publication = (
            workspace_module.WorkspaceResolver.from_environment().atomic_publish_bytes(
                kwargs["output_guard"],
                source_bytes,
            )
        )
        return {
            "ok": False,
            "changedParts": [],
            "openSafety": {"ok": True, "marker": "candidate"},
            "verificationReport": {
                "openSafety": {"ok": True, "marker": "candidate"}
            },
            "_workspacePublication": publication,
        }

    monkeypatch.setattr(server._OPS, "apply_table_ops", publish_then_reject)

    result = server.apply_table_ops(str(source), [], output=str(output))

    assert result["ok"] is False
    assert result["rolledBack"] is True
    assert output.read_bytes() == output_before
    receipt = result["verificationReceipt"]
    final_safety = receipt["openSafety"]
    assert final_safety["ok"] is False
    assert "marker" not in final_safety
    assert result["openSafety"] == final_safety
    assert result["verificationReport"]["openSafety"] == final_safety
    assert result["verificationReport"]["package"] == receipt["package"]
    assert result["verificationReport"]["reopen"] == receipt["reopen"]
    assert receipt["output"]["revision"] == _revision(output)
    assert receipt["output"]["expectedRevision"] is None


def test_specialized_initial_guard_rejects_external_lost_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    replacement = tmp_path / "external-lost-update.hwpx"
    _build_fixture(source)
    output.write_bytes(b"initial-output")
    external_bytes = b"external-lost-update"

    def race_guarded_publish(*args: Any, **kwargs: Any) -> dict[str, Any]:
        replacement.write_bytes(external_bytes)
        replacement.replace(output)
        workspace_module.WorkspaceResolver.from_environment().atomic_publish_bytes(
            kwargs["output_guard"],
            source.read_bytes(),
        )
        raise AssertionError("guarded publication unexpectedly succeeded")

    monkeypatch.setattr(server._OPS, "apply_table_ops", race_guarded_publish)

    with pytest.raises(workspace_module.WorkspacePathError) as rejected:
        server.apply_table_ops(str(source), [], output=str(output))

    assert rejected.value.reason == "output_target_changed"
    assert output.read_bytes() == external_bytes


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode preservation assertion")
def test_specialized_callback_exception_restores_recorded_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    output.write_bytes(b"preexisting-specialized-output")
    output.chmod(0o640)
    output_before = output.read_bytes()

    def publish_then_raise(*args: Any, **kwargs: Any) -> dict[str, Any]:
        publication = (
            workspace_module.WorkspaceResolver.from_environment().atomic_publish_bytes(
                kwargs["output_guard"],
                source.read_bytes(),
            )
        )
        kwargs["publication_sink"](publication)
        raise RuntimeError("specialized callback failed after publication")

    monkeypatch.setattr(server._OPS, "apply_table_ops", publish_then_raise)

    with pytest.raises(RuntimeError, match="failed after publication"):
        server.apply_table_ops(str(source), [], output=str(output))

    assert output.read_bytes() == output_before
    assert output.stat().st_mode & 0o777 == 0o640


@pytest.mark.skipif(os.name != "posix", reason="symlink race requires POSIX")
def test_specialized_snapshot_symlink_swap_never_reads_outside_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    source = root / "source.hwpx"
    output = root / "output.hwpx"
    displaced = root / "displaced-output.hwpx"
    outside = tmp_path / "outside-secret.hwpx"
    _build_fixture(source)
    output.write_bytes(source.read_bytes())
    secret = b"outside-secret-must-not-be-hashed"
    outside.write_bytes(secret)
    secret_revision = "sha256:" + hashlib.sha256(secret).hexdigest()
    observed_revision_inputs: list[bytes] = []
    real_revision = mixed_form_adapter._revision_bytes
    monkeypatch.delenv("HWPX_AUTOMATION_WORKSPACE_ROOTS", raising=False)
    monkeypatch.setenv("HWPX_MCP_WORKSPACE_ROOTS", str(root))

    def observe_revision(data: bytes) -> str:
        observed_revision_inputs.append(data)
        return real_revision(data)

    def swap_to_outside_symlink(*args: Any, **kwargs: Any) -> dict[str, Any]:
        output.rename(displaced)
        output.symlink_to(outside)
        return {"ok": True, "changedParts": []}

    monkeypatch.setattr(mixed_form_adapter, "_revision_bytes", observe_revision)
    monkeypatch.setattr(server._OPS, "apply_table_ops", swap_to_outside_symlink)

    with pytest.raises(workspace_module.WorkspacePathError) as rejected:
        server.apply_table_ops(str(source), [], output=str(output))

    public_error = str(rejected.value) + json.dumps(
        rejected.value.safe_details(),
        sort_keys=True,
    )
    assert secret_revision not in public_error
    assert secret not in observed_revision_inputs
    assert output.is_symlink()
    assert outside.read_bytes() == secret
    assert displaced.read_bytes() == source.read_bytes()


@pytest.mark.skipif(os.name != "posix", reason="symlink aliases require POSIX")
def test_compiled_plan_rejects_source_relocation_through_same_inode_alias(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    relocated = tmp_path / "relocated-source.hwpx"
    _build_fixture(source)
    compiled = server.analyze_form_fill(
        plan=_plan(source, output)
    )["compiledPlan"]

    source.rename(relocated)
    source.symlink_to(relocated.name)

    with pytest.raises(ValueError, match="canonical absolute path"):
        server.apply_form_fill(plan=compiled)

    assert source.is_symlink()
    assert relocated.exists()
    assert not output.exists()


@pytest.mark.skipif(os.name != "posix", reason="symlink aliases require POSIX")
def test_compiled_plan_rejects_output_relocation_through_same_inode_alias(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    relocated = tmp_path / "relocated-output.hwpx"
    _build_fixture(source)
    _build_fixture(output)
    compiled = server.analyze_form_fill(
        plan=_plan(source, output)
    )["compiledPlan"]

    output.rename(relocated)
    output.symlink_to(relocated.name)

    with pytest.raises(ValueError, match="canonical absolute path"):
        server.apply_form_fill(plan=compiled)

    assert output.is_symlink()
    assert relocated.exists()


@pytest.mark.skipif(os.name != "posix", reason="symlink relocation requires POSIX")
@pytest.mark.parametrize("relocate", ["source", "output"])
def test_canonical_final_receipt_rejects_same_inode_symlink_relocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relocate: str,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    relocated = tmp_path / f"relocated-{relocate}.hwpx"
    _build_fixture(source)
    original_receipt = mixed_form_adapter._unified_receipt
    moved = False

    def relocate_after_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal moved
        receipt = original_receipt(*args, **kwargs)
        if kwargs.get("phase") == "apply" and receipt["ok"] and not moved:
            path = source if relocate == "source" else output
            path.rename(relocated)
            path.symlink_to(relocated.name)
            moved = True
        return receipt

    monkeypatch.setattr(
        mixed_form_adapter,
        "_unified_receipt",
        relocate_after_receipt,
    )

    result = server.apply_form_fill(
        plan=_plan(source, output, key=f"same-inode-{relocate}-relocation")
    )

    assert moved is True
    assert result["ok"] is False
    assert result["error"]["code"] == (
        "source_revision_mismatch"
        if relocate == "source"
        else "materialized_output_changed"
    )
    assert (source if relocate == "source" else output).is_symlink()
    assert relocated.exists()


@pytest.mark.skipif(os.name != "posix", reason="symlink relocation requires POSIX")
@pytest.mark.parametrize("relocate", ["source", "output"])
def test_specialized_final_receipt_rejects_same_inode_symlink_relocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relocate: str,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    relocated = tmp_path / f"relocated-specialized-{relocate}.hwpx"
    _build_fixture(source)
    original_attach = mixed_form_adapter.attach_common_form_receipt
    moved = False

    def relocate_after_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal moved
        result = original_attach(*args, **kwargs)
        if result["ok"] and not moved:
            path = source if relocate == "source" else output
            path.rename(relocated)
            path.symlink_to(relocated.name)
            moved = True
        return result

    monkeypatch.setattr(
        mixed_form_adapter,
        "attach_common_form_receipt",
        relocate_after_receipt,
    )

    result = server.apply_table_ops(
        str(source),
        [],
        output=str(output),
    )

    assert moved is True
    assert result["ok"] is False
    assert result["error"]["code"] == (
        "source_mutated" if relocate == "source" else "specialized_output_changed"
    )
    assert (source if relocate == "source" else output).is_symlink()
    assert relocated.exists()


def test_canonical_fresh_success_requires_exact_publication_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    _build_fixture(source)
    original_publish = mixed_form_adapter._WorkspaceSavePipeline._publish

    def publish_then_forget_claim(self, *args: Any, **kwargs: Any) -> Any:
        result = original_publish(self, *args, **kwargs)
        self.publication = None
        return result

    monkeypatch.setattr(
        mixed_form_adapter._WorkspaceSavePipeline,
        "_publish",
        publish_then_forget_claim,
    )

    result = server.apply_form_fill(
        plan=_plan(source, output, key="canonical-missing-publication")
    )

    assert result["ok"] is False
    assert result["rolledBack"] is False
    assert result["error"]["code"] == "materialized_output_changed"
    assert output.exists()
    assert "canonical-missing-publication" not in mixed_form_adapter._IDEMPOTENCY_STORE


def test_canonical_post_publish_failure_removes_owned_missing_parent_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "new/deep/output.hwpx"
    _build_fixture(source)

    def publish_then_fail(
        self: mixed_form_adapter._WorkspaceSavePipeline,
        data: bytes,
        **kwargs: Any,
    ) -> Any:
        self._publish(
            data,
            kwargs.get("output_path"),
            kwargs.get("output_stream"),
        )
        raise RuntimeError("core failed after missing-parent publication")

    monkeypatch.setattr(
        mixed_form_adapter._WorkspaceSavePipeline,
        "run",
        publish_then_fail,
    )

    result = server.apply_form_fill(plan=_plan(source, output))

    assert result["ok"] is False
    assert result["rolledBack"] is True
    assert result["verificationReceipt"]["rollbackPreservation"]["preserved"] is True
    assert not (tmp_path / "new").exists()


def test_canonical_missing_parent_external_change_reports_incomplete_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "new/deep/output.hwpx"
    external = output.parent / "external.txt"
    _build_fixture(source)
    original_diff = mixed_form_adapter._member_diff
    changed = False

    def reject_after_external_change(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal changed
        report = original_diff(*args, **kwargs)
        if output.exists() and not changed:
            external.write_text("external state", encoding="utf-8")
            changed = True
            report["ok"] = False
        return report

    monkeypatch.setattr(
        mixed_form_adapter,
        "_member_diff",
        reject_after_external_change,
    )

    result = server.apply_form_fill(plan=_plan(source, output))

    assert changed is True
    assert result["ok"] is False
    assert result["rolledBack"] is False
    preservation = result["verificationReceipt"]["rollbackPreservation"]
    assert preservation["required"] is True
    assert preservation["preserved"] is False
    assert not output.exists()
    assert external.read_text(encoding="utf-8") == "external state"
    assert (tmp_path / "new/deep").is_dir()


def test_specialized_failure_does_not_create_missing_output_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "new/deep/output.hwpx"
    _build_fixture(source)

    monkeypatch.setattr(
        server._OPS,
        "apply_table_ops",
        lambda *args, **kwargs: {"ok": False, "changedParts": []},
    )

    result = server.apply_table_ops(str(source), [], output=str(output))

    assert result["ok"] is False
    assert result["verificationReceipt"]["output"]["exists"] is False
    assert not (tmp_path / "new").exists()


def test_specialized_missing_parent_precondition_rejects_external_appearance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "new/deep/output.hwpx"
    _build_fixture(source)
    original_write = server._OPS._services.save._write_patched
    external = b"external output"

    def create_external_before_materialization(*args: Any, **kwargs: Any) -> Any:
        output.parent.mkdir(parents=True)
        output.write_bytes(external)
        return original_write(*args, **kwargs)

    monkeypatch.setattr(
        server._OPS._services.save,
        "_write_patched",
        create_external_before_materialization,
    )

    with pytest.raises(workspace_module.WorkspacePathError):
        server.apply_table_ops(str(source), [], output=str(output))

    assert output.read_bytes() == external


def test_failed_canonical_receipt_rejects_same_bytes_source_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    replacement = tmp_path / "replacement-source.hwpx"
    _build_fixture(source)
    original_apply = mixed_form_adapter.apply_mixed_form_plan
    original_inode = source.stat().st_ino

    def fail_after_first(stage: str, index: int | None) -> None:
        if stage == "after_command" and index == 0:
            raise RuntimeError("injected core failure")

    def replace_source_after_core_failure(*args: Any, **kwargs: Any) -> Any:
        result = original_apply(*args, **kwargs)
        replacement.write_bytes(source.read_bytes())
        replacement.chmod(source.stat().st_mode & 0o777)
        os.replace(replacement, source)
        return result

    monkeypatch.setattr(
        mixed_form_adapter,
        "_fault_injector_for_tests",
        fail_after_first,
    )
    monkeypatch.setattr(
        mixed_form_adapter,
        "apply_mixed_form_plan",
        replace_source_after_core_failure,
    )

    result = server.apply_form_fill(plan=_plan(source, output))

    assert source.stat().st_ino != original_inode
    assert result["ok"] is False
    preservation = result["verificationReceipt"]["sourcePreservation"]
    assert preservation["ok"] is False
    assert preservation["preserved"] is False
    assert preservation["identityPreserved"] is False
