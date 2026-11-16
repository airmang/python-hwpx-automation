# 024 mixed-form reference

S-079에서 고정한 합성 1쪽 한국어 양식을 한 공개 계획으로 채우는 재현 가능한 기준 자료다.
`nativeField`, `labelCell`, `canonicalPath`, `bodyAnchor` 네 대상을 모두 mutation 전에 해석하고,
revision-bound `hwpx.agent-batch/v1` 하나로 적용한다. `source.hwpx`와 `expected.hwpx`는 항상 서로
다른 파일이다.

이 자료의 이름과 내용은 모두 합성 데이터다. `김서현`은 기능 검증용 가상 이름이며 실제 개인정보나
시험 콘텐츠를 포함하지 않는다.

## 파일

- `source-spec.json`: P1 고정 ID와 원본 표시값을 담은 생성 명세
- `build_reference.py`: 원본, 공개 계획, 기대 결과, 검증 영수증을 만드는 결정적 빌더
- `source.hwpx`: 미기입 합성 원본
- `expected-plan.json`: `hwpx.mixed-form-plan/v1` 공개 입력
- `expected.hwpx`: 네 대상을 한 batch로 채운 기대 결과
- `receipt.json`: dry-run, rollback, 멱등 재실행, OPC member 동일성, reopen/openSafety 증거

`expected-plan.json`의 source/output은 이 디렉터리를 기준으로 한 상대경로다. 빌더가 compile/apply
직전에 이 디렉터리로 작업 위치를 고정하므로 체크아웃의 절대경로는 compiled hash에 들어가지 않는다.

## 고정 대상과 값

| target | 고정 식별자 | 기대 표시값 |
|---|---|---|
| `nativeField` | `fieldId=240021` | `AI 수업 나눔의 날` |
| `labelCell` | `/section[1]`, `담당 부서` 오른쪽 셀 | `교육연구부` |
| `canonicalPath` | `/section[1]/paragraph[@id="240050"]` | `행사 목적: 교내 AI 활용 사례 공유` |
| `bodyAnchor` | `/section[1]`, `{{담당자}}`, `expectedCount=1` | `김서현` |

## 재현

공개 패키지가 설치된 환경에서는 이 디렉터리 위치와 무관하게 실행할 수 있다.

```bash
python3 build_reference.py
```

S-079 개발 worktree에서는 저장소 루트에서 다음과 같이 실행한다.

```bash
PYTHONPATH=../python-hwpx-s079/src \
  ../python-hwpx-s079/.venv/bin/python \
  demo/024-mixed-form/build_reference.py
```

빌더는 같은 입력에서 같은 네 산출물 바이트를 생성한다. 실행 중 사용하는 dry-run·실패 주입용
숨김 destination은 성공 여부를 검증한 뒤 삭제한다. 실제 한컴 전 페이지 렌더 판정은 이 구조 검증에
포함하지 않으며 `receipt.json`에 `pending-root-p5`로 정직하게 기록되어 있다.

## SHA-256

| 파일 | SHA-256 |
|---|---|
| `source-spec.json` | `sha256:fac2ca759acceab80814be3818313effd72652bfe9e09e14d97fc3e3050d76cf` |
| `source.hwpx` | `sha256:b3186f5870a6d8fc013594f8450aa9390fd140f723ef44af5f565caa0117db4c` |
| `expected-plan.json` | `sha256:a793a6d3862efda716fddf83427b31a71e05205f884a482330944113baf1c206` |
| `expected.hwpx` | `sha256:ec09fb9b6ff6e96bbcc270d314ceaea35357f2c5d150cafa41efbb238c2ded29` |
| `receipt.json` | `sha256:3ce04278e29d944a7b1424fa0e33941b4b61f2c28eff1f62eb42257c4da0f8ea` |

`receipt.json`에도 source/plan/output 해시와 compiled plan/request 해시가 기록되어 있다.
