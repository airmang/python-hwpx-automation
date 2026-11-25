<p align="center">
  <h1 align="center">python-hwpx-automation</h1>
  <p align="center">
    <strong>python-hwpx 엔진 위에서 한/글 문서 일을 자동화하는 응용 패키지 · MCP 서버 · 에이전트 플러그인</strong>
  </p>
  <p align="center">
    <a href="https://pypi.org/project/python-hwpx-automation/"><img src="https://img.shields.io/pypi/v/python-hwpx-automation?color=blue&label=PyPI" alt="PyPI"></a>
    <a href="https://pepy.tech/project/python-hwpx-automation"><img src="https://static.pepy.tech/badge/python-hwpx-automation/month" alt="Downloads"></a>
    <a href="https://pypi.org/project/python-hwpx-automation/"><img src="https://img.shields.io/pypi/pyversions/python-hwpx-automation" alt="Python"></a>
    <a href="https://github.com/airmang/python-hwpx-automation/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/airmang/python-hwpx-automation/tests.yml?branch=main&label=tests" alt="Tests"></a>
    <a href="https://github.com/airmang/python-hwpx-automation/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License"></a>
  </p>
  <p align="center">
    <a href="https://github.com/airmang/python-hwpx-automation/blob/main/docs/use-cases.md">사용 사례</a>
    · <a href="https://github.com/airmang/python-hwpx-automation/blob/main/docs/tool-contract.md">MCP 도구 계약</a>
    · <a href="https://github.com/airmang/python-hwpx-automation/blob/main/docs/hardening_guide_ko.md">하드닝 가이드</a>
    · <a href="https://github.com/airmang/python-hwpx-automation/blob/main/docs/compatibility-6x.md">호환 표면</a>
    · <a href="https://github.com/airmang/python-hwpx-automation/blob/main/CHANGELOG.md">변경 기록</a>
  </p>
</p>

