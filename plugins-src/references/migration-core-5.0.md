# python-hwpx 5.0 — 무엇이 어디로 갔나

`python-hwpx` 5.0은 HWPX 객체 모델·OXML·OPC와 그 위의 형식 고유 primitive만
남긴다. 라이브러리 안에서 자라던 응용 워크플로는 `hwpx-mcp-server`로 옮겼다.
그 구현의 정본은 4.x 시절부터 이미 MCP에 있었고, 이번에 core에서 사본이 사라진
것이다.

**폐기된 기능은 없다.** 제거된 import마다 대체 경로가 있고, `python-hwpx` 4.x는
전부 그대로 유지한다.

## MCP/스킬을 쓰고 있다면

할 일이 없다. 도구 이름·스키마·결과가 그대로다. 구현의 주소만 바뀌었고, 그 이동은
이번 릴리스 전에 끝나 있었다.

## `hwpx`를 직접 import하고 있다면

```bash
pip install hwpx-mcp-server
```

| 4.x import | 5.0 대체 |
|---|---|
| `hwpx.agent.*` · `hwpx` 명령 | `hwpx_mcp_server.office.agent` · 같은 `hwpx` 명령(MCP가 선언) |
| `hwpx.authoring` · `builder` · `design` · `presets` | `hwpx_mcp_server.office.authoring` |
| `hwpx.exam` | `hwpx_mcp_server.office.exam` — 또는 `compose_exam` 도구 |
| `hwpx.evalplan_fill` | `hwpx_mcp_server.office.evalplan` — 또는 `apply_evalplan_fill` |
| `hwpx.form_fill` · `formfill_quality` · `fill_residue` · `guidance_scan` · `template_formfit` | `hwpx_mcp_server.office.form_fill` — 또는 form-fill 3종 도구 |
| `hwpx.tools.official_lint` · `pii` | `hwpx_mcp_server.office.compliance` |
| `hwpx.tools.table_compute` · `style_profile` · `advanced_generators` · `report_parser` | `hwpx_mcp_server.office.utilities` / `office.authoring` |
| `hwpx.tools.mail_merge.mail_merge` | `merge_template_rows` (core, 이제 공개) |
| `hwpx.tools.doc_diff.build_comparison_table_plan` | `hwpx_mcp_server.office.document_ops` |

정확한 시그니처와 되돌리는 법은 `python-hwpx` 레포의 `docs/migration-mcp-5.0.md`가
정본이다.

## core에 남은 것

표(병합·분할·중첩)·메모와 anchor·머리말/꼬리말 story·변경추적·패키지 바이트
보존·필드/누름틀, 그리고 이들이 쓰는 fit 계약(`hwpx.form_fit`의 측정·정책·엔진).
MCP는 이 계약을 **import**한다 — 사본을 갖지 않는다.

## 두 가지 동작 변화

**마스킹 기본값.** 없어진 `mail_merge()` 래퍼는 명시적으로 끄지 않는 한 개인정보를
마스킹했다. 그 탐지 규칙은 이제 MCP에 있다. 기본값을 "아무것도 안 함"으로 뒤집으면
이 문서를 읽지 않은 사람에게 조용히 새므로, 래퍼를 없애고
`merge_template_rows(value_sanitizer=...)`로 **호출 지점에서 선택이 보이게** 했다.

**렌더러 탐색.** core는 더 이상 한컴이나 이미징 스택을 찾지 않는다. 백엔드를
주입하지 않으면 `render_checked=False`로 정직하게 떨어진다 — 하지 않은 검증을
통과로 보이게 하지 않는다.

```python
from hwpx_mcp_server.office.rendering import resolve_hancom_backend
verify_redline(before, after, oracle=resolve_hancom_backend())
```

## 되돌리기

`pip install "python-hwpx<5"` 로 4.x 표면이 전부 돌아온다. 4.x는 밀어내는 막다른
길이 아니다.
