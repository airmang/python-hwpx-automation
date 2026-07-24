# 변경추적 저작 (redline) — workflows-redline

**언제:** "이 문서 검토해서 고칠 곳을 **변경추적으로** 표시해줘 / 사람이 수락·거부하게 해줘" 같은 요청. 정부·법무·제3자 문서에서 **직접 바이트 수정(흔적 없음)** 대신, 사람이 한컴 **검토 리본**에서 개별 수락/거부할 수 있는 redline을 만든다. (일반 편집은 workflows-editing.)

**핵심 도구:** `add_tracked_edit(source_filename, destination_filename, edits, author="AI Agent", date=None, dry_run=False)`.
- `edits[]` 각 항목:
  - `{type: "insert", paragraph_index: N, text: "추가 문구"}`
  - `{type: "delete", paragraph_index: N, match: "지울 텍스트"}` (match 생략 시 문단 전체)
  - `{type: "replace", paragraph_index: N, old: "기존", new: "대체"}` (= 삭제 old + 삽입 new 한 쌍)
- 코멘트(사유)는 `add_memo_by_anchor`(작성자·일자 포함)로 같은 문단에 단다.

## 작성 루프

1. **문단 식별:** `get_document_map` / `get_document_outline` 으로 고칠 `paragraph_index` 를 찾는다.
2. **변경 구성:** insert / delete / replace 를 `edits[]` 로. 각 변경에 **사유 코멘트**를 `add_memo_by_anchor` 로 부착(작성자 "AI Agent").
3. **dry-run(선택):** `dry_run=True` 로 어디가 바뀌는지 먼저 확인(파일 미작성).
4. **적용:** `add_tracked_edit(source, destination, edits)`. **HWPX 전용·in-place 거부**(destination ≠ source, 비-.hwpx 거부 — fail-closed).
5. **응답 영수증 확인(`verify`):**
   - `changeCount` / `changesByType` — 의도한 삽입·삭제 수와 일치하는지.
   - `marksLinked` / `displayEnabled` — 마크가 헤더 변경에 TcId로 연결되고 표시 플래그가 켜졌는지.
   - `opensClean` / `render_checked` — Mac 한컴 가용 시 실제 렌더 영수증. **없으면 `render_checked=false`로 정직 강등**(거짓 통과 금지).

Tracked-change header/body linkage와 display flag는 `python-hwpx`의 generic
format contract이고, Hancom-bound verify/orchestration은 MCP
`office.document_ops`가 canonical `office.rendering`과 결합해 소유한다.
구조 검증과 visual 검증의 성공을 서로 대신 보고하지 않는다.

## 안전 수칙 (정직 보고)

- **수락/거부는 사람이** 한컴 검토 리본에서 한다. 에이전트는 redline 을 **작성**할 뿐 자동 수락하지 않는다(COM accept 액션 미노출 — 정석은 사람 검토).
- **byte-identity:** 미수정 part(ZIP 엔트리)는 byte-identical. 단 수정 섹션 내부는 재직렬화로 XML 표기(ns prefix/bool)가 바뀔 수 있음 — 한컴 렌더·수용엔 무영향이나, 문단단위 완전 byte-identical(surgical splice)은 현재 미지원(정직 한계).
- `render_checked`/`visual_ok` 가 오라클로 확인 안 되면 **`unverified`/`false` 라벨 그대로** 보고.

## 게이트 근거 (measure-first)

합성 변경추적이 한컴에 수용됨을 실증: 실 Windows 한컴 COM `IsTrackChange=1`·opens-clean·roundtrip + 검토 리본 **수락→반영·거부→취소** 확인 → "유효 XML≠한컴 수용" 위험 REFUTED.

## 데모

`demo/M4-redline/` — 공문에 삽입·치환 + 코멘트 2개를 이 표면으로 저작해 한컴 render_checked 확인(증거 PNG + verify-receipt).
