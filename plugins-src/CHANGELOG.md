# Changelog

## Unreleased

3스택 자동 갱신 트레인(검증된 플로어 핀). 스킬 계약·도구 표면·계약 해시 `8c278ebd5becba08`은 그대로입니다.

- **핀 정책 변경**: `exact-candidate` → `verified-floor`. 번들 런처는 검증 좌표
  이상, 같은 메이저 안의 최신 조합(`python-hwpx[preview]>=6.3.0,<7` ·
  `python-hwpx-automation[mcp,oracle]>=7.0.3,<8`)을 설치하고, 하루 1회 백그라운드에서
  새 세대를 빌드·자기검증한 뒤 원자적으로 교체합니다. 기동은 네트워크를 기다리지
  않고, 검증에 실패한 후보는 절대 활성화되지 않으며, 직전 세대는 롤백용으로 남습니다.
  `HWPX_STACK_AUTO_UPDATE=0`(끄기), `HWPX_STACK_UPDATE_INTERVAL_HOURS`(기본 24),
  `HWPX_STACK_CHANNEL=verified`(검증 좌표 고정).
- 런타임 상태 `update-state.json`을 `HWPX_STACK_UPDATE_STATE`로 서버에 전달합니다.
  automation 7.1.0 이상은 `mcp_server_health().stackUpdate`로 보고하고, SKILL.md는 새
  플러그인 번들이 있으면 호스트별 갱신 명령을 한 번 안내합니다.
- 런처 런타임 레이아웃이 `envs/<fingerprint>/gen-<core>-<automation>/` + `current`
  포인터로 바뀝니다. 기존 `envs/<fingerprint>/` 단일 venv는 그대로 두어도 무해하며
  첫 기동에서 새 레이아웃이 빌드됩니다(`.hwpx-mcp-runtime`를 지우면 공간이 회수됨).
- OpenClaw·Hermes 배선은 설치 창으로 이동했고, `uvx`가 스스로 갱신하지 않는다는 점과
  수동 갱신 명령을 문서화했습니다.

## [2.0.3] - 2026-09-03

Claude Code 번들 런처 수리 패치입니다. 코어·automation 핀(`python-hwpx[preview]==6.3.0` ·
`python-hwpx-automation[mcp,oracle]==7.0.3`), 스킬 내용, 도구 표면, 계약 해시
`8c278ebd5becba08`은 그대로입니다.

