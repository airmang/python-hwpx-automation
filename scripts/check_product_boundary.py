#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check automation application ownership and dependency direction."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

SOURCE_ROOT = "src/hwpx_automation"
FORBIDDEN_IMPORTS = ("hwpx_skill",)
CORE_VISUAL_CONTRACT_CONSUMERS = frozenset(
    {
        # Contract-only use of Block/detect_block_splits through the neutral
        # core geometry module. Runtime discovery belongs to office.rendering.
        "src/hwpx_automation/office/exam/measure.py",
    }
)
CANONICAL_RENDER_ROOT = "src/hwpx_automation/office/rendering"
# Ten since the 5.0 boundary closed. Core was still holding block_splits,
# detectors, diff and qa_contracts — and this owner imported three of them
# from there — so they came here with the rest of the rendering runtime. The
# count is a ratchet against drift, not a target; it moves when ownership
# moves, with a reason.
CANONICAL_RENDER_FILE_COUNT = 11
CANONICAL_RENDER_RESOURCES = frozenset(
    {
        "_hancom_open_rate.ps1",
        "_refresh_hwpx_mac.applescript",
        "_render_hwpx.ps1",
        "_render_hwpx_mac.applescript",
    }
)
ALLOWED_RENDERING_CORE_IMPORTS = (
    "hwpx.quality",
    "hwpx.quality.rendering",
    "hwpx.visual.block_splits",
    "hwpx.visual.detectors",
    "hwpx.visual.diff",
    "hwpx.visual.qa_contracts",
)
# Feature 049 D2: python-hwpx owns the neutral fit contract — policy, measure,
# engine, report, apply — and the companion layers import it instead of keeping a
# copy. Only its application half stays frozen: seal carries institutional rules
# and wordbox needs an imaging stack, so both belong to this layer.
FROZEN_CORE_FORM_FIT_APPLICATION = (
    "hwpx.form_fit.seal",
    "hwpx.form_fit.wordbox",
)

