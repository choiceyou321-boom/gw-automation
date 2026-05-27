"""
tax_invoice — 홈택스 전자세금계산서 발행 자동화.

흐름:
    매출 → TaxInvoiceDraft 생성
    → ITaxInvoiceProvider.issue() → 외부 발행
    → DB에 result 기록 (status, NTS ID)

Provider:
    NoopTaxInvoiceProvider — 개발/테스트용 (실제 발행 안 함)
    HometaxProvider       — 실제 홈택스 API (향후 구현)
    PopbillProvider       — 팝빌 API (외부 SaaS, 향후 구현)
"""

from src.office.tax_invoice.models import (
    TaxInvoiceDraft,
    TaxInvoiceLine,
    TaxInvoiceResult,
    TaxInvoiceRecord,
    InvoiceStatus,
)
from src.office.tax_invoice.provider import (
    ITaxInvoiceProvider,
    NoopTaxInvoiceProvider,
    HometaxProvider,
    PopbillProvider,
    get_default_provider,
)
from src.office.tax_invoice.service import (
    issue_invoice,
    get_invoice,
    list_invoices,
    cancel_invoice,
)

__all__ = [
    "TaxInvoiceDraft", "TaxInvoiceLine", "TaxInvoiceResult",
    "TaxInvoiceRecord", "InvoiceStatus",
    "ITaxInvoiceProvider", "NoopTaxInvoiceProvider",
    "HometaxProvider", "PopbillProvider", "get_default_provider",
    "issue_invoice", "get_invoice", "list_invoices", "cancel_invoice",
]
