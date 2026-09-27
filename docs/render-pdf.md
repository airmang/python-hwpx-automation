# render-pdf: 다른 환경에서 한컴 렌더 실행하기

`render-pdf`는 `.hwpx` 하나를 한컴으로 PDF로 렌더하고, 원하면 쪽마다 PNG도
만듭니다. 출력 바이트를 지키려고 python-hwpx 버전을 고정한 프로젝트도 쓸 수
있게 만든 명령입니다. 그런 프로젝트의 환경에 `python-hwpx-automation[oracle]`을
설치하면 core도 이 패키지가 요구하는 버전으로 올라갑니다. 대신 이 명령을 별도
환경에서 실행하고 결과는 stdout으로 받으세요.

## 실행

```bash
uvx --from "python-hwpx-automation[oracle]==<version>" \
  hwpx render-pdf in.hwpx out.pdf --png out/page --json
```

같은 명령을 모듈로도 실행할 수 있습니다.

```bash
uv run --isolated --with "python-hwpx-automation[oracle]==<version>" \
  python -m hwpx_automation.office.rendering render-pdf in.hwpx out.pdf --json
```

두 형태 모두 uv가 관리하는 격리 환경에서 실행되고, 호출하는 쪽 환경에는 아무것도
설치하지 않습니다. `<version>`에는 이 명령이 들어 있는 버전을 고정하세요. 렌더
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
- **Windows**: 한글과 COM 클래스 `HWPFrame.HwpObject` 등록이 필요합니다.
- `HWPX_ORACLE_STRUCTURAL_ONLY=1`이면 한컴을 찾지도 실행하지도 않고 종료 코드
  3으로 끝납니다.
- `--timeout`을 주지 않으면 `HWPX_ORACLE_BUDGET_SECONDS`가 시간 예산이 됩니다.
  한컴 설치·권한 확인은 따로 짧은 상한(권한 확인 5초, 앱 검색 10초)을 둡니다.

## 약속하지 않는 것

플러그인 캐시 안의 인터프리터 경로는 공개 표면이 아니며, 버전이나 설치 방식에
따라 달라집니다. 그 경로를 찾아 쓰지 말고 이 명령을 쓰세요.
