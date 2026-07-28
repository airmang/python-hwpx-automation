from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_STACK_TABLE = """\
| | 저장소 | 역할 |
|---|---|---|
| 📦 | [`python-hwpx`](https://github.com/airmang/python-hwpx) | HWPX 문서를 읽고·고치고·만드는 순수 파이썬 엔진 |
| 🔌 | [`python-hwpx-automation`](https://github.com/airmang/python-hwpx-automation) | 저작·양식 채움 워크플로, `hwpx` CLI, 선택형 MCP 서버 |
| 🎯 | [`hwpx-plugins`](https://github.com/airmang/hwpx-plugins) | 에이전트가 알맞은 도구를 고르도록 돕는 플러그인/스킬 번들 |\
"""


def test_readme_uses_the_canonical_three_stack_table() -> None:
    assert CANONICAL_STACK_TABLE in (ROOT / "README.md").read_text(encoding="utf-8")
