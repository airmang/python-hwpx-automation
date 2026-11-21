# SPDX-License-Identifier: Apache-2.0
"""Static metadata used for hardened tool responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ExampleTemplate:
    tool: str
    example_json: str

    def render(self, plan_id: str) -> Dict[str, str]:
        return {
            "tool": self.tool,
            "exampleJson": self.example_json.replace("<plan-id>", plan_id),
        }


PLAN_NEXT_ACTION = ExampleTemplate(
    tool="hwpx.preview_edit",
    example_json='{"planId":"<plan-id>"}',
)

PREVIEW_NEXT_ACTION = ExampleTemplate(
    tool="hwpx.apply_edit",
    example_json='{"planId":"<plan-id>","confirm":true}',
)

APPLY_BAD_EXAMPLE = ExampleTemplate(
    tool="hwpx.apply_edit",
    example_json='{"planId":"<plan-id>"}',
)

ERROR_PREVIEW_REQUIRED = ExampleTemplate(
    tool="hwpx.preview_edit",
    example_json='{"planId":"<plan-id>"}',
)
