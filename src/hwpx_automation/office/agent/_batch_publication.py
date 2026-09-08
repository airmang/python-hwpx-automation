# SPDX-License-Identifier: Apache-2.0
"""Revision-bound publication for the existing agent command executor.

Quality remains in core SavePipeline; identity/CAS and rollback reuse the
application workspace writer. Explicit Python paths do not acquire a cwd policy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hwpx.quality import SavePipeline

from ...workspace import WorkspaceOutputGuard, WorkspaceResolver
from .model import AgentContractError


class GuardedSavePipeline(SavePipeline):
    """Application publisher carrying the identity of its own publication.

    Existing domain publishers subclass this seam so the batch can retain their
    guarded publication and recovery receipts after running their quality gate.
    """

    publication: WorkspaceOutputGuard | None = None


class _BatchSavePipeline(GuardedSavePipeline):
    def __init__(self, binding: BatchPublication) -> None:
        super().__init__()
        self.binding = binding
        self.publication = None

    def _publish(self, data: bytes, output_path: Any, output_stream: Any) -> str:
        if (
            output_stream is not None
            or Path(output_path).resolve() != self.binding.output
        ):
            raise AgentContractError(
                "verification_failed", "unexpected batch publication destination"
            )
        guard = self.binding.workspace.materialize_output_guard(
            self.binding.output_guard
        )
        try:
            self.publication = self.binding.workspace.atomic_publish_bytes(guard, data)
        except BaseException:
            self.binding.workspace.cleanup_owned_parent_directories(guard)
            raise
        return str(self.publication.path)


def _existing_parent(path: Path) -> Path:
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return parent


class BatchPublication:
    """One disposable request's input snapshot and destination precondition."""

    def __init__(self, source: Path, output: Path) -> None:
        self.source_argument = source.absolute()
        self.source = source.resolve()
        self.output = output.resolve()
        self.workspace = WorkspaceResolver.from_roots(
            [self.source.parent, _existing_parent(self.output)],
            source="agent-explicit-paths",
        )
        self.source_guard = self.workspace.capture_output(self.source)
        self.input_data = self.workspace.read_guarded_bytes(self.source_guard)
        self.output_guard = self.workspace.capture_output_precondition(self.output)
        self.output_data = (
            self.workspace.read_guarded_bytes(self.output_guard)
            if isinstance(self.output_guard, WorkspaceOutputGuard)
            and self.output_guard.target_existed
            else None
        )
        self.publisher: GuardedSavePipeline | None = None
        self.publication_attempted = False

    def assert_current_source(self) -> None:
        try:
            if self.source_argument.resolve() != self.source:
                raise OSError("source path was rebound")
            current = self.workspace.read_guarded_bytes(self.source_guard)
            if current != self.input_data:
                raise OSError("source bytes changed")
        except OSError as exc:
            raise AgentContractError(
                "stale_revision",
                "input changed during editing; read its current revision before retrying",
                target="batch.input.filename",
            ) from exc

    def publish(
        self, data: bytes, pipeline: SavePipeline, verification: dict[str, Any]
    ) -> str:
        self.assert_current_source()
        if not isinstance(pipeline, GuardedSavePipeline) and type(pipeline)._publish is not SavePipeline._publish:
            raise AgentContractError(
                "unsupported_operation",
                "custom publishers must provide an identity-bound publication receipt",
                target="savePipeline",
            )
        self.publisher = (
            pipeline
            if isinstance(pipeline, GuardedSavePipeline)
            else _BatchSavePipeline(self)
        )
        self.publisher.publication = None
        self.publication_attempted = True
        written = self.publisher._publish(data, self.output, None)
        publication = self.publisher.publication
        if publication is None:
            verification["publication"] = {
                "ok": False,
                "ownershipMissing": True,
                "rolledBack": False,
            }
            raise AgentContractError(
                "verification_failed",
                "publisher did not provide an owned output receipt",
            )
        if self.source != self.output:
            self.assert_current_source()
        if self.workspace.read_guarded_bytes(publication) != data:
            raise AgentContractError(
                "verification_failed",
                "published bytes differ from the verified candidate",
            )
        verification["publication"] = {
            "ok": True,
            "inputRechecked": True,
            "outputPreconditionChecked": True,
        }
        return str(written)

    def rollback(self, verification: dict[str, Any]) -> None:
        publication = self.publisher.publication if self.publisher is not None else None
        if publication is None:
            unchanged = not self.publication_attempted
            if not unchanged:
                try:
                    unchanged = (
                        self.workspace.capture_output_precondition(self.output)
                        == self.output_guard
                    )
                except OSError:
                    unchanged = False
            verification.setdefault(
                "publication",
                {
                    "ok": False,
                    "candidatePublished": None if self.publication_attempted else False,
                    "rolledBack": unchanged,
                },
            )
            return
        restored = False
        try:
            if self.output_data is None:
                self.workspace.remove_output(publication)
                restored = self.workspace.cleanup_owned_parent_directories(publication)
            else:
                mode = (
                    self.output_guard.target_mode
                    if isinstance(self.output_guard, WorkspaceOutputGuard)
                    else None
                )
                self.workspace.atomic_publish_bytes(
                    publication, self.output_data, mode=mode
                )
                restored = True
        except (OSError, RuntimeError):
            # The publication capability never authorizes replacing another
            # writer's newer file. Do not claim that this request rolled it back.
            pass
        verification["publication"] = {
            "ok": False,
            "candidatePublished": True,
            "rolledBack": restored,
        }
