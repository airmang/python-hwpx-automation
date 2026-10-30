# render-pdf: 다른 환경에서 한컴 렌더 실행하기

`render-pdf`는 `.hwpx` 하나를 한컴으로 PDF로 렌더하고, 원하면 쪽마다 PNG도
만듭니다. 출력 바이트를 지키려고 python-hwpx 버전을 고정한 프로젝트도 쓸 수
있게 만든 명령입니다. 그런 프로젝트의 환경에 `python-hwpx-automation[oracle]`을
설치하면 core도 이 패키지가 요구하는 버전으로 올라갑니다. 대신 이 명령을 별도
환경에서 실행하고 결과는 stdout으로 받으세요.

## 실행

```bash
uvx --from "python-hwpx-automation[oracle]==7.4.1" \
  hwpx render-pdf in.hwpx out.pdf --png out/page --json
```

같은 명령을 모듈로도 실행할 수 있습니다.

```bash
uv run --isolated --with "python-hwpx-automation[oracle]==7.4.1" \
  python -m hwpx_automation.office.rendering render-pdf in.hwpx out.pdf --json
```

두 형태 모두 uv가 관리하는 격리 환경에서 실행되고, 호출하는 쪽 환경에는 아무것도
설치하지 않습니다. 버전은 이 명령이 처음 공개된 7.3.1 이상으로 고정하세요. 렌더
환경의 python-hwpx 버전은 그 automation 버전의 의존성에 따라 정해지며, 호출하는
쪽의 고정 버전과는 상관없습니다. 이미 `[oracle]`이 설치된 환경이라면
`hwpx render-pdf ...`를 바로 실행해도 됩니다. `hwpx --help` 목록에는 나오지
않으니 옵션은 `hwpx render-pdf --help`로 확인하세요.

| 인자 | 뜻 |
|---|---|
| `IN` | 렌더할 `.hwpx` |
| `OUT` | 쓸 PDF. 상위 폴더가 없으면 만듭니다 |
| `--png PREFIX` | 각 쪽을 `PREFIX-001.png`, `PREFIX-002.png`, …로 저장합니다(1부터, 세 자리) |
| `--dpi N` | PNG 해상도. 기본값 110 |
| `--backend auto\|mac\|windows` | `auto`(기본값)는 Windows COM, macOS 순으로 찾아 처음 닿는 한컴을 씁니다. `mac`·`windows`는 해당 백엔드만 쓰고, 닿지 않으면 다른 백엔드로 넘어가지 않고 실패합니다 |
| `--timeout SECONDS` | 이 렌더에서 실행하는 한컴 하위 프로세스 전체의 시간 상한 |
| `--json` | 결과를 JSON 한 줄로 출력합니다 |

## JSON 결과

`--json`을 주면 성공이든 실패든 stdout의 **마지막 줄**에 JSON 객체 하나를
씁니다. 한글 경로도 ASCII 이스케이프로 쓰므로 콘솔 인코딩과 관계없이 파싱할 수
있습니다. 백엔드가 출력하는 내용은 stderr로 보냅니다.

성공:

```json
{"ok":true,"pdf":"/abs/out.pdf","pages":2,"pngs":["/abs/out/page-001.png","/abs/out/page-002.png"],"backend":"mac"}
```

실패:

```json
{"ok":false,"error":"hancom-unavailable","message":"no Hancom reachable: ...","backend":null}
```

경로는 모두 절대경로입니다. `backend`는 `"mac"`, `"windows"`, 또는 백엔드를
정하기 전에 실패했으면 `null`입니다. `--json`이 없으면 사람이 읽는 형식으로
stdout에 결과를, stderr에 오류를 씁니다. 종료 코드는 같습니다.

| 종료 코드 | `error` | 뜻 |
|---|---|---|
| 0 | — | 렌더 성공 |
| 1 | `render-failed` | 한컴에는 닿았지만 PDF가 나오지 않았거나 읽을 수 없음 |
| 1 | `hancom-refused` | 한컴이 문서를 열지 않고 오류 창("파일이 손상되었습니다" 등)을 띄움. 이 렌더가 띄운 창만 닫고 바로 끝냄. PDF로 저장하다 손상된 표를 복원할지 물으면 `취소`로 답하고(`복원`은 누르지 않음) 이어서 뜨는 저장 오류 창까지 닫은 뒤 이 코드로 끝냄 |
| 1 | `hancom-hung` | PDF가 나오지 않았고 한컴이 몇 초 동안 CPU를 계속 80% 이상 쓰며 응답하지 않음(macOS). 한컴을 종료하고 다시 실행한 뒤 렌더하세요. 다시 실행할 때까지 이후 렌더도 모두 실패합니다. `render-pdf`는 한컴을 강제로 끝내지 않음 |
| 1 | `hancom-busy` | 다른 렌더가 macOS 데스크톱을 쓰는 중이라 시간 안에 차례가 오지 않음 |
| 1 | `internal-error` | 예상하지 못한 오류 |
| 2 | `usage` | 인자 오류 |
| 2 | `input-missing` | `IN` 파일이 없음 |
| 2 | `imaging-missing` | pymupdf가 없음. `[oracle]` extra로 설치하세요 |
| 2 | `output-unwritable` | 출력 폴더나 PNG를 쓸 수 없음 |
| 3 | `hancom-unavailable` | 닿는 한컴이 없음. `HWPX_ORACLE_STRUCTURAL_ONLY`가 켜진 경우도 포함 |

