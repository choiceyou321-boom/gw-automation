"""
tax_invoice 통합 서비스 — Draft 검증 + Provider 호출 + DB 저장.

진입점:
    issue_invoice(draft, owner_gw_id, provider) → TaxInvoiceRecord
    get_invoice(id) → TaxInvoiceRecord
    list_invoices(owner_gw_id, ...) → list[TaxInvoiceRecord]
    cancel_invoice(id, reason) → TaxInvoiceRecord
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from src.office.tax_invoice import db
from src.office.tax_invoice.models import (
    InvoiceStatus,
    TaxInvoiceDraft,
    TaxInvoiceRecord,
)
from src.office.tax_invoice.provider import (
    ITaxInvoiceProvider,
    get_default_provider,
)

logger = logging.getLogger(__name__)


_BIZ_NO_RE = re.compile(r"^\d{3}-\d{2}-\d{5}$|^\d{10}$")


class TaxInvoiceValidationError(ValueError):
    """발행 요청서 검증 실패."""


def _validate_draft(draft: TaxInvoiceDraft) -> None:
    """검증 — Provider 호출 전 최소 보장."""
    if not draft.supplier.company_name:
        raise TaxInvoiceValidationError("공급자 상호 없음")
    if not _BIZ_NO_RE.match(draft.supplier.business_number):
        raise TaxInvoiceValidationError(
            f"공급자 사업자등록번호 형식 오류: {draft.supplier.business_number!r}"
        )
    if not draft.buyer.company_name:
        raise TaxInvoiceValidationError("공급받는자 상호 없음")
    if not _BIZ_NO_RE.match(draft.buyer.business_number):
        raise TaxInvoiceValidationError(
            f"공급받는자 사업자등록번호 형식 오류: {draft.buyer.business_number!r}"
        )
    if not draft.lines:
        raise TaxInvoiceValidationError("품목 라인 0건 (최소 1건 필요)")
    if draft.total_amount <= 0:
        raise TaxInvoiceValidationError(
            f"합계금액 0 이하: total={draft.total_amount}"
        )


def issue_invoice(
    draft: TaxInvoiceDraft,
    owner_gw_id: str = "",
    provider: Optional[ITaxInvoiceProvider] = None,
) -> TaxInvoiceRecord:
    """
    Draft → 검증 → Provider 호출 → DB 저장 → TaxInvoiceRecord 반환.

    실패한 경우에도 DB에는 status=FAILED로 기록되어 추적 가능.
    """
    draft.auto_calc_all()
    _validate_draft(draft)

    provider = provider or get_default_provider()
    provider_name = getattr(provider, "name", provider.__class__.__name__)

    try:
        result = provider.issue(draft)
    except NotImplementedError as e:
        logger.error(f"Provider.issue 미구현: {provider_name}")
        raise
    except Exception as e:
        logger.error(f"Provider.issue 실패 ({provider_name}): {e}")
        # 실패도 DB에 기록
        from src.office.tax_invoice.models import TaxInvoiceResult
        failed_result = TaxInvoiceResult(
            success=False,
            status=InvoiceStatus.FAILED,
            error_message=str(e),
        )
        invoice_id = db.insert_invoice(
            draft, failed_result, owner_gw_id=owner_gw_id, provider_name=provider_name,
        )
        record = db.get_invoice(invoice_id)
        return record  # type: ignore[return-value]

    invoice_id = db.insert_invoice(
        draft, result, owner_gw_id=owner_gw_id, provider_name=provider_name,
    )
    record = db.get_invoice(invoice_id)
    if not record:
        raise RuntimeError(f"insert 직후 get_invoice({invoice_id}) 실패")
    return record


def get_invoice(invoice_id: int) -> Optional[TaxInvoiceRecord]:
    return db.get_invoice(invoice_id)


def list_invoices(
    owner_gw_id: Optional[str] = None,
    project_code: Optional[str] = None,
    status: Optional[InvoiceStatus] = None,
    limit: int = 100,
) -> list[TaxInvoiceRecord]:
    return db.list_invoices(
        owner_gw_id=owner_gw_id,
        project_code=project_code,
        status=status,
        limit=limit,
    )


def cancel_invoice(
    invoice_id: int,
    reason: str = "",
    provider: Optional[ITaxInvoiceProvider] = None,
) -> Optional[TaxInvoiceRecord]:
    """발행된 세금계산서 취소."""
    record = db.get_invoice(invoice_id)
    if not record or not record.result:
        return None
    if record.status == InvoiceStatus.CANCELLED:
        return record  # 이미 취소

    provider = provider or get_default_provider()
    try:
        result = provider.cancel(record.result.provider_id, reason)
        db.update_invoice_status(
            invoice_id,
            status=InvoiceStatus.CANCELLED if result.success else InvoiceStatus.FAILED,
            error_message=result.error_message,
        )
    except NotImplementedError:
        logger.warning(f"Provider.cancel 미구현 — DB만 CANCELLED 처리")
        db.update_invoice_status(invoice_id, status=InvoiceStatus.CANCELLED)
    return db.get_invoice(invoice_id)
