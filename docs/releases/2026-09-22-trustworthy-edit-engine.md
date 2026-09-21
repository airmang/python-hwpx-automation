# 6.5.0 / 7.2.0 / 2.3.0 공개 설치 관찰

2026-09-22 KST에 [`python-hwpx 6.5.0`](https://github.com/airmang/python-hwpx/releases/tag/v6.5.0), [`python-hwpx-automation 7.2.0`](https://github.com/airmang/python-hwpx-automation/releases/tag/v7.2.0), 호환 배포판 `hwpx-mcp-server 7.2.0`, [`hwpx-plugin 2.3.0`](https://github.com/airmang/hwpx-plugins/releases/tag/v2.3.0)의 공개 발행을 확인했다. 정식·호환 배포판은 각각 [PyPI](https://pypi.org/project/python-hwpx-automation/7.2.0/)와 [PyPI](https://pypi.org/project/hwpx-mcp-server/7.2.0/)에서 확인했다. 릴리스 태그는 `release-approved` 스냅샷을 보존하며, `released` 승격은 이 후속 커밋에만 기록한다.

격리한 Codex 홈에서 공개 GitHub marketplace를 새로 추가하고 `hwpx-plugin@hwpx` **2.3.0**을 설치했다. 설치된 플러그인의 MCP 설정으로 실제 도구를 호출해 공개 wheel `python-hwpx 6.5.0`·`python-hwpx-automation 7.2.0`, 기본 도구 **128개**, 계약 해시 **`5e5c23651f92785a`**를 확인했다. 문서 생성·표 편집·워크플로, workspace 밖·경로 우회·심볼릭 링크 차단, PII 마스킹을 확인했고 프로토콜 오류는 없었다. 렌더 백엔드가 설정되지 않은 환경에서는 렌더 결과를 사용 불가로 보고했다.

이 릴리스는 기존 문서의 명확한 혼합 run·필드·단순 머리말 편집, 새로 작성한 긴 표, 그림 자산 추출·교체, 결과와 렌더 증거의 연결을 보강한다. 지원 범위 밖의 모호한 편집은 거부한다. **과거 셀 채움 페이지 흐름 사례 두 건의 글자 가림은 남아 있다.** 저장·렌더 성공만으로 시각 검토나 제출 적합성을 보증하지 않는다.
