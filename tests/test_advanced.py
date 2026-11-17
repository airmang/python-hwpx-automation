import importlib

import pytest

from hwpx_automation.fastmcp_adapter import snapshot_runtime_tools


@pytest.fixture(autouse=True)
def enable_advanced(monkeypatch):
    """고급 도구 테스트 시 환경변수 설정.

    시험이 고급 도구를 켠 채 서버 모듈을 다시 불러오므로, 끝나면 환경 변수를 되돌리고
    서버 모듈을 한 번 더 불러와 같은 일꾼에서 뒤에 도는 시험이 기본 도구 목록을 보게 한다.
    """
    monkeypatch.setenv("HWPX_MCP_ADVANCED", "1")
    yield
    monkeypatch.undo()
    import hwpx_automation.server as server

    importlib.reload(server)


def test_package_parts(tmp_path):
    import hwpx_automation.server as server
    server = importlib.reload(server)

    target = tmp_path / "test.hwpx"
    server.create_document(str(target))

    result = server.package_parts(str(target))

    assert "parts" in result
    assert "Contents/content.hpf" in result["parts"]


def test_package_get_xml_truncation(tmp_path):
    import hwpx_automation.server as server
    server = importlib.reload(server)

    target = tmp_path / "test.hwpx"
    server.create_document(str(target))

    result = server.package_get_xml(str(target), "Contents/section0.xml", max_chars=100)

    assert result["truncated"] is True
    assert len(result["text"]) == 100


def test_advanced_tools_hidden_by_default(monkeypatch):
    """HWPX_MCP_ADVANCED 미설정 시 고급 도구가 등록되지 않는지 확인"""
    monkeypatch.delenv("HWPX_MCP_ADVANCED", raising=False)
    import hwpx_automation.server as server

    reloaded = importlib.reload(server)
    tool_names = set(snapshot_runtime_tools(reloaded.mcp))

    assert "package_parts" not in tool_names


def test_object_find_by_attr_matches_any_value_when_attr_value_omitted(tmp_path):
    import hwpx_automation.server as server
    server = importlib.reload(server)

    target = tmp_path / "test.hwpx"
    server.create_document(str(target))
    server.add_paragraph(str(target), "attribute target")

    result = server.object_find_by_attr(str(target), "pageBreak")

    assert result["objects"]
    assert all("pageBreak" in obj["attrs"] for obj in result["objects"])


# The plan_edit/preview_edit/apply_edit verification-flow tools were removed at
# the 5.0.0 major boundary (S-091); the underlying verification-plan engine is
# still exercised directly through HwpxOps in tests/test_hwpx_ops.py. Their MCP
# surface absence is asserted in tests/test_tool_contract.py.