FROZEN_CORE_VISUAL_RUNTIME_IMPORTS = (
    *FROZEN_CORE_FORM_FIT_APPLICATION,
    "hwpx.visual.fixture_corpus",
    "hwpx.visual.hancom_worker",
    "hwpx.visual.oracle",
    "hwpx.visual.page_qa",
    "hwpx.visual.qa_metrics",
)
CANONICAL_AGENT_ROOT = "src/hwpx_automation/office/agent"
CANONICAL_AGENT_FILE_COUNT = 19
CANONICAL_AUTHORING_ROOT = "src/hwpx_automation/office/authoring"
# 17 since the 5.0 train: report_parser joined the owner it always belonged to.
CANONICAL_AUTHORING_FILE_COUNT = 17
ALLOWED_AGENT_CORE_IMPORTS = (
    "hwpx.document",
    "hwpx.mutation_report",
    "hwpx.oxml",
    "hwpx.quality",
    "hwpx.table_patch",
    "hwpx.tools.package_validator",
)
ALLOWED_AUTHORING_CORE_IMPORTS = (
    "hwpx.document",
    "hwpx.opc.package",
    "hwpx.opc.relationships",
    "hwpx.oxml.namespaces",
    "hwpx.quality",
    "hwpx.tools.archive_cli",
    "hwpx.tools.id_integrity",
    "hwpx.tools.idempotence",
    "hwpx.tools.package_reconcile",
    "hwpx.tools.package_validator",
    "hwpx.tools.report_utils",
    "hwpx.tools.table_cleanup",
    "hwpx.tools.toc_author",
    "hwpx.tools.validator",
)
TEMPORARY_AUTHORING_CORE_IMPORTS: tuple[str, ...] = ()
FROZEN_CORE_AUTHORING_IMPORTS = (
    "hwpx.authoring",
    "hwpx.builder",
    "hwpx.design",
    "hwpx.presets",
    "hwpx.tools.advanced_generators",
    "hwpx.tools.style_profile",
    "hwpx.tools.template_analyzer",
)
CANONICAL_POLICY_ROOTS = {
    "src/hwpx_automation/office/compliance": ("hwpx.document",),
    "src/hwpx_automation/office/quality": ("hwpx",),
    "src/hwpx_automation/office/utilities": (),
}
FROZEN_CORE_POLICY_IMPORTS = (
    "hwpx.tools.official_lint",
    "hwpx.tools.pii",
    "hwpx.tools.page_guard",
    "hwpx.tools.table_compute",
)
CANONICAL_FORM_FILL_ROOT = "src/hwpx_automation/office/form_fill"
CANONICAL_FORM_FILL_FILE_COUNT = 15
ALLOWED_FORM_FILL_CORE_IMPORTS = (
    "hwpx.document",
    # Feature 049 D2: the neutral fit contract is core's, and this owner imports
    # it rather than keeping a second copy. Named module by module on purpose —
    # the package root re-exports seal and wordbox, which are application code.
    "hwpx.form_fit.apply",
    "hwpx.form_fit.engine",
    "hwpx.form_fit.measure",
    "hwpx.form_fit.policy",
    "hwpx.form_fit.report",
    "hwpx.oxml.namespaces",
    "hwpx.quality",
    "hwpx.table_patch",
    "hwpx.tools.package_validator",
    "hwpx.tools.validator",
)
TEMPORARY_FORM_FILL_CORE_IMPORTS: tuple[str, ...] = ()
FROZEN_CORE_FORM_FILL_IMPORTS = (
    "hwpx.fill_residue",
    "hwpx.form_fill",
    # The package root stays frozen because importing it pulls in seal and
    # wordbox; those two remain application code owned here.
    "hwpx.form_fit.seal",
    "hwpx.form_fit.wordbox",
    "hwpx.formfill_quality",
    "hwpx.guidance_scan",
    "hwpx.template_formfit",
)
CANONICAL_EVALPLAN_ROOT = "src/hwpx_automation/office/evalplan"
CANONICAL_EVALPLAN_FILE_COUNT = 2
ALLOWED_EVALPLAN_CORE_IMPORTS = (
    "hwpx.body_patch",
    "hwpx.patch",
    "hwpx.table_patch",
)
FROZEN_CORE_EVALPLAN_IMPORTS = ("hwpx.evalplan_fill",)
CANONICAL_EXAM_ROOT = "src/hwpx_automation/office/exam"
CANONICAL_EXAM_FILE_COUNT = 6
ALLOWED_EXAM_CORE_IMPORTS = (
    "hwpx.document",
    "hwpx.oxml",
    "hwpx.tools.table_cleanup",
    "hwpx.visual.block_splits",
)
FROZEN_CORE_EXAM_IMPORTS = (
    "hwpx.exam",
    *FROZEN_CORE_FORM_FIT_APPLICATION,
)
CANONICAL_DOCUMENT_OPS_ROOT = "src/hwpx_automation/office/document_ops"
CANONICAL_DOCUMENT_OPS_FILE_COUNT = 4
ALLOWED_DOCUMENT_OPS_CORE_IMPORTS = (
    "hwpx.document",
    "hwpx.quality.rendering",
    "hwpx.tools.doc_diff",
    "hwpx.tools.mail_merge",
    "hwpx.tools.redline",
)
# Feature 049 D2: the ban targets core's *application* callables, not its neutral
# contracts. hwpx.tools.redline.verify_redline used to resolve a Hancom oracle
# itself, which made calling it a boundary violation. It no longer does — it
# inspects structure and delegates rendering to an injected RenderBackend — so
# the canonical owner calls it and supplies the backend instead of keeping a
# second copy of the same judgement. build_comparison_table_plan and mail_merge
# stay frozen: those still carry application policy.
FROZEN_CORE_DOCUMENT_OPS_CALLABLES = {
    "hwpx": frozenset({"build_comparison_table_plan", "mail_merge"}),
    "hwpx.tools.doc_diff": frozenset({"build_comparison_table_plan"}),
    "hwpx.tools.mail_merge": frozenset({"mail_merge"}),
}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _imported_members(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    members: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            members.extend((node.module, alias.name) for alias in node.names)
    return members


def _policy_owner_import_violation(
    relative: str,
    imported: str,
) -> str | None:
    for root, allowed_imports in CANONICAL_POLICY_ROOTS.items():
        if relative == f"{root}.py" or relative.startswith(f"{root}/"):
            if any(
                imported == frozen or imported.startswith(f"{frozen}.")
                for frozen in FROZEN_CORE_POLICY_IMPORTS
            ):
                return (
                    "canonical policy owner imports frozen core compatibility "
                    f"copy: {relative} -> {imported}"
                )
            if imported == "hwpx" or imported.startswith("hwpx."):
                if not any(
                    imported == allowed
                    or (allowed != "hwpx" and imported.startswith(f"{allowed}."))
                    for allowed in allowed_imports
                ):
                    return (
                        "canonical policy owner uses unapproved core seam: "
                        f"{relative} -> {imported}"
                    )
            return None
    return None


def _form_fill_owner_import_violation(
    relative: str,
    imported: str,
) -> str | None:
    if not (
        relative == f"{CANONICAL_FORM_FILL_ROOT}.py"
        or relative.startswith(f"{CANONICAL_FORM_FILL_ROOT}/")
    ):
        return None
    if any(
        imported == frozen or imported.startswith(f"{frozen}.")
        for frozen in FROZEN_CORE_FORM_FILL_IMPORTS
    ):
        return (
            "canonical form-fill owner imports frozen core compatibility "
            f"copy: {relative} -> {imported}"
        )
    if imported == "hwpx" or imported.startswith("hwpx."):
        if not any(
            imported == allowed or imported.startswith(f"{allowed}.")
            for allowed in ALLOWED_FORM_FILL_CORE_IMPORTS
        ):
            return (
                "canonical form-fill owner uses unapproved core seam: "
                f"{relative} -> {imported}"
            )
    return None


def _evalplan_owner_import_violation(
    relative: str,
    imported: str,
) -> str | None:
    if not (
        relative == f"{CANONICAL_EVALPLAN_ROOT}.py"
        or relative.startswith(f"{CANONICAL_EVALPLAN_ROOT}/")
    ):
        return None
    if any(
        imported == frozen or imported.startswith(f"{frozen}.")
        for frozen in FROZEN_CORE_EVALPLAN_IMPORTS
    ):
        return (
            "canonical evalplan owner imports frozen core compatibility "
            f"copy: {relative} -> {imported}"
        )
    if imported == "hwpx" or imported.startswith("hwpx."):
        if not any(
            imported == allowed or imported.startswith(f"{allowed}.")
            for allowed in ALLOWED_EVALPLAN_CORE_IMPORTS
        ):
            return (
                "canonical evalplan owner uses unapproved core seam: "
                f"{relative} -> {imported}"
            )
    return None


def _exam_owner_import_violation(
    relative: str,
    imported: str,
) -> str | None:
    if not (
        relative == f"{CANONICAL_EXAM_ROOT}.py"
        or relative.startswith(f"{CANONICAL_EXAM_ROOT}/")
    ):
        return None
    if any(
        imported == frozen or imported.startswith(f"{frozen}.")
        for frozen in FROZEN_CORE_EXAM_IMPORTS
    ):
        return (
            "canonical exam owner imports frozen core compatibility "
            f"copy: {relative} -> {imported}"
        )
    if imported == "hwpx" or imported.startswith("hwpx."):
        if not any(
            imported == allowed or imported.startswith(f"{allowed}.")
            for allowed in ALLOWED_EXAM_CORE_IMPORTS
        ):
            return (
                "canonical exam owner uses unapproved core seam: "
                f"{relative} -> {imported}"
            )
    return None


def _rendering_owner_import_violation(
    relative: str,
    imported: str,
) -> str | None:
    """Reject runtime copies and unapproved core seams in the automation owner."""

    if not (
        relative == f"{CANONICAL_RENDER_ROOT}.py"
        or relative.startswith(f"{CANONICAL_RENDER_ROOT}/")
    ):
        return None
    if any(
        imported == frozen or imported.startswith(f"{frozen}.")
        for frozen in FROZEN_CORE_VISUAL_RUNTIME_IMPORTS
    ):
        return (
            "canonical rendering owner imports frozen core compatibility "
            f"runtime: {relative} -> {imported}"
        )
    if imported == "hwpx" or imported.startswith("hwpx."):
        if not any(
            imported == allowed or imported.startswith(f"{allowed}.")
            for allowed in ALLOWED_RENDERING_CORE_IMPORTS
        ):
            return (
                "canonical rendering owner uses unapproved core seam: "
                f"{relative} -> {imported}"
            )
    return None


def _document_ops_owner_import_violation(
    relative: str,
    imported: str,
) -> str | None:
    if not relative.startswith(f"{CANONICAL_DOCUMENT_OPS_ROOT}/"):
        return None
    if imported == "hwpx" or imported.startswith("hwpx."):
        if not any(
            imported == allowed or imported.startswith(f"{allowed}.")
            for allowed in ALLOWED_DOCUMENT_OPS_CORE_IMPORTS
        ):
            return (
                "canonical document-ops owner uses unapproved core seam: "
                f"{relative} -> {imported}"
            )
    return None


def evaluate(root: Path) -> dict[str, Any]:
    violations: list[str] = []
    source = root / SOURCE_ROOT
    files = sorted(source.rglob("*.py"))

    if (root / "src" / "hwpx").exists():
        violations.append("automation repository must not own or vendor src/hwpx")
    render_root = root / CANONICAL_RENDER_ROOT
    render_files = sorted(render_root.rglob("*.py"))
    if len(render_files) != CANONICAL_RENDER_FILE_COUNT:
        violations.append(
            "canonical rendering owner must contain exactly "
            f"{CANONICAL_RENDER_FILE_COUNT} Python files: {CANONICAL_RENDER_ROOT}"
        )
    render_resources = {
        path.name
        for path in render_root.iterdir()
        if path.is_file() and path.suffix in {".ps1", ".applescript"}
    } if render_root.is_dir() else set()
    if render_resources != CANONICAL_RENDER_RESOURCES:
        violations.append(
            "canonical rendering resources must match the frozen inventory: "
            f"{CANONICAL_RENDER_ROOT}"
        )
    agent_files = sorted((root / CANONICAL_AGENT_ROOT).rglob("*.py"))
    if len(agent_files) != CANONICAL_AGENT_FILE_COUNT:
        violations.append(
            "canonical agent owner must contain exactly "
            f"{CANONICAL_AGENT_FILE_COUNT} Python files: {CANONICAL_AGENT_ROOT}"
        )
    authoring_files = sorted((root / CANONICAL_AUTHORING_ROOT).rglob("*.py"))
    if len(authoring_files) != CANONICAL_AUTHORING_FILE_COUNT:
        violations.append(
            "canonical authoring owner must contain exactly "
            f"{CANONICAL_AUTHORING_FILE_COUNT} Python files: "
            f"{CANONICAL_AUTHORING_ROOT}"
        )
    form_fill_files = sorted((root / CANONICAL_FORM_FILL_ROOT).rglob("*.py"))
    if len(form_fill_files) != CANONICAL_FORM_FILL_FILE_COUNT:
        violations.append(
            "canonical form-fill owner must contain exactly "
            f"{CANONICAL_FORM_FILL_FILE_COUNT} Python files: "
            f"{CANONICAL_FORM_FILL_ROOT}"
        )
    evalplan_files = sorted((root / CANONICAL_EVALPLAN_ROOT).rglob("*.py"))
    if len(evalplan_files) != CANONICAL_EVALPLAN_FILE_COUNT:
        violations.append(
            "canonical evalplan owner must contain exactly "
            f"{CANONICAL_EVALPLAN_FILE_COUNT} Python files: "
            f"{CANONICAL_EVALPLAN_ROOT}"
        )
    exam_files = sorted((root / CANONICAL_EXAM_ROOT).rglob("*.py"))
    if len(exam_files) != CANONICAL_EXAM_FILE_COUNT:
        violations.append(
            "canonical exam owner must contain exactly "
            f"{CANONICAL_EXAM_FILE_COUNT} Python files: "
            f"{CANONICAL_EXAM_ROOT}"
        )
    document_ops_files = sorted(
        (root / CANONICAL_DOCUMENT_OPS_ROOT).rglob("*.py")
    )
    if len(document_ops_files) != CANONICAL_DOCUMENT_OPS_FILE_COUNT:
        violations.append(
            "canonical document-ops owner must contain exactly "
            f"{CANONICAL_DOCUMENT_OPS_FILE_COUNT} Python files: "
            f"{CANONICAL_DOCUMENT_OPS_ROOT}"
        )

    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            imports = _imports(path)
        except (OSError, SyntaxError) as exc:
            violations.append(f"could not inspect {relative}: {exc}")
            continue
        for imported, member in _imported_members(path):
            frozen_members = FROZEN_CORE_DOCUMENT_OPS_CALLABLES.get(imported)
            if frozen_members is not None and member in frozen_members:
                violations.append(
                    "automation production imports frozen core document-ops callable: "
                    f"{relative} -> {imported}.{member}"
                )
        for imported in imports:
            if any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORTS
            ):
                violations.append(
                    f"automation imports skill implementation: {relative} -> {imported}"
                )
            rendering_violation = _rendering_owner_import_violation(
                relative,
                imported,
            )
            if rendering_violation is not None:
                violations.append(rendering_violation)
            elif any(
                imported == frozen or imported.startswith(f"{frozen}.")
                for frozen in FROZEN_CORE_VISUAL_RUNTIME_IMPORTS
            ):
                if imported == "hwpx.visual.oracle":
                    violations.append(
                        "new direct render discovery bypasses office adapter: "
                        f"{relative}"
                    )
                else:
                    violations.append(
                        "automation production imports frozen core visual runtime: "
                        f"{relative} -> {imported}"
                    )
            if imported == "hwpx.agent" or imported.startswith("hwpx.agent."):
                violations.append(
                    "automation production imports frozen core agent copy: "
                    f"{relative} -> {imported}"
                )
            if any(
                imported == frozen or imported.startswith(f"{frozen}.")
                for frozen in FROZEN_CORE_AUTHORING_IMPORTS
            ):
                violations.append(
                    "automation production imports frozen core authoring copy: "
                    f"{relative} -> {imported}"
                )
            if any(
                imported == frozen or imported.startswith(f"{frozen}.")
                for frozen in FROZEN_CORE_POLICY_IMPORTS
            ):
                violations.append(
                    "automation production imports frozen core policy copy: "
                    f"{relative} -> {imported}"
                )
            if any(
                imported == frozen or imported.startswith(f"{frozen}.")
                for frozen in FROZEN_CORE_FORM_FILL_IMPORTS
            ):
                violations.append(
                    "automation production imports frozen core form-fill copy: "
                    f"{relative} -> {imported}"
                )
            if any(
                imported == frozen or imported.startswith(f"{frozen}.")
                for frozen in FROZEN_CORE_EVALPLAN_IMPORTS
            ):
                violations.append(
                    "automation production imports frozen core evalplan copy: "
                    f"{relative} -> {imported}"
                )
            if any(
                imported == frozen or imported.startswith(f"{frozen}.")
                for frozen in FROZEN_CORE_EXAM_IMPORTS
            ):
                violations.append(
                    "automation production imports frozen core exam copy: "
                    f"{relative} -> {imported}"
                )
            if relative.startswith(f"{CANONICAL_AGENT_ROOT}/") and (
                imported == "hwpx" or imported.startswith("hwpx.")
            ):
                if not any(
                    imported == allowed or imported.startswith(f"{allowed}.")
                    for allowed in ALLOWED_AGENT_CORE_IMPORTS
                ):
                    violations.append(
                        f"canonical agent uses unapproved core seam: {relative} -> {imported}"
                    )
            if relative.startswith(f"{CANONICAL_AUTHORING_ROOT}/") and (
                imported == "hwpx" or imported.startswith("hwpx.")
            ):
                approved = (
                    ALLOWED_AUTHORING_CORE_IMPORTS + TEMPORARY_AUTHORING_CORE_IMPORTS
                )
                if not any(
                    imported == allowed or imported.startswith(f"{allowed}.")
                    for allowed in approved
                ):
                    violations.append(
                        "canonical authoring uses unapproved core seam: "
                        f"{relative} -> {imported}"
                    )
            policy_violation = _policy_owner_import_violation(
                relative,
                imported,
            )
            if policy_violation is not None:
                violations.append(policy_violation)
            form_fill_violation = _form_fill_owner_import_violation(
                relative,
                imported,
            )
            if form_fill_violation is not None:
                violations.append(form_fill_violation)
            evalplan_violation = _evalplan_owner_import_violation(
                relative,
                imported,
            )
            if evalplan_violation is not None:
                violations.append(evalplan_violation)
            exam_violation = _exam_owner_import_violation(
                relative,
                imported,
            )
            if exam_violation is not None:
                violations.append(exam_violation)
            document_ops_violation = _document_ops_owner_import_violation(
                relative,
                imported,
            )
            if document_ops_violation is not None:
                violations.append(document_ops_violation)

    return {
        "ok": not violations,
        "pythonFiles": len(files),
        "canonicalRenderingRoot": CANONICAL_RENDER_ROOT,
        "canonicalRenderingPythonFiles": len(render_files),
        "canonicalRenderingResources": sorted(render_resources),
        "allowedRenderingCoreImports": list(ALLOWED_RENDERING_CORE_IMPORTS),
        "frozenCoreVisualRuntimeImports": list(
            FROZEN_CORE_VISUAL_RUNTIME_IMPORTS
        ),
        "canonicalAgentRoot": CANONICAL_AGENT_ROOT,
        "canonicalAgentPythonFiles": len(agent_files),
        "allowedAgentCoreImports": list(ALLOWED_AGENT_CORE_IMPORTS),
        "canonicalAuthoringRoot": CANONICAL_AUTHORING_ROOT,
        "canonicalAuthoringPythonFiles": len(authoring_files),
        "allowedAuthoringCoreImports": list(ALLOWED_AUTHORING_CORE_IMPORTS),
        "temporaryAuthoringCoreImports": list(TEMPORARY_AUTHORING_CORE_IMPORTS),
        "frozenCoreAuthoringImports": list(FROZEN_CORE_AUTHORING_IMPORTS),
        "canonicalPolicyRoots": {
            root: list(imports) for root, imports in CANONICAL_POLICY_ROOTS.items()
        },
        "frozenCorePolicyImports": list(FROZEN_CORE_POLICY_IMPORTS),
        "canonicalFormFillRoot": CANONICAL_FORM_FILL_ROOT,
        "canonicalFormFillPythonFiles": len(form_fill_files),
        "allowedFormFillCoreImports": list(ALLOWED_FORM_FILL_CORE_IMPORTS),
        "temporaryFormFillCoreImports": list(TEMPORARY_FORM_FILL_CORE_IMPORTS),
        "frozenCoreFormFillImports": list(FROZEN_CORE_FORM_FILL_IMPORTS),
        "canonicalEvalplanRoot": CANONICAL_EVALPLAN_ROOT,
        "canonicalEvalplanPythonFiles": len(evalplan_files),
        "allowedEvalplanCoreImports": list(ALLOWED_EVALPLAN_CORE_IMPORTS),
        "frozenCoreEvalplanImports": list(FROZEN_CORE_EVALPLAN_IMPORTS),
        "canonicalExamRoot": CANONICAL_EXAM_ROOT,
        "canonicalExamPythonFiles": len(exam_files),
        "allowedExamCoreImports": list(ALLOWED_EXAM_CORE_IMPORTS),
        "frozenCoreExamImports": list(FROZEN_CORE_EXAM_IMPORTS),
        "canonicalDocumentOpsRoot": CANONICAL_DOCUMENT_OPS_ROOT,
        "canonicalDocumentOpsPythonFiles": len(document_ops_files),
        "allowedDocumentOpsCoreImports": list(
            ALLOWED_DOCUMENT_OPS_CORE_IMPORTS
        ),
        "frozenCoreDocumentOpsCallables": {
            module: sorted(names)
            for module, names in FROZEN_CORE_DOCUMENT_OPS_CALLABLES.items()
        },
        "coreVisualContractConsumers": sorted(CORE_VISUAL_CONTRACT_CONSUMERS),
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args(argv)
    report = evaluate(args.root.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
