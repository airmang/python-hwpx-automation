#!/usr/bin/env python3
"""Build and verify the deterministic S-079 mixed-form reference fixture."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import zipfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator, Mapping

from hwpx import HwpxDocument, validate_editor_open_safety
from hwpx_mcp_server.office.agent import (
    MIXED_FORM_COMPILED_PLAN_SCHEMA,
    MIXED_FORM_PLAN_SCHEMA,
    HwpxAgentDocument,
    apply_mixed_form_plan,
    plan_mixed_form_fill,
    validate_mixed_form_plan,
    validate_mixed_form_request,
)
from hwpx.oxml.namespaces import HP


HERE = Path(__file__).resolve().parent
SOURCE_SPEC_PATH = HERE / "source-spec.json"
SOURCE_PATH = HERE / "source.hwpx"
PLAN_PATH = HERE / "expected-plan.json"
EXPECTED_PATH = HERE / "expected.hwpx"
RECEIPT_PATH = HERE / "receipt.json"
DRY_OUTPUT_PATH = HERE / ".dry-run-output.hwpx"
FAILURE_OUTPUT_PATH = HERE / ".failure-output.hwpx"

SOURCE_NAME = SOURCE_PATH.name
PLAN_NAME = PLAN_PATH.name
EXPECTED_NAME = EXPECTED_PATH.name

PLAN_SCHEMA = "hwpx.mixed-form-plan/v1"
SOURCE_SPEC_SCHEMA = "hwpx.demo.mixed-form-source/v1"
RECEIPT_SCHEMA = "hwpx.demo.mixed-form-receipt/v1"
TABLE_CELL_MARGIN = {
    "left": "510",
    "right": "510",
    "top": "141",
    "bottom": "141",
}


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(_json_bytes(value))


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "bytes": path.stat().st_size,
        "path": path.name,
        "sha256": _sha256_file(path),
    }


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{name} keys differ: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _load_source_spec() -> dict[str, Any]:
    value = json.loads(SOURCE_SPEC_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("source-spec.json must contain one JSON object")
    _exact_keys(
        value,
        {
            "schemaVersion",
            "dataPolicy",
            "document",
            "nativeField",
            "table",
            "bodyAnchor",
            "canonicalTarget",
        },
        "sourceSpec",
    )
    if value["schemaVersion"] != SOURCE_SPEC_SCHEMA:
        raise ValueError("source-spec.json has an unsupported schemaVersion")
    if value["dataPolicy"] != {
        "containsRealPersonalData": False,
        "containsTestMaterial": False,
        "synthetic": True,
    }:
        raise ValueError("source-spec.json must remain synthetic-only")

    document = value["document"]
    native = value["nativeField"]
    table = value["table"]
    body = value["bodyAnchor"]
    canonical = value["canonicalTarget"]
    for item, name in (
        (document, "document"),
        (native, "nativeField"),
        (table, "table"),
        (body, "bodyAnchor"),
        (canonical, "canonicalTarget"),
    ):
        if not isinstance(item, dict):
            raise ValueError(f"sourceSpec.{name} must be an object")
    _exact_keys(document, {"pageIntent", "title"}, "sourceSpec.document")
    _exact_keys(
        document["title"], {"paragraphId", "text"}, "sourceSpec.document.title"
    )
    _exact_keys(
        native,
        {
            "controlId",
            "fieldId",
            "label",
            "name",
            "paragraphId",
            "placeholder",
            "type",
        },
        "sourceSpec.nativeField",
    )
    _exact_keys(
        table,
        {
            "anchor",
            "anchorParagraphId",
            "cellParagraphIds",
            "columnCount",
            "paragraphId",
            "rowCount",
            "rows",
            "tableId",
        },
        "sourceSpec.table",
    )
    _exact_keys(body, {"paragraphId", "text"}, "sourceSpec.bodyAnchor")
    _exact_keys(
        canonical, {"paragraphId", "text"}, "sourceSpec.canonicalTarget"
    )
    if document["pageIntent"] != 1:
        raise ValueError("the reference fixture must retain a one-page intent")
    if table["rowCount"] != 2 or table["columnCount"] != 2:
        raise ValueError("the P1-frozen table must remain 2 by 2")
    if table["anchor"] != "담당 부서":
        raise ValueError("the P1-frozen table anchor changed")
    if table["rows"] != [["사업명", ""], ["담당 부서", ""]]:
        raise ValueError("the P1-frozen table text changed")
    if table["cellParagraphIds"] != [
        ["240032", "240033"],
        ["240034", "240035"],
    ]:
        raise ValueError("the deterministic table-cell paragraph IDs changed")
    if (
        table["anchorParagraphId"] != "240029"
        or table["paragraphId"] != "240030"
        or table["tableId"] != "240031"
    ):
        raise ValueError("the deterministic table anchor/host paragraph IDs changed")
    return value


def _append(parent: Any, tag: str, attrs: dict[str, str] | None = None) -> Any:
    child = parent.makeelement(tag, attrs or {})
    parent.append(child)
    return child


def _native_field_command(direction: str) -> str:
    payload = (
        f"Direction:wstring:{len(direction)}:{direction} "
        "HelpState:wstring:0:  "
    )
    return f"Clickhere:set:{len(payload) - 1}:{payload}"


def _add_native_field(document: HwpxDocument, spec: Mapping[str, Any]) -> None:
    paragraph = document.add_paragraph(str(spec["label"]))
    paragraph.element.set("id", str(spec["paragraphId"]))
    begin_run = _append(paragraph.element, f"{HP}run", {"charPrIDRef": "0"})
    control = _append(begin_run, f"{HP}ctrl")
    field_begin = _append(
        control,
        f"{HP}fieldBegin",
        {
            "id": str(spec["controlId"]),
            "fieldid": str(spec["fieldId"]),
            "type": str(spec["type"]),
            "name": str(spec["name"]),
            "editable": "1",
            "dirty": "0",
            "zorder": "-1",
            "metaTag": "",
        },
    )
    parameters = _append(
        field_begin,
        f"{HP}parameters",
        {"cnt": "3", "name": ""},
    )
    _append(parameters, f"{HP}integerParam", {"name": "Prop"}).text = "9"
    _append(
        parameters,
        f"{HP}stringParam",
        {"name": "Command", "{http://www.w3.org/XML/1998/namespace}space": "preserve"},
    ).text = _native_field_command(str(spec["name"]))
    _append(parameters, f"{HP}stringParam", {"name": "Direction"}).text = str(
        spec["name"]
    )
    value_run = _append(paragraph.element, f"{HP}run", {"charPrIDRef": "0"})
    _append(value_run, f"{HP}t").text = str(spec["placeholder"])
    end_run = _append(paragraph.element, f"{HP}run", {"charPrIDRef": "0"})
    end_control = _append(end_run, f"{HP}ctrl")
    _append(
        end_control,
        f"{HP}fieldEnd",
        {
            "beginIDRef": str(spec["controlId"]),
            "fieldid": str(spec["fieldId"]),
        },
    )
    paragraph.section.mark_dirty()


def _build_source(spec: Mapping[str, Any]) -> None:
    document_spec = spec["document"]
    title_spec = document_spec["title"]
    table_spec = spec["table"]
    body_spec = spec["bodyAnchor"]
    canonical_spec = spec["canonicalTarget"]

    with HwpxDocument.new() as document:
        title = document.sections[0].paragraphs[0]
        title.element.set("id", str(title_spec["paragraphId"]))
        title.text = str(title_spec["text"])

        _add_native_field(document, spec["nativeField"])

        table_anchor = document.add_paragraph(str(table_spec["anchor"]))
        table_anchor.element.set("id", str(table_spec["anchorParagraphId"]))
        table_paragraph = document.add_paragraph("", include_run=False)
        table_paragraph.element.set("id", str(table_spec["paragraphId"]))
        table = table_paragraph.add_table(
            int(table_spec["rowCount"]), int(table_spec["columnCount"])
        )
        table.element.set("id", str(table_spec["tableId"]))
        for row_index, row in enumerate(table_spec["rows"]):
            for column_index, value in enumerate(row):
                cell = table.rows[row_index].cells[column_index]
                cell.text = str(value)
                cell.element.set("hasMargin", "1")
                cell_margin = cell.element.find(f"{HP}cellMargin")
                if cell_margin is None:
                    raise AssertionError("generated table cell is missing cellMargin")
                cell_margin.attrib.update(TABLE_CELL_MARGIN)
                cell.paragraphs[0].element.set(
                    "id", str(table_spec["cellParagraphIds"][row_index][column_index])
                )

        body = document.add_paragraph("", include_run=False)
        body.element.set("id", str(body_spec["paragraphId"]))
        body.add_run(str(body_spec["text"]))

        canonical = document.add_paragraph(str(canonical_spec["text"]))
        canonical.element.set("id", str(canonical_spec["paragraphId"]))

        document.save_to_path(SOURCE_PATH)


def _public_plan(
    source_revision: str,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": PLAN_SCHEMA,
        "source": SOURCE_NAME,
        "output": EXPECTED_NAME,
        "expectedRevision": source_revision,
        "idempotencyKey": "s079-mixed-anchor-reference-v1",
        "dryRun": False,
        "overwrite": True,
        "quality": "transparent",
        "verificationRequirements": [
            "package",
            "reopen",
            "bytePreservation",
            "openSafety",
        ],
        "operations": [
            {
                "operationId": "native-project-name",
                "target": {"kind": "nativeField", "fieldId": "240021"},
                "value": "AI 수업 나눔의 날",
            },
            {
                "operationId": "label-department",
                "target": {
                    "kind": "labelCell",
                    "sectionPath": "/section[1]",
                    "tableAnchor": str(spec["table"]["anchor"]),
                    "cellAnchor": {
                        "label": "담당 부서",
                        "direction": "right",
                    },
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


@contextmanager
def _in_demo_directory() -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(HERE)
    try:
        yield
    finally:
        os.chdir(previous)


def _member_identity(source: Path, output: Path) -> dict[str, Any]:
    with zipfile.ZipFile(source) as source_zip, zipfile.ZipFile(output) as output_zip:
        source_names = {name for name in source_zip.namelist() if not name.endswith("/")}
        output_names = {name for name in output_zip.namelist() if not name.endswith("/")}
        common = sorted(source_names & output_names)
        members = []
        changed = []
        unchanged = []
        for name in common:
            source_hash = _sha256_bytes(source_zip.read(name))
            output_hash = _sha256_bytes(output_zip.read(name))
            identical = source_hash == output_hash
            members.append(
                {
                    "identical": identical,
                    "name": name,
                    "outputSha256": output_hash,
                    "sourceSha256": source_hash,
                }
            )
            (unchanged if identical else changed).append(name)
    return {
        "addedMembers": sorted(output_names - source_names),
        "changedMembers": changed,
        "memberCount": len(members),
        "members": members,
        "ok": bool(unchanged)
        and not (output_names - source_names)
        and not (source_names - output_names),
        "removedMembers": sorted(source_names - output_names),
        "unchangedMemberCount": len(unchanged),
        "unchangedMembers": unchanged,
    }


def _readback_expected() -> dict[str, str]:
    with HwpxDocument.open(EXPECTED_PATH) as document:
        fields = document.list_form_fields()
        if len(fields) != 1:
            raise AssertionError(f"expected exactly one native field, got {len(fields)}")
        project_name = fields[0]["current_value"]
        table_result = document.find_cell_by_label("담당 부서", direction="right")
        matches = table_result["matches"]
        if len(matches) != 1:
            raise AssertionError(f"expected exactly one label-cell match, got {len(matches)}")
        department = matches[0]["target_cell"]["text"]

    with HwpxAgentDocument.open(EXPECTED_PATH) as agent:
        purpose = agent.resolve_record('/section[1]/paragraph[@id="240050"]').summary[
            "text"
        ]
        owner = agent.resolve_record('/section[1]/paragraph[@id="240040"]').summary[
            "text"
        ]
    observed = {
        "bodyAnchorParagraph": str(owner),
        "canonicalParagraph": str(purpose),
        "labelCell": str(department),
        "nativeField": str(project_name),
    }
    expected = {
        "bodyAnchorParagraph": "담당자: 김서현",
        "canonicalParagraph": "행사 목적: 교내 AI 활용 사례 공유",
        "labelCell": "교육연구부",
        "nativeField": "AI 수업 나눔의 날",
    }
    if observed != expected:
        raise AssertionError(f"reopen values differ: {observed!r}")
    return observed


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def build_reference() -> dict[str, Any]:
    spec = _load_source_spec()
    _safe_unlink(DRY_OUTPUT_PATH)
    _safe_unlink(FAILURE_OUTPUT_PATH)
    _build_source(spec)
    source_revision = _sha256_file(SOURCE_PATH)
    public_plan = _public_plan(source_revision, spec)
    if public_plan["schemaVersion"] != MIXED_FORM_PLAN_SCHEMA:
        raise AssertionError("the public plan schema drifted")
    validate_mixed_form_request(public_plan)
    _write_json(PLAN_PATH, public_plan)

    source_before = SOURCE_PATH.read_bytes()
    with _in_demo_directory():
        compiled = plan_mixed_form_fill(public_plan)
        validate_mixed_form_plan(compiled)
        if compiled.to_dict()["schemaVersion"] != MIXED_FORM_COMPILED_PLAN_SCHEMA:
            raise AssertionError("the compiler returned the wrong plan schema")
        if [item.locator_kind for item in compiled.resolutions] != [
            "nativeField",
            "labelCell",
            "canonicalPath",
            "bodyAnchor",
        ]:
            raise AssertionError("the four P1 target types did not resolve in order")

        dry_request = deepcopy(public_plan)
        dry_request["output"] = DRY_OUTPUT_PATH.name
        dry_request["dryRun"] = True
        dry_request["idempotencyKey"] = "s079-mixed-anchor-reference-dry-run-v1"
        dry_result = apply_mixed_form_plan(plan_mixed_form_fill(dry_request))
        if not dry_result.ok or not dry_result.dry_run or DRY_OUTPUT_PATH.exists():
            raise AssertionError("dry-run wrote a destination or returned failure")

        failure_sentinel = b"S079 MIXED FORM FAILURE DESTINATION\n"
        FAILURE_OUTPUT_PATH.write_bytes(failure_sentinel)
        failure_before = _sha256_file(FAILURE_OUTPUT_PATH)
        failure_request = deepcopy(public_plan)
        failure_request["output"] = FAILURE_OUTPUT_PATH.name
        failure_request["idempotencyKey"] = "s079-mixed-anchor-reference-failure-v1"

        def fail_after_second_command(stage: str, index: int | None) -> None:
            if stage == "after_command" and index == 1:
                raise RuntimeError("injected S-079 reference failure")

        failure_result = apply_mixed_form_plan(
            plan_mixed_form_fill(failure_request),
            fault_injector=fail_after_second_command,
        )
        failure_after = _sha256_file(FAILURE_OUTPUT_PATH)
        if (
            failure_result.ok
            or not failure_result.rolled_back
            or failure_before != failure_after
            or FAILURE_OUTPUT_PATH.read_bytes() != failure_sentinel
        ):
            raise AssertionError("injected failure did not preserve the destination")

        _safe_unlink(EXPECTED_PATH)
        idempotency_store: dict[str, Any] = {}
        commit_result = apply_mixed_form_plan(
            compiled, idempotency_store=idempotency_store
        )
        if not commit_result.ok or commit_result.rolled_back or not EXPECTED_PATH.exists():
            raise AssertionError("reference commit failed")
        output_before_replay = _sha256_file(EXPECTED_PATH)
        replay_result = apply_mixed_form_plan(
            compiled, idempotency_store=idempotency_store
        )
        output_after_replay = _sha256_file(EXPECTED_PATH)

    if SOURCE_PATH.read_bytes() != source_before:
        raise AssertionError("the source changed during plan/apply verification")
    if not replay_result.ok or output_before_replay != output_after_replay:
        raise AssertionError("idempotent replay changed the committed output")
    replay_evidence = replay_result.verification_report.get("idempotency", {})
    if replay_evidence.get("replayed") is not True:
        raise AssertionError("idempotent replay was not reported as a replay")

    expected_hash = _sha256_file(EXPECTED_PATH)
    if commit_result.input_revision != source_revision:
        raise AssertionError("commit input revision differs from source bytes")
    if commit_result.document_revision != expected_hash:
        raise AssertionError("commit document revision differs from output bytes")
    if commit_result.verification_report.get("openSafety", {}).get("ok") is not True:
        raise AssertionError("agent verification did not pass openSafety")

    output_open_safety = validate_editor_open_safety(EXPECTED_PATH)
    source_open_safety = validate_editor_open_safety(SOURCE_PATH)
    if not output_open_safety.ok or not source_open_safety.ok:
        raise AssertionError("editor-open safety failed")
    observed = _readback_expected()

    member_identity = _member_identity(SOURCE_PATH, EXPECTED_PATH)
    byte_report = commit_result.verification_report.get("bytePreservation", {})
    reported_changed = sorted(byte_report.get("changedMembers", []))
    if (
        byte_report.get("ok") is not True
        or not member_identity["ok"]
        or reported_changed != member_identity["changedMembers"]
        or member_identity["changedMembers"] != ["Contents/section0.xml"]
        or member_identity["unchangedMemberCount"] != 10
    ):
        raise AssertionError("OPC member identity evidence disagrees with the commit")

    artifacts = {
        "output": _artifact(EXPECTED_PATH),
        "plan": _artifact(PLAN_PATH),
        "source": _artifact(SOURCE_PATH),
        "sourceSpec": _artifact(SOURCE_SPEC_PATH),
    }
    receipt: dict[str, Any] = {
        "schemaVersion": RECEIPT_SCHEMA,
        "fixture": "024-mixed-form",
        "status": "passed",
        "artifacts": artifacts,
        "contract": {
            "compiledPlanHash": compiled.plan_hash,
            "compiledRequestHash": compiled.request_hash,
            "inputRevision": compiled.input_revision,
            "operationCount": len(compiled.resolutions),
            "publicPlanSchema": public_plan["schemaVersion"],
            "resolutions": [item.to_dict() for item in compiled.resolutions],
            "singleAgentBatch": True,
            "targetKinds": [item.locator_kind for item in compiled.resolutions],
        },
        "checks": {
            "sourceOutputSeparation": {
                "ok": SOURCE_PATH.resolve() != EXPECTED_PATH.resolve(),
                "output": EXPECTED_NAME,
                "source": SOURCE_NAME,
                "sourceUnchanged": SOURCE_PATH.read_bytes() == source_before,
            },
            "dryRun": {
                "ok": dry_result.ok and dry_result.dry_run and not DRY_OUTPUT_PATH.exists(),
                "destinationWritten": DRY_OUTPUT_PATH.exists(),
            },
            "injectedFailure": {
                "destinationPreserved": failure_before == failure_after,
                "errorCode": (
                    None if failure_result.error is None else failure_result.error.code
                ),
                "ok": (not failure_result.ok)
                and failure_result.rolled_back
                and failure_before == failure_after,
                "rolledBack": failure_result.rolled_back,
            },
            "idempotentReplay": {
                "ok": replay_result.ok
                and replay_evidence.get("replayed") is True
                and output_before_replay == output_after_replay,
                "outputUnchanged": output_before_replay == output_after_replay,
                "replayed": replay_evidence.get("replayed") is True,
            },
            "opcMemberIdentity": member_identity,
            "reopen": {"ok": True, "observed": observed},
            "openSafety": {
                "ok": output_open_safety.ok,
                "output": output_open_safety.to_dict(),
                "source": source_open_safety.to_dict(),
            },
        },
        "dataPolicy": {
            "containsRealPersonalData": False,
            "containsTestMaterial": False,
            "synthetic": True,
            "syntheticNameNotice": "김서현은 기준 문서용 가상 이름입니다.",
        },
        "layout": {
            "pageIntent": int(spec["document"]["pageIntent"]),
            "realHancom": {
                "performed": False,
                "status": "pending-root-p5",
            },
        },
    }
    check_values = receipt["checks"].values()
    if not all(bool(check.get("ok")) for check in check_values):
        raise AssertionError("one or more reference checks failed")
    _write_json(RECEIPT_PATH, receipt)

    _safe_unlink(DRY_OUTPUT_PATH)
    _safe_unlink(FAILURE_OUTPUT_PATH)
    return receipt


def main() -> int:
    # The minimal synthetic package intentionally omits optional manifest
    # relations. Their fallback warnings are preserved in receipt.openSafety;
    # keep the command-line build summary focused on pass/fail evidence.
    logging.getLogger("hwpx.opc.package").setLevel(logging.ERROR)
    receipt = build_reference()
    summary = {
        "artifacts": receipt["artifacts"],
        "checks": {name: check["ok"] for name, check in receipt["checks"].items()},
        "status": receipt["status"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
