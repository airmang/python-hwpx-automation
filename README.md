[![MCP Toplist](https://mcptoplist.com/badge/smithery%2Fairmang%2Fhwpx-mcp-server.svg)](https://mcptoplist.com/server/smithery%2Fairmang%2Fhwpx-mcp-server)

<p align="center">
  <h1 align="center">python-hwpx-automation</h1>
  <p align="center">
    <strong>HWPX 저작·양식 채움·업무 워크플로를 위한 Python 자동화 계층</strong>
  </p>
  <p align="center">
    <a href="https://pypi.org/project/python-hwpx-automation/"><img src="https://img.shields.io/pypi/v/python-hwpx-automation?color=blue&label=PyPI" alt="PyPI"></a>
    <a href="https://pepy.tech/project/python-hwpx-automation"><img src="https://static.pepy.tech/badge/python-hwpx-automation/month" alt="Downloads"></a>
    <a href="https://pypi.org/project/python-hwpx-automation/"><img src="https://img.shields.io/pypi/pyversions/python-hwpx-automation" alt="Python"></a>
    <a href="https://github.com/airmang/python-hwpx-automation/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/airmang/python-hwpx-automation/tests.yml?branch=main&label=tests" alt="Tests"></a>
    <a href="https://github.com/airmang/python-hwpx-automation/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License"></a>
  </p>
</p>

<!-- release-state: released -->
> [!NOTE]
> 공개 트레인: `python-hwpx 6.0.2 → python-hwpx-automation 7.0.1 →
> hwpx-plugin 2.0.0` (released 2026-08-04, 엔진 완전성 트레인 — 계약
> `34a91560759dc47a`). 공개 좌표는 원격 진실(core·automation PyPI와
> plugin GitHub
> Release·marketplace·실제 marketplace 설치) 관찰 후에만
> 승격됩니다 — [릴리스 runbook](docs/release-runbook.md)

[python-hwpx](https://github.com/airmang/python-hwpx) 엔진 위에서 문서 저작·
양식 채움·시험지 조판·안전한 에이전트 워크플로를 제공하는 응용 계층입니다.
기본 설치는 MCP 없이 Python API와 `hwpx` CLI로 쓰고,
[모델 컨텍스트 프로토콜(MCP)](https://modelcontextprotocol.io) 서버는 필요할 때
`[mcp]` extra로 더합니다. 한컴오피스도 Windows도 필요 없으므로 **파이썬이 도는
ChatGPT 채팅 안에서도** 그대로 동작합니다.

| | 저장소 | 역할 |
|---|---|---|
| 📦 | [`python-hwpx`](https://github.com/airmang/python-hwpx) | HWPX 문서를 읽고·고치고·만드는 순수 파이썬 엔진 |
| 🔌 | [`python-hwpx-automation`](https://github.com/airmang/python-hwpx-automation) | 저작·양식 채움 워크플로, `hwpx` CLI, 선택형 MCP 서버 |
| 🎯 | [`hwpx-plugins`](https://github.com/airmang/hwpx-plugins) | 에이전트가 알맞은 도구를 고르도록 돕는 플러그인/스킬 번들 |

## Python 자동화 시작하기

```bash
pip install python-hwpx-automation
```

```python
from hwpx_automation import create_document_from_plan

document = create_document_from_plan(
    {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "회의 결과",
        "blocks": [{"type": "paragraph", "text": "결정 사항"}],
    }
)
document.save_to_path("meeting-result.hwpx")
```

`python -m hwpx_automation --help`와 `hwpx help`는 같은 task CLI를 실행합니다.

## MCP 어댑터 시작하기

```bash
pip install "python-hwpx-automation[mcp]"
hwpx-automation-mcp
```

MCP 클라이언트 설정 파일에 아래 블록 하나면 `hwpx` 서버를 잡습니다 — Claude Desktop은
`claude_desktop_config.json`, VS Code는 `.vscode/mcp.json`(키가 `mcpServers` 대신 `servers`),
Gemini CLI는 `~/.gemini/settings.json`, Cursor·Windsurf는 각 에디터의 MCP 설정 파일입니다.

```json
{
  "mcpServers": {
    "hwpx": {
      "command": "uvx",
      "args": [
        "--from",
        "python-hwpx-automation[mcp]==6.1.3",
        "hwpx-automation-mcp"
      ],
      "env": {
        "HWPX_AUTOMATION_WORKSPACE_ROOTS": "[\"~/Documents\"]"
      }
    }
  }
}
```

`HWPX_AUTOMATION_WORKSPACE_ROOTS`에는 문서가 있는 폴더(절대경로 또는 `~`)를
지정하세요. Windows는 `"[\"C:\\\\hwpx\"]"`처럼 씁니다. 값을 비워 두면 GUI
클라이언트는 서버를 시스템 디렉터리에서 띄우기 때문에 모든 문서 경로가
막힙니다 — 처음부터 지정하는 것을 권장합니다. 나머지 옵션은
[환경 변수](#환경-변수) 표를 참고하세요.

> 비-HWPX 문서(PDF/DOCX/XLSX/HTML/TXT)를 `document_to_markdown`으로 읽으려면
> `pip install "python-hwpx-automation[ingest]"`로 MarkItDown adapter를 함께
> 설치합니다. 요구 사항: `Python >= 3.10` · `python-hwpx >= 5.0.0`.

기존 `hwpx-mcp-server` 배포·import·콘솔·설정 키도 6.x 동안 그대로 동작합니다 —
전체 목록과 유지 규칙: [6.x 호환 표면](docs/compatibility-6x.md)

## 무엇을 하나

기본 모드에서 다수의 HWPX 도구를 제공하며, 고급 모드(`HWPX_AUTOMATION_ADVANCED=1`)에서 점검·검증용 도구가 추가됩니다.

- **읽기·탐색** — `get_document_info`, `get_document_map`(아웃라인·표 지도·앵커를 한 호출로), `find_text` (저장하지 않음)
- **검색·치환·편집** — `search_and_replace`, `apply_document_commands`(이종 편집 원자 적용·dry-run·롤백·멱등키), `add_tracked_edit`(변경 추적)
- **표·양식 채움** — `analyze_form_fill` → `apply_form_fill` → `verify_form_fill` 바이트 보존 트랜잭션, `table_compute`(합계·소계)
- **문서 생성·공문** — 선언형 `create_document_from_plan`, `inspect_official_document_style`(행정 규정 lint), `mail_merge`
- **서식·그림·생성기** — `set_paragraph_format`·`set_page_setup`, `insert_picture`, 사진대지·명패·조직도
- **프리뷰·추출·복구·진단** — `render_preview`(HTML/PNG 자기검증), `hwpx_to_markdown`, `repair_hwpx`, `mcp_server_health`

자세한 내용: [사용 사례](docs/use-cases.md) · [스킬 우선 워크플로](docs/skill-first-workflows.md)

## 안전하게 쓰는 법

처음부터 모든 도구를 외울 필요는 없습니다. 보통 이렇게 흘러갑니다.

1. **읽기** — `get_document_info` → `get_document_outline`/`get_document_text` → `find_text`, `get_table_map`으로 필요한 부분만 파악합니다. (저장하지 않음)
2. **안전 수정** — `copy_document`로 사본을 만들고, 가장 작은 변경(`search_and_replace`, `set_table_cell_text`, `apply_document_commands`)을 적용한 뒤 다시 읽어 확인하고, 검토가 끝난 사본을 전달합니다.

핵심은 **copy first · smallest edit · re-read after edits**입니다. 수정 도구는
호출 즉시 저장되므로 검토용 작업은 반드시 사본에서 하세요.

모델은 operation/plan만 보내고 raw XML을 직접 편집하지 않습니다. 일반 저장
경로는 python-hwpx의 단일 `SavePipeline` 게이트를 통과해 무결성·XML·OPC/ID·
열림안전을 검사하고, 게이트가 실패하면 아무것도 쓰지 않습니다. capability
handshake는 core/automation/plugin 버전+해시 skew를 fail-closed로 차단합니다.
보안 상세: [하드닝 가이드](docs/hardening_guide_ko.md) · 옛 이름과의 호환
식별자: [6.x 호환 표면](docs/compatibility-6x.md)

> **위치 계약** — `paragraph_index`는 본문 직속 문단의 0-based 인덱스입니다. 표 안 문단은 여기 섞지 않고
> `{"kind":"table_cell_paragraph","table_index":0,"row":0,"col":1,"cell_paragraph_index":0}` 같은 `location`
> 객체로 지정하며, `get_table_map`/`find_text`가 반환한 값을 그대로 넘길 수 있습니다.

## 환경 변수

| 변수 | 설명 | 기본값 |
|---|---|---|
| `HWPX_AUTOMATION_WORKSPACE_ROOTS` | 허용할 workspace 절대경로의 JSON 배열(복수 root 지원). 상대경로는 첫 root 기준 | unset → 프로세스 cwd. degenerate cwd는 `WORKSPACE_ROOT_INVALID`로 거부 |
| `HWPX_AUTOMATION_MAX_CHARS` | 텍스트 반환 도구 기본 최대 길이 | `10000` |
| `HWPX_AUTOMATION_AUTOBACKUP` | `1`이면 저장 전 `.bak` 백업 생성 | `1` |
| `HWPX_AUTOMATION_ADVANCED` | `1`이면 고급 도구 활성화 | `0` |
| `HWPX_AUTOMATION_FETCH_TIMEOUT_SECONDS` | URL 기반 HWPX fetch timeout | `20.0` |
| `HWPX_AUTOMATION_ALLOW_PRIVATE_NETWORK` | `1`이면 신뢰된 사설/루프백 HTTPS 대상 허용. 링크로컬·metadata·예약 주소는 계속 차단 | `0` |
| `HWPX_AUTOMATION_QUALITY` | 전역 기본 저장 게이트 정책(`transparent`/`strict`). 도구별 `quality`가 우선 | `transparent` |
| `HWPX_AUTOMATION_REQUIRE_CAPABILITY` | `0`이면 capability skew fail-closed를 끔(진단/전문가용) | `1` |
| `HWPX_AUTOMATION_WORKFLOW_STORE` | durable workflow SQLite 경로. 기존 `HWPX_WORKFLOW_STORE`보다 우선 | 기존 6.x 상태 경로 |
| `LOG_LEVEL` | 로그 레벨 | `INFO` |

동일 suffix의 기존 `HWPX_MCP_*` 키는 6.x 동안 fallback으로 유지되며, 두 키가
함께 있으면 `HWPX_AUTOMATION_*`이 우선합니다. render·workflow·oracle·plugin
연동용 보존 키 전체 목록과 workflow DB 경로 규칙은
[6.x 호환 표면](docs/compatibility-6x.md)에 있습니다.

경로는 기본적으로 workspace 밖 traversal과 symlink escape를 거부하고, URL 입력은 HTTPS·공개 IP만
허용합니다. 원자 rename을 제공하지 않는 호스트의 동시성 주의사항은 [하드닝 가이드](docs/hardening_guide_ko.md)를 보세요.

## 기여하기

[good first issue](https://github.com/airmang/python-hwpx-automation/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) ·
[마일스톤](https://github.com/airmang/python-hwpx-automation/milestones) ·
[Discussions](https://github.com/airmang/python-hwpx-automation/discussions) ·
[CONTRIBUTING](CONTRIBUTING.md) ·
[CHANGELOG](CHANGELOG.md)

```bash
python -m pip install -e ".[test]"   # 테스트 의존성
python -m pytest -q                   # 전체 테스트
python scripts/run_conformance.py run \
  --tier structural --check tests/conformance/golden/structural.json
```

## 감사의 말

코어 라이브러리 [python-hwpx](https://github.com/airmang/python-hwpx) 위에서 동작하며, 아래 공개 표준·프로젝트에 빚지고 있습니다.

- **[OWPML — 개방형 워드프로세서 마크업 언어 (KS X 6101)](https://www.kssn.net/search/stddetail.do?itemNo=K001010119985)** — HWPX가 기반하는 한국 산업 표준
- **[hancom-io/hwpx-owpml-model](https://github.com/hancom-io/hwpx-owpml-model)** — OWPML 요소 구조 참조 모델 · **[neolord0/hwpxlib](https://github.com/neolord0/hwpxlib)** — 오라클 샘플 코퍼스
- **[edwardkim/rhwp](https://github.com/edwardkim/rhwp)** — 멱등성·검증 게이트 설계 영감

## License · Maintainer

Apache-2.0 ([LICENSE](LICENSE) · [NOTICE](NOTICE)) — **Kohkyuhyun** [@airmang](https://github.com/airmang) · [kokyuhyun@hotmail.com](mailto:kokyuhyun@hotmail.com)