## 플랫폼 요구 사항

- **macOS**: 한컴오피스 한글(`Hancom Office HWP.app`)과 로그인된 GUI 세션이
  필요합니다. 명령을 실행하는 프로세스(터미널 등)에는 손쉬운 사용과 자동화 권한이
  있어야 합니다. GUI로 메뉴를 조작해 렌더하므로 한 번에 하나씩만 렌더합니다.
  렌더 worker와 같은 데스크톱 잠금을 써서, 다른 렌더가 끝날 때까지
  `--timeout`(없으면 백엔드 기본값 300초) 안에서 기다립니다.
- **Windows**: 한글과 COM 클래스 `HWPFrame.HwpObject` 등록이 필요합니다. 한글은
  자동화가 사용자 임시 폴더(`%TEMP%`) 밖의 파일을 열거나 저장할 때마다 접근을
  허용할지 묻는데, 무인 렌더에서는 아무도 답하지 않습니다. 그래서 문서를 임시
  폴더 안의 전용 폴더로 복사해 렌더하고, 다 만든 PDF만 요청한 경로로 옮깁니다.
  보안 모듈이 `HKCU\SOFTWARE\HNC\HwpAutomation\Modules`에 등록돼 있으면 그것도
  모듈 종류 `FilePathCheckDLL`로 등록해 씁니다. 등록할 값 이름은
  `HWPX_HANCOM_SECURITY_MODULE`로 정할 수 있고, 없으면 `FilePathCheckerModuleExample`,
  그다음 등록된 다른 이름을 차례로 씁니다.
- `HWPX_ORACLE_STRUCTURAL_ONLY=1`이면 한컴을 찾지도 실행하지도 않고 종료 코드
  3으로 끝납니다.
- `--timeout`을 주지 않으면 `HWPX_ORACLE_BUDGET_SECONDS`가 시간 예산이 됩니다.
  한컴 설치·권한 확인은 따로 짧은 상한(권한 확인 5초, 앱 검색 10초)을 둡니다.

## 약속하지 않는 것

플러그인 캐시 안의 인터프리터 경로는 공개 표면이 아니며, 버전이나 설치 방식에
따라 달라집니다. 그 경로를 찾아 쓰지 말고 이 명령을 쓰세요.

## Python에서 같은 데스크톱 잠금 사용하기

하류 도구가 Mac 한/글의 공유 데스크톱을 조작할 때는 공개 컨텍스트 관리자를
사용합니다. CLI와 렌더 워커도 같은 사용자별 파일에 POSIX `flock`을 겁니다.

```python
from hwpx_automation.office.rendering import HancomBusy, hancom_desktop_lock

try:
    with hancom_desktop_lock(wait=10.0):
        # 이 구간에서 도구가 소유한 한/글 작업을 수행합니다.
        pass
except HancomBusy:
    # 지정한 시간 동안 다른 스레드나 프로세스가 데스크톱을 사용했습니다.
    pass
```

`wait`는 유한한 0 이상의 초이며 기본값 0은 즉시 획득을 시도합니다.
같은 스레드에서는 중첩할 수 있고, 예외로 구간을 나가도 잠금은 해제됩니다.
Windows에서는 COM 렌더마다 별도 한/글 프로세스를 사용하므로 이 컨텍스트는
아무 잠금 파일도 열지 않는 no-op입니다. 잠금은 문서를 열거나 한/글을 실행하지
않습니다. 공개 모듈 원장의 기존 `office.rendering` 및 `.mac_session` 항목을
통해 제공하며 MCP extra가 필요하지 않습니다.

Mac `MacHancomOracle.refresh_document(path)`도 같은 공유 경고창 정책을 사용합니다.
새로 열린 경고창이 하나로 확인될 때만 `확인`을 누르며, 손상된 표 복원 질문에는
`취소`만 누릅니다. 기존 경고창이나 여러 개가 일치하는 경우에는 누르지 않습니다.
거부 시 반환값은 `False`이고 `oracle.last_refusal`에 문구가 남습니다. 다음 호출
시 이 값은 초기화됩니다. `True`는 스크립트가 정확히 `OK`로 끝나고 저장 시각이
바뀌었음을 뜻합니다. 이 수정의 검증은 가짜 관찰과 순수 AppleScript 판정이며,
새로운 실한컴 렌더 검증을 뜻하지 않습니다.