[python-hwpx](https://github.com/airmang/python-hwpx)는 파일에 적힌 대로만 읽고 쓰는 엔진입니다. 정답이 하나로 정해지지
않는 일, 곧 다른 형식으로 바꾸기, 이름표로 양식 칸 찾기, 메일 머지, 보고서 서식, 미리보기, 한컴 렌더는 이 패키지가 맡습니다.
MCP 서버와 Claude Code·Codex 플러그인도 여기 있습니다. 한컴오피스 없이 Windows·macOS·Linux에서 돌아갑니다.

<p align="center">
  <img src="https://raw.githubusercontent.com/airmang/python-hwpx/main/docs/assets/hancom-7.0-report.png" width="600" alt="이 패키지의 보고서 서식으로 만든 2026년 디지털 교육 운영 계획을 한컴오피스가 그린 쪽">
</p>
<p align="center"><sub>Markdown 원고를 <code>from_markdown(md, style="report")</code>로 만든 보고서. 한컴오피스 12.30.0이 그린 쪽입니다.</sub></p>

| | 저장소 | 역할 |
|---|---|---|
| 📦 | [`python-hwpx`](https://github.com/airmang/python-hwpx) | 한/글 문서를 읽고·고치고·만드는 엔진 |
| 🔌 | [`python-hwpx-automation`](https://github.com/airmang/python-hwpx-automation) | 변환·양식 채움·메일 머지·미리보기·보고서 서식, `hwpx` CLI, MCP 서버, Claude Code·Codex 플러그인 (이 저장소) |
| 🏫 | [`hwpx-school`](https://github.com/airmang/hwpx-school) | 학교 문서(지필평가 원안지·학습지·수행평가 문제지·보고서)를 학교 서식 그대로 만드는 도구 |

## 설치

쓰는 방식에 따라 고르세요.

| 쓰는 방식 | 설치 |
|---|---|
| Claude Code·Codex 같은 에이전트 | 아래 [플러그인](#에이전트에서-쓰기-claude-codecodex). pip 설치는 필요 없습니다 |
| 파이썬 코드 | `pip install -U python-hwpx-automation` (python-hwpx 7.0도 함께 설치됩니다) |
| 그 밖의 MCP 클라이언트 | `pip install -U "python-hwpx-automation[mcp]"` 후 [MCP 서버](#mcp-서버)로 등록 |

### 에이전트에서 쓰기 (Claude Code·Codex)

이 저장소 주소 하나로 플러그인을 설치합니다. 플러그인이 python-hwpx와 이 패키지를 검증한 판으로 설치하고,
MCP 도구와 작업 안내(스킬)를 함께 붙입니다. 미리 [uv](https://docs.astral.sh/uv/getting-started/installation/)가
설치되어 있어야 합니다.

```bash
# Claude Code
claude plugin marketplace add airmang/python-hwpx-automation
claude plugin install hwpx-plugin@hwpx

# Codex
codex plugin marketplace add airmang/python-hwpx-automation
codex plugin add hwpx-plugin@hwpx
```

에이전트에게 "https://github.com/airmang/python-hwpx-automation 플러그인을 설치해 줘"라고 부탁해도 됩니다.
플러그인은 새 세션부터 쓰입니다. 예전 주소 `airmang/hwpx-plugins`로 설치한 플러그인도 같은 번들을 받으므로
그대로 업데이트됩니다.

## 파이썬에서 쓰기

Markdown 원고를 보고서 서식의 한/글 문서로 만듭니다. 위 그림이 이렇게 만든 문서입니다.

```python
from hwpx_automation.markdown import from_markdown

md = """\
# 2026년 운영 계획

## 추진 배경

- 학생 1인 1기기 보급 완료
  - 교사 연수 수요 증가

## 추진 일정

| 구분 | 기간 |
|---|---|
| 1단계 | 3월 ~ 6월 |
"""
doc = from_markdown(md, style="report", byline="2026. 3.  교육과정부")
doc.save("운영계획.hwpx")
```

python-hwpx 7.0에서 이 패키지로 옮겨 온 기능은 아래에 있습니다. 인자와 결과는 python-hwpx 6.x와 같습니다.

| 하는 일 | 모듈 |
|---|---|
| Markdown으로 문서 만들기, Markdown·HTML로 내보내기 | `hwpx_automation.markdown` |
| 이름표로 양식 칸 찾아 채우기, 글자로 적힌 선택 칸 | `hwpx_automation.forms` |
| 메일 머지 | `hwpx_automation.mail_merge` |
| 미리보기(HTML·PNG), 수식 그림 | `hwpx_automation.preview` |
| 서식 규칙 검사(명령 `hwpx-check-format`) | `hwpx_automation.format_rules` |
| 다른 형식 가져오기, LangChain·LlamaIndex | `hwpx_automation.ingest`, `hwpx_automation.integrations` |
| 표 정리·보고서 수치, 공문 표기·개인정보 검사 | `hwpx_automation.office.utilities`, `hwpx_automation.office.compliance` |

명령줄에서는 `hwpx help`(또는 `python -m hwpx_automation --help`)로 시작합니다.

## MCP 서버

```bash
pip install -U "python-hwpx-automation[mcp]"
hwpx-automation-mcp
```

MCP 클라이언트 설정 파일에 아래 블록 하나면 `hwpx` 서버를 잡습니다. Claude Desktop은 `claude_desktop_config.json`,
VS Code는 `.vscode/mcp.json`(키가 `mcpServers` 대신 `servers`), Gemini CLI는 `~/.gemini/settings.json`,
Cursor·Windsurf는 각 에디터의 MCP 설정 파일입니다.

```json
{
  "mcpServers": {
    "hwpx": {
      "command": "uvx",
      "args": [
        "--from",
        "python-hwpx-automation[mcp]==8.0.0",
        "hwpx-automation-mcp"
      ],
      "env": {
        "HWPX_AUTOMATION_WORKSPACE_ROOTS": "[\"~/Documents\"]"
      }
    }
  }
}
```

`HWPX_AUTOMATION_WORKSPACE_ROOTS`에는 문서가 있는 폴더(절대 경로나 `~`)를 적으세요. Windows는 `"[\"C:\\\\hwpx\"]"`처럼
씁니다. 비워 두면 GUI 클라이언트가 서버를 시스템 폴더에서 띄우는 바람에 모든 문서 경로가 막히므로, 처음부터 적어 두기를
권합니다. 나머지 설정은 [환경 변수](#환경-변수)에 있습니다.

> PDF·DOCX·XLSX·HTML·TXT 같은 다른 형식을 `document_to_markdown`으로 읽으려면 `pip install "python-hwpx-automation[ingest]"`로
> MarkItDown 어댑터를 함께 설치합니다. 요구 사항: Python 3.10 이상, python-hwpx 7.0 이상.

예전 `hwpx-mcp-server` 배포판·import·명령·설정 키도 그대로 동작합니다. 전체 목록과 유지 규칙은
[호환 표면](https://github.com/airmang/python-hwpx-automation/blob/main/docs/compatibility-6x.md)에 있습니다.

### 작은 로컬 모델용 프로필

Ollama·Open WebUI의 27B급 모델처럼 도구가 많으면 길을 잃는 환경에서는
`hwpx-automation-mcp --profile minimal`(또는 `HWPX_AUTOMATION_PROFILE=minimal`)로
굵은 도구 여섯 개만 띄웁니다: `read_outline`(id 붙은 짧은 목록) →
`apply_text_changes`(`{id: 새 글}`, 서식 유지 — 서식이 섞인 곳을 가로질러 첫 서식으로 다시 쓴 id는
`rewritten`, 칸 넘침은 `overflow`, 볼 것이 있으면 `reviewRequired`), `replace_text`,
`stage_text` → `create_from_markdown`, `validate_document`. 긴 본문은 도구 인수에
한 번에 싣지 않고 `stage_text`로 1,000자 안팎씩 나눠 보낸 뒤 `draft_id`로 넘깁니다.
`create_from_markdown`의 `byline`(200자까지)은 제목 아래 오른쪽에 쓰는 부서·날짜 줄입니다.
수정 도구의 결과에는 문서 본문을 싣지 않고(건수와 id만), 수정본은 기본으로 `<이름>.edited.hwpx`에
저장합니다. `read_outline`은 문단·표 칸마다 앞 200자까지 원문을 싣습니다(개인정보를 가리지 않습니다) —
문단이 짧은 문서는 본문 전체가 결과에 실립니다.

## 한컴으로 PDF 렌더하기

한컴(macOS 한컴오피스 한글 또는 Windows 한글 COM)이 있는 컴퓨터에서 문서 하나를
PDF와 쪽 PNG로 렌더합니다. 별도 환경에서 실행하므로 호출하는 쪽의 python-hwpx
고정 버전을 건드리지 않습니다.

```bash
uvx --from "python-hwpx-automation[oracle]==8.0.0" \
  hwpx render-pdf in.hwpx out.pdf --png out/page --json
```

JSON 결과·종료 코드·플랫폼 요구 사항: [render-pdf](https://github.com/airmang/python-hwpx-automation/blob/main/docs/render-pdf.md)

## MCP 도구

기본 모드에서 다수의 HWPX 도구를 제공하며, 고급 모드(`HWPX_AUTOMATION_ADVANCED=1`)에서 점검·검증용 도구가 추가됩니다.

- **읽기·탐색** — `get_document_info`, `get_document_map`(아웃라인·표 지도·앵커를 한 호출로), `find_text` (저장하지 않음)
- **검색·치환·편집** — `search_and_replace`, `apply_document_commands`(이종 편집 원자 적용·dry-run·롤백·멱등키), `add_tracked_edit`(변경 추적)
- **표·양식 채움** — `analyze_form_fill` → `apply_form_fill` → `verify_form_fill` 바이트 보존 트랜잭션, `table_compute`(합계·소계)
- **문서 생성·공문** — 선언형 `create_document_from_plan`, `inspect_official_document_style`(행정 규정 lint), `mail_merge`
- **서식·그림·생성기** — `set_paragraph_format`·`set_page_setup`, `insert_picture`, 사진대지·명패·조직도
- **프리뷰·추출·복구·진단** — `render_preview`(HTML/PNG 자기검증), `hwpx_to_markdown`, `repair_hwpx`, `mcp_server_health`

자세한 내용: [사용 사례](https://github.com/airmang/python-hwpx-automation/blob/main/docs/use-cases.md) · [스킬 우선 워크플로](https://github.com/airmang/python-hwpx-automation/blob/main/docs/skill-first-workflows.md)

## 안전하게 쓰는 법

처음부터 모든 도구를 외울 필요는 없습니다. 기존 문서 수정은 [조회·대상 확정·보존 저장·검증 안내](https://github.com/airmang/python-hwpx-automation/blob/main/docs/existing-edit-navigation.md)를,
새 문서는 document-plan을 먼저 봅니다. 보통 이렇게 흘러갑니다.

1. **읽기** — `get_document_info` → `get_document_outline`/`get_document_text` → `find_text`, `get_table_map`으로 필요한 부분만 파악합니다. (저장하지 않음)
2. **안전 수정** — `copy_document`로 사본을 만들고, 가장 작은 변경(`search_and_replace`, `set_table_cell_text`, `apply_document_commands`)을 적용한 뒤 다시 읽어 확인하고, 검토가 끝난 사본을 전달합니다.

핵심은 **copy first · smallest edit · re-read after edits**입니다. 수정 도구는
호출 즉시 저장되므로 검토용 작업은 반드시 사본에서 하세요.

모델은 operation/plan만 보내고 raw XML을 직접 편집하지 않습니다. 일반 저장
경로는 python-hwpx의 단일 `SavePipeline` 게이트를 통과해 무결성·XML·OPC/ID·
열림안전을 검사하고, 게이트가 실패하면 아무것도 쓰지 않습니다. capability
handshake는 core/automation/plugin 버전+해시 skew를 fail-closed로 차단합니다.
보안 상세: [하드닝 가이드](https://github.com/airmang/python-hwpx-automation/blob/main/docs/hardening_guide_ko.md) · 옛 이름과의 호환
식별자: [호환 표면](https://github.com/airmang/python-hwpx-automation/blob/main/docs/compatibility-6x.md)

> **위치 계약** — `paragraph_index`는 본문 직속 문단의 0-based 인덱스입니다. 표 안 문단은 여기 섞지 않고
> `{"kind":"table_cell_paragraph","table_index":0,"row":0,"col":1,"cell_paragraph_index":0}` 같은 `location`
> 객체로 지정하며, `find_text`가 반환한 값을 그대로 넘길 수 있습니다. `get_table_map`은 기본(`detail="compact"`)으로
> 실제 칸만 한 번씩 싣고(병합은 `row_span`/`col_span`) 위치는 응답의 `cell_paragraph_location` 틀에 `table_index`·`row`·`col`을
> 넣어 만듭니다. 칸마다 `location`이 든 이전 형태는 `detail="full"`로 받습니다.

## 환경 변수

| 변수 | 설명 | 기본값 |
|---|---|---|
| `HWPX_AUTOMATION_WORKSPACE_ROOTS` | 허용할 workspace 절대경로의 JSON 배열(복수 root 지원). 상대경로는 첫 root 기준 | unset → 프로세스 cwd. degenerate cwd는 `WORKSPACE_ROOT_INVALID`로 거부 |
| `HWPX_AUTOMATION_MAX_CHARS` | 텍스트 반환 도구 기본 최대 길이 | `10000` |
| `HWPX_AUTOMATION_AUTOBACKUP` | `1`이면 저장 전 `.bak` 백업 생성 | `1` |
| `HWPX_AUTOMATION_ADVANCED` | `1`이면 고급 도구 활성화 | `0` |
| `HWPX_AUTOMATION_PROFILE` | `minimal`이면 작은 로컬 모델용 도구 6개만 제공(`--profile`과 같음) | `full` |
| `HWPX_AUTOMATION_FETCH_TIMEOUT_SECONDS` | URL 기반 HWPX fetch timeout | `20.0` |
| `HWPX_AUTOMATION_ALLOW_PRIVATE_NETWORK` | `1`이면 신뢰된 사설/루프백 HTTPS 대상 허용. 링크로컬·metadata·예약 주소는 계속 차단 | `0` |
| `HWPX_AUTOMATION_QUALITY` | 전역 기본 저장 게이트 정책(`transparent`/`strict`). 도구별 `quality`가 우선 | `transparent` |
| `HWPX_AUTOMATION_REQUIRE_CAPABILITY` | `0`이면 capability skew fail-closed를 끔(진단/전문가용) | `1` |
| `HWPX_AUTOMATION_WORKFLOW_STORE` | durable workflow SQLite 경로. 기존 `HWPX_WORKFLOW_STORE`보다 우선 | 기존 6.x 상태 경로 |
| `LOG_LEVEL` | 로그 레벨 | `INFO` |

동일 suffix의 기존 `HWPX_MCP_*` 키는 fallback으로 유지되며, 두 키가
함께 있으면 `HWPX_AUTOMATION_*`이 우선합니다. render·workflow·oracle·plugin
연동용 보존 키 전체 목록과 workflow DB 경로 규칙은
[호환 표면](https://github.com/airmang/python-hwpx-automation/blob/main/docs/compatibility-6x.md)에 있습니다.

경로는 기본적으로 workspace 밖 traversal과 symlink escape를 거부하고, URL 입력은 HTTPS·공개 IP만
허용합니다. 원자 rename을 제공하지 않는 호스트의 동시성 주의사항은 [하드닝 가이드](https://github.com/airmang/python-hwpx-automation/blob/main/docs/hardening_guide_ko.md)를 보세요.

## 릴리스 상태

<!-- release-state: released -->
> [!NOTE]
> 8.0.0 공개 발행과 전체 트레인의 실제 marketplace 설치를 관찰했습니다.
> 검증·공개 트레인: `python-hwpx 7.0.0 → python-hwpx-automation 8.0.0 → hwpx-plugin 8.0.0` (`c895883d5f4350ae`). 이 좌표는 `src/hwpx_automation/identity.json`의 `releaseState.candidate`·`currentPublic`과 같아야 합니다(`tests/test_audit_identity_docs.py`).
> 이전 공개 트레인: `python-hwpx 6.6.0 → python-hwpx-automation 7.3.1 → hwpx-plugin 2.4.0`. 계약 변경은 `docs/tool-contract-delta-8.0.0.json`에 있습니다.
> [발행·설치 영수증](https://github.com/airmang/python-hwpx-automation/blob/main/docs/releases/2026-11-21-engine-7-automation-8.md)
> 공개 좌표는 core·automation PyPI와 plugin GitHub
> Release·marketplace·실제 marketplace 설치 관찰 후에만 승격합니다.
> [릴리스 runbook](https://github.com/airmang/python-hwpx-automation/blob/main/docs/release-runbook.md)

## 기여하기

[good first issue](https://github.com/airmang/python-hwpx-automation/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) ·
[마일스톤](https://github.com/airmang/python-hwpx-automation/milestones) ·
[Discussions](https://github.com/airmang/python-hwpx-automation/discussions) ·
[CONTRIBUTING](https://github.com/airmang/python-hwpx-automation/blob/main/CONTRIBUTING.md) ·
[CHANGELOG](https://github.com/airmang/python-hwpx-automation/blob/main/CHANGELOG.md)

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

Apache-2.0 ([LICENSE](https://github.com/airmang/python-hwpx-automation/blob/main/LICENSE) · [NOTICE](https://github.com/airmang/python-hwpx-automation/blob/main/NOTICE)) — **Kohkyuhyun** [@airmang](https://github.com/airmang) · [kokyuhyun@hotmail.com](mailto:kokyuhyun@hotmail.com)
