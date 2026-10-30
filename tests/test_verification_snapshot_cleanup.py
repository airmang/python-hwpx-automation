# SPDX-License-Identifier: Apache-2.0
"""Narrow #78 investigation: same-inode chmod/rewrite under descriptor CAS."""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpx_automation.workspace import WorkspaceResolver, _descriptor_cas_supported


@pytest.mark.skipif(not _descriptor_cas_supported(), reason="requires POSIX atomic descriptor CAS")
@pytest.mark.parametrize("rewritten", [b"original", b"rewritten"])
def test_mode_changed_snapshot_can_be_recaptured_and_removed(tmp_path: Path, rewritten: bytes) -> None:
    workspace = WorkspaceResolver.from_roots([tmp_path])
    path = tmp_path / ".hwpx-verify-output.hwpx"
    publication = workspace.atomic_publish_bytes(
        workspace.capture_output(path, create_parents=False), b"original", mode=0o400
    )
    path.chmod(0o600)
    path.write_bytes(rewritten)

    # This is the verifier's actual recovery exception tuple, not a broader
    # catch in the test. A mode/digest mismatch must enter its recovery path.
    try:
        workspace.remove_output(publication)
    except (OSError, RuntimeError):
        pass
    else:
        pytest.fail("the stale publication guard must reject a mutated snapshot")

    current = workspace.capture_output(path, create_parents=False)
    assert (current.target_device, current.target_inode) == (publication.target_device, publication.target_inode)
    workspace.remove_output(current)
    assert list(tmp_path.iterdir()) == []
