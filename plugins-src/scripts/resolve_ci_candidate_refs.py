#!/usr/bin/env python3
"""Resolve the python-hwpx / python-hwpx-automation commits the Tests job checks out.

Order of authority:

1. explicit ``workflow_dispatch`` inputs or the repository variables
   (``HWPX_CORE_CANDIDATE_REF`` / ``HWPX_AUTOMATION_CANDIDATE_REF``) — the
   reviewed candidate commits; both must be exact 40-hex SHAs;
2. only for ``pull_request`` runs from a fork, where GitHub does not pass the
   ``vars`` context: the public release tags of the stack this tree declares as
   its candidate in ``packaging/product-identity.json``, resolved to commits
   with ``git ls-remote``. If those tags do not exist yet (unpublished
   candidate), the run fails with a message pointing at maintainer dispatch;
3. anything else (same-repository runs without refs) fails hard, unchanged.

Results are appended to ``$GITHUB_OUTPUT`` as ``core_ref``, ``automation_ref``,
``automation_repository`` and ``source``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "packaging" / "product-identity.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_AUTOMATION_REPOSITORY = "airmang/hwpx-mcp-server"
RELEASE_OWNER = "airmang"


class ResolutionError(Exception):
    """A refusal to run the job, rendered as a GitHub ``::error::``."""


TagResolver = Callable[[str, str], "str | None"]


def ls_remote_tag(repository: str, tag: str) -> str | None:
    """Return the commit a public tag points at (peeled for annotated tags)."""
    url = f"https://github.com/{repository}.git"
    result = subprocess.run(
        ["git", "ls-remote", "--tags", url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    refs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        refs[ref.strip()] = sha.strip()
    return refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")


def _is_fork_pull_request(env: Mapping[str, str]) -> bool:
    if env.get("EVENT_NAME") != "pull_request":
        return False
    head = env.get("HEAD_REPOSITORY", "")
    return head != env.get("BASE_REPOSITORY", "")


def _explicit(env: Mapping[str, str]) -> dict[str, str]:
    core = env.get("CORE_CANDIDATE_REF", "")
    automation = env.get("AUTOMATION_CANDIDATE_REF", "")
    if not core:
        raise ResolutionError(
            "Set workflow input core_ref or HWPX_CORE_CANDIDATE_REF to the reviewed candidate commit."
        )
    if not automation:
        raise ResolutionError(
            "Set workflow input automation_ref or HWPX_AUTOMATION_CANDIDATE_REF to the reviewed candidate commit."
        )
    if not SHA_RE.match(core):
        raise ResolutionError(
            "core_ref must be an exact lowercase 40-hex commit, not a branch or guessed SHA."
        )
    if not SHA_RE.match(automation):
        raise ResolutionError(
            "automation_ref must be an exact lowercase 40-hex commit, not a branch or guessed SHA."
        )
    return {
        "core_ref": core,
        "automation_ref": automation,
        "automation_repository": env.get("AUTOMATION_CANDIDATE_REPOSITORY")
        or DEFAULT_AUTOMATION_REPOSITORY,
        "source": "candidate-refs",
    }


def _released_tags(identity: dict, resolve_tag: TagResolver) -> dict[str, str]:
    candidate = identity["releaseState"]["candidate"]
    components = identity["components"]
    core_repo = f"{RELEASE_OWNER}/{components['core']['repository']}"
    automation_repo = f"{RELEASE_OWNER}/{components['automation']['repository']}"
    wanted = (
        ("core_ref", core_repo, f"v{candidate['pythonHwpx']}"),
        ("automation_ref", automation_repo, f"v{candidate['canonicalAutomation']}"),
    )
    resolved: dict[str, str] = {}
    for key, repository, tag in wanted:
        sha = resolve_tag(repository, tag)
        if not sha or not SHA_RE.match(sha):
            raise ResolutionError(
                f"Fork pull requests do not receive repository variables, and {repository} has no "
                f"public tag {tag} for the candidate this tree declares. A maintainer must run the "
                "Tests workflow by workflow_dispatch with explicit core_ref/automation_ref."
            )
        resolved[key] = sha
    resolved["automation_repository"] = automation_repo
    resolved["source"] = "released-tags"
    return resolved


def resolve(
    env: Mapping[str, str],
    identity: dict,
    resolve_tag: TagResolver = ls_remote_tag,
) -> dict[str, str]:
    has_explicit = bool(env.get("CORE_CANDIDATE_REF") or env.get("AUTOMATION_CANDIDATE_REF"))
    if has_explicit or not _is_fork_pull_request(env):
        return _explicit(env)
    return _released_tags(identity, resolve_tag)


def main() -> int:
    identity = json.loads(IDENTITY.read_text(encoding="utf-8"))
    try:
        refs = resolve(os.environ, identity)
    except ResolutionError as exc:
        print(f"::error::{exc}")
        return 2
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"::error::could not resolve public release tags: {exc}")
        return 2
    if refs["source"] == "released-tags":
        print(
            "::notice::Fork pull request: repository variables are unavailable, so this run "
            "tests against the public release tags of the declared candidate stack "
            f"(core {refs['core_ref']}, automation {refs['automation_ref']})."
        )
    output = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{key}={value}\n" for key, value in refs.items())
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(lines)
    else:
        sys.stdout.write(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
