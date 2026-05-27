"""
Office 도메인(CRM·세금계산서) 챗봇 핸들러 — 분리 계획 v4 A 트랙.

도구:
  save_contact_from_image  — 명함 이미지 OCR → 연락처 등록
  list_contacts            — 연락처 목록 조회
  issue_tax_invoice        — 세금계산서 발행 (Noop/Hometax/Popbill)
  list_tax_invoices        — 발행 기록 조회
  cancel_tax_invoice       — 발행 취소

handlers/_impl.py의 안전한 호출 패턴을 따른다(예외 처리 + 한국어 메시지).
"""

from __future__ import annotations

import logging
import traceback
from datetime import date
from pathlib import Path
from typing import Any

from src.office.crm import service as crm_service
from src.office.tax_invoice import service as tax_service
from src.office.tax_invoice.models import (
    InvoiceStatus,
    InvoiceType,
    Party,
    TaxInvoiceDraft,
    TaxInvoiceLine,
)

logger = logging.getLogger("handlers.office")


# ─────────── 공통 유틸 ───────────


def _user_id_from(ctx: dict | None) -> str:
    if not ctx:
        return ""
    return ctx.get("gw_id") or ctx.get("user_id") or ""


def _format_contact(contact) -> str:
    """Contact dataclass → 사용자 표시용 한국어 라인."""
    parts = [contact.name or "(이름 없음)"]
    if contact.title:
        parts.append(contact.title)
    if contact.company:
        parts.append(f"@ {contact.company}")
    line = " ".join(parts)
    extras = []
    if contact.phone_mobile:
        extras.append(f"📱 {contact.phone_mobile}")
    if contact.email:
        extras.append(f"✉️ {contact.email}")
    extras_text = " · ".join(extras)
    return f"• {line}" + (f"\n   {extras_text}" if extras_text else "")


# ─────────── 핸들러 ───────────


def handle_save_contact_from_image(
    params: dict, user_context: dict | None = None
) -> str:
    """
    명함 사진을 OCR 처리해 CRM에 등록한다.

    Args:
        params:
            image_path (str, required) — 업로드된 명함 이미지 경로
            tags (list[str], optional) — ["거래처", "VIP"]
            project_codes (list[str], optional) — ["GS-25-0088"]
            note (str, optional) — 사용자 메모
    """
    image_path = (params or {}).get("image_path", "").strip()
    if not image_path:
        return "❌ image_path가 비어 있습니다. 명함 이미지 파일 경로가 필요합니다."

    if not Path(image_path).exists():
        return f"❌ 이미지 파일을 찾을 수 없습니다: {image_path}"

    try:
        contact = crm_service.save_contact_from_image(
            image_path,
            owner_gw_id=_user_id_from(user_context),
            tags=params.get("tags") or [],
            project_codes=params.get("project_codes") or [],
            note=params.get("note") or "",
        )
    except FileNotFoundError as e:
        return f"❌ {e}"
    except Exception as e:
        logger.error("save_contact_from_image 실패: %s\n%s", e, traceback.format_exc())
        return f"❌ 명함 등록 실패: {e}"

    lines = [
        "✅ 명함이 CRM에 등록되었습니다.",
        f"   ID: {contact.id}",
        _format_contact(contact),
    ]
    if contact.google_resource_name:
        lines.append(f"   Google Contacts: {contact.google_resource_name}")
    return "\n".join(lines)


def handle_list_contacts(
    params: dict, user_context: dict | None = None
) -> str:
    """
    CRM에 등록된 연락처 목록을 조회한다.

    Args:
        params:
            company (str, optional) — 회사명 부분 일치
            mine_only (bool, optional) — true면 본인 등록분만
            limit (int, optional) — 기본 20
    """
    params = params or {}
    owner = _user_id_from(user_context) if params.get("mine_only") else None
    try:
        contacts = crm_service.list_contacts(
            owner_gw_id=owner,
            company=params.get("company") or None,
            limit=int(params.get("limit") or 20),
        )
    except Exception as e:
        logger.error("list_contacts 실패: %s", e)
        return f"❌ 연락처 조회 실패: {e}"

    if not contacts:
        return "📒 조건에 맞는 연락처가 없습니다."

    header = f"📒 연락처 {len(contacts)}건"
    return header + "\n\n" + "\n".join(_format_contact(c) for c in contacts)