- **수리**: Claude Code 번들 런처(`scripts/hwpx-automation-mcp`)가 런타임 venv를
  새로 만들 때마다 `installed HWPX stack version mismatch … 'python-hwpx': '6.3.0' !=
  … '6.0.2'`로 종료해 MCP 서버가 뜨지 않던 결함을 고쳤습니다 (#26). 2.0.1·2.0.2의
  모든 신규 설치와 플러그인 업데이트가 이 지점에서 실패했습니다. 기대 버전을
  손으로 전진시키는 리터럴 대신 설치 핀(`==X` 또는 로컬 휠 파일명)에서 파생하고,
  릴리스 게이트 `clean_install_smoke.py`가 기대 버전을 env로 주입해 결함을 가리던
  경로를 제거했습니다. 리터럴이 다시 들어오면 validator와 테스트가 실패합니다.
- Codex 번들 `.mcp.json`과 OpenClaw·Hermes 배선, 런처의 `uvx` 폴백에서 기동마다
  붙던 `--refresh-package` 두 개를 제거했습니다 (#23). 핀이 정확 고정이라 동작은
  같고, 세션 시작마다의 PyPI 왕복과 오프라인 하드 실패만 사라집니다. 최초 venv
  빌드의 1회성 refresh는 유지합니다.
- Codex 번들 `.mcp.json`에 `env_vars` 전달 목록을 추가했습니다. Codex는
  화이트리스트에 없는 환경 변수를 MCP 서버 자식 프로세스에 전달하지 않으므로,
  사용자가 셸에 export한 `HWPX_AUTOMATION_CHROME_PATH`(6.x 레거시 별칭
  `HWPX_MCP_CHROME_PATH` 포함)가 이제 서버까지 전달되어 `render_preview`
  스크린샷 백엔드 차단이 해소됩니다 (#19, 기여 @Jaempark).

## [2.0.2] - 2026-08-22

core 6.3.0(왕복 충실도 트레인)·automation 7.0.3을 따라가는 핀 범프
릴리스입니다. 스킬 내용·도구 표면은 그대로이고 계약 해시는
`8c278ebd5becba08`로 이동합니다(floor-only 델타 — `minPythonHwpx`
6.0.2 → 6.3.0, 도구 136 불변).

- 번들 설치 핀이 `python-hwpx[preview]==6.3.0` ·
  `python-hwpx-automation[mcp,oracle]==7.0.3`으로 전진합니다 — instid
  속성명 수리(core #88·automation #101: 각주/미주 복제 시 인스턴스 ID
  재발급, 실한컴 파일의 각주 식별)·hp:audio 분류 정직화(core #89)·표
  정렬 프리미티브 `reorder_rows`가 플러그인 설치 경로에 전달됩니다.
- 공개 왕복 충실도 지표 신설: 실한컴 저장본 76건 무편집 왕복 실질 변화
  0 · 재개봉 판정 가능 73/73 무손상 (corpus-metrics 페이지).

## [2.0.1] - 2026-08-16

automation 7.0.2 패치를 따라가는 핀 범프 릴리스입니다. 스킬 내용·도구
표면·계약 해시(`34a91560759dc47a`)·플로어는 그대로입니다.

- 번들 설치 핀이 `python-hwpx-automation[mcp,oracle]==7.0.2`로
  전진합니다 — Windows에서 모든 저장이 `WORKSPACE_PATH_CHANGED`로
  실패하던 결함 수정(automation #98)과 클라이언트 업로드 경로
  (`/mnt/user-data/...`) 안내 에러(automation #75, 기여 @adity982)가
  플러그인 설치 경로에도 전달됩니다.
- 코어 핀은 `python-hwpx[preview]==6.1.0` 그대로입니다.

## [2.0.0] - 2026-08-04

엔진 완전성 트레인입니다. 스킬 계약의 도구 어휘는 그대로이고(128/136/29
불변), 스택이 major로 이동합니다 — 핀 `python-hwpx 6.0.0 ·
python-hwpx-automation 7.0.1`, 계약 해시 `34a91560759dc47a`(플로어 전진만으로
이동: minPythonHwpx 6.0.0 · minAutomationVersion 7.0.0 · minSkillVersion
2.0.0).

### 상류 반영

- python-hwpx 6.0.0: 루트 표면 102→34, 도메인 네임스페이스
  (`doc.notes`/`fields`/`shapes`/`styles`/`page`), 스타일 이름 해석,
  `add_heading`, 단일 반환 규약, 공개 경로 typed error 100%. 5.x 루트
  이름 79개는 deprecation shim으로 7.0까지 유지됩니다.
- python-hwpx-automation 7.0.1: 전 콜사이트가 6.0 네임스페이스 표면으로
  이동(`DeprecationWarning`=테스트 실패 게이트), compat 셸은 ==7.0.1 위임.
- 동봉 tool-contract 참조를 7.0.0 계약으로 재생성했습니다.

### 주의

- [1.8.0]은 발행되지 않았습니다 — release-approved 후보 상태에서 이
  트레인에 흡수되었고, 그 정직성 수리 내용은 아래 항목과 상류 CHANGELOG에
  그대로 남아 있습니다. 마지막 공개 스택은 `5.7.0 / 6.7.1 / 1.7.0`입니다.

## [1.8.0] - 2026-08-03 (unpublished — absorbed into 2.0.0)

정직성 트레인입니다 — 스킬 계약(도구 어휘·라우팅)은 그대로이고, 스택 핀이
`python-hwpx 5.8.0 · python-hwpx-automation 6.8.0`(계약 `6ba7bc0ca7226f2f`)으로
전진합니다.

### 고쳐짐

- `hwpx.builder` import를 안내하던 참조 3곳(라우팅 표·API 레퍼런스·결재란
  규칙)을 실재 경로(`hwpx_automation.office.authoring.builder`)로 정정했습니다
  — 문서를 따라 하면 `ImportError`가 나던 상태였습니다.
- "각주는 한컴 렌더 미지원" 지시를 삭제했습니다 — core 5.5.0 트레인에서
  수리·실한컴 검증된 기능을 문서가 억누르고 있었습니다.

### 상류 반영

- 동봉 tool-contract 참조를 6.8.0 계약으로 재생성했습니다(도구 수 불변
  128/136/29, 해시는 플로어 전진만으로 이동).
- 상류 정직성 수리(영수증 무결성·자기서술 검증기·코퍼스 v3 재측정)는 core
  5.8.0/automation 6.8.0 CHANGELOG를 참조하십시오.

## Unreleased

## [1.7.0] - 2026-08-03

양식개체·기안문 장르 트레인 — 핀은 `python-hwpx[preview]==5.7.0` ·
`python-hwpx-automation[mcp,oracle]==6.7.1`(계약 128/136/29 @
`98510af22d13899c`)입니다.

### 추가
- **기안문 서식 저작 라우팅**: 별지 제1호서식(일반기안문)·제2호서식
  (간이기안문)을 `compose_official_draft`/`compose_simple_draft` →
  `validate_document_plan` → `create_document_from_plan`으로 안내합니다.
  `references/workflows-authoring.md`에 두뇌가 판정할 항목(수신 형태·내부결재·
  결재자 목록·전결/대결·공개구분)과 규정 불변식 3종(결재란 가변 N·결문 라벨
  미인쇄·`[ ]`+√ 관례)을 정리했습니다.
- **체크박스 경계 안내**: 한컴 체크박스 양식개체는 **공문서가 아닌** 서식에
  쓰며, 공문서 선택 항목은 `[  ]`+√ 텍스트를 씁니다(시행규칙 별표 4 제10호).

### 정직 경계
- 기안문 본문 글꼴·글자 크기와 행 높이 mm는 법령이 정하지 않습니다 — 프리셋
  기본값이며 규정 근거로 주장하지 않습니다.
- document_plan 문단 `align`이 산출물에 반영되지 않는 알려진 결함이 있어,
  가운데 정렬은 생성 후 `set_paragraph_format`으로 맞추도록 안내합니다.

## [1.6.0] - 2026-08-03

에이전트 계약 표면 트레인 — 핀은 `python-hwpx[preview]==5.6.0` ·
`python-hwpx-automation[mcp,oracle]==6.6.1`(계약 126/134/29 @
`19898dba41495c47`)입니다.

### 추가
- **`run_edit_plan` 라우팅**: SKILL.md 케이스 표에 "부분 적용이 허용 안 되는
  바이트-스플라이스 다단 편집 → 계획 1파일(dry_run 승인 루프)" 행을
  추가했습니다. `references/workflows-editing.md` §5-b가 판단 규칙(두뇌=스킬·
  손=계획)·원자성 계약·`hwpx://schemas/edit-plan-v1` 리소스 구독을 안내합니다.
- **MCP resources 구독**: 계약 문서 4종(support-matrix·recipes-traversal·
  mutation-semantics·known-traps)과 스키마 4종을 도구 호출 없이 리소스로
  읽을 수 있습니다.

### 변경
- `run_edit_plan`은 `apply_table_ops`/`apply_body_ops`와 같은 skill-required
  등급입니다(28→29).

## [1.5.0] - 2026-08-02

운영계획 zero-base 저작 트레인(automation 6.5.0, 계약
`f61d2c60c0aa0413`, 기본 125/고급 133/스킬 필수 28). 브리프만으로
장르-충실 운영계획서를 백지 합성 — 섹션칩(`compose_section_chip`)·표-기반
박스 조직도(`add_boxed_org_chart`)·장르 문법 조회(`get_genre_grammar`)와
`style_preset="genre:operating_plan"`(뱅크-구동 타이포).

- 라우팅: SKILL.md 운영계획 행 + `references/workflows-authoring.md`
  zero-base 판단 블록(변주 슬롯·inline 칩 번호 위임·accent 후처리).
- 번들 핀 갱신: `python-hwpx[preview]==5.5.0` ·
  `python-hwpx-automation[mcp,oracle]==6.5.0`.

## [1.4.1] - 2026-08-02

각주/미주 렌더 계약 수리 트레인(core-only — automation 6.4.2·계약
`dbdbdfaac26148b7` 불변). core 5.5.0은 실한컴 gold 리버스로 각주 방출을
수리해 **실한컴에서 각주가 실제로 그려지고**, 리더가 실한컴산 문서의
ctrl-래핑 각주를 읽습니다.

- 번들 핀 갱신: `python-hwpx[preview]==5.5.0` ·
  `python-hwpx-automation[mcp,oracle]==6.4.2`.

## [1.4.0] - 2026-08-01

표 서식·저작 기본값 수리 트레인. `format_table` 테두리·음영 확장
(automation 6.4.0, 계약 `dbdbdfaac26148b7`, 기본 122/고급 130/스킬 필수
28) — `border_type`(OWPML 선 종류 어휘, 밖은 typed 거부)·`border_color`·
`border_width`·`fill_color`·`row`/`col` 셀 단위 적용. core 5.4.0은 표
기본값(셀 안여백 510/141·본문폭·중첩=부모 셀 폭), 목록 paraPr 비상속,
하이퍼링크 파랑/밑줄 관례, 첨자 offset 부호 정정, `ensure_run_style`
확장 7종을 담는다.

- 라우팅: SKILL.md 표 행 확장 + `references/workflows-editing.md` 테두리·
  음영 판단 규칙(표 단위 vs 셀 단위·DASH 렌더 패턴 주의).
- 번들 핀 갱신: `python-hwpx[preview]==5.4.0` ·
  `python-hwpx-automation[mcp,oracle]==6.4.0`.

## [1.3.0] - 2026-07-31

차트 생성 트레인. `add_chart` 도구(automation 6.3.1, 계약
`236f8ea855c875fe`, 기본 122/고급 130/스킬 필수 28)로 데이터 시리즈를
네이티브 차트(막대·꺾은선·원)로 삽입한다 — ECMA-376 chartML만 저장하고
실한컴이 그대로 그리며(OLE 폴백 없음), 밖의 유형은 typed 거부.

- 라우팅: SKILL.md 차트 행 + `references/workflows-authoring.md` 차트 삽입
  판단 규칙(유형 제한·시리즈 정합·배치 주소·시각 확인).
- 번들 핀 갱신: `python-hwpx[preview]==5.3.0` ·
  `python-hwpx-automation[mcp,oracle]==6.3.1`.

## [1.2.0] - 2026-07-31

수식 저작 트레인. `add_equation` 도구(automation 6.2.1, 계약
`342cf672f29cd183`, 기본 121/고급 129/스킬 필수 28)로 LaTeX 수식을 네이티브
`<hp:equation>`으로 삽입한다 — 렌더 검증된 토큰셋 밖은 typed 거부(무음 근사
없음), 응답의 `readerLatex`가 자기 왕복 증거.

- 라우팅: SKILL.md 수식 행 + `references/workflows-authoring.md` 수식 삽입
  판단 규칙(커버리지 밖 대응·왕복 확인·표 셀 배치·줄높이 주의).
- 번들 핀 갱신: `python-hwpx[preview]==5.2.0` ·
  `python-hwpx-automation[mcp,oracle]==6.2.1`.

## [1.1.0] - 2026-07-31

누름틀 필드 저작 트레인. `add_form_field` 도구(automation 6.1.0, 계약
`ac1a422376b5ac84`, 기본 120/고급 128/스킬 필수 28)로 양식 수명주기
(create→list→fill→verify)가 한컴 수동 준비 없이 자급된다.

- 번들 핀 갱신: `python-hwpx[preview]==5.1.0` ·
  `python-hwpx-automation[mcp,oracle]==6.1.0`.
- `references/workflows-forms.md`: 누름틀 생성 판단 규칙(이름=선택자·안내문
  미인쇄·배치 주소 3형·생성 직후 왕복 확인) 추가.
- generated tool-contract 참조 재생성(128 도구), task-eval 프로파일
  `current-1.1.0` 회전.

## [1.0.1] - 2026-07-31

core `python-hwpx 5.0.2` repin 트레인. automation은 `6.0.4` 그대로이고 MCP
계약 해시도 `0ce938371f0b55a6`으로 불변이다(core-only 패치 + 핀 추종).

### Changed
- 번들 핀 갱신: `python-hwpx[preview]==5.0.2` (5.0.2 = 조용한 첫 실행
  경고 픽스 + Python 3.13/3.14 공식 지원 + 릴리스 검증기 수정).
- `references/api.md` 시그니처 기준을 5.0.1 실측으로 현대화(드리프트 2건
  교정: `add_table`의 `inherit_style`, `set_cell_text`의 fit 계약).
- 검증기의 트레인 락 상수(previous public train)를 2026-07-28 발행 트레인
  (5.0.1/6.0.4/1.0.0)으로 전진, task-eval 프로파일 `current-1.0.1` 추가.

## [1.0.0] - 2026-07-28

5.0 스택 트레인. 발행 당시 직전 공개 스택은
`python-hwpx 4.2.0` / `hwpx-mcp-server 5.1.0` / `hwpx-plugin 0.8.0`이었다.
후보에서는 `python-hwpx` 5.0이 응용 워크플로를 내려놓고
`python-hwpx-automation` 6.0이 그 유일한 소유자가 된다. 스킬의 라우팅 정책 자체는 바뀌지 않았다 —
바뀐 것은 core 직접 import 대안이 더 이상 존재하지 않는다는 사실이다.

### Changed — BREAKING
- 후보 스택 핀 갱신: `python-hwpx[preview]==5.0.0` ·
  `python-hwpx-automation[mcp,oracle]==6.0.0`. 정식 MCP 콘솔은
  `hwpx-automation-mcp`이고, `hwpx-mcp-server` 배포/import/콘솔은 6.x
  호환 표면이다. 계약 `429cb6706323e762` → `0ce938371f0b55a6`
  (119/127/28 불변 — 이름·순서·스키마·분류·오류계약 전부 동일).
  검토 중이던 `e592ede5b0eb1a35`는 advanced 환경변수 안내가 옛 이름만
  가리킨 후보였고, `9abec41b740f3e0e`는 `minAutomationVersion`을 정식
  이름으로 싣기 전 후보였으므로 둘 다 발행하지 않고 supersede했다.
- 새 4-host 설정의 local key를 `hwpx`, bundle launcher를
  `scripts/hwpx-automation-mcp`로 통일했다. 기존 `hwpx-mcp-server` key와
  `scripts/hwpx-mcp-server`는 각각 명시적 기존 설정 override와 canonical
  launcher 위임 wrapper로만 6.x에서 유지한다. FastMCP 이름은 별개인
  `python-hwpx-automation`이다.
- 4.x 호환 창 안내 문서 7종을 완료된 이행 하나
  (`references/migration-core-5.0.md`)로 대체했다. 이미 끝난 이행을 아직
  진행 중인 것처럼 설명하는 문서를 남기는 것이 코드네임을 지우는 것보다 나쁘다.
- 워크플로별 최소 버전 표기(`hwpx-mcp-server>=4.3.0` 등)를 제거했다. 스킬 계약의
  바닥이 6.0.0인 이상 지원되는 어떤 설치에도 4.3.0은 없으므로, 그 문장은
  안내가 아니라 오해만 만든다. 도구 존재 확인은 `mcp_server_health()`로 한다.

### Fixed
- **README·`references/api.md`의 버전 표가 낡아 있었다.** "최소 호환 버전"은
  core `>=4.2.0` / MCP `>=5.1.0`을, api.md의 "플러그인 설치 핀"은
  `==4.2.0`/`==5.1.0`을 가리켰다 — 두 파일 사이에서도 서로 어긋났고, api.md를
  따라 설치하면 이 스킬이 지원하지 않는 조합이 된다. `product-identity.json`은
  줄곧 옳은 값을 담고 있었지만 아무도 대조하지 않았기 때문에 통과했다.
  이제 대조하는 테스트가 있다.
- SKILL.md에서 마이그레이션 참조 항목이 라우팅 표 한가운데에 들어가 표를
  깨뜨리던 것을 참조 목록으로 옮겼다.
- `hwpx.presets`·`hwpx.builder`를 import하던 예제 2개를 MCP 소유자 경로로
  바꿨다. 자기 예제가 돌지 않는 스킬은 예제가 없는 것만 못하다.

## [0.8.0] - 2026-07-22

### Added
- 평가계획 실채움 워크플로(`references/workflows-evalplan.md`) — 빈 양식 + 검토용 MD를
  `apply_evalplan_fill(phase="clean")` 한 경로로 잔존물 없이 채우는 두뇌 판단(J1~J6).
### Changed
- 스택 핀 갱신: `python-hwpx[visual,preview]==4.2.0` · `hwpx-mcp-server==5.1.0`. 계약 429cb6706323e762.

## [0.7.1] - 2026-07-21

### Changed
- 스택 핀 갱신: `python-hwpx[visual,preview]==4.1.1` (form-fill 차등 판정기
  테두리 기반 교정 — `verify_form_fill` 계열 게이트의 허위 shape/overflow 실패
  제거, 산출물 불변). `hwpx-mcp-server==5.0.0` 유지.

## [0.7.0] - 2026-07-21

### Changed
- 5.0 경계 가이드 이주: `hwpx-mcp-server` 5.0.0에서 제거되는 stub 5종
  (`plan_edit`/`preview_edit`/`apply_edit`/`analyze_quality_generation`/
  `apply_quality_generation`)에 대한 스킬 가이드 참조를 canonical
  `apply_document_commands`·`create_document_from_plan`·`inspect_document_quality`
  경로로 전량 이주했다. 1군(`fill_form_field`,
  `analyze_template_formfit`/`apply_template_formfit`) 문구를 "관찰 릴리스"에서
  "DEPRECATED — 5.0 경계 확정(동작 유지, 제거는 다음 major)"로 갱신했다. 2군
  (`apply_edits`/`fill_by_path`/`create_comparison_table_document`)은 분류 불변,
  교육 경로만 canonical로 이주했다.
- 신설 [`references/migration-mcp-5.0.md`](references/migration-mcp-5.0.md) — 제거 5종
  대체표 + 1군 DEPRECATED 공지 + 2군 권장 경로.

## [0.6.8] - 2026-07-21

### Notes
- `v0.6.7`은 보존 태그입니다 — 당시 핀 `hwpx-mcp-server==4.4.0`이 릴리스 게이트
  실패로 PyPI에 발행되지 않아 설치가 해석 단계에서 실패합니다(잘못된 비트가
  설치되지는 않음). 본 0.6.8이 `==4.4.1`로 복구한 대표 릴리스입니다.

## [0.6.7] - 2026-07-21 (보존 태그)

### Added
- `references/workflows-preview.md`: 한컴 없이 스크롤 통독하는 문서 프리뷰
  워크플로 — `render_preview(viewer=true)` 계약(`hwpx-mcp-server>=4.4.0`),
  3단 수식 fail-closed 의미, 환경별 전달(Artifact/로컬 open), 정직 티어 보고.

### Changed
- Repins the bundle to `python-hwpx[visual,preview]==3.8.0`(수식 MathML 렌더
  포함) and `hwpx-mcp-server==4.4.0`. Contract hash `c89cbc5f98eb5367`
  (additive-only delta: render_preview optional `viewer` param — proof in the
  server repo's `docs/tool-contract-delta-4.4.0.json`).

## [0.6.7] - 2026-07-21

### Notes
- `v0.6.5`는 버전락 테스트 미갱신(red 스위트)으로 보존된 태그입니다 — 번들
  내용의 기능 결함은 없으며 마켓플레이스 산출물은 본 0.6.7이 대표합니다.

## [0.6.5] - 2026-07-21 (보존 태그)

### Changed
- Repins the bundle core to `python-hwpx[visual,preview]==3.8.0` — the Safe Write
  Contract release: explicit write mode(patch|rebuild|auto), mutation-report/v1
  receipts, no-silent-fallback(PreservationDowngradeError), 공개 지원 매트릭스.
  `hwpx-mcp-server` stays `==4.3.2`; contract hash unchanged.

## [0.6.5] - 2026-07-21

### Changed
- Repins the bundle MCP server to `hwpx-mcp-server==4.4.0`, which ships the
  degenerate-cwd workspace fallback fix: GUI MCP clients (Windows Claude
  Desktop 등) that launch the server from a system directory now get an
  actionable `HWPX_MCP_WORKSPACE_ROOTS` configuration error instead of every
  path being rejected. Core stays `python-hwpx[visual,preview]==3.8.0`; contract hash
  unchanged.

## [0.6.5] - 2026-07-20

### Changed
- Repins the bundle core to `python-hwpx[visual,preview]==3.8.0` (structural
  form-fill fix: inline-control width modeled, impossible fills are typed
  refusals; silent breakage 47%->16.7% on the wild differential).
  `hwpx-mcp-server` stays `==4.3.0`, contract hash unchanged.
- `references/workflows-bulk-compare.md`: the honest-limit guidance now says
  control-sharing cells are refused by design (pick the intended value cell)
  and multi-page form fills should go through a render gate.

## [0.6.5] - 2026-07-20

### Changed
- Repins the bundle core to `python-hwpx[visual,preview]==3.8.0` so the installed
  surface reaches the height-budget fit engine (form-fill shrink and
  typed overflow refusal are now real, reachable via `mail_merge`'s
  `fit_mode`). `hwpx-mcp-server` stays `==4.3.0` and the contract hash is
  unchanged (`f82caecbcfc742e9`) — no MCP change. Replay profile renamed to
  `current-0.6.8`.

## [0.6.5] - 2026-07-19

### Changed
- Repins the bundle core to `python-hwpx[visual,preview]==3.8.0` — the exact stack the
  M9 published-corpus measurement ran on (open 476/476 all-pass, per-axis
  reports; see the core repo's `docs/corpus-metrics.md`). `hwpx-mcp-server`
  stays `==4.3.0` (contract `f82caecbcfc742e9` unchanged, floor `>=3.3.1`
  admits 3.6.0). The deterministic replay profile moves to `current-0.6.8`.
- Core `v3.4.0` is a preserved failed tag (prepublish hygiene gate); 3.6.0 is
  the recovery release this bundle pins.

## [0.6.0] - 2026-07-18

### Changed
- Migrates the tier-1 facade guides to the canonical form-fill trio
  (`analyze_form_fill` → `apply_form_fill` → `verify_form_fill`): the
  `analyze_template_formfit`/`apply_template_formfit` tutorial in
  `references/api.md` shrinks to a compatibility note, `fill_form_field` is
  documented as observation-only (native-field fills are expressed as
  canonical-plan `nativeField` operations), and the legacy MCP form-fit
  example is replaced by `examples/08_mcp_canonical_form_fill.md`. The three
  tools stay installed and functional; demotion is deferred to the next major
  after observing consumption. `examples/08_template_formfit.py` remains as
  the labelled compatibility regression gate (`quickcheck --template-formfit`).
- Documents `apply_table_ops`/`apply_body_ops` as public low-level primitives
  (promoted out of the compatibility-facade table in MCP 4.3.0); form filling
  still routes through the single canonical transaction.
- Repins the bundle stack to `python-hwpx[visual]==3.3.1` ·
  `hwpx-mcp-server==4.4.0` (contract hash `f82caecbcfc742e9`, surface
  unchanged at 121 default / 132 advanced / 28 skill-required) and renames the
  deterministic replay profile to `current-0.6.0`.

## [0.5.1] - 2026-07-18

### Note
- Recovery release. The `v0.5.0` tag was cut before the MCP `v4.2.0`
  prepublish failure surfaced, so its bundles carried a stale generated
  contract document and its CI pinned the previous stack. `v0.5.0` is
  preserved as failure history and was never announced to the marketplace as
  current; 0.5.1 is the actual public release, pinned to the recovered
  `hwpx-mcp-server 4.2.1` at contract `fff2c9093ca4677b`.

### Changed
- The task-eval harness now hard-fails when `hwpx_mcp_server.server` fails to
  import for any reason other than a missing FastMCP SDK. A broken or
  mismatched sibling stack previously degraded to the fallback adapter and
  reported a plausible-looking 0/44 score; it now raises an explicit
  environment error instead.
- Replaced stale internal-stage `hwpx-mcp-server>=4.0.0` contract labels in SKILL.md
  and the toc/reading/exam workflow references with the current declared floor
  (stage labels age; version floors stay true).
- Publishes the 0.5.1 triplet pins: `python-hwpx==3.3.0`,
  `hwpx-mcp-server==4.2.1`, plugin `0.5.1`. The tool surface stays exactly
  121 default / 132 advanced / 28 skill-required; the contract hash moves to
  `fff2c9093ca4677b` purely through the version coordinates embedded in the
  canonical payload.
- The MCP floor gains an exact SDK pin (`mcp==1.28.1`), a zero-import-cycle
  architecture baseline, and bounded optional-oracle waits
  (`HWPX_ORACLE_STRUCTURAL_ONLY`, `HWPX_ORACLE_BUDGET_SECONDS`, TCC
  reachability probe in core 3.3.0).

## [0.4.0] - 2026-07-17

### Added
- Documents the command-only existing-header story path for
  `apply_document_commands`, allowing body, table-cell, and one simple existing section
  header to commit in the same revision-bound, idempotent transaction without adding an
  MCP tool or changing the public node catalog.
- Adds the release-final `demo/025-runtime-modularization` reference package for the synthetic
  two-section Korean office document, including frozen exact source/output bytes, a replayable
  public MCP request, public-index replay support, and bundled warning-free Hancom evidence.

### Changed
- Publishes the approved triplet as `python-hwpx 3.2.0`,
  `hwpx-mcp-server 4.1.0`, and `hwpx-plugin 0.4.0`; the four generated host bundles pin
  the exact released core and MCP packages after regeneration.
- Requires the same `3.2.0 / 4.1.0 / 0.4.0` minimum stack. Public core 3.1.0 rejects the
  new header path, so retaining the old floor would advertise a capability the declared
  minimum cannot execute.
- Keeps the 121 default / 132 advanced tool-name surface and 28 skill-required tools while
  moving core OXML ownership, MCP handlers, and `HwpxOps` domains behind bounded facades.

### Fixed
- Records the core section-creation contract that copies renderable page layout, keeps
  section stories independent, synchronizes `hh:head/@secCnt`, and fails before mutation
  when a renderable adjacent layout is unavailable.
- Preserves unrelated section bytes, existing header identities, rollback, reopen,
  openSafety, and one-serialization semantics in the installed multi-story transaction.

## [0.3.0] - 2026-07-16

### Removed
- Removes the four repository-QA fixture tools from the public skill routing and generated host bundles:
  `visual_review_fixture`, `visual_repair_fixture`, `run_fixture_benchmark`, and
  `export_fixture_benchmark`. Their synthetic fixtures and runners remain repository-internal regression assets.

### Changed
- Routes ordinary and mixed-anchor forms through one typed `analyze_form_fill` → `apply_form_fill` →
  `verify_form_fill` transaction, while keeping exam and evalplan requests on their explicit specialized paths.
- Adds a machine-readable first-party product identity for released/minimum/pinned versions and maturity vocabulary,
  and publishes the core `3.1.0`, MCP `4.0.0`, and plugin `0.3.0` triplet.
- Renames task-eval output as deterministic direct-call replay and explicitly excludes live-agent routing,
  recovery, and unnecessary-call claims.

### Fixed
- Bundles the previously missing TOC reference, changelog, and product identity in every host artifact and validates
  safe, existing relative Markdown links so broken or traversal links fail closed.
- Refreshes the API reference from obsolete 2.x baseline language to the public
  `3.1.0 / 4.0.0 / 0.3.0` stack.

## [0.2.0] - 2026-07-16

### Removed
- Removes the seven private-practice scenario/campaign tools from the public plugin without compatibility
  aliases. Internal campaign work now belongs to the workspace-private QA harness.

### Changed
- Binds the plugin to `python-hwpx==3.0.0` and `hwpx-mcp-server==3.0.0`. Public document work should use
  `apply_document_commands`, `apply_evalplan_fill`, `scan_form_guidance`, `apply_table_ops`, `apply_body_ops`,
  or `verify_form_fill`; exam, evalplan, form-fill, authoring, editing, verification, workflow, and render routes
  remain public.

## [0.1.31] - 2026-07-15

### Security
- Codex no longer fixes MCP `cwd` to the plugin cache. Its root-independent `uvx` command preserves the
  active thread workspace; Claude keeps its absolute plugin-root launcher while preserving project CWD.
- The bundled launcher builds an exact `python-hwpx==2.29.2` / `hwpx-mcp-server==2.23.1` runtime behind a
  stale-aware concurrency lock, verifies both installed versions, and atomically promotes a full
  plugin/MCP/core/Python-ABI/platform fingerprint. Parallel cold starts cannot observe a partial venv.
- Public bundles drop private/generated benchmark state, generated evidence, and workstation metadata;
  GitHub Actions use immutable commits with CodeQL, dependency review, Dependabot, and runtime SBOM gates.

### Changed
- Raises the bundle contract to `python-hwpx==2.29.2`, `hwpx-mcp-server==2.23.1`, and skill `0.1.31`
  without changing the 133 default / 143 advanced tool names.
- Synthetic benchmark outputs are generated in disposable workspaces. Installed host bundles no longer carry
  duplicate blind packets, routing, scored passes, or result projections.

## [0.1.30] - 2026-07-15

### Added
- typed `.hwpxbp` dump/inspect/repack와 portable/source-bound atomic replay를 안내하는
  `workflows-agent-blueprint` 라우팅. strict fidelity, rollback, lossless/openSafety, 실제 한컴 영수증을
  요구하고 raw XML·resident/watch·OfficeCLI fallback을 금지한다.
- 문서 투영·조회·원자 명령을 하나의 경로로 묶는 agent document workflow와
  `get_document_node`, `query_document_nodes`, `apply_document_commands` 3도구 라우팅.
- 페이지 PNG fixture의 전 페이지 결함 검수, append-only evidence ledger, 최대 3회 안전수정과
  unsafe/unmapped escalation을 안내하는 스킬 라우팅 및 설치 MCP leap-demo 하네스.
- fixture 영수증은 절대 `renderChecked=true` 또는 실한컴 검증으로 승격하지 않는 hard rule.
- 비동기 실한컴 `render_health` → `render_submit` → `render_status`/`render_cancel` 라우팅과
  입력·출력 hash, Hancom build, worker provenance, PDF/페이지 PNG 검증 절차.
- 설치 플러그인 MCP E2E에 4개 render 도구와 honest unavailable/선택적 real-render 게이트 추가.
- 합성 블라인드 qualification fixture: 6개 family의 work order 72개, must-abstain 12개,
  versioned fixture profile 3개와 익명 artifact 216개. 독립 `agent_judge` 2회용 템플릿과 단일 result
  manifest 기반 report/gallery/scorecard projection 및 drift gate를 포함한다.

### Changed
- 공개 결속을 `python-hwpx==2.29.1`, `hwpx-mcp-server==2.23.0`, 스킬 `0.1.30`으로 올리고
  default/advanced ToolSpec을 133/143개로 갱신했다. 이보다 낮은 구성은 capability handshake에서
  fail closed 한다.
- Claude, Codex, Hermes, OpenClaw 번들을 같은 정본 계약과 핀에서 재생성한다.

### Fixed
- 공개 0.1.26/0.1.27이 고정했던 병적인 음수 자간 복구와 SQUEEZE 셀 wrap 안전성을 새 3-stack
  결속에서도 유지한다.

### Note
- core `v2.29.0`은 prepublish 실패 태그로만 보존되고 PyPI/GitHub Release가 없으므로, 실제 공개
  결속은 수정 릴리스 `python-hwpx==2.29.1`을 사용한다.
- 0.1.28/0.1.29는 단계별 로컬 후보였으며 공개 배포 이력이 아니다. 해당 누적 변경은 이 0.1.30
  공개 항목으로 통합한다.

## [0.1.27] - 2026-07-14
### Fixed
- 표 양식의 `SQUEEZE` 셀에 긴 텍스트를 채울 때 한컴이 글자 폭을 겹칠 정도로 압축하던 문제를
  고친 `hwpx-mcp-server==2.18.3`(`python-hwpx>=2.24.1`)을 모든 호스트 런처와 설치 문서에 고정.

## [0.1.26] - 2026-07-13
### Fixed
- 텍스트 교체·문단 추가·표 셀 채움에서 병적인 음수 자간이 새 내용에 전파되어 글자가 겹치던
  문제를 고친 `hwpx-mcp-server==2.18.2`를 번들 런처와 설치 문서에 고정.
- PyPI 릴리스 직후 `uv` 메타데이터 캐시 때문에 스택 릴리스가 전파 대기에서 멈추지 않도록
  패키지 메타데이터를 강제 새로고침.
- 릴리스 계약 검증이 최소 호환 버전과 현재 번들 버전을 동일값으로 오인하지 않고, 현재 버전이
  최소값 이상인지 비교하도록 수정.

## [0.1.25] - 2026-07-10
### Fixed
- FastMCP 2.18.1 핫픽스를 고정해 universal form-fill 7도구가 설치 플러그인 표면에서 실제 호출되도록 복구.
- 런처가 실제 스킬 버전 0.1.25를 capability handshake에 전달하고, clean-install smoke용
  local-editable 비활성화/패키지 override를 지원.
- ToolSpec에서 생성한 default/advanced/필수 도구 API 인덱스를 4호스트 번들에 포함.

## [0.1.24] - 2026-07-09
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.18.0`으로 갱신.


## [0.1.21] - 2026-07-06
### Fixed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.16.0`(`python-hwpx>=2.23.0`)으로 갱신. **styled-run 글자속성 픽스**를 배포: `add_paragraph`/`insert_paragraph`/`add_table`가 새 run에 문단 스타일의 글자속성을 실어 준다(기존엔 `charPrIDRef="0"` 기본값 → 0번이 제목용 큰 글자인 양식에서 본문이 통째로 커지는 버그; 예: KACE 투고양식은 charPr 0 = 17pt라 `j-본문` 본문이 17pt로 샜음 → 이제 9pt). 회귀 가드(`_enforce_run_char_pr`)로 재확인. 부수적으로 `hwpx-mcp-server` 2.16.0의 Spec 013 document ingest + Markdown-plan bridge 포함.

## [0.1.20] - 2026-07-03
### Added
- `references/workflows-forms.md` ④ 경로에 **폰트 shrink-to-fit** 안내: `fill_cell`의 `max_lines`로 셀을 N줄 안에 맞게 폰트 축소(열 너비 부족 시 세로 축소). 폼 기본 폰트가 작으면 autofit(가로)이 주력임을 명시.
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.15.0`(폰트 축소맞춤)으로 갱신, `python-hwpx>=2.23.0` 필요.
- README 정비 471→178줄(5개 설치 섹션을 호스트별 1개로 통합, 긴 예제·중복 제거, 버전 최신화).

## [0.1.19] - 2026-07-03
### Added
- `references/workflows-forms.md` ④ 경로에 **열 너비 조정**: `apply_table_ops`의 `autofit_columns`(내용에 맞춰 열너비 재균형, 긴 텍스트의 세로 cramping 완화)·`set_column_widths`(명시적 지정) 안내. 한컴이 행 높이는 자동으로 늘리므로 autofit은 가로 재분배 미용 단계임을 명시.
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.14.0`(열너비 op)으로 갱신, `python-hwpx>=2.22.0` 필요.

## [0.1.18] - 2026-07-03
### Added
- `references/workflows-forms.md` **④ 구조 변경 보존 채움** 경로 (M10): 채우며 표 구조를 바꿔야 하는 양식(안 쓰는 표·열 삭제, 내용에 맞춰 행 증설)을 `apply_table_ops`(fill_cell + delete_column/delete_row/delete_table + insert_row_by_clone)로 **원본 서식 보존한 채** 수술하고 `verify_form_fill`(실한컴 렌더 게이트)로 검증. "표 재생성 금지" 철칙 배너 + 매 학기 재사용 레시피(빈 양식 + 콘텐츠 md + 규칙). SKILL.md 라우팅 추가.
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.13.0`(M10 form-fill 도구)으로 갱신, `python-hwpx>=2.21.0`(`hwpx.table_patch`) 필요.

## [0.1.15] - 2026-07-01
### Added
- `references/workflows-pii.md` — 개인정보(PII) 마스킹 워크플로 (M5). 양식채움·메일머지·추출이 기계검증 PII(주민등록번호·휴대폰·이메일·카드)를 **기본 마스킹**하고, `scan_personal_info` 로 감사. 기계세트=항상-on, 맥락형=라벨게이트 low-confidence(과마스킹 방지). SKILL.md 라우터 + 참조 목록 연결.
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.10.0`(PII 마스킹 표면)으로 갱신, `python-hwpx>=2.18.0`(`hwpx.tools.pii`) 필요.

## [0.1.14] - 2026-06-30
### Added
- `references/workflows-redline.md` — 변경추적(redline) 저작 워크플로 (M4). `add_tracked_edit`(insert/delete/replace + 코멘트)로 에이전트가 redline을 저작하고 사람이 한컴 검토 리본에서 수락/거부. verify 영수증(render_checked 정직 강등)·byte-identity/수락방식의 정직 한계 명시. SKILL.md 라우터 + 참조 목록에 연결.
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.9.0`(`add_tracked_edit` redline 표면)으로 갱신, `python-hwpx>=2.17.0`(redline 저작 API + 메모 본문 픽스) 필요.

## [0.1.13] - 2026-06-29
### Added
- `references/workflows-authoring.md` + SKILL.md routing row — M3 document authoring: 공문/보고서/가정통신문 작성 루프(`create_document_from_plan` with `metadata.document_type` + `gyeolmun`), 공문 구조 hard-gate 해석, 맞춤법/각주 정직 라벨, HWPX-only. Added to `packaging/hosts.json` sharedAssets; 4 host bundles rebuilt.
### Changed
- Launcher pins `hwpx-mcp-server==2.8.0` (M3 surface: document_type routing, 결문 IR, 공문 hard-gate, `render_checked`; pulls `python-hwpx>=2.16.0`).

## [0.1.12] - 2026-06-27
### Added
- Route 시험지 조판(출제 md를 학교 양식에 재조판) → `compose_exam` · `verify_question_splits` and a new `references/workflows-exam.md`: 문항 keep-together(단/쪽 경계 미분리), 관리박스·머리글/꼬리글 무손실 보존, `[그림N]`/`[표N]`은 텍스트 placeholder, 한컴 커브-export 양식의 정직 게이트(`splits=null`+`needsReview` → `render_preview` 시각 증거, 텍스트 0 사칭 금지). 4개 호스트 번들에 reference 동봉. leap 데모: `demo/exam-typesetting/`.
### Changed
- 번들 Codex/Claude/OpenClaw/Hermes 런처 + MCP 설치 문서 핀을 `hwpx-mcp-server==2.7.0`(시험지 조판 `compose_exam`/`verify_question_splits` + keep-together)으로 갱신, `python-hwpx>=2.15.0`(`hwpx.exam`) 필요 (다운스트림 릴리스).

## [0.1.11] - 2026-06-25
### Added
- Route 직인/관인 날인 → `place_seal` · `check_seal_compliance` (발신명의 끝글자에 도장, 한컴 오라클로 0.12pt 검증; 오라클 없으면 `renderChecked=false` 정직 degrade) and a new `references/workflows-forms.md` ④ 날인 경로.
- Route fit-aware 메일머지 + 명부(CSV/XLSX) + 표 셀 placeholder → `mail_merge` `fit_mode` (셀 넘침/결측 행을 `needsReview[]`/`skipped[]`로 격리, `fitAware`).
### Fixed
- Pin bundled Codex/Claude/OpenClaw/Hermes launchers + MCP install docs to `hwpx-mcp-server==2.6.0` (place_seal/check_seal_compliance/mail_merge fit_mode + `[oracle]` extra), which requires `python-hwpx>=2.14.0`.

## [0.1.10] - 2026-06-25
### Fixed
- Pin bundled Codex/Claude launchers and MCP install docs to `hwpx-mcp-server==2.5.0` (Phase F VisualComplete quality contract — fail-closed `visualComplete` gate + capability handshake), which requires `python-hwpx>=2.12.0`.

## [0.1.9] - 2026-06-12
### Fixed
- Pin bundled Codex/Claude launchers and MCP install docs to `hwpx-mcp-server==2.4.1`, which pulls `python-hwpx>=2.11.1`.
- Generated document-plan reports now use real `개요 N`/`Outline N` paragraph styles and visible title/heading hierarchy by default, so one-shot report creation produces structured headings without follow-up prompting.
- Refresh skill/reference compatibility notes and task-eval current profile for the `0.1.9` bundle.

## [0.1.8] - 2026-06-12
### Changed
- SKILL.md를 390줄 매뉴얼 합본에서 99줄 케이스→경로 라우터(단일 라우팅 표 39행)로 재구성 — 발화당 컨텍스트 비용 약 67% 절감. 상세 워크플로는 `references/workflows-{editing,creation,forms,bulk-compare}.md`와 `references/evidence-contract.md`로 분리(증거 계약 4회 중복 → 1곳).
- 2.4.0 도구 표면 중 미안내였던 19종(트랜잭션 편집 `apply_edits`·`undo_last_edit`·revision 가드, 서식 편집 5종, 그림 2종, 신구대조 2종, 고급 생성기 3종, `get_document_map`, `byte_preserving_patch`)의 교육을 추가하고 편집 표준 루프를 1급 케이스로 승격.
- 평가 하니스 guidance 채점을 프로파일 태그 자기신고에서 스킬 번들 본문 검증으로 전환(태그만으로 통과 불가, 단위 테스트 보증). 평가 태스크 32→42개. 신 번들 42/42 vs 0.1.6 33/42 vs 0.1.5 25/42.

## [0.1.7] - 2026-06-12
### Changed
- 플러그인 런처를 `hwpx-mcp-server==2.4.0`(+ `python-hwpx>=2.11.0`)으로 핀 갱신 — 신뢰 루프(트랜잭션 편집·렌더 프리뷰·revision 가드)·서식 편집·누름틀·공문서 lint·고급 생성기·메일머지·서식 이식 도구 전체가 설치 플러그인에 노출된다 (배포 스큐 해소).
- SKILL.md·README·api.md의 호환 기준을 `python-hwpx >= 2.11.0`으로 갱신.

## [0.1.6] - 2026-06-09
### Fixed
- Pin bundled MCP fallback launchers and MCP install docs to `hwpx-mcp-server==2.3.5`, which includes the editor-open safety gate backed by `python-hwpx>=2.10.3`.
- Validate ZIP-level script outputs before replacing targets so `zip_replace_all.py` and `fix_namespaces.py` do not leave editor-unsafe HWPX files behind.
- Make direct `zip_replace_all()` and `fix_namespaces()` helper-function calls use temporary output plus open-safety validation by default before replacing the requested target.
- Remove the public `verify_open_safety=False` bypass from ZIP-level helper functions; unchecked writes are now private implementation details used only before a later validation gate.
- Fail closed when ZIP-level helpers cannot import `validate_editor_open_safety`, instead of falling back to weaker legacy package/open checks.
- Normalize section/header root namespaces and `standalone="yes"` declarations in ZIP-level script outputs, matching the hardened `python-hwpx` save surface.
- Add explicit editor-open safety checks to `quickcheck.py` for the base output and optional proposal, document-plan, builder, operating-plan, and template form-fit outputs.

### Changed
- Bump packaged plugin manifests and Codex marketplace entry to `0.1.6`.

## [0.1.3] - 2026-06-04
### Changed
- Pin bundled MCP fallback launchers and MCP install docs to `hwpx-mcp-server==2.3.3`, which exposes document-plan v2 and government-report MCP tools backed by `python-hwpx>=2.10.1`.
- Bump packaged plugin manifests and Codex marketplace entry to `0.1.3`.

## [0.1.2] - 2026-06-04
### Fixed
- Pin bundled MCP fallback launchers and MCP install docs to `hwpx-mcp-server==2.3.2`, which clears layout caches for placeholder form-fill text insertion paths.

### Changed
- Bump packaged plugin manifests and Codex marketplace entry to `0.1.2`.

## [0.1.1] - 2026-06-04
### Fixed
- Remove stale HWPX `lineSegArray` layout caches from XML parts changed by `zip_replace_all.py` so Hancom recalculates text layout after replacements.
- Pin bundled MCP fallback launchers and MCP install docs to `hwpx-mcp-server==2.3.1`, which includes cross-run replacement fixes for overlapping glyphs.

### Changed
- Bump packaged plugin manifests and Codex marketplace entry to `0.1.1`.

## [0.1.0]
### Added
- Added `hwpx.builder` onboarding docs, API reference, example, and quickcheck coverage for the builder core.

### Changed
- Updated bundled MCP fallback launchers to `hwpx-mcp-server==2.3.0`, which requires `python-hwpx>=2.10.0`.
- License relicensed to Apache-2.0 (sole author, full consent).
- Previous license terms no longer apply to future releases.
