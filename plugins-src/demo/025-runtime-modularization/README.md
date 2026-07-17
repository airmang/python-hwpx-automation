# 025 runtime modularization reference

S-080의 런타임 모듈화와 기존 단순 머리글 story 편집을 공개 MCP 경계에서 함께 검증하는
결정적 기준 자료다. 두 구역으로 된 합성 HWPX에서 본문, 표 셀, 기존 `BOTH` 머리글을
`apply_document_commands` 한 번으로 원자 편집하고, 두 번째 구역의 본문과 머리글이 그대로
보존되는지 확인한다.

이 디렉터리는 `python-hwpx 3.2.0`, `hwpx-mcp-server 4.1.0`, `hwpx-plugin 0.4.0`
공개 릴리스를 대상으로 한다. canonical renderer가 만든 tool-contract hash는
`c127914cc3f4480e`다. 포함된 HWPX는 release-final-v3에서 로컬 휠로 설치한 정확한
`3.2.0/4.1.0/0.4.0` 스택이 만든 source/output pair다. output은 한컴오피스 한글
12.30.0 build 6382에서 경고 없이 2/2쪽·2/2구역으로 열렸고, 검토 전후 바이트가 같다.
공개 인덱스 재생도 core와 MCP의 순차 게시 뒤 같은 빌더로 통과했으며, 포함된
receipt에 별도 기록했다.

## 파일

- `source-spec.json`: 합성 원본, 고정 좌표, 보존 대상, 바이트 lineage 명세
- `source.hwpx`: 2구역 합성 원본
- `expected-request.json`: 공개 `apply_document_commands` 입력
- `expected.hwpx`: 동결된 release-final-v3 기대 바이트
- `build_reference.py`: 설치된 공개 MCP 경계로 commit과 동일 요청 retry를 재생하는 빌더
- `receipt.json`: release-final-v3, 이전 후보 이력, public-index gate를 구분한 영수증
- `visual-review.json`: 번들된 한컴 스크린샷 3장과 exact-byte lineage
- `release-final-v3-*.jpeg`: 모든 쪽과 두 구역 story를 확인한 한컴 검토 화면

## 원자 편집과 보존 계약

| command | canonical path | 원본 | 기대값 |
|---|---|---|---|
| `body` | `/section[1]/paragraph[@id="0"]` | `2026학년도 디지털 교육 운영 계획(초안)` | `2026학년도 디지털 교육 운영 계획(확정)` |
| `cell` | `/section[1]/paragraph[@id="641758544"]/table[@id="1279708826"]/row[1]/cell[2]` | `교육연구부` | `디지털교육지원팀` |
| `header` | `/section[1]/header[@page-type="BOTH"]` | `S-080 검토용 머리글` | `S-080 확정 머리글` |

두 번째 구역의 `붙임 1. 2절 보존 점검표`와 `S-080 붙임 보존 머리글`은 바뀌지 않아야 한다.
source/output의 OPC member 집합은 같고 `Contents/section0.xml`만 변경된다.

## 재생

대상 릴리스 패키지가 설치된 격리 환경에서 다음을 실행한다.

```bash
python3 build_reference.py --check --package-origin local-wheel
```

`--check`는 임시 workspace 안에서 source를 복사해 MCP server를 import하기 전에 workspace root를
고정하고, commit 뒤 같은 idempotency key와 같은 입력을 그대로 retry한다. 체크아웃의 파일은 쓰지
않는다. 바이트와 구조 검증이 모두 통과한 휠 설치 환경에서 `--check`를 빼고
`--package-origin local-wheel` 또는 게시 후 `--package-origin public-index`로 실행하면
`receipt.json`의 release-final 또는 public-index replay 항목만 갱신한다.

검증 항목은 source 불변, commit/retry exact-byte 동일성, 기대 HWPX exact-byte 일치,
`openSafety`, reopen, story-preservation receipt, 그리고 OPC ZIP member 차이다. 현재 포함된
expected 바이트는 release-final-v3에서 로컬 휠로 설치한 3.2.0/4.1.0/0.4.0 스택이 공개
FastMCP 경계에서 재현했고, 번들된 한컴 스크린샷으로 2/2쪽·2/2구역을 모두 검토했다.
`readyForPublicRelease`는 `true`다. `publicIndexReplay`는 공개 PyPI의 core 3.2.0과
MCP 4.1.0만으로 같은 바이트를 재현해 receipt와 visual summary 모두 `passed`로 승격됐다.