# ─────────── 세금계산서 ───────────


def _party_from_dict(d: dict | None) -> Party:
    d = d or {}
    return Party(
        business_number=str(d.get("business_number") or "").strip(),
        company_name=str(d.get("company_name") or "").strip(),
        ceo_name=str(d.get("ceo_name") or "").strip(),
        address=str(d.get("address") or "").strip(),
        business_type=str(d.get("business_type") or "").strip(),
        business_item=str(d.get("business_item") or "").strip(),
        email=str(d.get("email") or "").strip(),
        contact_name=str(d.get("contact_name") or "").strip(),
        contact_phone=str(d.get("contact_phone") or "").strip(),
    )


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    s = str(value or "").strip()
    if not s:
        return date.today()
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise ValueError(f"날짜 형식 오류 (YYYY-MM-DD 필요): {value!r}")


def _line_from_dict(d: dict) -> TaxInvoiceLine:
    return TaxInvoiceLine(
        item_name=str(d.get("item_name") or "").strip() or "(품목 없음)",
        unit=str(d.get("unit") or "").strip(),
        quantity=float(d.get("quantity") or 1),
        unit_price=int(d.get("unit_price") or 0),
        supply_amount=int(d.get("supply_amount") or 0),
        tax_amount=int(d.get("tax_amount") or 0),
        note=str(d.get("note") or "").strip(),
    )


def handle_issue_tax_invoice(
    params: dict, user_context: dict | None = None
) -> str:
    """
    세금계산서를 발행한다 (Provider는 환경변수로 결정, 미설정 시 Noop).

    Args:
        params:
            supplier (dict, required) — Party 키 (business_number, company_name, ...)
            buyer (dict, required)    — Party 키
            issue_date (str)          — YYYY-MM-DD (미입력 시 오늘)
            lines (list[dict])        — 품목 라인 (item_name/quantity/unit_price 등)
            invoice_type (str)        — taxable | zero_rate | exempt (기본 taxable)
            purpose (str)             — 영수/청구
            remark (str)              — 비고
            project_code (str)        — GS-25-XXXX
            document_no (str)         — 내부 문서번호
    """
    params = params or {}
    try:
        supplier = _party_from_dict(params.get("supplier"))
        buyer = _party_from_dict(params.get("buyer"))
        issue_d = _parse_date(params.get("issue_date"))
        lines_raw = params.get("lines") or []
        if not isinstance(lines_raw, list):
            return "❌ lines는 리스트여야 합니다."
        lines = [_line_from_dict(l) for l in lines_raw if isinstance(l, dict)]
        inv_type_str = (params.get("invoice_type") or "taxable").lower()
        inv_type_map = {
            "taxable": InvoiceType.TAXABLE,
            "zero_rate": InvoiceType.ZERO_RATE,
            "exempt": InvoiceType.EXEMPT,
        }
        invoice_type = inv_type_map.get(inv_type_str, InvoiceType.TAXABLE)
        draft = TaxInvoiceDraft(
            supplier=supplier,
            buyer=buyer,
            issue_date=issue_d,
            invoice_type=invoice_type,
            lines=lines,
            purpose=str(params.get("purpose") or "").strip(),
            remark=str(params.get("remark") or "").strip(),
            project_code=str(params.get("project_code") or "").strip(),
            document_no=str(params.get("document_no") or "").strip(),
        )
    except Exception as e:
        return f"❌ 발행 요청서 작성 실패: {e}"

    try:
        record = tax_service.issue_invoice(
            draft, owner_gw_id=_user_id_from(user_context)
        )
    except tax_service.TaxInvoiceValidationError as e:
        return f"❌ 검증 실패: {e}"
    except NotImplementedError:
        return "❌ 선택된 Provider가 아직 구현되지 않았습니다. TAX_INVOICE_PROVIDER 환경 변수를 확인하세요."
    except Exception as e:
        logger.error("issue_tax_invoice 실패: %s\n%s", e, traceback.format_exc())
        return f"❌ 발행 실패: {e}"

    status_label = {
        InvoiceStatus.ISSUED: "✅ 발행 완료",
        InvoiceStatus.PENDING: "⏳ 발행 대기",
        InvoiceStatus.SENT: "✅ 전송 완료",
        InvoiceStatus.FAILED: "❌ 발행 실패",
        InvoiceStatus.CANCELLED: "🚫 취소됨",
    }.get(record.status, f"({record.status.value})")
    lines_out = [
        f"{status_label} — 세금계산서 #{record.id}",
        f"   공급자: {draft.supplier.company_name} ({draft.supplier.business_number})",
        f"   공급받는자: {draft.buyer.company_name} ({draft.buyer.business_number})",
        f"   공급가액: {draft.total_supply:,}원",
        f"   부가세:   {draft.total_tax:,}원",
        f"   합계:     {draft.total_amount:,}원",
    ]
    if record.result and record.result.nts_id:
        lines_out.append(f"   국세청 승인번호: {record.result.nts_id}")
    if record.result and record.result.error_message:
        lines_out.append(f"   오류: {record.result.error_message}")
    return "\n".join(lines_out)


