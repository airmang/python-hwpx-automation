# SPDX-License-Identifier: Apache-2.0
"""Canonical Hancom rendering owner for the automation application layer.

The package owns runtime discovery, renderer execution, serialized worker
policy, fixture orchestration, and visual-QA measurement.  ``python-hwpx``
supplies only renderer-neutral contracts and deterministic geometry helpers.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from hwpx.quality import SavePipeline
from hwpx.quality.rendering import EditMask, VisualReport

if TYPE_CHECKING:
    from .mac_session import HancomBusy, hancom_desktop_lock
    from .oracle import (
        MacHancomOracle,
        NullOracle,
        RenderBackend,
        RenderOracle,
        WindowsComOracle,
        resolve_oracle,
        visual_check,
    )

_ORACLE_EXPORTS = (
    "MacHancomOracle",
    "NullOracle",
    "RenderBackend",
    "RenderOracle",
    "WindowsComOracle",
    "resolve_oracle",
    "visual_check",
)


def __getattr__(name: str) -> Any:
    """Load the Hancom side only when someone asks for it.

    Importing this package eagerly would drag the oracle in behind any import of
    a neutral contract — ``block_splits``, ``detectors``, ``diff`` — because a
    submodule import initialises its package first. Those contracts exist so
    exam typesetting can compute question splits with no renderer present, and
    that promise is worth nothing if reaching them starts one.

    Core's ``hwpx.visual`` used the same lazy hook for the same reason. The move
    to this owner dropped it, and the boundary test caught it.
    """
    if name in _ORACLE_EXPORTS or name in {"HancomBusy", "hancom_desktop_lock"}:
        import importlib

        owner = "oracle" if name in _ORACLE_EXPORTS else "mac_session"
        return getattr(importlib.import_module(f"{__name__}.{owner}"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *_ORACLE_EXPORTS, "HancomBusy", "hancom_desktop_lock"})


def _runtime_export(name: str) -> Any:
    """Resolve a lazy export while preserving an explicit runtime patch."""

    value = globals().get(name)
    return value if value is not None else __getattr__(name)


class HancomRenderBackend:
    """Adapt a discovered Hancom render transport to the core check protocol."""

    def __init__(self, oracle: Any) -> None:
        self._oracle = oracle

    def available(self) -> bool:
        return bool(self._oracle is not None and self._oracle.available())

    def check(
        self,
        before_hwpx: str | None,
        after_hwpx: str,
        *,
        edit_mask: EditMask | None = None,
        diff_eps: float = 0.005,
        dpi: int = 150,
        work_dir: str | None = None,
        keep_artifacts: bool = False,
    ) -> VisualReport:
        # Module-dict lookup, not a direct submodule import: a test that
        # patches ``rendering.visual_check`` must still win, and __getattr__
        # only runs when the name is absent from the module dict.
        return _runtime_export("visual_check")(
            before_hwpx,
            after_hwpx,
            oracle=self._oracle,
            edit_mask=edit_mask,
            diff_eps=diff_eps,
            dpi=dpi,
            work_dir=work_dir,
            keep_artifacts=keep_artifacts,
        )


def resolve_hancom_backend(*, dpi: int = 150, **_options: Any) -> HancomRenderBackend:
    """Discover Hancom at the application boundary and return a core backend."""

    return HancomRenderBackend(resolve_hancom_oracle(dpi=dpi))


def resolve_hancom_oracle(*, dpi: int = 150, **_options: Any) -> Any:
    """Return the canonical Hancom transport at the automation boundary."""

    return _runtime_export("resolve_oracle")(dpi=dpi)


@contextmanager
def bind_document_rendering(document: Any) -> Iterator[None]:
    """Temporarily bind automation-owned rendering to one core document save."""

    sentinel = object()
    previous = getattr(document, "_save_pipeline", sentinel)
    document._save_pipeline = SavePipeline(oracle_factory=resolve_hancom_backend)
    try:
        yield
    finally:
        if previous is sentinel:
            delattr(document, "_save_pipeline")
        else:
            document._save_pipeline = previous


__all__ = [
    "HancomBusy",
    "HancomRenderBackend",
    "MacHancomOracle",
    "NullOracle",
    "RenderBackend",
    "RenderOracle",
    "WindowsComOracle",
    "bind_document_rendering",
    "hancom_desktop_lock",
    "resolve_hancom_backend",
    "resolve_hancom_oracle",
    "resolve_oracle",
    "visual_check",
]
