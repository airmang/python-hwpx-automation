# 하우스 스타일과 장르 문법 — 판단은 skill, 실행은 MCP

운영 계획서처럼 장르 고유의 구조·타이포그래피·섹션 구분자가 필요한
zero-base 문서에 적용한다.

## 책임 경계

- skill: 요청의 장르를 판단하고, 프로필·번호 체계·칩 형태·accent·이미지
  같은 변주를 선택한다.
- MCP: `hwpx_automation.office.house_style`의 typed bank/genre service와
  document-plan composition을 소유한다.
- core: `HwpxDocument`, 표·셀·문단·스타일 같은 범용 primitive만 소유한다.

`hwpx.house_style`이나 core `build_section_chip`은 사용하지 않는다. 이 둘은
미공개 실험 경로였고 python-hwpx 공개 표면에 들어가지 않는다.

## 운영 계획서 판단 순서

1. 사용자의 산출물이 기관·사업·정책의 운영 계획인지 판단한다. 아니라면
   해당 장르 워크플로를 선택한다.
2. 운영 계획서는 `operating_plan` genre와 그 기본 typography인 `report`
   profile을 사용한다.
3. 다음 variable slot은 내용과 사용자 요청을 보고 skill이 결정한다.

   - `numbering`: `roman` 또는 `arabic`;
   - `chipStyle`: `box` 또는 `inline`;
   - `bulletGlyph`: `○` 또는 `ㅇ`;
   - `accentColor`: 문서 전체에서 한 색만;
   - `headerImage`: 제공된 로고·엠블럼이 있을 때만.

4. 선택값을 document plan에 구체화한다. section chip은 generic block으로
   낮춘다.

   - box: `{"type":"table","rows":[["Ⅰ","","근거"]],"columnWidths":[1,0.4,11]}`
   - inline: `{"type":"heading","level":1,"text":"Ⅰ 근거"}`

5. 공개 MCP 경로로 실행한다.

   `validate_document_plan` →
   `analyze_document_plan(..., quality_profile="operating_plan")` →
   `create_document_from_plan(..., quality_profile="operating_plan")` →
   `inspect_operating_plan_quality`

MCP 내부 typed house-style service는 프로필·장르 데이터 검증과 block
composition의 정본이다. ToolSpec은 바뀌지 않으므로 skill은 기존
document-plan 도구 표면으로만 라우팅한다.

## 변주 원칙

- 장르 문법은 유지하고 표면만 변주한다.
- 프로필을 추측한 척하지 말고 판단 근거를 짧게 남긴다.
- 한 문서 안에서 번호 체계와 chip style을 섞지 않는다.
- portable 전달이 필요하면 A-grade 한컴 폰트를 bank의 portable mapping으로
  낮춘다.
- 실한컴 render가 없으면 시각 완성도를 `unverified`로 남긴다.

## 금지

- genre/profile 선택을 core Python heuristic으로 구현;
- 새 장르마다 core module이나 top-level export 추가;
- skill bundle에 별도 Python house-style engine 추가;
- MCP bank를 core로 복제하여 두 정본 유지;
- section chip을 HWPX 전용 primitive인 것처럼 core에 고정.
