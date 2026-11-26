# hwpx-mcp-server — 호환 배포

이 이름은 6.0.0부터 **얇은 셸**입니다. 실제 코드는
[`python-hwpx-automation`](https://pypi.org/project/python-hwpx-automation/)에
있습니다.

응용 계층 5만 줄 중 MCP 전송은 4%뿐이라, 그 4%의 이름이 전체를 대표하고
있었습니다. 이름을 제자리로 옮기되 **기존 설치와 MCP 설정은 그대로 둡니다.**

```bash
pip install hwpx-mcp-server          # 계속 동작 — automation[mcp]를 끌어옵니다
pip install python-hwpx-automation   # 새 이름. MCP 없이 파이썬 API만
```

이 배포판은 `python-hwpx-automation[mcp]`와 **같은 판 번호**로 나가고 그 판을 정확히
요구합니다(예: `hwpx-mcp-server 8.0.1` → `python-hwpx-automation[mcp]==8.0.1`). 남은 것은
아래 둘뿐입니다.

| 남은 것 | 동작 | 새로 쓸 것 |
|---|---|---|
| 콘솔 명령 `hwpx-mcp-server` | `hwpx-automation-mcp`와 같은 서버를 띄웁니다(MCP `serverInfo.name`은 `python-hwpx-automation`) | 새 MCP 설정은 `hwpx-automation-mcp` |
| `import hwpx_mcp_server`와 그 아래 공개 deep import | `hwpx_automation`의 같은 모듈을 돌려주며 `DeprecationWarning`을 냅니다 | 새 코드는 `import hwpx_automation` |

호스트 설정의 `hwpx` key는 protocol identity가 아니라 각 호스트의 local alias입니다.
기존 설정은 바꾸지 않아도 계속 동작합니다. 이 두 호환 경로를 언제 없앨지는 아직 정하지
않았고, 정하면 이 문서와 변경 기록에 먼저 적습니다.

PyPI에 이미 올라간 판의 설명은 그 판이 나갈 때의 README이며, 이 문서를 고쳐도 바뀌지
않습니다. 다음 판부터 이 설명이 실립니다.

셸의 리다이렉트는 런타임 전용이라 mypy/pyright 같은 정적 타입 검사기는 옛
경로를 해석하지 못합니다. 타입 검사가 필요한 코드는 `hwpx_automation`을 직접
import하세요 — 그쪽이 `py.typed`를 배포합니다.

`importlib.resources`의 package data는 복제하지 않습니다. 리소스 소비자는
`importlib.resources.files("hwpx_automation")`을 사용해야 하며, 호환 셸에는
shim 외의 구현·데이터 사본이 없습니다.
