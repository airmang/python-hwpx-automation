# Cross-repository README wording — 현재 공개 릴리스와 승인된 train

릴리스 상태: `release-approved` — 6.0.2/5.0.1/1.0.0 train 발행이 승인되어 진행
중이며, 원격 truth 관찰 전까지 공개 좌표는 4.2.0/5.1.0/0.8.0이다.

이 파일은 `packaging/product-identity.json`의 제품 정체성·공개 버전·성숙도 어휘를
`python-hwpx`와 `python-hwpx-automation` README에 적용할 때 사용할 정확 문구다. 이 저장소의
번들 자산은 아니며, 각 저장소 변경 시 해당 저장소의 테스트와 함께 검증한다.
현재 공개 스택과 아직 발행하지 않은 5.0/6.0/1.0 후보를 절대로 같은 상태로
표현하지 않는다.

## 공통 first-party 범위

> 이 구성요소는 python-hwpx 프로젝트가 직접 유지보수하는 first-party HWPX 스택의 일부입니다.
> “first-party”는 프로젝트 유지보수 관계를 뜻하며, 한컴 또는 제3자의 공식 인증을 뜻하지 않습니다.

공개 릴리스와 호환성 기준은 서로 다른 개념으로 표기한다.

- 공개 릴리스: 승인·배포된 구성요소 버전.
- 최소 호환 버전: 이 릴리스 조합이 지원하는 가장 낮은 버전.
- 플러그인 설치 핀: 재현 가능한 설치를 위해 플러그인이 실제로 고정하는 정확한 버전.
- 성숙도: 버전 숫자와 별개인 공개 분류. 선언하지 않은 구성요소는 `미선언`으로 적는다.

## `python-hwpx` README 교체 문구

제품 관계 문구:

> `python-hwpx`는 HWPX 파싱·편집·생성을 제공하는 코어 라이브러리이며,
> `python-hwpx-automation`과 `hwpx-plugin`은 같은 프로젝트가 직접 유지보수하는 first-party 연동 구성요소입니다.

성숙도 문구:

> 현재 패키지 분류는 `Development Status :: 3 - Alpha`입니다. 이 분류는 API와 제품의
> 성숙도를 나타내며, 공개 버전이나 플러그인의 최소 호환 버전을 대신하지 않습니다.

시각 검증 문구:

> 문서 파싱·편집·생성은 순수 Python으로 수행할 수 있습니다. 다만 페이지 나눔, 표 넘침,
> 글꼴 대체 등 최종 시각 품질을 확언하려면 필요에 따라 실제 한컴 렌더 오라클을 별도로 사용합니다.

기존의 무범위 “공식 스킬” 표현은 위 first-party 문구로 교체한다.

버전 문구:

> 현재 공개 릴리스는 `python-hwpx 4.2.0`입니다. `python-hwpx 5.0.0`은
> 아직 발행하지 않은 다음 스택 후보입니다.

## `python-hwpx-automation` README 교체 문구

제품 관계 문구:

> `python-hwpx-automation`은 python-hwpx 프로젝트가 직접 유지보수하는
> first-party 고수준 문서 자동화 계층입니다. MCP는 선택 가능한 `[mcp]` 어댑터이며,
> 이는 한컴의 공식 제품 또는 인증 서버라는 뜻이 아닙니다.

상태 모델 문구:

> 파일 원시 도구는 명시적인 locator와 입력·출력 경로를 사용합니다. 반면 장기 workflow,
> 렌더 큐, revision/idempotency 기록은 의도적으로 상태를 보유합니다. 따라서 서버 전체를
> stateless라고 표현하지 않습니다.

성숙도 문구:

> MCP 서버는 현재 별도의 Development Status classifier를 선언하지 않습니다. 공개 버전과
> 지원 버전은 문서화하되, classifier가 추가되기 전까지 성숙도를 임의로 승격하지 않습니다.

배지 교정:

```text
https://github.com/airmang/hwpx-mcp-server/actions/workflows/tests.yml/badge.svg
```

버전 문구:

> 현재 공개 릴리스는 `hwpx-mcp-server 5.1.0`이며 공개 플러그인은
> `hwpx-plugin 0.8.0`, 공개 코어는 `python-hwpx 4.2.0`입니다.
> `python-hwpx-automation 6.0.2` / `python-hwpx 5.0.1` /
> `hwpx-plugin 1.0.0`은 미발행 후보입니다. 후보 번들은 재현 검증을 위해
> `python-hwpx-automation[mcp,oracle]==6.0.2`과
> `python-hwpx[preview]==5.0.1`을 고정합니다.
