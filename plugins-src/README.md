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
    <a href="https://pypi.org/project/python-hwpx-automation/"><img src="https://img.shields.io/pypi/v/python-hwpx-automation?color=blue&label=automation" alt="automation"></a>
    <a href="https://github.com/airmang/hwpx-plugins"><img src="https://img.shields.io/badge/plugin-hwpx--plugin-181717" alt="plugin"></a>
    <a href="https://github.com/airmang/hwpx-plugins/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License"></a>
  </p>
</p>

<!-- release-state: released -->

> [!NOTE]
> 현재 공개 트레인은 `python-hwpx 6.4.0` · `python-hwpx-automation 7.1.0` · `hwpx-plugin 2.2.0`입니다.
> 2026-09-09에 공개 발행과 실제 Codex marketplace 설치·도구 호출을 관찰했습니다.
> 계약은 `ba0211fc854a0a97`(이전 `8c278ebd5becba08`에서 floor만 변경)입니다.
> [설치 검증 영수증](references/release-2026-09-09-existing-edit-stack.md)

HWPX를 잘 몰라도 됩니다. 스킬을 설치하면 Claude Code·Codex·Cursor 같은
에이전트에게 자연어로 말하는 것만으로 한글 문서를 다룰 수 있습니다. 에이전트는
`SKILL.md`의 의사결정 트리를 따라 알맞은 스크립트와 MCP 도구를 스스로 고르고,
문서 처리는 코어 [python-hwpx](https://github.com/airmang/python-hwpx)가 순수
파이썬으로 수행합니다.

| | 저장소 | 역할 |
|---|---|---|
| 📦 | [`python-hwpx`](https://github.com/airmang/python-hwpx) | HWPX 문서를 읽고·고치고·만드는 순수 파이썬 엔진 |
| 🔌 | [`python-hwpx-automation`](https://github.com/airmang/python-hwpx-automation) | 저작·양식 채움 워크플로, `hwpx` CLI, 선택형 MCP 서버 |
| 🎯 | [`hwpx-plugins`](https://github.com/airmang/hwpx-plugins) | 에이전트가 알맞은 도구를 고르도록 돕는 플러그인/스킬 번들 |

응용 저장소는 `python-hwpx-automation`으로 이름을 바꿨습니다 — 정식 배포·
import·콘솔은 각각 `python-hwpx-automation` · `hwpx_automation` ·
`hwpx-automation-mcp`이고, 기존 `hwpx-mcp-server` 표면은 6.x 동안 그대로
동작합니다.

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

설치 뒤 런타임(`python-hwpx`·`python-hwpx-automation`)은 번들 런처가 하루 1회 같은 메이저 안의
최신으로 스스로 갱신합니다. 끄려면 `HWPX_STACK_AUTO_UPDATE=0`, 검증 좌표에 고정하려면
`HWPX_STACK_CHANNEL=verified`를 MCP 서버 환경에 둡니다. 스킬 번들 자체의 갱신은 호스트가 맡습니다 —
Claude Code는 `/plugin` → Marketplaces → `hwpx`에서 자동 업데이트를 켜거나
`claude plugin marketplace update hwpx && claude plugin update hwpx-plugin@hwpx`, Codex는
`codex plugin marketplace upgrade && codex plugin add hwpx-plugin@hwpx`를 실행합니다.

Cursor는 canonical skill 파일을 `.cursor/skills/hwpx/`(또는 글로벌 `~/.cursor/skills/hwpx/`)에 복사하고
`.cursor/rules/hwpx.mdc` 트리거 룰을 둡니다. OpenClaw·Hermes는 각 호스트 번들(`plugins/openclaw/hwpx-plugin`,
`plugins/hermes/hwpx`)에 MCP 배선 안내가 함께 들어 있습니다. 저장소 이름 `hwpx-plugins`와 설치되는
skill 이름 `hwpx`를 혼동하지 마세요.

## 에이전트에게 말 걸기

설치 후 사용자가 직접 파이썬을 칠 일은 거의 없습니다. 에이전트에게 자연어로 말하면 스킬이 트리거됩니다.

| 이렇게 말하면 | 에이전트가 하는 일 |
|---|---|
| "이 hwpx 텍스트 전부 뽑아줘" | 표 안 문단·각주 포함 텍스트 추출 |
| "이 양식은 그대로 두고 내용만 채워줘" | 바이트 보존 양식 form-fit (셀 채움·행/열 조정·한컴 검증) |
| "머리글·쪽번호 들어간 계획서 새로 만들어줘" | 문서 빌더(document plan)로 레이아웃 민감 문서 조립 |
| "한컴에서 안 열리는 hwpx인데 복구해줘" | repair/recover 복구 복사본 생성 |

> **예시 —** 사용자: "첨부한 가정통신문 양식에서 학교명이랑 날짜만 우리 학교 걸로 바꿔서 새 파일로 줘."
> 에이전트가 원본을 보존한 채 form-fit으로 값을 채우고, 패키지·스키마 검증을 거친 새 파일을 돌려줍니다.

## 무엇을 하나

- **에이전트 온보딩 스킬** — `SKILL.md` 의사결정 트리로 요청 성격에 맞는 스크립트·MCP 도구를 스스로 선택
- **문서 능력 한 벌** — 읽기·양식 채움·생성·편집·공문서·신구대조표·mail merge
- **MCP 서버 동봉 배선** — 호스트별 MCP 설정과 런처가 포함되어 스킬과 도구가 한 번에 로드
- **호스트별 번들** — Claude Code·Codex·Cursor·OpenClaw·Hermes 진입점을 한 canonical 소스에서 빌드
- **신뢰 루프** — `render_preview` 페이지 PNG 자기검증·package/schema/text 검증·시각 검토 evidence

자세한 내용: [SKILL.md](SKILL.md) · [references/](references/)

## 버전·호환성·성숙도

| 구분 | 의미 | 현재 값 |
|---|---|---|
| 완전한 공개 트레인 | 현재 공개 릴리스 — 실제 설치까지 관찰한 조합 | `python-hwpx 6.4.0` · `python-hwpx-automation 7.1.0` · `hwpx-plugin 2.2.0` |
| 검증 좌표 | 공개 발행·설치 관찰 완료 | `python-hwpx 6.4.0` · `python-hwpx-automation 7.1.0` · `hwpx-plugin 2.2.0` |
| 최소 호환 버전 | 2.0 스킬 계약이 지원하는 가장 낮은 조합 | `python-hwpx >= 6.4.0` · `python-hwpx-automation >= 7.1.0` · skill `>= 2.0.0` |
| 검증 좌표 | 이 플러그인 릴리스가 함께 검증한 정확 조합. `HWPX_STACK_CHANNEL=verified`를 주면 이 조합만 설치하고 갱신하지 않음 | `python-hwpx 6.4.0` · `python-hwpx-automation 7.1.0` |
| 플러그인 설치 제약 | 번들 런처가 설치하고 하루 1회 자동 갱신하는 창 — 같은 메이저 안의 최신 | `python-hwpx[preview]>=6.4.0,<7` · `python-hwpx-automation[mcp,oracle]>=7.1.0,<8` |

- 코어 성숙도: `Development Status :: 3 - Alpha`. Python 기준은 3.10 이상입니다.
- MCP 서버·플러그인 성숙도: 미선언. 버전 숫자를 성숙도 주장으로 해석하지 않습니다.

산출물이 실제 한컴오피스에서 열리는지는 코어가 동결 코퍼스 전수로 측정해 그대로
공개합니다 — [실측 코퍼스 메트릭](https://airmang.github.io/python-hwpx/corpus-metrics.html).

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

[python-hwpx](https://github.com/airmang/python-hwpx) · [python-hwpx-automation](https://github.com/airmang/python-hwpx-automation) 위에서 동작하며, 아래 공개 표준·프로젝트에 빚지고 있습니다.

- **[OWPML — 개방형 워드프로세서 마크업 언어 (KS X 6101)](https://www.kssn.net/search/stddetail.do?itemNo=K001010119985)** — HWPX가 기반하는 한국 산업 표준
- **[hancom-io/hwpx-owpml-model](https://github.com/hancom-io/hwpx-owpml-model)** — OWPML 요소 구조 참조 모델 · **[neolord0/hwpxlib](https://github.com/neolord0/hwpxlib)** — 오라클 샘플 코퍼스
- **[edwardkim/rhwp](https://github.com/edwardkim/rhwp)** — 멱등성·검증 게이트 설계 영감

## License · Maintainer

Apache-2.0 ([LICENSE](https://github.com/airmang/hwpx-plugins/blob/main/LICENSE) · [NOTICE](https://github.com/airmang/hwpx-plugins/blob/main/NOTICE)) — **Kohkyuhyun** [@airmang](https://github.com/airmang) · [kokyuhyun@hotmail.com](mailto:kokyuhyun@hotmail.com)

### 관리 런타임의 갱신 시점

Claude Code와 Codex는 같은 관리 런처를 실행합니다. 시작할 때 마지막 점검에서
24시간(설정 가능)이 지났으면 백그라운드로 갱신을 시도합니다. 검증한 새 세대는
다음 서버 시작부터 사용하며 실행 중인 서버를 교체하지 않습니다. 계속 켜 두거나
실행하지 않은 호스트에서 24시간 내 활성화를 보장하지 않습니다. 최초 설치에는
네트워크가 필요하고, 준비된 런타임의 시작은 네트워크를 기다리지 않습니다.
`HWPX_STACK_CHANNEL=verified`는 정확 검증 조합을 고정하고 자동 갱신을 끕니다.
OpenClaw·Hermes의 직접 uvx 설치 안내는 관리 런처를 쓰지 않으므로 수동 갱신입니다.

Codex는 번들 `env_vars`에 선언된 환경변수만 전달합니다. `HWPX_STACK_CHANNEL`,
`HWPX_STACK_AUTO_UPDATE`, `HWPX_STACK_UPDATE_INTERVAL_HOURS`,
`HWPX_AUTOMATION_RUNTIME_ROOT`, `HWPX_AUTOMATION_ADVANCED`,
`HWPX_AUTOMATION_WORKSPACE_ROOTS` 및 실한컴 렌더의 큐·인증서 환경변수를
설정한 환경에서 새 Codex 세션을 시작하세요. `HWPX_AUTOMATION_ADVANCED=1`은
고급 도구를 켜며, 미지정 기본값은 0입니다. secret 값을 설정 파일에 복사할 필요는 없습니다.

관리 상태의 `runtime.installed`는 다음 시작에 사용할 세대입니다. 상태 보고를 지원하는
automation에서 `runtime.running`과 `runtime.restartRequired`로 실행 중인 버전과
구분합니다. `stackUpdate` 필드는 automation 7.1.0부터 제공됩니다.

기존 문서 수정은 [조회·대상 확정·보존 저장·검증 안내](references/workflows-existing-edit.md)를 먼저 확인하세요. 새 문서는 document-plan, 에이전트 연결은 선택 MCP와 호스트 플러그인을 사용합니다.
