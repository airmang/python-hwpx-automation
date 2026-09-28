# 6.6.0 / 7.3.1 / 2.4.0 공개 설치 관찰

2026-09-28 KST에 [`python-hwpx 6.6.0`](https://github.com/airmang/python-hwpx/releases/tag/v6.6.0), [`python-hwpx-automation 7.3.1`](https://github.com/airmang/python-hwpx-automation/releases/tag/v7.3.1), 호환 배포판 `hwpx-mcp-server 7.3.1`, [`hwpx-plugin 2.4.0`](https://github.com/airmang/hwpx-plugins/releases/tag/v2.4.0)의 공개 발행을 확인했다. 정식·호환 배포판은 각각 [PyPI](https://pypi.org/project/python-hwpx-automation/7.3.1/)와 [PyPI](https://pypi.org/project/hwpx-mcp-server/7.3.1/)에서 확인했다. `v7.3.0`은 보존된 실패 태그다(아무것도 게시되지 않았다). 릴리스 태그는 `release-approved` 스냅샷을 보존하며, `released` 승격은 이 후속 커밋에만 기록한다.

격리한 Codex 홈에서 공개 GitHub marketplace를 새로 추가하고 `hwpx-plugin@hwpx` **2.4.0**을 설치했다(codex-cli 0.157.0). 설치된 플러그인의 MCP 설정을 격리한 홈·캐시로 그대로 띄워, 공개 PyPI에서 런타임 `gen-6.6.0-7.3.1`이 만들어지고 `python-hwpx 6.6.0`·`python-hwpx-automation 7.3.1`, 기본 도구 **128개**(기대 128), 계약 해시 **`5e5c23651f92785a`**, 스킬 번들 2.4.0을 확인했다. `create_document` 실호출이 성공했다.

이 트레인은 격리 환경에서 한컴 렌더를 부르는 `hwpx render-pdf` 명령과, core의 HWP 5.0 읽기·쓰기와 템플릿용 공개 API를 더한다. 공개 PyPI 7.3.1로 `uvx --isolated --from "python-hwpx-automation[oracle]==7.3.1" hwpx render-pdf ... --json`을 실제 한/글(Mac)로 돌려 렌더 성공(종료 0)을 확인했다. 빌더 `Metadata`는 이제 본문이 아니라 문서 정보에 들어간다. 텍스트에서 만든 정부 보고서의 제목이 본문에 보이지 않는 문제는 [#137](https://github.com/airmang/python-hwpx-automation/issues/137)에 남아 있다. 저장·렌더 성공만으로 시각 검토나 제출 적합성을 보증하지 않는다.
