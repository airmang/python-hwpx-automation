# SPDX-License-Identifier: Apache-2.0
"""기안문(별지 제1·2호서식) 장르 합성 — 응용 계층 소유.

「행정업무의 운영 및 혁신에 관한 규정 시행규칙」(행정안전부령 제408호,
2023-06-28) 별지 제1호서식(일반기안문)·제2호서식(간이기안문)의 **공개 구조**를
일반 document-plan 블록으로 낮춘다(클린룸 — 상용 템플릿 파일을 복제하지 않는다).

규정에서 곧바로 오는 세 가지 계약이 이 모듈의 존재 이유다:

1. **결재란은 고정 칸이 아니다** — 규칙 제7조제4항 "서명 또는 '전결' 표시를
   하지 아니하는 사람의 서명란은 만들지 아니한다". 칸 수는 결재자 목록 길이다.
2. **결문 라벨 대부분은 인쇄하지 않는다** — 별지 제1호서식 비고: 행정기관명·
   발신명·기안자·검토자·결재권자·직위(직급) 서명·처리과명-일련번호(시행일)·
   도로명주소·홈페이지 주소·전자우편주소·공개 구분은 "표시하지 아니하고 그
   내용을 적는다". 반대로 시행·접수·우·협조자·전화번호·팩스번호는 표시한다.
3. **체크박스 개체를 쓰지 않는다** — 별표 4 제10호가 `[  ]`+√ 텍스트를 규정한다.

법령이 정하지 않는 것(본문 글꼴·글자 크기·행 높이 mm)은 여기서 값으로 주장하지
않는다. 판단(어떤 수신 형태인지, 전결인지)은 스킬이 하고, 이 모듈은 결정된
값을 규정 구조에 배치만 한다.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: 별지 제1호서식 비고 — 표시하지 않는 용어(값만 적는다).
HIDDEN_LABELS: tuple[str, ...] = (
    "행정기관명", "발신명", "기안자", "검토자", "결재권자", "직위(직급) 서명",
    "처리과명-연도별 일련번호(시행일)", "도로명주소", "홈페이지 주소",
    "공무원의 전자우편주소", "공개 구분",
)
#: 표시하는 라벨.
SHOWN_LABELS: tuple[str, ...] = (
    "수신", "(경유)", "제목", "붙임", "시행", "접수", "우", "협조자",
    "전화번호", "팩스번호",
)


class Approver(BaseModel):
    """결재란 한 칸 — 직위(직급)와 서명(성명).

    ``mark``는 전결/대결 표시(규칙 제7조제2·3항)로, 해당 권자의 서명란에 붙는다.
    서명도 전결 표시도 하지 않는 사람은 **애초에 목록에 넣지 않는다**(제7조제4항).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    position: str
    name: str = ""
    mark: Literal["", "전결", "대결"] = ""
    date: str = ""

    @field_validator("position")
    @classmethod
    def _position_required(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("approver position must be non-empty")
        return normalized

    def signature_cell(self) -> str:
        """서명 칸 텍스트 — 전결/대결 표시·날짜·성명을 줄로 쌓는다."""

        lines = [part for part in (f"{self.mark} {self.date}".strip(), self.name) if part]
        return "\n".join(lines)


class OfficialDraftPlan(BaseModel):
    """일반기안문(별지 제1호서식)의 값 집합."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agency: str
    subject: str
    recipient: str = "내부결재"
    via: str = ""
    body: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    sender: str = ""
    internal_only: bool = False
    seal: Literal["직인", "관인생략", "서명생략", "none"] = "none"
    approvers: list[Approver] = Field(default_factory=list)
    cooperators: list[str] = Field(default_factory=list)
    issued: str = ""
    received: str = ""
    postal_code: str = ""
    address: str = ""
    homepage: str = ""
    phone: str = ""
    fax: str = ""
    email: str = ""
    disclosure: str = "공개"

    @field_validator("agency", "subject")
    @classmethod
    def _required(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("agency and subject must be non-empty")
        return normalized

    @field_validator("approvers")
    @classmethod
    def _approvers_present(cls, value: list[Approver]) -> list[Approver]:
        if not value:
            raise ValueError(
                "approvers must list every person who signs or marks 전결 "
                "(규칙 제7조제4항: 서명하지 않는 사람의 서명란은 만들지 않는다)"
            )
        return value

    def to_document_plan_blocks(self) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = [
            {"type": "paragraph", "text": self.agency, "align": "center"},
            {"type": "paragraph", "text": f"수신  {self.recipient}"},
            {"type": "paragraph", "text": f"(경유)  {self.via}".rstrip()},
            {"type": "paragraph", "text": f"제목  {self.subject}"},
        ]
        blocks.extend({"type": "paragraph", "text": line} for line in self.body)
        blocks.extend(_attachment_blocks(self.attachments))

        if not self.internal_only and self.sender.strip():
            sender_text = self.sender.strip()
            if self.seal in {"관인생략", "서명생략"}:
                sender_text = f"{sender_text}    {self.seal}"
            blocks.append({"type": "paragraph", "text": sender_text, "align": "center"})

        blocks.append(_approval_table(self.approvers))
        blocks.append(self._footer_table())
        return blocks

    def _footer_table(self) -> dict[str, Any]:
        rows = [
            {"label": "협조자", "value": "  ".join(self.cooperators)},
            {
                "label": "시행",
                "value": f"{self.issued}    접수  {self.received}".rstrip(),
            },
            {
                "label": "우",
                "value": "  ".join(
                    part for part in (f"{self.postal_code} {self.address}".strip(), self.homepage) if part
                ),
            },
            {
                "label": "전화번호",
                "value": "  ".join(
                    part
                    for part in (
                        self.phone,
                        f"팩스번호 {self.fax}".strip() if self.fax else "",
                        self.email,
                        self.disclosure,
                    )
                    if part
                ),
            },
        ]
        return {
            "type": "table",
            "showHeader": False,
            "columns": [
                {"key": "label", "label": "구분", "widthWeight": 2},
                {"key": "value", "label": "내용", "widthWeight": 14},
            ],
            "rows": rows,
        }


class SimpleDraftPlan(BaseModel):
    """간이기안문(별지 제2호서식) — 내부결재 전용(규칙 제3조제3항).

    두문·발신명의·시행/접수·주소가 **없고**, 결재란이 오른쪽 상단에 온다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    issuer: str
    written_date: str
    summary: str = ""
    registration_number: str = ""
    registered_date: str = ""
    approved_date: str = ""
    disclosure: str = "공개"
    approvers: list[Approver] = Field(default_factory=list)
    cooperators: list[str] = Field(default_factory=list)

    @field_validator("title", "issuer", "written_date")
    @classmethod
    def _required(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("title, issuer and written_date must be non-empty")
        return normalized

    @field_validator("approvers")
    @classmethod
    def _approvers_present(cls, value: list[Approver]) -> list[Approver]:
        if not value:
            raise ValueError("approvers must list every signing person (규칙 제7조제4항)")
        return value

    def to_document_plan_blocks(self) -> list[dict[str, Any]]:
        registration = {
            "type": "table",
            "showHeader": False,
            "columns": [
                {"key": "label", "label": "구분", "widthWeight": 3},
                {"key": "value", "label": "값", "widthWeight": 4},
            ],
            "rows": [
                {"label": "생산등록번호", "value": self.registration_number},
                {"label": "등록일", "value": self.registered_date},
                {"label": "결재일", "value": self.approved_date},
                {"label": "공개 구분", "value": self.disclosure},
            ],
        }
        blocks: list[dict[str, Any]] = [
            registration,
            _approval_table(self.approvers),
        ]
        if self.cooperators:
            blocks.append(
                {"type": "paragraph", "text": f"협조자  {'  '.join(self.cooperators)}"}
            )
        blocks.append({"type": "paragraph", "text": self.title, "align": "center"})
        if self.summary.strip():
            blocks.append(
                {"type": "paragraph", "text": self.summary.strip(), "align": "center"}
            )
        blocks.append({"type": "paragraph", "text": self.written_date, "align": "center"})
        blocks.append({"type": "paragraph", "text": self.issuer, "align": "center"})
        return blocks


def _approval_table(approvers: list[Approver]) -> dict[str, Any]:
    """결재란 — 칸 수는 결재자 수(규칙 제7조제4항). 라벨 행은 만들지 않는다."""

    columns = []
    row: dict[str, str] = {}
    for index, approver in enumerate(approvers):
        position_key = f"pos{index}"
        signature_key = f"sig{index}"
        columns.append({"key": position_key, "label": f"직위{index}", "widthWeight": 3})
        columns.append({"key": signature_key, "label": f"서명{index}", "widthWeight": 4})
        row[position_key] = approver.position
        row[signature_key] = approver.signature_cell()
    return {"type": "table", "showHeader": False, "columns": columns, "rows": [row]}


def _attachment_blocks(attachments: list[str]) -> list[dict[str, Any]]:
    """붙임 + `끝.` — 규칙 제4조제5항의 본문/붙임 종결 규칙.

    붙임이 없으면 본문 끝에 `끝.`만 놓고, 1건이면 한 줄, 2건 이상이면 번호를
    붙여 항목화한다(마지막 항목 뒤에 `끝.`).
    """

    items = [item.strip() for item in attachments if item.strip()]
    if not items:
        return [{"type": "paragraph", "text": "끝."}]
    if len(items) == 1:
        return [{"type": "paragraph", "text": f"붙임  {items[0]}  끝."}]
    blocks = [{"type": "paragraph", "text": f"붙임  1. {items[0]}"}]
    for number, item in enumerate(items[1:], start=2):
        suffix = "  끝." if number == len(items) else ""
        blocks.append({"type": "paragraph", "text": f"      {number}. {item}{suffix}"})
    return blocks


def compose_official_draft(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """일반기안문 값 집합을 일반 document-plan 블록으로 낮춘다."""

    return OfficialDraftPlan.model_validate(plan).to_document_plan_blocks()


def compose_simple_draft(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """간이기안문 값 집합을 일반 document-plan 블록으로 낮춘다."""

    return SimpleDraftPlan.model_validate(plan).to_document_plan_blocks()


__all__ = [
    "HIDDEN_LABELS",
    "SHOWN_LABELS",
    "Approver",
    "OfficialDraftPlan",
    "SimpleDraftPlan",
    "compose_official_draft",
    "compose_simple_draft",
]