def handle_list_tax_invoices(
    params: dict, user_context: dict | None = None
) -> str:
    """
    발행된 세금계산서 목록을 조회한다.

    Args:
        params:
            mine_only (bool, optional)
            project_code (str, optional)
            status (str, optional) — draft | pending | issued | sent | cancelled | failed
            limit (int, optional) — 기본 20
    """
    params = params or {}
    owner = _user_id_from(user_context) if params.get("mine_only") else None
    status_str = (params.get("status") or "").strip().lower()
    status = None
    if status_str:
        try:
            status = InvoiceStatus(status_str)
        except ValueError:
            return f"❌ 잘못된 상태: {status_str!r} (가능: draft/pending/issued/sent/cancelled/failed)"

    try:
        records = tax_service.list_invoices(
            owner_gw_id=owner,
            project_code=params.get("project_code") or None,
            status=status,
            limit=int(params.get("limit") or 20),
        )
    except Exception as e:
        logger.error("list_tax_invoices 실패: %s", e)
        return f"❌ 조회 실패: {e}"

    if not records:
        return "📋 조건에 맞는 세금계산서가 없습니다."

    out = [f"📋 세금계산서 {len(records)}건"]
    for r in records:
        d = r.draft
        if not d:
            continue
        out.append(
            f"• #{r.id} [{r.status.value}] {d.issue_date.isoformat()} "
            f"{d.buyer.company_name} {d.total_amount:,}원 "
            f"(프로젝트: {d.project_code or '-'})"
        )
    return "\n".join(out)


def handle_cancel_tax_invoice(
    params: dict, user_context: dict | None = None
) -> str:
    """세금계산서 발행 취소.

    Args:
        params:
            invoice_id (int, required)
            reason (str, optional)
    """
    params = params or {}
    invoice_id = params.get("invoice_id")
    if not invoice_id:
        return "❌ invoice_id가 필요합니다."
    try:
        record = tax_service.cancel_invoice(int(invoice_id), reason=str(params.get("reason") or ""))
    except Exception as e:
        logger.error("cancel_tax_invoice 실패: %s", e)
        return f"❌ 취소 실패: {e}"
    if not record:
        return f"❌ 해당 ID의 세금계산서가 없습니다: {invoice_id}"
    if record.status == InvoiceStatus.CANCELLED:
        return f"🚫 세금계산서 #{record.id} 취소 완료"
    return f"⚠️ 취소 시도 후 상태: {record.status.value}"


# ─────────── 도구 등록 매핑 ───────────


TOOLS: dict[str, callable] = {
    "save_contact_from_image": handle_save_contact_from_image,
    "list_contacts": handle_list_contacts,
    "issue_tax_invoice": handle_issue_tax_invoice,
    "list_tax_invoices": handle_list_tax_invoices,
    "cancel_tax_invoice": handle_cancel_tax_invoice,
}

__all__ = [
    "handle_save_contact_from_image",
    "handle_list_contacts",
    "handle_issue_tax_invoice",
    "handle_list_tax_invoices",
    "handle_cancel_tax_invoice",
    "TOOLS",
]
