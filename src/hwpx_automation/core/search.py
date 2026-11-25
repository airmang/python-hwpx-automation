# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any

from hwpx.errors import HwpxValueError

from ..upstream import repair_pathological_text_spacing
from .locations import iter_paragraph_locations, location_anchor


def _replace_within_runs(runs: list[Any], find_text: str, replace_text: str) -> int:
    replaced_total = 0
    for run in runs:
        run_text = run.text or ""
        if not run_text or find_text not in run_text:
            continue
        expected = run_text.count(find_text)
        if expected <= 0:
            continue

        replaced = 0
        if hasattr(run, "replace_text"):
            try:
                replaced = int(run.replace_text(find_text, replace_text))
            except Exception:  # noqa: BLE001
                replaced = 0

        if replaced <= 0:
            run.text = run_text.replace(find_text, replace_text)
            replaced = expected

        replaced_total += replaced
    return replaced_total


def _match_starts(text: str, find_text: str) -> list[int]:
    """Where each non-overlapping occurrence of *find_text* starts in *text*, left to right."""

    starts: list[int] = []
    position = text.find(find_text)
    while position >= 0:
        starts.append(position)
        position = text.find(find_text, position + len(find_text))
    return starts


def _replace_across_runs(paragraph: Any, find_text: str, replace_text: str) -> int:
    """Replace every occurrence in *paragraph* with python-hwpx's ``paragraph.replace_range``.

    Each new character takes the run (and character shape) of the old character at its place,
    as Hancom's 찾아 바꾸기 writes it; the runs stay as they are. An occurrence with a tab, a line
    break, a control or an object inside it is not one stretch of text and is left as it is.
    The occurrences are replaced from the last so the earlier positions stay valid.
    """

    if not find_text:
        return 0
    replaced = 0
    for start in reversed(_match_starts(paragraph.text or "", find_text)):
        try:
            paragraph.replace_range(start, start + len(find_text), replace_text)
        except HwpxValueError as error:
            if getattr(error, "code", None) != "paragraph-range-crosses-element":
                raise
            continue
        replaced += 1
    return replaced


def _replace_in_paragraph(paragraph: Any, find_text: str, replace_text: str) -> int:
    runs = list(getattr(paragraph, "runs", []))
    if not runs:
        return 0

    # Decide from the text before any replacement: re-scanning afterwards would find
    # find_text again inside replace_text when the one contains the other.
    if not _has_match_across_runs([run.text or "" for run in runs], find_text):
        return _replace_within_runs(runs, find_text, replace_text)
    return _replace_across_runs(paragraph, find_text, replace_text)


def _has_match_across_runs(texts: list[str], find_text: str) -> bool:
    """Whether some occurrence of *find_text* in the joined text spans two runs."""
    return "".join(texts).count(find_text) != sum(text.count(find_text) for text in texts)


def _changed_runs(paragraph: Any, before_run_texts: list[str]) -> list[Any]:
    return [
        run
        for index, run in enumerate(getattr(paragraph, "runs", []))
        if (run.text or "") and (index >= len(before_run_texts) or (run.text or "") != before_run_texts[index])
    ]


def _replace_in_one_paragraph(doc: Any, paragraph: Any, find_text: str, replace_text: str) -> int:
    """Replace in *paragraph*; a paragraph with no run at all gets its text set as a whole."""

    runs = list(getattr(paragraph, "runs", []))
    before_run_texts = [run.text or "" for run in runs]
    replaced = _replace_in_paragraph(paragraph, find_text, replace_text)
    if not runs and not getattr(paragraph, "tables", []):
        text = paragraph.text or ""
        if find_text in text:
            replaced = text.count(find_text)
            paragraph.text = text.replace(find_text, replace_text)
    if replaced:
        repair_pathological_text_spacing(doc, paragraph=paragraph, runs=_changed_runs(paragraph, before_run_texts))
    return replaced


def find_in_doc(doc: Any, text_to_find: str, match_case: bool = True, max_results: int = 50) -> dict:
    if text_to_find == "":
        raise ValueError("text_to_find는 빈 문자열일 수 없습니다.")
    matches: list[dict] = []
    needle = text_to_find if match_case else text_to_find.lower()

    for resolved in iter_paragraph_locations(doc):
        location = resolved.location
        haystack_raw = resolved.paragraph.text or ""
        haystack = haystack_raw if match_case else haystack_raw.lower()
        cursor = 0
        while True:
            pos = haystack.find(needle, cursor)
            if pos < 0:
                break
            context_start = max(0, pos - 20)
            context_end = min(len(haystack_raw), pos + len(text_to_find) + 20)
            match = {
                "location": location,
                "anchor": location_anchor(location, pos),
                "position": pos,
                "context": haystack_raw[context_start:context_end],
            }
            if location.get("kind") == "body_paragraph":
                match["paragraph_index"] = location["paragraph_index"]
            else:
                match["table_index"] = location["table_index"]
                match["row"] = location["row"]
                match["col"] = location["col"]
                match["cell_paragraph_index"] = location["cell_paragraph_index"]
            matches.append(match)
            if len(matches) >= max_results:
                return {"matches": matches, "total_matches": len(matches)}
            cursor = pos + max(1, len(text_to_find))

    return {"matches": matches, "total_matches": len(matches)}


def replace_in_doc(doc: Any, find_text: str, replace_text: str) -> int:
    if find_text == "":
        raise ValueError("find_text는 빈 문자열일 수 없습니다.")

    count = 0
    try:
        # Visit exactly the paragraphs find_in_doc searches: the body paragraphs, then the
        # paragraphs of every table cell, tables inside cells included, each one once.
        # The places are listed first so a replacement cannot change what is visited.
        for resolved in list(iter_paragraph_locations(doc)):
            count += _replace_in_one_paragraph(doc, resolved.paragraph, find_text, replace_text)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"텍스트 치환 중 오류: {e}") from e
    return count


def batch_replace_in_doc(doc: Any, replacements: list[dict]) -> dict:
    results: list[dict] = []
    total = 0
    for index, item in enumerate(replacements):
        if not isinstance(item, dict):
            raise ValueError(f"replacements[{index}]는 dict여야 합니다.")

        found = str(item.get("find", ""))
        repl = str(item.get("replace", ""))
        if found == "":
            raise ValueError(f"replacements[{index}].find는 빈 문자열일 수 없습니다.")

        replaced = replace_in_doc(doc, found, repl)
        total += replaced
        results.append({"find": found, "replace": repl, "replaced_count": replaced})
    return {"results": results, "total_replaced": total}
