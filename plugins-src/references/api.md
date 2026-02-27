# python-hwpx 실측 API 노트 (OpenClaw hwpx v3)

이 문서는 `python-hwpx`를 스킬에서 사용할 때 **헷갈리기 쉬운 포인트만** 정리합니다.

- 검증 버전: `python-hwpx 2.3`
- import 이름: `hwpx`

## 설치

```bash
pip install -U python-hwpx
# ZIP-level 수정 후 네임스페이스 정리에 필요
pip install -U lxml
```

## 기본 import

```python
from hwpx import HwpxDocument, HwpxPackage, TextExtractor, ObjectFinder
from hwpx.opc.package import HwpxPackageError, HwpxStructureError
```

---

## HwpxDocument

### 열기/생성

```python
from hwpx import HwpxDocument

with HwpxDocument.open("input.hwpx") as doc:
    ...

doc = HwpxDocument.new()
```

### 저장 (중요)

- `save()`는 **deprecated compatibility wrapper**입니다.
- 경로 저장은 `save_to_path(path)`를 권장합니다.

```python
with HwpxDocument.open("input.hwpx") as doc:
    doc.save_to_path("output.hwpx")

# save()는 향후 제거될 수 있음
# doc.save("output.hwpx")
```

### 런(run) 기반 치환

```python
with HwpxDocument.open("input.hwpx") as doc:
    doc.replace_text_in_runs("{A}", "B")
    doc.save_to_path("output.hwpx")
```

주의(실측): `replace_text_in_runs()`는 **표 내부 텍스트 치환이 보장되지 않음**.
- 표까지 포함한 전역 치환은 ZIP-level 치환으로 분리하는 것을 권장.

### 헤더 텍스트

`set_header_text()`는 문서/버전 조합에 따라 결과가 불안정할 수 있습니다.
- 자동화에서는 결과 검증(열어서 확인)을 전제로 사용.

---

## TextExtractor

`TextExtractor`는 “반복 가능한 섹션 iterator” 형태가 아니라, 아래 메서드 사용이 안정적입니다.

### 전체 추출

```python
from hwpx import TextExtractor

tex = TextExtractor("input.hwpx")
text = tex.extract_text(paragraph_separator="\n", skip_empty=True)
```

### 문단 스트리밍

```python
from hwpx import TextExtractor

tex = TextExtractor("input.hwpx")
for p in tex.iter_document_paragraphs(include_nested=True):
    print(p.text())
```

---

## ObjectFinder

태그 기반으로 OWPML 요소를 전수조사할 때 사용합니다.

```python
from hwpx import ObjectFinder

finder = ObjectFinder("input.hwpx")
texts = finder.find_all(tag="t")
tables = finder.find_all(tag="tbl")
```

시그니처(2.3):
- `find_all(tag=..., attrs=..., xpath=..., section_filter=..., limit=...)`

---

## HwpxPackage

고급/복구/특수 처리(파트 단위 접근)에 사용합니다.

```python
from hwpx import HwpxPackage

pkg = HwpxPackage.open("input.hwpx")
```

예외:

```python
from hwpx.opc.package import HwpxPackageError, HwpxStructureError
```
