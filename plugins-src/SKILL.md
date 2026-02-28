---
name: hwpx
description: "HWPX(.hwpx/OWPML) 문서 처리 스킬 v3: python-hwpx 기반 열기/생성/편집, TextExtractor로 텍스트 추출, ObjectFinder로 구조 탐색, 대량 치환은 ZIP-level + 네임스페이스 정리(fix_namespaces)."
---

# hwpx v3 (HWPX / OWPML)

이 스킬은 `.hwpx`(한글 OWPML, ZIP 컨테이너) 문서를 **읽기/추출/편집/치환**하는 실전 워크플로를 제공합니다.

- 기준 라이브러리: `python-hwpx` (import: `hwpx`)
- API 검증 버전(로컬): `python-hwpx 2.5`

## 빠른 선택 가이드

1) **문서 생성/간단 편집** → `HwpxDocument`
2) **텍스트만 빠르게 추출** → `TextExtractor.extract_text()` 또는 `iter_document_paragraphs()`
3) **OWPML 태그/표/플레이스홀더 전수 조사** → `ObjectFinder.find_all()`
4) **표 포함 문서 전역 대량 치환** → ZIP-level 문자열 치환(여러 XML 파트) → `scripts/fix_namespaces.py`

---

## 0) 설치

```bash
pip install -U python-hwpx
# ZIP-level 치환 후 네임스페이스 정리에 필요
pip install -U lxml
```

주요 import:

```python
from hwpx import HwpxDocument, HwpxPackage, TextExtractor, ObjectFinder
from hwpx.opc.package import HwpxPackageError, HwpxStructureError
```

---

## 1) 문서 생성/열기/저장 (HwpxDocument)

### 1.1 새 문서 만들기

```python
from hwpx import HwpxDocument

doc = HwpxDocument.new()
doc.add_paragraph("자동 생성 문서")

# 권장: save_to_path()
doc.save_to_path("out.hwpx")
```

### 1.2 기존 문서 열기

```python
from hwpx import HwpxDocument

with HwpxDocument.open("input.hwpx") as doc:
    doc.add_paragraph("추가 문단")
    doc.save_to_path("output.hwpx")
```

### 1.3 저장 API 주의사항

- `save()`는 **하위호환을 위한 deprecated wrapper**입니다(향후 제거 가능).
- **경로 저장은 `save_to_path(path)`**를 사용하세요.

```python
with HwpxDocument.open("input.hwpx") as doc:
    doc.save_to_path("output.hwpx")

# 바이트가 필요하면 (버전별 제공 여부 확인)
# data = doc.to_bytes()
```

---

## 2) 텍스트 추출 (TextExtractor)

`TextExtractor`는 편집 DOM을 만들지 않고 텍스트를 모으는 용도입니다.

### 2.1 한 번에 문자열로 추출: `extract_text()`

```python
from hwpx import TextExtractor

tex = TextExtractor("input.hwpx")
text = tex.extract_text(paragraph_separator="\n", skip_empty=True)
print(text[:2000])
```

### 2.2 문단 단위 스트리밍: `iter_document_paragraphs()`

```python
from hwpx import TextExtractor

tex = TextExtractor("input.hwpx")
for p in tex.iter_document_paragraphs(include_nested=True):
    t = (p.text() or "").strip()
    if t:
        print(t)
```

---

## 3) 구조 탐색/플레이스홀더 조사 (ObjectFinder)

`ObjectFinder`는 문서 내부 XML에서 특정 태그를 찾아 **전수 조사**할 때 씁니다.

```python
from hwpx import ObjectFinder

finder = ObjectFinder("input.hwpx")

# 텍스트 노드(<t>) 전수
for el in finder.find_all(tag="t"):
    t = (el.text or "").strip()
    if t:
        print(repr(t))

# 표(<tbl>) 개수 확인
tables = finder.find_all(tag="tbl")
print("tables:", len(tables))
```

버전/문서에 따라 `FoundElement`의 내부 구조가 달라질 수 있으니, 필요하면 다음처럼 확인합니다.

```python
x = finder.find_all(tag="t", limit=1)[0]
print(type(x))
print([n for n in dir(x) if not n.startswith("_")])
```

---

## 4) 텍스트 치환 (중요한 제한 포함)

### 4.1 문서 본문 런(run) 기반 치환: `replace_text_in_runs()`

```python
from hwpx import HwpxDocument

with HwpxDocument.open("input.hwpx") as doc:
    doc.replace_text_in_runs("{기관명}", "OO구청")
    doc.save_to_path("output.hwpx")
```

#### 제한(실측): 표 내부 텍스트는 치환되지 않을 수 있음

`replace_text_in_runs()`는 **표 내부(테이블 셀)의 텍스트까지 보장되지 않습니다.**
- 표 안 플레이스홀더까지 바꿔야 하면 아래 4.2의 **ZIP-level 치환**을 우선 고려하세요.

### 4.2 문서 전역(표 포함) 대량 치환: ZIP-level 문자열 치환

HWPX는 ZIP 안에 여러 XML 파트가 있으므로, 단순 플레이스홀더 치환은 ZIP-level로 빠르게 처리할 수 있습니다.

주의:
- 태그 조각을 바꾸는 치환은 금지(문서가 깨질 수 있음)
- 치환 후 네임스페이스 선언이 꼬일 수 있어 **반드시 `fix_namespaces.py` 후처리** 권장

```python
import zipfile


def zip_replace_all(in_hwpx: str, out_hwpx: str, repl: dict[str, str]) -> dict:
    stats = {"parts": 0, "changed_xml": 0, "replacements": 0}

    with zipfile.ZipFile(in_hwpx, "r") as zin:
        with zipfile.ZipFile(out_hwpx, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                stats["parts"] += 1
                data = zin.read(info.filename)

                if info.filename.lower().endswith(".xml"):
                    try:
                        s = data.decode("utf-8")
                    except UnicodeDecodeError:
                        zout.writestr(info.filename, data)
                        continue

                    before = s
                    n_here = 0
                    for old, new in repl.items():
                        if not old:
                            continue
                        c = s.count(old)
                        if c:
                            s = s.replace(old, new)
                            n_here += c

                    if s != before:
                        stats["changed_xml"] += 1
                        stats["replacements"] += n_here
                        data = s.encode("utf-8")

                zout.writestr(info.filename, data)

    return stats
```

치환 후 네임스페이스 정리:

```bash
python3 scripts/fix_namespaces.py output.hwpx --inplace --backup
```

---

## 5) 머리말/꼬리말 설정 주의

`set_header_text()`는 일부 문서/버전에서 **레이아웃이 깨지거나 적용이 불안정**하다는 사례가 있습니다.
- 자동화 파이프라인에서는 적용 결과를 **반드시 열어서 확인**하세요.
- 문제가 재현되면: (1) 헤더 편집을 생략 (2) 템플릿에서 헤더를 고정 (3) ZIP-level로 해당 파트만 조정 중 하나로 우회합니다.

---

## 6) 네임스페이스 정리 스크립트

ZIP-level 치환/수정 후 XML 파트의 namespace prefix 선언이 불안정해질 수 있습니다.
이 스킬은 이를 완화하는 스크립트를 포함합니다.

- 위치: `scripts/fix_namespaces.py`
- 동작: HWPX 내부의 `.xml` 파트를 `lxml`로 파싱 후 재직렬화

```bash
python3 scripts/fix_namespaces.py input.hwpx --out fixed.hwpx
```
