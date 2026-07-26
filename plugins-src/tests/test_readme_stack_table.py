from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_STACK_TABLE = """\
| 계층 | 저장소 | 정본 책임 |
|---|---|---|
| Core | [`python-hwpx`](https://github.com/airmang/python-hwpx) | HWPX package/object model·OPC/OXML·직렬화·재사용 primitive |
| Automation | [`python-hwpx-automation`](https://github.com/airmang/python-hwpx-automation) | Python 자동화·워크플로·profile/policy·렌더·선택형 MCP adapter |
| Judgment | [`hwpx-plugins`](https://github.com/airmang/hwpx-plugins) | 에이전트 intent/genre 판단·ambiguity 처리·plugin/skill 가이드 |\
"""


def test_readme_uses_the_canonical_three_stack_table() -> None:
    assert CANONICAL_STACK_TABLE in (ROOT / "README.md").read_text(encoding="utf-8")
