# SPDX-License-Identifier: Apache-2.0
"""MCP Resource 직렬화 모델."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class ResourceModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


class ParagraphResourceEntry(ResourceModel):
    paragraph_index: int = Field(alias="paragraphIndex")
    text: str


class TableResourceEntry(ResourceModel):
    table_index: int = Field(alias="tableIndex")
    row_count: int = Field(alias="rowCount")
    column_count: int = Field(alias="columnCount")


class DocumentMetadataResource(ResourceModel):
    handle_id: str = Field(alias="handleId")
    locator: Dict[str, Any]
    meta: Dict[str, Any]
    section_count: int = Field(alias="sectionCount")
    paragraph_count: int = Field(alias="paragraphCount")
    header_count: int = Field(alias="headerCount")


class DocumentParagraphsResource(ResourceModel):
    handle_id: str = Field(alias="handleId")
    paragraphs: List[ParagraphResourceEntry]


class DocumentTablesResource(ResourceModel):
    handle_id: str = Field(alias="handleId")
    tables: List[TableResourceEntry]
