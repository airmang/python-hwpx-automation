# SPDX-License-Identifier: Apache-2.0
"""Drive the minimal profile over stdio without a model — a pre-flight check.

    python scripts/minimal_profile_smoke.py <path to hwpx-automation-mcp> <work dir>

Stages a short Markdown body in two chunks, creates a document from it, reads
the outline, edits one table cell by id and validates the result. Every line
it prints is one tool result; the last call is meant to fail (bad arguments).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(server: str, work: Path) -> int:
    work.mkdir(parents=True, exist_ok=True)
    params = StdioServerParameters(
        command=server, args=["--profile", "minimal"], cwd=str(work)
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        tools = [tool.name for tool in (await client.list_tools()).tools]
        print("tools:", tools)

        async def call(name: str, args: dict) -> dict:
            result = await client.call_tool(name, args)
            data = json.loads(result.content[0].text)
            print(
                f"{name}: isError={result.isError}",
                json.dumps(data, ensure_ascii=False)[:200],
            )
            return data

        draft = await call(
            "stage_text",
            {"text": "# 현장체험학습 안내\n\n학부모님께 알려 드립니다.\n\n"},
        )
        await call(
            "stage_text",
            {
                "text": "| 항목 | 내용 |\n|---|---|\n| 일시 | 11월 20일 |\n| 장소 | 국립과학관 |\n",
                "draft_id": draft["draftId"],
            },
        )
        made = await call(
            "create_from_markdown",
            {"draft_id": draft["draftId"], "output": str(work / "notice.hwpx")},
        )
        outline = await call("read_outline", {"path": made["output"]})
        line = next(
            line
            for line in outline["outline"].splitlines()
            if line.endswith("국립과학관")
        )
        edited = await call(
            "apply_text_changes",
            {
                "path": made["output"],
                "changes": {line[1 : line.index("]")]: "국립중앙과학관"},
            },
        )
        checked = await call("validate_document", {"path": edited["output"]})
        bad = await call("create_from_markdown", {"output": str(work / "x.hwpx")})
        ok = (
            len(tools) == 6
            and made["ok"]
            and edited["changed"] == 1
            and checked["ok"]
            and bad["ok"] is False
        )
        print("SMOKE", "PASS" if ok else "FAIL")
        return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(sys.argv[1], Path(sys.argv[2]).resolve())))
