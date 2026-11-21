# SPDX-License-Identifier: Apache-2.0
"""Discriminated public mutation vocabularies with legacy-payload adapters."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Mapping, TypeAlias

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, RootModel, model_validator


class _ClosedModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ReplacementRule(_ClosedModel):
    find_text: str = Field(
        validation_alias=AliasChoices("findText", "find_text", "find"),
        serialization_alias="findText",
    )
    replace_text: str = Field(
        default="",
        validation_alias=AliasChoices("replaceText", "replace_text", "replace"),
        serialization_alias="replaceText",
    )


class EditReplaceText(_ClosedModel):
    type: Literal["replace_text"]
    find_text: str = Field(
        validation_alias=AliasChoices("findText", "find_text", "find"),
        serialization_alias="findText",
    )
    replace_text: str = Field(
        default="",
        validation_alias=AliasChoices("replaceText", "replace_text", "replace"),
        serialization_alias="replaceText",
    )


class EditBatchReplace(_ClosedModel):
    type: Literal["batch_replace"]
    replacements: list[ReplacementRule]


class EditAddHeading(_ClosedModel):
    type: Literal["add_heading"]
    text: str = ""
    level: int = Field(default=1, ge=1, le=9)


class EditAddParagraph(_ClosedModel):
    type: Literal["add_paragraph"]
    text: str = ""
    style: str | int | None = None


class EditInsertParagraph(_ClosedModel):
    type: Literal["insert_paragraph"]
    paragraph_index: int = Field(
        ge=0,
        validation_alias=AliasChoices("paragraphIndex", "paragraph_index"),
        serialization_alias="paragraphIndex",
    )
    text: str = ""
    style: str | int | None = None


class EditDeleteParagraph(_ClosedModel):
    type: Literal["delete_paragraph"]
    paragraph_index: int = Field(
        ge=0,
        validation_alias=AliasChoices("paragraphIndex", "paragraph_index"),
        serialization_alias="paragraphIndex",
    )


class EditAddTable(_ClosedModel):
    type: Literal["add_table"]
    rows: int = Field(ge=1)
    cols: int = Field(ge=1, validation_alias=AliasChoices("cols", "columns"))
    data: list[list[Any]] | None = None


class EditSetTableCellText(_ClosedModel):
    type: Literal["set_table_cell_text"]
    table_index: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("tableIndex", "table_index"),
        serialization_alias="tableIndex",
    )
    row: int = Field(ge=0)
    col: int = Field(ge=0, validation_alias=AliasChoices("col", "column"))
    text: str = ""
    preserve_format: bool = Field(
        default=True,
        validation_alias=AliasChoices("preserveFormat", "preserve_format"),
        serialization_alias="preserveFormat",
    )
    split_paragraphs: bool = Field(
        default=False,
        validation_alias=AliasChoices("splitParagraphs", "split_paragraphs"),
        serialization_alias="splitParagraphs",
    )


class EditFillByPath(_ClosedModel):
    type: Literal["fill_by_path"]
    mappings: dict[str, str] = Field(min_length=1)


class EditAddPageBreak(_ClosedModel):
    type: Literal["add_page_break"]


EditOperationUnion: TypeAlias = Annotated[
    EditReplaceText
    | EditBatchReplace
    | EditAddHeading
    | EditAddParagraph
    | EditInsertParagraph
    | EditDeleteParagraph
    | EditAddTable
    | EditSetTableCellText
    | EditFillByPath
    | EditAddPageBreak,
    Field(discriminator="type"),
]


class EditOperation(RootModel[EditOperationUnion]):
    @model_validator(mode="before")
    @classmethod
    def normalize_discriminator(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            payload = dict(value)
            raw = payload.get("type", payload.get("op", payload.get("operation")))
            if isinstance(raw, str):
                payload["type"] = raw.strip().replace("-", "_")
            payload.pop("op", None)
            payload.pop("operation", None)
            return payload
        return value


class CellAnchor(_ClosedModel):
    label: str
    direction: Literal["right", "left", "below", "above"] = Field(
        default="right",
        validation_alias=AliasChoices("direction", "dir"),
    )


class _TableAddress(_ClosedModel):
    section_path: str = Field(
        default="Contents/section0.xml",
        validation_alias=AliasChoices("sectionPath", "section_path"),
        serialization_alias="sectionPath",
    )
    table_index: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("tableIndex", "table_index"),
        serialization_alias="tableIndex",
    )
    table_anchor: str | None = Field(
        default=None,
        validation_alias=AliasChoices("tableAnchor", "table_anchor"),
        serialization_alias="tableAnchor",
    )

    @model_validator(mode="after")
    def require_table_target(self) -> "_TableAddress":
        if self.table_index is None and not self.table_anchor:
            raise ValueError("tableIndex or tableAnchor is required")
        return self


class TableFillCell(_TableAddress):
    op: Literal["fill_cell"]
    row: int | None = Field(default=None, ge=0)
    col: int | None = Field(default=None, ge=0)
    text: str
    cell_anchor: CellAnchor | None = Field(
        default=None,
        validation_alias=AliasChoices("cellAnchor", "cell_anchor"),
        serialization_alias="cellAnchor",
    )
    max_lines: int | None = Field(
        default=None,
        ge=1,
        validation_alias=AliasChoices("maxLines", "max_lines"),
        serialization_alias="maxLines",
    )

    @model_validator(mode="after")
    def require_cell_target(self) -> "TableFillCell":
        if (self.row is None or self.col is None) and self.cell_anchor is None:
            raise ValueError("row+col or cellAnchor is required")
        return self


class TableDeleteColumn(_TableAddress):
    op: Literal["delete_column"]
    col: int | None = Field(default=None, ge=0)
    cols: list[int] | None = None

    @model_validator(mode="after")
    def require_columns(self) -> "TableDeleteColumn":
        if self.col is None and not self.cols:
            raise ValueError("col or cols is required")
        return self


class TableDeleteRow(_TableAddress):
    op: Literal["delete_row"]
    row: int | None = Field(default=None, ge=0)
    rows: list[int] | None = None

    @model_validator(mode="after")
    def require_rows(self) -> "TableDeleteRow":
        if self.row is None and not self.rows:
            raise ValueError("row or rows is required")
        return self


class TableDeleteTable(_TableAddress):
    op: Literal["delete_table"]


class TableCloneTable(_TableAddress):
    op: Literal["clone_table"]
    count: int = Field(default=1, ge=1)


class TableInsertRowByClone(_TableAddress):
    op: Literal["insert_row_by_clone"]
    ref_row: int = Field(ge=0)
    count: int = Field(default=1, ge=1)


class TableInsertBlockByClone(_TableAddress):
    op: Literal["insert_block_by_clone"]
    ref_rows: tuple[int, int]
    count: int = Field(default=1, ge=1)


class TableSetColumnWidths(_TableAddress):
    op: Literal["set_column_widths"]
    widths: dict[int, int] | list[int]


class TableAutofitColumns(_TableAddress):
    op: Literal["autofit_columns"]
    min_frac: float = Field(default=0.06, gt=0, lt=1)
    damp: float = Field(default=0.5, gt=0, le=1)


class TableSetRowHeights(_TableAddress):
    op: Literal["set_row_heights"]
    heights: dict[int, int]


class TableSplitCellVertical(_TableAddress):
    op: Literal["split_cell_vertical"]
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    sizes: list[int] = Field(min_length=2)


class TableSetCellLineSpacing(_TableAddress):
    op: Literal["set_cell_line_spacing"]
    cells: list[tuple[int, int]] = Field(default_factory=list)
    rows: list[int] = Field(default_factory=list)
    line_spacing: int = Field(
        gt=0,
        validation_alias=AliasChoices("lineSpacing", "line_spacing"),
        serialization_alias="lineSpacing",
    )

    @model_validator(mode="after")
    def require_cells_or_rows(self) -> "TableSetCellLineSpacing":
        if not self.cells and not self.rows:
            raise ValueError("cells or rows is required")
        return self


TableOperationUnion: TypeAlias = Annotated[
    TableFillCell
    | TableDeleteColumn
    | TableDeleteRow
    | TableDeleteTable
    | TableCloneTable
    | TableInsertRowByClone
    | TableInsertBlockByClone
    | TableSetColumnWidths
    | TableAutofitColumns
    | TableSetRowHeights
    | TableSplitCellVertical
    | TableSetCellLineSpacing,
    Field(discriminator="op"),
]


class TableOperation(RootModel[TableOperationUnion]):
    @model_validator(mode="before")
    @classmethod
    def normalize_discriminator(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            payload = dict(value)
            raw = payload.get("op", payload.get("type"))
            if isinstance(raw, str):
                payload["op"] = raw.strip().replace("-", "_")
            payload.pop("type", None)
            return payload
        return value


class BodyReplaceText(_ClosedModel):
    op: Literal["replace_text"]
    find: str
    replace: str = ""
    count: int = Field(default=1, ge=1)


class BodyDeleteParagraph(_ClosedModel):
    op: Literal["delete_paragraph"]
    index: int = Field(ge=0)
    allow_tables: bool = False


class BodyInsertParagraphByClone(_ClosedModel):
    op: Literal["insert_paragraph_by_clone"]
    ref_index: int = Field(ge=0)
    count: int = Field(default=1, ge=1)
    texts: list[str] | None = None


class BodySetParagraphText(_ClosedModel):
    op: Literal["set_paragraph_text"]
    index: int = Field(ge=0)
    text: str


class BodyReorderParagraphs(_ClosedModel):
    op: Literal["reorder_paragraphs"]
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    order: list[int]


class BodyRestyleText(_ClosedModel):
    op: Literal["restyle_text"]
    find: str
    count: int = Field(default=1, ge=1)
    text_color: str | None = None
    drop_italic: bool = True


BodyOperationUnion: TypeAlias = Annotated[
    BodyReplaceText
    | BodyDeleteParagraph
    | BodyInsertParagraphByClone
    | BodySetParagraphText
    | BodyReorderParagraphs
    | BodyRestyleText,
    Field(discriminator="op"),
]


class BodyOperation(RootModel[BodyOperationUnion]):
    @model_validator(mode="before")
    @classmethod
    def normalize_discriminator(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            payload = dict(value)
            raw = payload.get("op", payload.get("type"))
            if isinstance(raw, str):
                payload["op"] = raw.strip().replace("-", "_")
            payload.pop("type", None)
            return payload
        return value


def operation_payloads(values: list[Any]) -> list[dict[str, Any]]:
    """Convert validated models or direct-call legacy dictionaries to core payloads."""

    payloads: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, RootModel):
            payloads.append(value.root.model_dump(by_alias=True, exclude_none=True))
        elif isinstance(value, BaseModel):
            payloads.append(value.model_dump(by_alias=True, exclude_none=True))
        elif isinstance(value, Mapping):
            payloads.append(dict(value))
        else:
            raise TypeError("mutation operations must be objects")
    return payloads


__all__ = ["BodyOperation", "EditOperation", "TableOperation", "operation_payloads"]
