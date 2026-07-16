# S-079 cross-repository README wording evidence

이 파일은 `packaging/product-identity.json`의 제품 정체성·버전·성숙도 어휘를
`python-hwpx`와 `hwpx-mcp-server` README에 적용할 때 사용할 정확 문구다. 이 저장소의
번들 자산은 아니며, 각 저장소 변경 시 해당 저장소의 테스트와 함께 검증한다.

## 공통 first-party 범위

> 이 구성요소는 python-hwpx 프로젝트가 직접 유지보수하는 first-party HWPX 스택의 일부입니다.
> “first-party”는 프로젝트 유지보수 관계를 뜻하며, 한컴 또는 제3자의 공식 인증을 뜻하지 않습니다.

릴리스 후보와 호환성 기준은 서로 다른 개념으로 표기한다.

- 릴리스 후보: 별도 승인 전에는 공개를 뜻하지 않는 검증 대상 구성요소 버전.
- 최소 호환 버전: 이 릴리스 조합이 지원하는 가장 낮은 버전.
- 플러그인 설치 핀: 재현 가능한 설치를 위해 플러그인이 실제로 고정하는 정확한 버전.
- 성숙도: 버전 숫자와 별개인 공개 분류. 선언하지 않은 구성요소는 `미선언`으로 적는다.

## `python-hwpx` README 교체 문구

제품 관계 문구:

> `python-hwpx`는 HWPX 파싱·편집·생성을 제공하는 코어 라이브러리이며,
> `hwpx-mcp-server`와 `hwpx-plugin`은 같은 프로젝트가 직접 유지보수하는 first-party 연동 구성요소입니다.

성숙도 문구:

> 현재 패키지 분류는 `Development Status :: 3 - Alpha`입니다. 이 분류는 API와 제품의
> 성숙도를 나타내며, 릴리스 후보 버전이나 플러그인의 최소 호환 버전을 대신하지 않습니다.

시각 검증 문구:

> 문서 파싱·편집·생성은 순수 Python으로 수행할 수 있습니다. 다만 페이지 나눔, 표 넘침,
> 글꼴 대체 등 최종 시각 품질을 확언하려면 필요에 따라 실제 한컴 렌더 오라클을 별도로 사용합니다.

기존의 무범위 “공식 스킬” 표현은 위 first-party 문구로 교체한다.

## `hwpx-mcp-server` README 교체 문구

제품 관계 문구:

> `hwpx-mcp-server`는 python-hwpx 프로젝트가 직접 유지보수하는 first-party MCP 서버입니다.
> 이는 한컴의 공식 제품 또는 인증 서버라는 뜻이 아닙니다.

상태 모델 문구:

> 파일 원시 도구는 명시적인 locator와 입력·출력 경로를 사용합니다. 반면 장기 workflow,
> 렌더 큐, revision/idempotency 기록은 의도적으로 상태를 보유합니다. 따라서 서버 전체를
> stateless라고 표현하지 않습니다.

성숙도 문구:

> MCP 서버는 현재 별도의 Development Status classifier를 선언하지 않습니다. 릴리스 버전과
> 지원 버전은 문서화하되, classifier가 추가되기 전까지 성숙도를 임의로 승격하지 않습니다.

배지 교정:

```text
https://github.com/airmang/hwpx-mcp-server/actions/workflows/tests.yml/badge.svg
```

버전 문구:

> S-079 릴리스 후보는 `hwpx-mcp-server 4.0.0`이며 최소 호환 코어는 `python-hwpx 3.1.0`입니다.
> `hwpx-plugin 0.3.0` 후보 설치 번들은 재현성을 위해 MCP를 `==4.0.0`, 코어를 `==3.1.0`으로 고정합니다.
> 이 버전 좌표는 별도 소유자 승인 전까지 공개 또는 배포를 뜻하지 않습니다.
