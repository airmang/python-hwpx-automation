> **실한컴 렌더 검증용 패키지(pymupdf·pillow·numpy)는 기본 설치에 없다.** 읽기·편집·생성·미리보기에는 필요 없다.
> 렌더 검증 도구가 `pymupdf`를 찾지 못한다고 하면 사용자의 동의를 받아 아래 명령을 한 번 실행하고 다시 시도한다
> (`<server>`는 이 스킬 폴더에서 두 단계 위의 `server` 폴더, 약 210 MB 추가, 플러그인을 업데이트하면 다시 실행).
> `uv sync --frozen --inexact --group render --project "<server>"`
