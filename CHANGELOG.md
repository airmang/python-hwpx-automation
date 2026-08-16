# Changelog

## Unreleased

### 추가됨

- **클라이언트 업로드 경로 안내 에러 (#75, #84).** 대화창에 업로드된 파일의
  내부 경로(`/mnt/user-data/...`)가 도구에 전달되면, 일반 workspace 해석보다
  먼저 감지해 typed·redacted `CLIENT_UPLOAD_PATH_UNAVAILABLE` validation
  에러와 "파일을 PC에 저장한 뒤 실제 로컬 경로를 전달하세요" 안내를
  돌려줍니다. 기여: @adity982.

### 고쳐짐

- **Windows에서 모든 저장·삭제 경로가 `WORKSPACE_PATH_CHANGED`
  (`output_target_changed` / `output_candidate_changed`)로 실패하던 결함을
  수정했습니다 (#98).** Windows `os.open`은 CRT 텍스트 모드가 기본이라
  workspace 스냅샷 digest가 CRLF 변환과 0x1A 조기 EOF를 거친 바이트를
  해시했고, 바이너리로 읽은 실제 파일 바이트와 절대 일치할 수 없었습니다.
  ZIP 컨테이너인 HWPX에는 두 바이트 패턴이 항상 존재하므로 Windows의
  portable 폴백 공표는 전부 차단됐습니다. `_snapshot_target`과
  `_relative_file_snapshot`이 `O_BINARY`로 열도록 고치고, 실제 Windows
  러너에서 공표 폴백을 실행하는 CI 게이트
  (`tests/test_workspace_windows_gate.py`, `windows-publish-gate` 잡)를
  추가했습니다.
>>>>>>> origin/main

## [7.0.1] - 2026-08-04

`v7.0.0`은 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다.
`error::DeprecationWarning` 게이트(이 트레인 자신의 산물)가 CI Python 3.12의
stdlib tar filter 예고 경고를 적발해 업로드 전에 중단했습니다.
`extractall(filter="data")` 명시로 고친 동일 내용이 7.0.1입니다.
삭제·이동·재사용하지 않습니다.

## [7.0.0] - 2026-08-04 (preserved failed tag — nothing published)

엔진 완전성 major입니다. 도구 표면은 그대로입니다(128/136/29 — 추가·제거·
승격·프로파일 이동 0). 계약 해시는 플로어 전진만으로 `34a91560759dc47a`로
이동합니다: `minPythonHwpx 6.0.2` · `minAutomationVersion 7.0.1` ·
`minSkillVersion 2.0.0`.

[6.8.1]은 발행되지 않았습니다 — release-approved 후보 상태에서 이 트레인에
흡수되었습니다. 마지막 공개 트레인은 6.7.1입니다.

### 바뀜

- **python-hwpx 6.0 표면으로 전면 이주.** 모든 콜사이트가 이동한 5.x 루트
  이름 대신 6.0 도메인 네임스페이스(`doc.notes`/`fields`/`shapes`/
  `styles`/`page`)를 직접 호출합니다. 회귀는 구조적으로 봉쇄됩니다 —
  테스트 스위트가 `error::DeprecationWarning`으로 돌므로 살아남은 shim
  호출은 곧 스위트 실패입니다.
- 의존 창이 `python-hwpx>=6.0.0,<7`로 이동하고, capability handshake
  플로어(`MIN_PYTHON_HWPX`)가 6.0.0으로 core 버전과 원자적으로
  전진합니다 — 플로어 선상향은 스큐 가드가 실설치 core를 거부하는 것을
  실측으로 확인하고 릴리스 커밋에 묶었습니다.
- compat 배포 `hwpx-mcp-server`는 `==7.0.0` 정확 위임으로 전진하며 7.x
  시리즈 전체에서 유지됩니다.

### 고쳐짐 (릴리스 게이트 정직성)

- README 설치-휠 게이트가 후보 휠의 core 의존을 PyPI에서 해석하던 결합을
  제거했습니다 — 핀 좌표가 마침 발행돼 있을 때만 통과하던 게이트가, 이제
  방금 빌드한 wheelhouse에서 해석하고 휠 파일명에서 ==핀을 파생합니다.
- compat 위임 테스트의 `==6.8.1` 리터럴 기대를 canonical pyproject 파생으로
  바꿨습니다 — 셸이 한 트레인 뒤처지는 스큐가 이 테스트의 적발 대상인데
  리터럴이 그 스큐를 만들고 있었습니다.

## [6.8.1] - 2026-08-03 (unpublished — absorbed into 7.0.0)

`v6.8.0`은 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다.
prepublish의 pyright 게이트가 정렬 수리의 dict-스플랫 타입 부정밀을 적발해
업로드 전에 트레인을 중단했습니다(로컬 태그-전 게이트에서 pyright를 생략한
것이 원인 — runbook 체크리스트에 pyright를 명문화). 호출을 정밀 타입으로
고친 동일 내용이 6.8.1입니다. 삭제·이동·재사용하지 않습니다.


정직성 트레인입니다 — 도구를 추가·제거·이동하지 않습니다. 계약 해시는
플로어 전진(core 5.8.0·skill 1.8.0)만으로 `6ba7bc0ca7226f2f`로 이동합니다.

### 고쳐짐 (영수증 무결성)

- `apply_evalplan_fill`이 내용 채움 26건을 보고하면서 파일을 한 바이트도
  쓰지 않을 수 있던 무음 no-op을 수리했습니다. 도메인 payload가 구조 단계
  결과를 최종 판정으로 재사용하던 것이 원인 — 이제 산출 바이트에서
  `byteIdentical`·`changedParts`를 재산출하고, 발행 판정은 payload 필드가
  아니라 산출 바이트를 원본과 직접 비교합니다.
- 저장 seam이 보존 영수증의 모순 조합(`byteIdentical=true` + 변경 part
  목록)을 전달하는 대신 `MUTATION_REPORT_INCOHERENT`로 거부합니다.
- document plan의 문단 `align`이 검증을 통과한 뒤 무음 폐기되던 결함을
  수리했습니다(v2 계획에서 실반영, v1 계획은 역할 기반 스키마임을 검증
  경고로 안내). 완결-진실 불변식 테스트가 신설되어, 결함을 되살리면
  "영수증은 True, 바이트는 False"로 실패함을 양방향 실행으로 증명했습니다.

### 고쳐짐 (릴리스 기계)

- 릴리스 경로의 모든 버전 좌표가 `identity.json` 단일 원천에서 유도됩니다.
  4일간 실패 태그 13건 중 11건의 원인이던 손편집 리터럴(동결 currentPublic
  사전·compat 매트릭스 임베디드 핀 9곳·워크플로 core 핀)을 제거했습니다.
- `currentPublic` 검증을 동결 사전 대신 **PyPI·GitHub 실관찰**로 교체했습니다
  (`scripts/check_current_public_remote.py`). 태그 없이 전체 게이트를 도는
  dry-run job이 매 푸시마다 돕니다.
- 태그 게이트를 워크플로 heredoc에서 `scripts/check_tag_release_gate.py`로
  추출해 로컬에서 실행 가능하게 했습니다.

### 추가됨

- core 퍼즈 하니스가 이 레포 CI에서 고정 시드 회귀 자산으로 돌아갑니다
  (5.0 분리 이후 어느 CI에서도 돌지 않던 자산의 부활 — 배선 자체를 가드하는
  테스트 동반).
- 릴리스 runbook에 태그-전 체크리스트(신선 체크아웃 확인·로컬 게이트·트레인
  후 워크트리 정리)를 정본화했습니다.

### 바닥(floors)

- `python-hwpx >= 5.8.0` (영수증 무결성·자기서술 검증기·코퍼스 v3를 포함한
  core 정직성 트레인), `minSkillVersion 1.8.0`.

## [6.7.1] - 2026-08-03

`v6.7.0`은 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다.
릴리스 잡의 동결 currentPublic 게이트에서 버전 리터럴 4개 중 3개만 전진해
`pythonHwpx`가 지지난 트레인 값으로 남아 있었습니다. 게이트가 이를 저지했고,
6.7.1이 같은 내용의 복구 릴리스입니다.

양식개체·기안문 장르 트레인입니다. core 바닥이 5.7.0(체크박스 저작
프리미티브)으로 올라갑니다.

### 추가
- **`compose_official_draft`**(별지 제1호서식 일반기안문)·**`compose_simple_draft`**
  (별지 제2호서식 간이기안문): 「행정업무의 운영 및 혁신에 관한 규정 시행규칙」의
  **공개 서식 구조**를 범용 document-plan 블록으로 낮춥니다(클린룸 — 상용 템플릿
  파일을 복제하지 않습니다). 파일을 쓰지 않으며 반환 blocks를
  `create_document_from_plan`에 넣어 생성합니다.

  규정에서 곧바로 오는 계약 3가지를 합성이 강제합니다:
  ①**결재란 칸 수 = 결재자 목록 길이**(제7조제4항 — 서명·전결 표시를 하지 않는
  사람의 서명란은 만들지 않습니다). ②**결문 라벨 미인쇄**(별지 제1호서식 비고 —
  행정기관명·발신명·기안자/검토자/결재권자·직위(직급) 서명·주소·공개 구분 등의
  용어는 표시하지 않고 값만 적습니다). ③**체크박스 개체를 쓰지 않습니다** —
  별표 4 제10호가 `[  ]`+√ 텍스트를 규정합니다.
- **하우스 스타일 장르 2종 추가**: `official_draft`·`simple_draft`
  (`get_genre_grammar`로 조회). 문법·라벨 정책·체크박스 정책·용지 여백을
  규정 근거(prov)와 함께 싣고, 법령이 정하지 않는 본문 글꼴·행 높이는
  **미확인으로 정직 표기**합니다.

### 변경
- 계약 128 default / 136 advanced / 29 skill-required @ `98510af22d13899c`
  (`docs/tool-contract-delta-6.7.0.json`, additive).
- 버전 바닥: `MIN_PYTHON_HWPX` 5.7.0 · `MIN_SKILL_VERSION` 1.7.0.

## [6.6.4] - 2026-08-03

`v6.6.0`~`v6.6.3`은 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다.
v6.6.3은 minimum-Python clean-wheel 게이트가 core wheel 파일명
`python_hwpx-5.5.0-`을 핀하고 있었습니다. scripts/ 전체 트레인 리터럴을 한
번에 감사했고, 두 게이트 스크립트 로컬 실행을 태그 전 절차로 못박았습니다.

(이전 실패 상세) `v6.6.0`·`v6.6.1`·`v6.6.2`는 보존된 실패 태그입니다 — 아무것도 게시되지
않았습니다. v6.6.2는 compat 매트릭스의 임베디드 정확버전 프로브가 6.5.1에
머물러 있었습니다(전진 완료, 태그 전 로컬 전체 매트릭스 실행을 절차화).

(이전 실패 상세) `v6.6.0`·`v6.6.1`은 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다.
v6.6.0은 릴리스 워크플로의 동결 공개-core 관찰 스텝이 5.5.0에 머물러 있었고,
v6.6.1은 로컬 생성 `.compat-core-wheel/python_hwpx-5.5.0` 부산물이 실수로
커밋되어 CI 체크아웃의 wheel 디렉터리를 오염시켰습니다(제거·ignore 처리).
6.6.2가 같은 내용의 복구 릴리스입니다.

(v6.6.0 상세) `v6.6.0`은 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다. 릴리스
워크플로의 동결 공개-core 관찰 스텝이 5.5.0을 단언한 채 남아 있었고, 이번
트레인의 관찰 대상 공개 core는 5.6.0입니다. 6.6.1이 같은 내용의 복구
릴리스입니다.

에이전트 계약 표면 트레인입니다. core 바닥이 5.6.0(`hwpx.plan`/`hwpx.capabilities`)
으로 올라갑니다.

### 추가
- **`run_edit_plan`** (public·mutating·skill-required): 선언적 편집 계획
  (`hwpx.edit-plan/v1`)을 core `hwpx.plan` 실행기로 위임합니다 — 정적 선검증 →
  전 체인 인메모리 실행 → 최종 open-safety 검증 → 단 1회 원자 쓰기. 중간 step
  실패 시 output·source가 바이트 불변이고 `ok=false` `hwpx.plan-report/v1`
  (failedStepId·step error·step별+원본→최종 실측 mutation-report 사영)이
  돌아옵니다. `dry_run=true`는 동일 체인을 전부 실행하되 쓰기만 생략합니다.
- **첫 MCP resources 표면 9종**: core 동봉 계약 문서 4종(support-matrix·
  recipes-traversal·mutation-semantics·known-traps)·라이브 빌드 JSON Schema
  4종(edit-plan·plan-report·mutation-report·capabilities)·automation 도구 계약
  payload. 등록은 `fastmcp_adapter.register_canonical_resource` seam으로만
  합니다(어댑터 유일 SDK 접점 규율 유지).
- **`describe_capabilities` additive 확장**: core 자기서술 블록
  (`hwpx.capabilities/v1`)·무실행(render 발사 없음) 오라클 가용성 프로브·리소스
  카탈로그를 기존 도구에 합성합니다 — 자기서술 도구를 둘로 쪼개지 않습니다.

### 변경
- 계약 126 default / 134 advanced / 29 skill-required @ `19898dba41495c47`
  (`docs/tool-contract-delta-6.6.0.json`, additive — removed/promoted/
  profileMoves 전부 없음). `run_edit_plan`은 `apply_table_ops`/`apply_body_ops`
  와 같은 skill-required 등급입니다.
- 버전 바닥: `MIN_PYTHON_HWPX` 5.6.0 · `MIN_SKILL_VERSION` 1.6.0.

## [6.5.1] - 2026-08-02

`v6.5.0`은 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다. 호환
설치 매트릭스의 임베디드 정확버전 프로브가 6.4.2에 머물러 있었고, 이번
트레인에서 매트릭스 로컬 전체 실행을 생략한 것이 원인입니다(6.3.0 실패와
동류). 핀을 갱신하고 매트릭스·py3.10 스모크를 로컬 전체 실행한 동일
내용이 6.5.1로 복구되었습니다. 삭제·이동·재사용하지 않습니다.

## [6.5.0] - 2026-08-02 (미게시 후보)

운영계획 장르 저작(zero-base 하우스 스타일) 트레인 1차 — 새 public 기본
도구 3종, 계약 기본 125/고급 133/스킬 필수 28 @ `f61d2c60c0aa0413`.

### 추가
- **`add_boxed_org_chart`**: 실물 운영계획 관례 그대로의 박스 조직도 —
  테두리 없는 표 캔버스 + 병합 라벨 박스 + 셀 테두리 커넥터(스텁·레일).
  깊이 ≤4·박스 ≤40 밖은 typed 거부, 루트 accent 배경 지원, 실한컴 렌더
  픽셀 검증.
- **`compose_section_chip`**: 운영계획 섹션 구분자(1×3 accent 칩 또는
  inline 헤딩)를 범용 document_plan block으로 합성(파일 미작성).
- **`get_genre_grammar`**: 하우스 스타일 장르 문법·타이포 역할·상속
  프로파일 read-only 조회 — 스킬이 per-문서 인스턴스화 판단에 사용.

### 변경
- 코어 플로어 `python-hwpx>=5.5.0`(각주 수리 트레인) 동반 이동. 에이전트
  런타임(시맨틱 프로젝터·블루프린트 replay·복사 identity)이 5.5.0의
  ctrl-래핑 각주 계약을 읽고 재생하도록 수리 — 복사 identity 리프레셔는
  lxml 프록시에서도 안전한 단일 재귀로 재작성(각주 내부 id=0은 계약상
  보존).

## [6.4.2] - 2026-08-01

`v6.4.1`도 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다. release
잡의 태그 게이트가 currentPublic 기대를 6.2 트레인 시점의 옛 공개
스택(5.2.0/6.2.1/1.2.0)으로 동결하고 있어, 현 공개 스택(5.3.0/6.3.1/1.3.0)을
정확히 기록한 identity가 오히려 거부됐습니다. 게이트 동결값을 현 공개
스택으로 갱신한 동일 내용이 6.4.2로 복구되었습니다. 삭제·이동·재사용하지
않습니다.

## [6.4.1] - 2026-08-01 (미게시 후보)

`v6.4.0`은 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다. identity
상태 머신이 unreleased-candidate인 채로 태그를 밀어 태그 게이트가 올바르게
중단했습니다(tag publish는 release-approved 필요). 상태를 전진시킨 동일
내용이 6.4.1로 복구되었습니다. 삭제·이동·재사용하지 않습니다.

## [6.4.0] - 2026-08-01 (미게시 후보)

### 추가
- **`format_table` 테두리·음영 확장(additive)**: `border_type`(OWPML 선
  종류 어휘 — SOLID/DASH/DOT/DOUBLE_SLIM/WAVE 등, 어휘 밖은 typed 거부),
  `border_color`, `border_width`, `fill_color`(셀 음영)와 선택 `row`/`col`
  (함께 지정 시 그 셀에만 적용 — 홀로 지정은 typed 거부). 수리된 core
  5.4.0의 `ensure_border_fill(border_type=…)`·`set_cell_border_fill` 표면
  위에 구현. 도구 수 불변(122/130), 계약 해시 `dbdbdfaac26148b7`.

### 변경
- **core 바닥 5.4.0**: 저작 충실도 감사 수리 트레인 편입 — 표
  기본값(셀 안여백 510/141·본문폭·중첩=부모 셀 폭), 목록 paraPr 비상속,
  하이퍼링크 파랑/밑줄 관례(표시 런 한정), 첨자 offset 부호 정정,
  `ensure_run_style` 확장 7종. mail-merge fit 판정은 이제 실한컴 셀
  안여백을 반영해 가용폭을 계산합니다.

## [6.3.1] - 2026-07-31

`v6.3.0`은 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다. 호환
설치 매트릭스가 공개 모듈 인벤토리 카운트를 스크립트에 내장하는데, 신규
`office.charting` 모듈이 172→173으로 옮긴 것을 로컬 게이트 재현이 커버하지
못했습니다. 내장 핀을 갱신한 동일 내용이 6.3.1로 복구되었습니다. 삭제·이동·
재사용하지 않습니다.

## [6.3.0] - 2026-07-31 (미게시 후보)

차트 생성 트레인. 새 public 기본 도구 `add_chart`(edit 도메인) 1종 —
데이터 시리즈를 ECMA-376 chartML로 컴파일해(렌더 검증 MVP: bar·line·pie,
밖은 `CHART_UNSUPPORTED` typed 거부) `Chart/chartN.xml` 파트로 저장하고
`<hp:chart chartIDRef>` 앵커를 방출합니다. 실한컴은 chartML만으로 차트를
그립니다(OLE 폴백·사전렌더 이미지 미생성 — 실측 계약).

- 계약: 기본 122 / 고급 130 / 스킬 필수 28 @ `236f8ea855c875fe`
  (델타 영수증 `docs/tool-contract-delta-6.3.0.json`, additive-tool 증명).
- 플로어 동반 이동: `python-hwpx>=5.3.0` · automation `6.3.0` · skill `1.3.0`.
- 배치: 새 문단(float)·기존 문단·표 셀·인라인(treat_as_char).

## [6.2.1] - 2026-07-31

`v6.2.0`은 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다. prepublish
아키텍처 래칫이 content_layout.py의 1줄 드리프트(타입 내로잉 픽스 후 래칫
로컬 재실행 누락)를 적발해 중단했고, 래칫 핀을 갱신한 동일 내용이 6.2.1로
복구되었습니다. 관례에 어긋난 bare 태그 `6.2.0`도 게시물 0으로 보존됩니다.
둘 다 삭제·이동·재사용하지 않습니다.

## [6.2.0] - 2026-07-31 (미게시 후보)

수식 저작 트레인. 새 public 기본 도구 `add_equation`(edit 도메인) 1종 —
LaTeX(렌더 검증 토큰셋, 밖은 `EQUATION_LATEX_UNSUPPORTED` typed 거부) 또는
EqEdit script를 받아 네이티브 `<hp:equation>`을 삽입하고, 응답에 리더 왕복
`readerLatex`를 담습니다. 배치는 새 문단·기존 문단·표 셀 3형.

- 계약: 기본 121 / 고급 129 / 스킬 필수 28 @ `342cf672f29cd183`
  (델타 영수증 `docs/tool-contract-delta-6.2.0.json`, additive-tool 증명).
- 플로어 동반 이동: `python-hwpx>=5.2.0` · automation `6.2.0` · skill `1.2.0`.
- 저작 어휘는 실한컴 렌더 오라클 픽셀 실측으로 확정 — 실한컴이 거부하는
  철자는 대체(`->`·`FORALL`·`dint`/`tint`·`dmatrix`) 또는 typed 거부.

## [6.1.3] - 2026-07-31

`v6.1.2`도 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다. release
잡의 태그 게이트가 currentPublic 기대를 6.0 트레인 시점의 옛 공개
스택(4.2.0/5.1.0/0.8.0)으로 동결하고 있어, 현 공개 스택
(5.0.2/6.0.4/1.0.1)을 정확히 기록한 identity가 오히려 거부됐습니다. 게이트
동결값을 현 공개 스택으로 갱신한 동일 내용이 6.1.3으로 복구되었습니다.
`v6.1.2`는 삭제·이동·재사용하지 않습니다.

## [6.1.2] - 2026-07-31 (미게시 후보)

`v6.1.1`도 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다. 신규
도구 테스트 파일의 미사용 import 하나가 prepublish Ruff 게이트에서
적발됐습니다. 이번에는 release 정적 게이트 전부를 로컬에서 선실행한 뒤
6.1.2로 복구합니다. `v6.1.1`은 삭제·이동·재사용하지 않습니다.

## [6.1.1] - 2026-07-31 (미게시 후보)

`v6.1.0`은 보존된 실패 태그입니다 — 아무것도 게시되지 않았습니다. 태그
워크플로의 public core dependency 관측 스텝이 5.0.1로 동결돼 있어(5.0.2
패치 트레인·5.1.1 코어 복구를 반영하지 못함) prepublish에서 중단했습니다.
관측 좌표를 5.1.1로 갱신한 동일 내용이 6.1.1로 복구되었습니다. `v6.1.0`은
삭제·이동·재사용하지 않습니다.

## [6.1.0] - 2026-07-31 (미게시 후보)

### Added
- **`add_form_field` — 누름틀(click-here) 필드 저작 도구.** 실한컴이 만드는
  CLICKHERE 형상 그대로 필드를 생성해 양식 수명주기(create→list→fill→verify)가
  한컴 수동 준비 없이 자급됩니다. 배치는 문서 끝 새 문단(기본)·`paragraph_index`·
  `tableIndex`+`row`+`col`(표 셀, 중첩 포함)을 지원하고, 안내문(`prompt`)은
  화면 전용(미인쇄)입니다. 잘못된 타깃 조합은 typed 오류
  (`FORM_FIELD_TARGET_INVALID`/`TABLE_INDEX_OUT_OF_RANGE`/
  `PARAGRAPH_INDEX_OUT_OF_RANGE`)로 거부됩니다. 설치 계약은 기본 120 /
  고급 128 / 스킬 필수 28, 계약 해시 `ac1a422376b5ac84`
  (델타 영수증 `docs/tool-contract-delta-6.1.3.json`).
- Official Python 3.13/3.14 support: the CI matrix now runs the full suite on
  CPython 3.10–3.14 (1,390 passed verified on both new versions before
  widening), and the canonical/compat classifiers follow. The canonical
  distribution also declares `Typing :: Typed` — it has shipped `py.typed`
  all along. The compat README now states that the legacy import shell is a
  runtime redirect: type-checked code should import `hwpx_automation`
  directly.

### Changed
- Version floors move with the train: `python-hwpx>=5.1.0,<6`
  (`add_form_field` 프리미티브·리더 `dirty`/`is_placeholder` 노출·fill의
  dirty=1/안내문 스타일 스왑을 포함하는 첫 공개 코어), automation floor
  `6.1.0`, skill floor `1.1.0`.

## [6.0.4] - 2026-07-28

`v6.0.3` published the canonical `python-hwpx-automation` 6.0.3 but the
compatibility upload was rejected (the `hwpx-mcp-server` project's
trusted publisher did not yet accept the renamed repository). Per the
partial-publish rule the canonical 6.0.3 release is preserved and the
train recovers as 6.0.4 so the exact canonical==compat version lock
holds. Never delete, move, or reuse `v6.0.3`.

## [6.0.3] - 2026-07-28

`v6.0.1` and `v6.0.2` are preserved failed tags; neither published
anything. 6.0.1 stopped in prepublish (missing uv and the core fixtures
checkout), 6.0.2 stopped at the tag gate because this changelog heading
was not date-finalized. 6.0.3 is the same train content with the
coordinates audited repository-wide and the release job's static gates
simulated locally before tagging. Never delete, move, or reuse either
tag.

## [6.0.1]

`v6.0.0` is a preserved failed tag: its release run stopped in prepublish
(the parity suites need a `python-hwpx` repository checkout for fixtures,
and the clean installed-wheel gates need `uv`; the workflow provided
neither) and nothing was published. 6.0.1 is the same train content plus
those workflow fixes and the core-5.0.1 observation pins. Never delete,
move, or reuse `v6.0.0`.

## [6.0.0] - unreleased

The core-5.0/automation-6.0 train. `python-hwpx` 5.0 removes the application
workflows it had been carrying as compatibility copies. The existing
`hwpx-mcp-server` repository and history are renamed in place to
`python-hwpx-automation`; this is the one canonical implementation, not a fork.

### Added

- The canonical distribution/import pair is now
  `python-hwpx-automation` / `hwpx_automation`.
- The base install exposes a curated task API and `python -m hwpx_automation`
  without importing the optional MCP SDK.
- `hwpx-automation-mcp` is the canonical MCP console. The existing
  `hwpx-mcp-server` distribution, import namespace, and console remain bounded
  6.x compatibility surfaces.
- `hwpx_automation/identity.json` records canonical, compatibility, and
  host-local identifiers. Compatibility removal is not before 7.0 and requires
  at least 90 days of public notice/observation plus separate owner approval.
- Native macOS and Windows jobs build clean core/canonical `[oracle]` wheels on
  the minimum Python 3.10, then execute PyMuPDF extraction, Pillow
  rasterization, and NumPy pixel access before verifying labelled
  structural-only oracle degradation and the fail-closed MCP-without-`[mcp]`
  path. No GUI application is launched.

### Changed — BREAKING

- Version floors are now `python-hwpx>=5.0.0`,
  `python-hwpx-automation>=6.0.0`, skill
  `>=1.0.0`. A mixed install is exactly what these floors exist to prevent: core
  5.0 no longer has the modules a 5.x server would reach for.
- This package now declares the `hwpx` console command, which `python-hwpx` 5.0
  stops declaring. Same command, same subcommands. Because declaring it requires
  core `>=5.0.0`, no valid install ends up with two packages claiming the name.
- MCP `serverInfo.name`, health identity, and argparse program name now use the
  canonical automation identity. Host configuration keys such as `hwpx` remain
  host-local aliases.
- `HWPX_AUTOMATION_*` is the canonical environment prefix. Existing
  `HWPX_MCP_*` keys and the existing workflow-state path remain supported
  fallbacks through 6.x to avoid silent configuration or state loss.
- Frozen wire/receipt names that contain `mcp` remain exact in 6.x and are
  classified explicitly in the identity manifest: `hwpx.mcp-error/v1`,
  `versions.mcp`, `minMcpVersion`, `MIN_MCP_VERSION`, the `hwpx-mcp.*`
  architecture receipts, and `mcpRuntimeMembers`. They are compatibility
  identifiers, not product-ownership claims.
- Contract `429cb6706323e762` → `0ce938371f0b55a6` at an unchanged 119 default /
  127 advanced / 28 skill-required. Names, order, schemas, classifications and
  error contracts are all identical — nothing a caller binds against moved. The
  hash covers the version floors and identity/description/availability guidance:
  `minAutomationVersion` is canonical while `minMcpVersion` remains an additive
  6.x compatibility alias,
  `compose_exam` and `verify_question_splits` dropped an internal stage codename,
  and advanced-profile guidance names `HWPX_AUTOMATION_ADVANCED` first while
  retaining `HWPX_MCP_ADVANCED` as a 6.x fallback. See
  `docs/tool-contract-delta-6.0.0.json`.
- `office.document_ops.verify_redline` delegates to core rather than carrying a
  parallel implementation. The owner's job is to *supply* a render backend, and
  a behavioural test now enforces that it does: core degrades honestly when
  nothing is injected, which is right for a library and wrong for the canonical
  owner, since a caller reaching this surface asked for a Hancom-backed verdict.
- `office.form_fill.fit.*` re-exports the neutral `hwpx.form_fit.*` contract
  instead of duplicating it, which removed roughly 1,300 lines of second copy.
- `office.authoring.report_parser` moved here from core.

### Documentation

- The 2026-07-24 compatibility/deprecation observation was published for a
  window running to 2026-10-31, with every surface decided `extend` and removal
  count zero. This release supersedes it ahead of that date on an explicit owner
  decision. The window's purpose is downstream notice and notice begins at
  publication, so this shortens the notice period rather than satisfying it —
  stated plainly here because the observation issues promised otherwise.
- `docs/tool-contract-delta-6.0.0.json` records the contract delta and the
  superseded intermediate hash.
- Release state now advances at the coherent three-stack boundary. The
  automation tag keeps `release-approved` and the old `currentPublic`, attaches
  a plugin handoff receipt after observing canonical/compatibility publication,
  and permits `released` only after the plugin GitHub Release, marketplace
  entry, and a real marketplace install are also observed.

### Fixed

- Five parity test files compared this package against core surfaces that 5.0
  deletes. They now compare against fingerprints and goldens frozen from the
  commit before removal, and each was checked for discrimination by tampering
  with the frozen value — a parity test whose subject is gone can otherwise pass
  by comparing nothing to nothing.
- Canonical office owners and architecture ledgers now consistently say
  automation owner/application layer. MCP wording remains only where it names
  the optional protocol adapter or a classified frozen compatibility identifier.
- Retained core document-operation and form-fit primitives now have exact
  module/symbol and installed-source-origin gates. A full transitive import of
  all 172 base-public automation modules must make zero attempts to load the
  removed `hwpx.form_fit.seal` or `hwpx.form_fit.wordbox` modules.
- The guidance tool tests no longer skip on the deliberately removed
  `hwpx.guidance_scan` compatibility module; all seven now exercise the
  canonical automation owner. The release suite also installs `[oracle]`, so
  imaging-path tests cannot disappear behind missing-extra skips.

## [5.1.0] - 2026-07-22

### Added
- `apply_evalplan_fill`에 `phase` 파라미터를 추가했습니다 —
  `"structural"|"all"(기본, 기존 동작)|"clean"`. `"clean"`은 채움 뒤 core의
  결정론적 양식 정리(제목·교사·정의적 채움, 양식 지시문·외래 샘플 prune, 빨강 제거,
  파랑→검정, 표 꼬리 캡션 strip)까지 한 호출로 수행해, 별도 정리 스크립트 없이
  실제 도교육청 평가계획 양식을 잔존물 없이 채웁니다. 기본값 `"all"`은 비파괴입니다.
  (core `python-hwpx>=4.2.0`의 `fill_evalplan(phase="clean")` 필요.)
- 계약 델타: docs/tool-contract-delta-5.1.0.json. 계약 해시 c2cd81fdb3089bae → 429cb6706323e762.

## [5.0.0] - 2026-07-21

### Removed (breaking, 5.0.0 major boundary)
- The five one-transition stubs `plan_edit`, `preview_edit`, `apply_edit`,
  `analyze_quality_generation`, and `apply_quality_generation` are removed from
  the tool registry, the explicit bindings, the FastMCP server aliases, and the
  workflow `TRANSACTIONAL_EDIT` allowlist. No alias and no ghost wrapper stands
  in for them (S-078 policy). Migrate per `docs/deprecation-5.0.0.md`:
  `apply_document_commands` (dry-run for the old plan/preview semantics) for the
  edit trio, and `create_document_from_plan` + `inspect_document_quality` for
  quality generation.

### Changed (breaking, 5.0.0 major boundary)
- The three template-formfit facades `analyze_template_formfit`,
  `apply_template_formfit`, and `fill_form_field` demote from
  `COMPATIBILITY` to `DEPRECATED`. Their handlers and behaviour are unchanged;
  they now carry the one-transition deprecation guidance toward the canonical
  `analyze_form_fill`/`apply_form_fill`/`verify_form_fill` trio and are slated
  for removal at the next major boundary.
- Baseline classification drops 136 → 131 (compatibility 9 → 6, deprecated
  5 → 3); the installed advanced surface is 132 → 127, the default surface
  121 → 119, and skill-required stays 28. The contract hash moves
  `c89cbc5f98eb5367` → `c9a451a7c003752a`; the delta is recorded in
  `docs/tool-contract-delta-5.0.0.json` and cross-checked against the live
  registry by `scripts/render_contract_delta.py`.

### Internal
- `handlers/form_fill.py` now imports the template-formfit callables from the
  `hwpx.template_formfit` submodule instead of the `hwpx` top level. At the core
  4.0.0 boundary the top-level re-exports become deprecated shims that warn on
  access; the demoted-but-functional MCP tools must not emit a runtime warning.
  The submodule path is stable across core 3.3.1 and 4.0.0.

## [4.4.1] - 2026-07-21

### Notes
- `v4.4.0`은 릴리스 게이트 실패로 미발행 보존 태그입니다(prepublish가 core를
  `[preview]` extra 없이 설치해 MathML 성공경로 테스트가 정직 실패 — 워크플로
  설치 라인 수정으로 복구). PyPI 산출물은 존재하지 않습니다.

## [4.4.0] - 2026-07-21 (미발행)

### Added
- `render_preview` gains an additive optional `viewer` parameter (default
  `false`). When `true`, the manifest carries a self-contained scrollable
  document viewer under `structuredContent.viewer` — a sticky top bar, live
  page indicator, continuous scroll, and equations rendered as native MathML
  (with `python-hwpx[preview]`; the core chain fails closed to a LaTeX/script
  code block otherwise, never a silent drop). The viewer HTML is written to a
  workspace-guarded `viewer.html` and returned inline under a byte cap that
  degrades to path-only. `viewer.equationRendering` reports honest
  MathML/latex/script fallback counts. The parameter is orthogonal to
  rasterization; pair with `screenshot="off"` for the lightweight text path.
  Non-HWPX inputs and out-of-workspace writes are rejected by the existing
  guards. The contract hash moves to `c89cbc5f98eb5367`; the delta is proven
  additive-only (one tool, one optional input parameter plus one optional
  output field) in `docs/tool-contract-delta-4.4.0.json`.

### Internal
- Brings the five former `[dynamic-seam]` files (`ops_services/{form_fields,
  save_policy,tables,transactions}.py` and `workflow/service.py`) into the
  Pyright gate, typing-first: `DocumentStorage.save_document` gains
  the universal `quality` kwarg; the Local-only guarded exact-sidecar publication
  is narrowed to `LocalDocumentStorage` at the consumers; the table addressing
  kwargs use a `TypedDict`. Behavior is preserved. Only the 9 `[schema-frozen]`
  handlers remain excluded from Pyright.

## [4.3.2] - 2026-07-21

### Notes
- `v4.3.1`은 릴리스 게이트 실패로 미발행 보존 태그입니다(버전 고정 테스트 미갱신
  + CI 한정 스냅샷 정리 테스트 실패 — 조사 기록은 저장소 이슈/영수증 참조).
  PyPI/GitHub Release 산출물은 존재하지 않습니다.

## [4.3.1] - 2026-07-20 (미발행)

### Fixed
- workspace 루트가 설정되지 않았을 때의 cwd 폴백이 GUI MCP 클라이언트의
  퇴화 cwd(Windows Claude Desktop의 `C:\Windows\System32`, macOS의 `/`)를
  workspace로 삼아 — Windows에서는 모든 실제 경로가 거부되고 macOS에서는
  전체 파일시스템이 열리는 — 두 오동작을 모두 막습니다. 이제 퇴화 cwd가
  감지되면 `HWPX_MCP_WORKSPACE_ROOTS` 설정 예시를 담은 명확한
  `WORKSPACE_ROOT_INVALID` 오류를 반환하고, 서버는 기동을 유지해
  `mcp_server_health`로 원인을 확인할 수 있습니다. (#73, #77)


### Fixed
- The implicit cwd workspace fallback no longer silently adopts a degenerate
  current directory. GUI MCP clients launch the server from the filesystem root
  (`/` on macOS) or the Windows system directory (`C:\Windows\System32`), which
  made every real document path rejected as "outside the authorized workspace
  roots" (unusable for unconfigured Windows users) or — at the filesystem root —
  unbounded, defeating the fail-closed design. When neither
  `HWPX_MCP_WORKSPACE_ROOTS` nor the legacy `HWPX_MCP_SANDBOX_ROOT` is configured
  and the cwd is degenerate, `WorkspaceResolver.from_environment` now raises
  `WORKSPACE_ROOT_INVALID` with an actionable message naming
  `HWPX_MCP_WORKSPACE_ROOTS` and a short example. Explicit configuration
  behaviour is unchanged. (#73, refs #56)

### Changed
- An unconfigured degenerate cwd no longer crashes import or startup:
  `LocalDocumentStorage` defers the error so the server still boots,
  `mcp_server_health` reports the misconfiguration, and each document tool call
  returns the clean `WORKSPACE_ROOT_INVALID`. Explicit configuration errors
  still fail fast at startup.
- The README Claude Desktop / MCP client quickstart now sets
  `HWPX_MCP_WORKSPACE_ROOTS` from the start so new users avoid the cwd fallback.

## [4.3.0] - 2026-07-18

### Changed
- Promotes `apply_table_ops` and `apply_body_ops` from `compatibility` to
  `public`. Both are directly consumed as core primitives of the universal
  form-fill workflow, so the public classification states the truth; their
  `replacementTools` guidance is cleared. The installed surface stays exactly
  121 default / 132 advanced / 28 skill-required; baseline classification
  moves to 110 public / 9 compatibility. The contract hash moves to
  `f82caecbcfc742e9`; the delta is proven classification-only by payload
  substitution in `docs/tool-contract-delta-4.3.0.json`.
- Starts the tier-1 facade observation release: shipped skill guides now
  route `analyze_template_formfit` / `apply_template_formfit` /
  `fill_form_field` traffic to the canonical
  `analyze_form_fill`/`apply_form_fill`/`verify_form_fill` trio. The three
  tools stay registered and functional; demotion to `deprecated` is deferred
  to the next major after observing consumption.
- Raises the core floor to `python-hwpx>=3.3.1` (release-train alignment).

### Fixed
- `get_tables_by_handle` crashed with `AttributeError` on any document that
  contains a table, because it read the non-existent `table.columns`
  attribute; it now reads `column_count` and carries a regression test. Found
  by the Pyright ramp below.

### Internal
- Decomposes the worst-complexity handlers behaviour-preservingly:
  `_ensure_table_border_fill` (C901 57→≤10, via the private leaf
  `ops_services/_border_fill.py`), `apply_style_to_text_ranges` (48→≤10), and
  `matches` (29→split). The complexity ratchet baselines are lowered to match.
- Extends Pyright to the full mypy surface (8→22 of 36 files) with itemized
  exclusions: 9 `[schema-frozen]` handlers (implicit-Optional is the FastMCP
  schema source; explicit-Optional conversion belongs to a contract-changing
  release) and 5 `[dynamic-seam]` files pending a typed core seam.

## [4.2.1] - 2026-07-18

### Fixed
- Repoints the hermetic CI core checkout pin from the python-hwpx 3.2.0 release
  commit to the 3.3.0 release commit. The `v4.2.0` prepublish failed on this
  stale pin before publication, so no 4.2.0 PyPI artifact or GitHub Release
  exists; the tag is preserved as failure history and 4.2.1 is the actual
  public release. The contract hash moves to `fff2c9093ca4677b` because
  `MIN_MCP_VERSION` is part of the canonical payload; the tool surface stays
  exactly 121 default / 132 advanced / 28 skill-required.

### Note
- The feature content of 4.2.1 is identical to the unpublished 4.2.0 entry
  below.

## [4.2.0] - 2026-07-18 (tag preserved; not published)

### Changed
- Pins the MCP SDK exactly (`mcp==1.28.1`) so the package resolver admits the
  same set the runtime allowlist (`AUDITED_MCP_PATCHES`) admits: anything pip
  can install now also starts. Admitting a new SDK patch is an explicit
  re-audit documented in `docs/mcp-sdk-reaudit.md`.
- Removes the last package import cycle: the shared v2 render contracts
  (`RenderStatus`, `RenderJobV2`, `RenderReceiptV2`, `sign_submission`) moved
  to the leaf module `workflow/render_contracts.py`; `workflow/rendering` and
  `workflow/render_queue` re-export them unchanged. The architecture ratchet
  cycle baseline is now exactly zero, and a new SDK-import allowlist ratchet
  fails when any module outside the audited seams imports the `mcp` SDK.
- Optional real-Hancom verification now honors the core oracle controls:
  `HWPX_ORACLE_STRUCTURAL_ONLY=1` never enters GUI automation, and
  `HWPX_ORACLE_BUDGET_SECONDS` propagates one external deadline into every
  oracle subprocess timeout (python-hwpx >= 3.3.0 reachability probe applies).

### Fixed
- Workflow abstention receipts now carry the injected `tool_spec_hash` instead
  of the frozen released constant, keeping both receipt paths consistent when a
  divergent contract is injected.

## [4.1.0] - 2026-07-17

### Added
- Extends the existing `apply_document_commands` transaction to edit body text,
  table-cell text, and simple text in an existing section `BOTH` header in one
  revision-bound serialization. Dry-run, rollback, idempotency, byte preservation,
  reopen, and open-safety receipts remain part of the same installed tool.
- Adds architecture ratchets for handler ownership, service boundaries, import cycles,
  FastMCP private-access isolation, complexity, and the supported `mcp==1.28.1`
  registration/error/protocol contract.

### Changed
- Requires `python-hwpx>=3.2.0` for the multi-story transaction and correct
  renderable multi-section package construction. The `oracle` and `vision` extras
  require the matching `python-hwpx[visual]>=3.2.0` floor.
- Decomposes all 132 canonical callables into ten handler owners behind one immutable
  binding map, and places the exact `HwpxOps` compatibility facade over twelve bounded
  services. All unavoidable FastMCP private access is confined to one audited adapter.
- Preserves the exact 121 default / 132 advanced tool names, order, schemas, and 28
  skill-required tools. The approved minimum coordinates are MCP `4.1.0`, core `3.2.0`,
  and skill `0.4.0`; because those coordinates are part of the canonical payload, the
  release contract hash is `c127914cc3f4480e`.

### Fixed
- Routes durable workflow dispatch and direct FastMCP registration through the same
  immutable callable owners, preventing the two runtime paths from drifting.
- Fails the non-body story command closed for unsupported rich/control headers instead
  of partially editing or flattening their structure.

## [4.0.0] - 2026-07-16

### Added
- Adds one closed `hwpx.mixed-form-plan/v1` surface for native fields, label-adjacent
  cells, canonical paths, and exact-one body anchors. Analysis is non-mutating and
  apply reuses the core revision-bound transaction for dry-run, rollback, replay,
  byte-preservation, reopen, and open-safety receipts.
- Adds generated machine-readable input/output schemas, typed availability reasons,
  lifecycle/replacement metadata, and a narrow FastMCP adapter boundary.

### Changed
- Requires `python-hwpx>=3.1.0`, `mcp>=1.28.1,<1.29`, and `pydantic>=2.11,<3`.
  One ordered `ToolSpec` registry now validates
  registration, callables, signatures, schemas, profiles, health/capabilities,
  generated documentation, and the plugin contract.
- The transition surface is 121 default / 132 advanced tools with contract hash
  `f46ec677231b3a20`. Existing `hwpx.formfill.v1`, evalplan, native-field, and exam
  behavior remains explicit; five older planner tools are deprecated for one transition.

### Fixed
- Publishes and validates the source-owned `render_preview` manifest schema as
  `CallToolResult.structuredContent` while preserving inline image content blocks,
  instead of incorrectly advertising the outer MCP response envelope.
- Resolves postponed annotations without Python 3.10's implicit-`Optional`
  rewrite, keeping advertised input schemas and live argument validation identical
  across supported Python versions.
- Pre-reserves exact, randomly named recovery sidecars before transactional form and
  byte-preserving writes. Successful writes remove them after final identity checks;
  failed or raced writes retain the immutable preimages without overwriting an external
  winner, including publish-then-claim-loss and sparse backup-rotation cases.

### Removed
- Retires the pre-FastMCP 70-tool shadow registry and its unused legacy server,
  prompt handlers, schema sanitizer/builder, and logging bootstrap. Installed
  tools, schemas, health, capabilities, and documentation now come exclusively
  from the canonical `ToolSpec` registry and FastMCP entrypoint.

## [3.0.0] - 2026-07-16

### Removed
- Removes seven non-product QA tools and their bundled runtime from the public wheel. Supported
  exam, evaluation-plan, form-fill, authoring, editing, verification, workflow, and real-Hancom
  render surfaces remain public.

### Changed
- Requires `python-hwpx>=3.0.0` and exposes 126 default / 136 advanced product tools.
- Raises the matching skill floor to `0.2.0`; the intentional breaking delta, replacements,
  and zero-alias policy are recorded in [`docs/tool-contract-delta-3.0.0.json`](docs/tool-contract-delta-3.0.0.json)
  and [`docs/product-boundary-migration-3.0.0.md`](docs/product-boundary-migration-3.0.0.md).

## [2.23.1] - 2026-07-15

### Security
- Adds one fail-closed multi-root workspace resolver for relative, absolute, missing-output-parent,
  traversal, and symlink-escape cases. Hosts may provide `HWPX_MCP_WORKSPACE_ROOTS` as a JSON array;
  otherwise the intentional process working directory is the bounded single-root fallback.
- Promotes tool failures to redacted `hwpx.mcp-error/v1` JSON-RPC errors instead of successful results
  containing error text. Validation, permission, not-found, capability, document, network, and internal
  categories have stable MCP codes and retry guidance.
- Blocks outbound loopback, private, link-local, reserved, metadata, and redirect destinations by default.
  Intentional private render/storage networks require an explicit opt-in and link-local metadata stays denied.

### Changed
- Removes the unused `modelcontextprotocol` dependency and narrows ingest to
  `markitdown[pdf,docx,xlsx]>=0.1.6,<0.2`, matching the advertised input formats.
- Adds clean base/all-extra installation checks, public text/HWPX/wheel hygiene, Ruff `E9,F`, CodeQL,
  dependency review, Dependabot, immutable Action pins, and CycloneDX release SBOM generation.
- Makes source CI install the checked-out core explicitly and lets the public-wheel job wait for the newly
  released core to become visible on PyPI, avoiding a false failure during dependency-ordered releases.
- Requires `python-hwpx>=2.29.2` while preserving the exact 133 default / 143 advanced tool names.

## [2.23.0] - 2026-07-15

### Added
- **Typed agent document and blueprint surfaces**: compact semantic node/query/atomic-command tools plus typed
  `.hwpxbp` dump and strict atomic replay facades, sharing the core catalog, revision, fidelity, dependency,
  idempotency, rollback, lossless, and open-safety contracts.
- **Durable document workflows and rendering**: server-enforced workflow policy, authenticated durable Hancom
  render queue/transport, fixture visual-QA and guarded repair, blind benchmark receipts, and hardened
  non-product QA infrastructure.
- The exact release-facing ToolSpec expands to 133 default / 143 advanced tools.

### Fixed
- Retains the public 2.18.2 pathological-spacing repair for every touched replacement, paragraph insertion,
  addition, form fill, and table path while preserving legitimate compressed spacing and untouched source styles.
- Retains the public 2.18.3 SQUEEZE-cell safety through `python-hwpx>=2.29.1`; changed non-empty cells wrap with
  `BREAK`, while no-op, clear, and untouched cells preserve their original mode.
- Makes the release-facing `test` extra self-contained for visual fixture tests by installing Pillow and NumPy.
- Resolves the render-worker integration fixture from `PYTHON_HWPX_REPO` or the standard sibling checkout instead
  of a retired Stage-specific `python-hwpx-s067` worktree name, so GitHub CI exercises the current public core.

### Note
- Binds to the corrected public core release `2.29.1`; core `v2.29.0` was an immutable failed prepublish tag
  and did not produce a PyPI package or GitHub Release.
- 2.19.0–2.22.0 were staged local candidates rather than public releases; their accumulated changes are
  consolidated into this 2.23.0 public entry.

## [2.18.3] - 2026-07-14

### Fixed
- Prevent long values written into `lineWrap="SQUEEZE"` template cells from being compressed into unreadable overlapping glyphs. `apply_table_ops(fill_cell)` and regular table-cell edits now require `python-hwpx>=2.24.1`, which changes only touched non-empty cells to `lineWrap="BREAK"`; untouched/no-op/cleared cells retain their original wrap mode.

## [2.18.2] - 2026-07-13

### Fixed
- Prevent unreadable glyph over-print after text replacement, paragraph insertion, and table-cell fills when a template placeholder carries pathological character spacing (`hh:spacing <= -40`). Only touched runs are remapped to a deduplicated safe clone; the source character style and legitimate compressed spacing (for example `-37`) remain unchanged. Paragraph insertion now inherits the target neighbor instead of the unrelated section tail.

## [2.18.1] - 2026-07-10
### Fixed
- Restored the seven universal form-fill tools on the release-facing FastMCP entrypoint.
- Replaced legacy-union/count-based health with an exact ToolSpec contract shared by registration,
  capability reporting, generated skill API documentation, and installed-surface tests.
- Tightened core/MCP/plugin compatibility reporting and added protocol-level plugin smoke coverage.

## [2.18.0] - 2026-07-08
### Added
- **`describe_capabilities`**: task-oriented capability map for agents. Groups the ~150 flat tools into 16 domains (read·form-fill·author·edit·tables·styles·layout·toc-xref·pii·redline·exam·seal·generators·memo·verify·package) with intent + when-to-use + entry-point tools; `domain=` filters one group. A coverage drift-guard test asserts every registered tool is mapped (adding a tool without mapping it fails CI). Lets an external agent orient itself with one call instead of reading ~150 tool descriptions.


## [2.17.0] - 2026-07-08
### Added
- **Stage 3 universal form-fill tool surface**: `scan_form_guidance` (non-mutating form recon), `apply_body_ops` (byte-preserving body-paragraph ops incl. set_paragraph_text/strip/recolor, dryRun), `inspect_fill_residue` (fill residue zero-check gate). `apply_table_ops` gains `split_cell_vertical`·`clone_table`·`set_row_heights`·`set_cell_line_spacing` ops and `dryRun` transcript. Requires python-hwpx>=2.24.0.
### 비고
- Validated by producing a full 3학년 평가계획 from the blank form end-to-end (delete·reshape·fill·cleanup·recolor) with generic primitives only; real-Hancom render + owner review PASS.


## [2.16.0] - 2026-07-06
### Added
- **Document ingest gateway + Markdown-plan bridge (Spec 013)**: MCP surface to ingest external documents and bridge Markdown → `hwpx.document_plan` (`ingest_adapters`, `markdown_plan`).
### Fixed
- **Styled paragraph/table font size (양식 채우기 글자 크기)**: `add_paragraph` / `insert_paragraph` (and therefore `create_document_from_plan`) now apply the paragraph *style's* char property (`charPrIDRef`) to the text run instead of letting python-hwpx default it to `charPrIDRef="0"`. On templates whose char property #0 is a large title font — e.g. the KACE 투고양식, where #0 = 17pt (국문_제목) — styled body text no longer renders at that title size; it uses the style's real size (`j-본문` = 9pt). `add_table` cells get the document body (바탕글/Normal) char property for the same reason. A guard (`_enforce_run_char_pr`) re-asserts the style char property on freshly created runs and warns on an unexpected mismatch (regression detection). `add_heading` already passed `char_pr_id_ref`; this restores the same behaviour for body paragraphs and table cells.

## [2.15.0] - 2026-07-03
### Added
- **Font shrink-to-fit (M10 follow-on)**: `apply_table_ops` `fill_cell` op now accepts `max_lines` — the cell font is shrunk (down to a floor) so its text fits within that many lines, backed by `hwpx.table_patch` font materialisation (python-hwpx ≥ 2.23.0). Complements `autofit_columns` (width) for the "long text" case.
### Changed
- `python-hwpx>=2.23.0`.
- README trimmed 599→184 lines (the exhaustive tool catalog moved to themed highlights + links to `docs/use-cases.md` / `docs/skill-first-workflows.md`).

## [2.14.0] - 2026-07-03
### Added
- **Column-width fit (M10 follow-on)**: `apply_table_ops` gains two ops — `set_column_widths` (explicit logical column widths, merge-aware) and `autofit_columns` (rebalance widths to content: widen content-heavy columns, narrow light ones, table total preserved) so long text is not cramped in a narrow column. Both are byte-preserving (cellSz only). Backed by `hwpx.table_patch` (python-hwpx ≥ 2.22.0).
### Changed
- `python-hwpx>=2.22.0` (column-width fit).

## [2.13.0] - 2026-07-03
### Added
- **Byte-preserving structural form-fill (M10/S-064)**: `apply_table_ops` — fill cells + edit table structure (`fill_cell`, `delete_column`, `delete_row`, `delete_table`, `insert_row_by_clone`) in one transactional tool that PRESERVES the original table formatting and every untouched byte (never rebuild — the 2026-07-03 failure mode). `delete_column` redistributes freed width and cascades a delete of any row it empties; `insert_row_by_clone` clones a `rowSpan==1` reference row (formatting kept); every structure edit is grid-validated and refuses on an invalid result (fail-closed). `renderCheck='required'|'auto'` gates on / attaches a real-Hancom render verdict. `verify_form_fill` — render before/after in real Hancom → `renderChecked` + overflow/overlap(글자겹침)/pageCount, honest degrade, `require=true` fail-closed. Backed by `hwpx.table_patch` (python-hwpx ≥ 2.21.0); tools return `TABLE_OPS_UNAVAILABLE` on version skew.
### Changed
- `python-hwpx>=2.21.0` (M10 `hwpx.table_patch`).
- **네이티브 자동 차례·상호참조 (M7/S-062)**: `add_toc` — 개요 스타일 제목들로 한컴 네이티브 `TABLEOFCONTENTS` 필드 삽입(`dirty=1` 기본 = 한컴이 처음 여는 순간 항목·스타일·쪽번호 재계산; 방출 쪽번호는 추정치로 정직 표기). `add_cross_reference` — 제목 텍스트로 타깃을 지정하는 쪽 번호 `CROSSREF`(한컴이 자동 재계산). `verify_toc` — 캐시 쪽번호 검증: 구조 verdict + **오라클-free stale 신호**(상호참조↔차례 캐시 모순), `verify_render=True`면 실제 한컴 렌더 대조(`toc_correctness_ratio`), `refresh=True`면 macOS 새로고침 세션 구동, 오라클 없으면 정직 `unverified`, 비-HWPX fail-closed.
### Changed
- python-hwpx 의존 핀 `>=2.19.0` → `>=2.20.0` (`hwpx.tools.toc_author`/`toc_fidelity` + Mac 오라클 refresh 레그).

## [2.11.0] - 2026-07-02
### Added
- **런서식 충실 읽기 표면 (M6/S-060)**: `hwpx_extract_json` 이 `doc.notes[]`(각주/미주 kind·instId·anchorParaIndex·bodyText·bodySpans, PII 마스킹) 를 방출하고, `format_detail=True` 런 상세에 명명 필드 `fontSize`·`fontName`·`superscript`·`subscript` 추가. `hwpx_to_markdown` 은 각주/미주 정의 부록(`[^fn1]: 본문`) 을 덧붙인다 — 이전엔 모든 읽기 표면이 각주 본문을 드롭했다. 정본 `hwpx.tools.read_fidelity` 재사용으로 표면=하니스 일치.
### Fixed
- **strikeout 상시-true 버그**: `_run_format_detail` 이 항상 존재하는 `<hh:strikeout shape="NONE"/>` 의 멤버십만 검사해 모든 런에 취소선을 보고하던 문제 — shape 속성으로 정규화. `underline` type `NONE`→`null` 정규화.
- 기본 테스트 스위트가 라이브 한컴 렌더를 간헐 유발하던 flake(`test_add_tracked_edit_writes_structural_redline_receipt`) — 해당 테스트를 no-oracle degrade 경로로 고정(라이브 렌더는 `HWPX_MAC_ORACLE_SMOKE` opt-in).
### Changed
- python-hwpx 의존 핀 `>=2.18.0` → `>=2.19.0` (read-fidelity 하니스).

## [2.10.0] - 2026-07-01
### Added
- **개인정보(PII) 마스킹 표면 (M5/S-059)**: `scan_personal_info(filename|text)` — read-only PII 감사(유형별 건수 + 마스킹 예시만, 원본값 미노출). `get_document_text`·`hwpx_to_markdown`·`hwpx_extract_json` 에 `mask` 파라미터(기본 ON) — 추출 텍스트의 기계검증 PII(주민등록번호·휴대폰·이메일·카드) 자동 마스킹. `apply_form_fill` 은 채워지는 값 + `applied[]` echo 를 마스킹. `mail_merge` 는 엔진 기본-on 마스킹을 상속. 기계세트=항상-on high-confidence, 맥락형(계좌·주소·이름)=라벨게이트 low-confidence(과마스킹 방지).
### Changed
- python-hwpx 의존 핀 `>=2.17.0` → `>=2.18.0` (PII 마스킹 엔진 `hwpx.tools.pii`).

## [2.9.0] - 2026-06-30
### Added
- `add_tracked_edit(source_filename, destination_filename, edits, author="AI Agent", date=None, dry_run=False)` — redline 저작 MCP 표면 (M4/S-058). `edits[]` 의 `insert`/`delete`/`replace` 를 python-hwpx `add_tracked_*` 프리미티브로 `paragraph_index` 에 적용하고, `verify_redline` 영수증(changeCount/marksLinked/displayEnabled/opensClean/render_checked, 오라클 없으면 정직 강등)을 응답에 fold합니다. in-place·비-.hwpx 거부(fail-closed), `dry_run` 지원. 사람은 한컴 검토 리본에서 수락/거부합니다.
### Changed
- python-hwpx 의존 핀 `>=2.16.0` → `>=2.17.0` (redline 저작 API + 메모 본문 픽스).

## [2.8.0] - 2026-06-29
### Added
- `create_document_from_plan` — M3 document authoring (S-057). When `document_plan.metadata.document_type` is 공문/보고서/가정통신문 the document is composed from a real Hancom-harvested profile (opens-clean), not the from-scratch builder. 공문 supports a 결문 block `document_plan.gyeolmun = {issuer, productionNumber, enforcementDate, disclosure}`. The response `quality` now carries: `gongmun_structure` (공문서 작성규정 구조 hard-gate — 수신·발신명의·시행·공개구분·끝., anchored by a real 시행문; `structure_pass`), `korean_proofing_status` (honest `unverified` / `llm_proofed_not_oracle_verified`, never a silent pass), and `render_checked`/`visual_complete`.
- `create_document_from_plan` `verify_render` param — opt into a real Mac Hancom render receipt (`render_checked`/`visual_complete=true`); absent an oracle it degrades to `unverified` (Constitution V).
### Changed
- `create_document_from_plan` output is **HWPX-only** — a non-`.hwpx` filename (ODT 기안문, docx, pdf) returns `created=false`, `handoff_status="unsupported_format"` with no silent attempt (FR-011; ODT 기안문 is a separate track).
- Require `python-hwpx >= 2.16.0` (M3 document_type routing, 결문 IR, 공문 structure hard-gate, render_checked). Co-located editable resolution for local dev.
### Note
- 각주(footnote) authoring is honest-deferred (`unverified`): `add_footnote` emits valid round-tripping XML but the footnote does not render in Hancom, so it is **not** exposed as a working tool until a real-footnote XML diff fix lands.

## [2.7.0] - 2026-06-26
### Added
- `compose_exam` — 시험지 조판(re-typeset) leap tool (S-056 Plan 3). Pours authored exam Markdown into a school form `.hwpx` using the form's existing named styles, attaches keep-together so no 문항 splits across a column/page, preserves 관리박스 + 머리글/꼬리글 losslessly, and leaves `[그림N]`/`[표N]`/`[식N]` as text placeholders (a human inserts images later). `exam_md` (inline) XOR `exam_md_filename` (path). `verify=True` renders via the Hancom oracle and degrades to `renderChecked=false` when absent; `verify=False` composes without a render. Forms that Hancom exports as vector curves report `splits=null` + `needsReview=true` (no silent 0). Malformed md / unprofilable form → `ok=false`, nothing written (fail-loud). Attaches `openSafety` for the output.
- `verify_question_splits` — standalone honest 문항-split gate (spec 3b): renders via the oracle and runs `measure_question_splits`. No oracle → `renderChecked=false`; curve-export form (0 composed 문항 in the extractable text) → `splits=null` + `needsReview`. `valid_question_numbers` scopes grouping so form chrome (e.g. a "2026." year) can't open a spurious block.
- `set_paragraph_format` keep-together params `keep_with_next` / `keep_lines` / `page_break_before` (spec 3a) — forwarded to the python-hwpx engine's `<hh:breakSetting>` via a freshly minted paraPr (lossless).
### Changed
- Tool surface 88 → 90 (`compose_exam`, `verify_question_splits`); `mcp_server_health` expected count updated and `compose_exam` registered as a key tool.
- Requires `python-hwpx >= 2.15.0` (the `hwpx.exam` 시험지 조판 composer). Imported under a guarded fallback, so an older python-hwpx without `hwpx.exam` leaves the server importable and the exam tools degrade to `ok=false` ("module unavailable").

## [2.6.0] - 2026-06-25
### Added
- `place_seal` / `check_seal_compliance` — oracle-bound 직인/관인 tools (M2 P3 / FR-003). `place_seal` renders the form via the Hancom oracle to locate the 발신명의 anchor, stamps a floating seal on it (`textWrap=IN_FRONT_OF_TEXT` — no text reflow), saves through the openSafety gate, and (verify=True) re-renders to attach the compliance verdict. Falls back to an explicit `anchor_x`/`anchor_y`; with no oracle and no anchor it degrades to `renderChecked=false` rather than guessing. `check_seal_compliance` is the standalone pass/fail check (centered seal passes, mis-placed fails).
- `mail_merge` `fit_mode` (keep/wrap/shrink/wrap_then_shrink/…) + `max_lines` — fit-aware batch (M2 P4 / FR-004): measures each placeholder slot once, isolates slot-overflow / missing-field rows into `needsReview[]` / `skipped[]` (`fitAware` in the report). Excel/CSV/XLSX 명부 reachable via python-hwpx ingestion.
- `[oracle]` extra (`python-hwpx[visual]` → PyMuPDF) for the seal/form-fill render-oracle path; absent it degrades honestly (`renderChecked=false`), never crashes.
### Changed
- Require `python-hwpx >= 2.14.0` (seal placement, `extract_image_boxes`, `mail_merge` fit_policy + xlsx, `isEmbeded` image-render fix).
- Tool surface 86 → 88 (`place_seal`, `check_seal_compliance`); `mcp_server_health` expected count updated.

## [2.5.0] - 2026-06-24
### Added
- VisualComplete quality contract for general document saves: these writes use python-hwpx's `SavePipeline` and capability handshake, and their responses carry a `visualComplete` block (`ok`/`status`/`errorCodes`/`warnings`/`suggestedRetry`). (`byte_preserving_patch` is an explicit byte-preserving fast path: open-safety + capability gated, render gate N/A by design.)
- `quality` block on writes (default `transparent`; `strict` or per-field overrides like `overflowPolicy`/`layoutLint`). On a gate failure the save is withheld (`ok=false`) and the model gets a structured, retry-able error (`FIELD_OVERFLOW`, `STALE_LINESEG_DETECTED`, `VISUAL_COMPLETE_FAILED`, …) with `suggestedRetry`. New `HWPX_MCP_QUALITY` global default.
- Capability handshake in `mcp_server_health` (core/mcp/plugin versions + fingerprint hash) that **fails closed** on skew — writes are blocked when the installed python-hwpx can't honour the gate. Bypass with `HWPX_MCP_REQUIRE_CAPABILITY=0`.
- README "no raw XML" quality-contract section.

### Changed
- Require `python-hwpx >= 2.12.0` (the VisualComplete quality stack: `hwpx.quality` SavePipeline, `form_fit`, `layout`, `design`).

## [2.4.1] - 2026-06-12
### Changed
- Require `python-hwpx >= 2.11.1` so document-plan generated headings receive real `개요 N`/`Outline N` paragraph styles and visible title/heading hierarchy.

### Fixed
- `create_document_from_plan` outputs now round-trip through `get_document_outline` as structured headings instead of plain emphasized paragraphs.
- `get_document_outline` no longer promotes plain short or numbered paragraphs when a document has outline styles; legacy markdown `#` heading fallback remains available for older generated files.

## [2.4.0] - 2026-06-12
### Added
- Transactional editing: `apply_edits` (atomic multi-op with rollback, `dry_run`, `expected_revision`, `idempotency_key`), `undo_last_edit`, automatic `.bak` rotation, and semantic diff summaries on write responses.
- `render_preview` layout preview tool (page-approximate HTML/PNG for agent self-checks).
- Document revision concurrency guard: reads return `document_revision`; writes reject on `expected_revision` mismatch; Hancom file-lock warnings.
- Native form field (누름틀) workflows: `list_form_fields`, `fill_form_field`, plus match-confidence grades in `analyze_form_fill`.
- Existing-document format editing tools: `set_paragraph_format`, `set_page_setup`, header/footer/page-number and list/bullet tools (human units).
- Official document style lint `inspect_official_document_style` and approval-box (결재란) preset support.
- Advanced generator tools: photo sheet (`image_grid`), meeting nameplates, table-based org chart.
- `doc_diff` paragraph diff and reference-consistency lint tools.
- `mail_merge` bulk generation and `table_compute` (sum/avg) tools.
- Style profile transfer (`extract_style_profile`) and template registry tools.
- Picture asset workflows (safe insert/replace with manifest validation).
- Byte-preserving patch tool `byte_preserving_patch` backed by `hwpx.patch`.
- `get_document_map` single-call document map; compact write responses (`verbosity` compact/full); plugin health diagnostics in `mcp_server_health`; actionable `suggestion` fields on common errors.

### Changed
- Require `python-hwpx >= 2.11.0` for the fuzz-hardened, parser-hardened authoring surface backing the new tools.

### Fixed
- `add_heading` no longer stores a literal markdown `#` prefix in document text (it leaked into the Hancom editor view). Headings now use the template's built-in `개요 N` paragraph styles with emphasized run styling; outline readers (`get_document_outline`, structure extraction, form-fill analysis) detect style-based headings first while still recognizing legacy `#` headings, and a paragraph added right after a heading no longer inherits the outline style.

## [2.3.5] - 2026-06-09
### Changed
- Require `python-hwpx >= 2.10.3` so MCP saves inherit the upstream editor-open safety guard for stale `lineSegArray` layout caches.

### Fixed
- Add an open-safety save gate for local and HTTP storage. Saves are written to a temporary target, checked for blocking package validation failures and reopenability, and only then replace or upload the document.
- Add open-safety verification evidence to direct generated-document and repair paths, including document-plan, proposal, quality-generation, form-fill, and `repair_hwpx` outputs.
- Return `verification.openSafety` evidence from stateless `create_document` so blank-document creation has the same handoff signal as other generated outputs.
- Block `copy_document` from creating a new HWPX from an unsafe source and preserve an existing destination when validation fails.
- Return `openSafety` evidence from successful `copy_document` calls so copied HWPX handoffs expose the same editor-open signal as generated outputs.
- Save generated document-plan/proposal and quality-generation outputs to sibling temporary files first, then replace the requested destination only after open-safety verification passes.
- Return `verification` and `openSafety` evidence from HWP-to-HWPX conversion outputs.
- Return `verificationReport.openSafety` evidence from `make_blank` and `fill_template` outputs.
- Return `verificationReport` plus top-level `openSafety` evidence from stateless edit tools such as text replacement, paragraph/table edits, formatting, and memo operations.
- Block unsafe HTTP downloads from being promoted into the local cache; remote payloads are first written to a temporary file and open-safety checked.
- Apply form-fill changes to a sibling temporary HWPX and replace the destination only after structure, package, document, and open-safety validation pass.
- Include `repair.openSafety` in successful `apply_form_fill` responses so the repair/repack step exposes its own editor-open evidence.
- Fail closed when an older `python-hwpx` installation lacks the editor-open safety classifier or repair helper, instead of importing the MCP server with weak save validation.
- Fail closed in quality-generation validation when package validation support is unavailable, so generated HWPX cannot be handed off without package/document/open-safety evidence.
- Preserve the HTTP storage cache when remote upload fails by replacing the cache only after temporary save, open-safety verification, and upload all succeed.
- Inherit upstream repair/recover cleanup for stale `lineSegArray` layout caches so `repair_hwpx` can fix that editor-open failure class instead of only rejecting it.
- Inherit upstream save-time normalization for named paragraph `styleIDRef` values so existing malformed documents can be edited and saved with numeric style references.
- Preserve the previous target when a save fails open-safety verification.
- Surface the stricter upstream `openSafety.ok` signal, including hard document-validation failures in addition to package and reopen failures.

## [2.3.4] - 2026-06-06
### Added
- Add a shared paragraph location contract covering body paragraphs and table-cell paragraphs, plus anchors that can be passed between search, lookup, memo, and edit tools.
- Add `get_location_text`, `add_memo_by_anchor`, `replace_in_paragraph`, `replace_by_anchor`, and `mcp_server_health`.

### Changed
- Search now returns reusable `location` and `anchor` values for body and table-cell matches.
- `set_table_cell_text` supports `preserve_format` and `split_paragraphs`, preserving existing run `charPrIDRef` while replacing text.
- `get_table_map` separates `caption_text` from `preceding_paragraph_text` and keeps cell paragraph boundaries in previews.
- Require `python-hwpx >= 2.10.2` for the table location and table-cell formatting behavior.

### Fixed
- Clarify sandbox path errors so users know to use a relative path under the sandbox root or an absolute path inside that root.

## [2.3.3] - 2026-06-04
### Added
- Expose document-plan validation, analysis, creation, authoring-quality, operating-plan quality, template form-fit, proposal quality, and repair workflows through MCP.
- Add `create_government_report_document`, `compute_report_value`, and `parse_government_report_text` MCP tools backed by `python-hwpx` government-report/report utility APIs.

### Changed
- Require `python-hwpx >= 2.10.1` so installed MCP servers have document-plan v2, government-report preset, report calculators/parser, table cleanup, and id-integrity support.

## [2.3.2] - 2026-06-04
### Fixed
- Clear stale `lineSegArray` layout caches when placeholder form-fill inserts text into an existing paragraph.
- Clear layout caches when the single remaining paragraph is emptied by `delete_paragraph`, so Hancom recalculates rendered text instead of reusing stale line layout.

## [2.3.1] - 2026-06-04
### Fixed
- Prevent Hancom glyph overlap after replacing text in existing HWPX paragraphs by collapsing cross-run replacements into the first run instead of redistributing text across stale run boundaries.
- Clear stale `lineSegArray` layout caches in XML fallback table-cell replacement paths so Hancom recalculates line layout after edits.

## [2.3.0] - 2026-06-02
### Added
- Add stack smoke-test workflow and benchmark follow-up docs under `python-hwpx/shared/hwpx` so the shared HWPX stack baseline lives with the upstream engine repo.

### Changed
- Require `python-hwpx >= 2.10.0` so `uvx hwpx-mcp-server` and plugin fallback launchers resolve the S-013 builder core, authoring-quality, validation-severity, and template/form-fill surface shipped by the upstream engine.
- Refresh README requirements to the `python-hwpx 2.10.0` public stack baseline.

## [2.2.6] - 2026-04-27
### Changed
- Require `python-hwpx >= 2.9.1` so downstream consumers pick up the upstream interop fixes for `ET.SubElement` on lxml elements (airmang/python-hwpx#30) and the signed int32 ID generators (airmang/python-hwpx#34, #35).
- License relicensed to Apache-2.0 (sole author, full consent); previous license terms no longer apply to future releases.

### Removed
- Drop the `_patch_upstream_id_generators_to_signed_int32` compat shim and its regression tests. The shim existed only to bridge users still pinned to `python-hwpx 2.9.0`; it is superseded by the upstream fix in `python-hwpx 2.9.1`. The `_patch_sub_element_for_lxml_parent` shim is retained because `hwpx/oxml/document.py` still carries stdlib `ET.SubElement` call sites outside the cell-text and run-style paths that 2.9.1 fixed. Thanks to [@seonghoony](https://github.com/seonghoony) for the original shim in #64.

### Fixed
- Drop the legacy `License :: OSI Approved :: Apache Software License` classifier that coexisted with the PEP 639 `license` expression in `pyproject.toml`, which broke `pip install -e .` and `python -m build` under `setuptools>=77`.

## [2.2.5]
- Add filename-based MCP tools `get_table_map`, `find_cell_by_label`, and `fill_by_path` on top of the upstream `python-hwpx` table navigation helpers.
- Keep the downstream layer thin by limiting this integration to validation, document open/save handling, and LLM-friendly structured JSON responses.
- Add regression coverage for table discovery shape, Korean label normalization, ambiguous/out-of-bounds path reporting, persisted fills, and filename-only MCP schemas.
- Refresh README and workflow docs for the new table/form helpers and remove stale claims about public `save` / `save_as` tools.

## [2.2.4]
- README를 기존 레이아웃 스타일에 맞춰 정리하고 문서를 한글 중심으로 재정비했습니다.
- 패키지 소개와 설치, MCP 설정, 주요 도구, 환경 변수 중심으로 문서 구조를 다듬었습니다.
- HTTP 전송 관련 설명과 과도한 내부 구현 설명을 제거해 PyPI 설명을 간결하게 정리했습니다.

## [2.2.3]
- Clarify the post-pivot product boundary so release-facing docs consistently treat `python-hwpx` as the upstream engine, `hwpx-mcp-server` as the active FastMCP product surface, and skills/workflows as orchestration only.
- Add skill-first workflow guidance and thin example skills for reference-preserving edit, public-form filling, template-based generation, and cautious copy-first review flows without adding new public MCP tools.
- Add release-readiness documentation and final scope-alignment notes, and explicitly defer non-surface items such as public `fill_template`, public `save_as`, structure diff, and layout-drift reporting.

## [2.2.2]
- Isolate `python-hwpx` integration behind a dedicated downstream adapter and reduce duplicated upstream-facing logic across the MCP server, core helpers, and `HwpxOps`.
- Fix advanced MCP wrappers so `object_find_by_attr` works with attribute-only queries and `plan_edit` / `preview_edit` / `apply_edit` reflect the currently implemented hardened verification flow instead of sending invalid payloads.
- Remove memo anchor remnants when `remove_memo` runs so memo IDs no longer leak into paragraph text after deletion.
- Add real-output regression coverage for advanced tool wrappers, memo cleanup, and memo-polluted paragraph planning behavior.

## [2.2.1]
- Require `python-hwpx >= 2.6` for the documented MCP feature set and verify downstream compatibility against released `python-hwpx 2.7.1` in a clean environment.
- Make `format_text` persist real run-level `charPrIDRef` changes instead of returning success after a no-op style rewrite.
- Make `create_custom_style` return a reusable `style_id` backed by a distinct upstream `charPr` when formatting overrides are requested, and resolve style names to real style IDs in `add_paragraph` / `insert_paragraph`.
- Route local write paths through the shared atomic save flow (`temp -> validate -> replace`) instead of mixing direct `save_to_path()` writes with storage-backed writes.

## [2.2.0]
- Stabilize tests when an inherited `HWPX_MCP_SANDBOX_ROOT` would otherwise block pytest temp paths.
