<p align="center">
  <h1 align="center">hwpx-plugins</h1>
  <p align="center">
    <strong>python-hwpx 프로젝트가 직접 유지보수하는 first-party HWPX 에이전트 스킬</strong>
  </p>
  <p align="center">
    문서 편집은 순수 Python으로 수행하며, 최종 시각 검증은 필요할 때 한컴 오라클을 사용합니다.
  </p>
  <p align="center">
    <a href="https://pypi.org/project/python-hwpx/"><img src="https://img.shields.io/pypi/v/python-hwpx?color=blue&label=core" alt="core"></a>
    <a href="https://pypi.org/project/hwpx-mcp-server/"><img src="https://img.shields.io/pypi/v/hwpx-mcp-server?color=blue&label=mcp" alt="mcp"></a>
    <a href="https://github.com/airmang/hwpx-plugins"><img src="https://img.shields.io/badge/plugin-hwpx--plugin-181717" alt="plugin"></a>
    <a href="https://github.com/airmang/hwpx-plugins/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License"></a>
  </p>
</p>

<!-- release-state: unreleased-candidate -->

HWPX를 잘 모르는 사용자도 스킬만 설치하면 Claude Code·Codex·Cursor 같은 에이전트에게 자연어로
말하는 것만으로 한글 문서를 다룰 수 있습니다. 에이전트는 `SKILL.md`의 의사결정 트리를 따라
알맞은 스크립트나 MCP 도구를 스스로 호출하고, 문서 처리는 코어 [python-hwpx](https://github.com/airmang/python-hwpx)가
순수 파이썬으로 수행합니다.

| | 레포 | 역할 |
|---|---|---|
| 📦 | [`python-hwpx`](https://github.com/airmang/python-hwpx) | 순수 파이썬 HWPX 코어 |
| 🤖 | [`python-hwpx-automation`](https://github.com/airmang/hwpx-mcp-server) | 고수준 문서 워크플로·정책·렌더·MCP 어댑터 |
| 🎯 | **`hwpx-plugins`** | 에이전트용 플러그인·스킬 번들 (이 레포) |

응용 저장소는 아직 GitHub에서 pre-rename 경로
`airmang/hwpx-mcp-server`에 있지만, 6.0 후보의 정식 배포/import/MCP 콘솔은 각각
`python-hwpx-automation`, `hwpx_automation`, `hwpx-automation-mcp`입니다.
새 4-host 설정은 프로토콜 식별자와 별개인 host-local key `hwpx`와 canonical
launcher `scripts/hwpx-automation-mcp`를 사용합니다. 기존
`hwpx-mcp-server` 배포·import·콘솔·설정 키와 `scripts/hwpx-mcp-server`
wrapper는 6.x 호환 표면입니다.

## 시작하기

호스트의 플러그인 명령으로 스킬과 MCP 서버를 함께 설치합니다. **설치·재설치 후에는 새 에이전트
세션을 시작해야** 새 skill과 MCP 도구가 로드됩니다.

```bash
# Claude Code
claude plugin marketplace add airmang/hwpx-plugins
claude plugin install hwpx-plugin@hwpx

# Codex CLI
codex plugin marketplace add airmang/hwpx-plugins
codex plugin add hwpx-plugin@hwpx
```

Cursor는 canonical skill 파일을 `.cursor/skills/hwpx/`(또는 글로벌 `~/.cursor/skills/hwpx/`)에 복사하고
`.cursor/rules/hwpx.mdc` 트리거 룰을 둡니다. OpenClaw·Hermes는 각 호스트 번들(`plugins/openclaw/hwpx-plugin`,
`plugins/hermes/hwpx`)에 MCP 배선 안내가 함께 들어 있습니다. 저장소 이름 `hwpx-plugins`와 설치되는
skill 이름 `hwpx`를 혼동하지 마세요.

### 버전·호환성·성숙도

| 구분 | 의미 | 현재 값 |
|---|---|---|
| 공개 릴리스 | 현재 승인·배포된 구성요소 버전 | `python-hwpx 4.2.0` · `hwpx-mcp-server 5.1.0` · `hwpx-plugin 0.8.0` |
| 미발행 후보 | 이 checkout에서 검증 중이며 아직 공개 릴리스가 아닌 조합 | `python-hwpx 5.0.0` · `python-hwpx-automation 6.0.0` · `hwpx-plugin 1.0.0` |
| 최소 호환 버전 | 1.0 후보 스킬 계약이 지원할 예정인 가장 낮은 조합 | `python-hwpx >= 5.0.0` · `python-hwpx-automation >= 6.0.0` · skill `>= 1.0.0` |
| 플러그인 설치 핀 | 후보 검증용 번들이 고정한 정확 버전 | `python-hwpx[preview]==5.0.0` · `python-hwpx-automation[mcp,oracle]==6.0.0` |

- 코어 성숙도: `Development Status :: 3 - Alpha`. Python 기준은 3.10 이상입니다.
- MCP 서버·플러그인 성숙도: 미선언. 버전 숫자를 성숙도 주장으로 해석하지 않습니다.

## 무엇을 하나

- **에이전트 온보딩 스킬** — `SKILL.md` 의사결정 트리로 에이전트가 요청 성격에 따라 알맞은 스크립트·MCP 도구를 스스로 고름
- **문서 능력 한 벌** — 코어의 HWPX primitive와 automation의 고수준 워크플로를 조합해 읽기·양식 채움·생성·편집·공문서·신구대조표·mail merge 수행
- **MCP 서버 동봉 배선** — 호스트별 MCP 설정과 런처가 포함되어 스킬과 도구가 한 번에 로드됨
- **호스트별 번들** — Claude Code·Codex·Cursor·OpenClaw·Hermes 진입점을 한 canonical 소스에서 빌드
- **신뢰 루프** — `render_preview` 페이지 PNG 자기검증·package/schema/text 검증·시각 검토 evidence 계약

자세한 내용: [SKILL.md](SKILL.md) · [references/](references/)

### 에이전트에게 말 걸기

설치 후 사용자가 직접 파이썬을 칠 일은 거의 없습니다. 에이전트에게 자연어로 말하면 스킬이 트리거됩니다.

| 이렇게 말하면 | 에이전트가 하는 일 |
|---|---|
| "이 hwpx 텍스트 전부 뽑아줘" | 표 안 문단·각주 포함 텍스트 추출 |
| "이 양식은 그대로 두고 내용만 채워줘" | 바이트 보존 양식 form-fit (셀 채움·행/열 조정·한컴 검증) |
| "머리글·쪽번호 들어간 계획서 새로 만들어줘" | `hwpx.builder`로 레이아웃 민감 문서 조립 |
| "한컴에서 안 열리는 hwpx인데 복구해줘" | repair/recover 복구 복사본 생성 |

> **예시 —** 사용자: "첨부한 가정통신문 양식에서 학교명이랑 날짜만 우리 학교 걸로 바꿔서 새 파일로 줘."
> 에이전트가 원본을 보존한 채 form-fit으로 값을 채우고, 패키지·스키마 검증을 거친 새 파일을 돌려줍니다.

## 실측은 코어가 말합니다

이 번들의 문서 능력은 코어 [python-hwpx](https://github.com/airmang/python-hwpx)와
응용 계층 [python-hwpx-automation](https://github.com/airmang/hwpx-mcp-server)이 수행합니다. 산출물이 실제
한컴오피스에서 열리는지는 코어가 동결 코퍼스 전수를 측정해 그대로 공개합니다 —
[실측 코퍼스 메트릭](https://airmang.github.io/python-hwpx/corpus-metrics.html). 스킬은 이 계약 위에서
도구 선택과 evidence 루프만 조율합니다.

## 알려진 제약

- 대상 포맷은 Open XML 기반 `.hwpx`입니다. 레거시 바이너리 `.hwp` 직접 편집은 범위 밖입니다.
- `visual_review_required=true`는 package/schema/text 검사는 통과했지만 열린 문서의 페이지 나눔·표 맞춤은 아직 미확인이라는 뜻입니다. 최종 제출을 말하려면 viewer에서 열어 `observed_pass` evidence를 남깁니다.
- 예제·문서에는 이름·전화번호·이메일·주소 등 PII를 redaction 없이 넣지 않습니다.

## 기여하기

[Discussions](https://github.com/airmang/hwpx-plugins/discussions) ·
[이슈](https://github.com/airmang/hwpx-plugins/issues) ·
[CONTRIBUTING](https://github.com/airmang/hwpx-plugins/blob/main/CONTRIBUTING.md) ·
[CHANGELOG](CHANGELOG.md)

canonical `SKILL.md`·`references/`·`examples/`·`scripts/`를 편집한 뒤
`python3 scripts/build_hwpx_plugins.py`로 호스트 번들을 재빌드하고
`python3 scripts/validate_hwpx_plugin.py`로 검증합니다.

## 감사의 말

[python-hwpx](https://github.com/airmang/python-hwpx) · [python-hwpx-automation](https://github.com/airmang/hwpx-mcp-server) 위에서 동작하며, 아래 공개 표준·프로젝트에 빚지고 있습니다.

- **[OWPML — 개방형 워드프로세서 마크업 언어 (KS X 6101)](https://www.kssn.net/search/stddetail.do?itemNo=K001010119985)** — HWPX가 기반하는 한국 산업 표준
- **[hancom-io/hwpx-owpml-model](https://github.com/hancom-io/hwpx-owpml-model)** — OWPML 요소 구조 참조 모델 · **[neolord0/hwpxlib](https://github.com/neolord0/hwpxlib)** — 오라클 샘플 코퍼스
- **[edwardkim/rhwp](https://github.com/edwardkim/rhwp)** — 멱등성·검증 게이트 설계 영감

## License · Maintainer

Apache-2.0 ([LICENSE](https://github.com/airmang/hwpx-plugins/blob/main/LICENSE) · [NOTICE](https://github.com/airmang/hwpx-plugins/blob/main/NOTICE)) — **Kohkyuhyun** [@airmang](https://github.com/airmang) · [kokyuhyun@hotmail.com](mailto:kokyuhyun@hotmail.com)
