"""
세금계산서 발행 Provider 인터페이스.

Provider 종류:
  - NoopTaxInvoiceProvider : 개발/테스트용 — 항상 성공으로 가짜 ID 반환
  - HometaxProvider        : 홈택스 직접 (향후 구현, Playwright + 공인인증서)
  - PopbillProvider        : 팝빌 API (향후 구현, REST + API Key)

선택 기준:
  - 공인인증서 기반 자동화 — HometaxProvider (느림, 정확)
  - 외부 SaaS API           — PopbillProvider (빠름, 비용 발생)
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Protocol

from src.office.tax_invoice.models import (
    TaxInvoiceDraft, TaxInvoiceResult, InvoiceStatus,
)

logger = logging.getLogger(__name__)


class ITaxInvoiceProvider(Protocol):
    """세금계산서 발행 어댑터 인터페이스."""

    name: str

    def issue(self, draft: TaxInvoiceDraft) -> TaxInvoiceResult:
        """draft → 외부 시스템 호출 → 발행 결과 반환."""
        ...

    def cancel(self, provider_id: str, reason: str = "") -> TaxInvoiceResult:
        """발행 취소."""
        ...

    def check_status(self, provider_id: str) -> InvoiceStatus:
        """현재 상태 조회 (전송 완료/대기 등)."""
        ...


class NoopTaxInvoiceProvider:
    """개발/테스트용 — 항상 ISSUED 상태로 가짜 ID 반환."""

    name = "Noop"

    def issue(self, draft: TaxInvoiceDraft) -> TaxInvoiceResult:
        nts_id = f"NTS-NOOP-{uuid.uuid4().hex[:10]}"
        logger.info(
            "[NoopTaxInvoiceProvider] issue %s → %s → %s원 (가짜 발행)",
            draft.supplier.company_name,
            draft.buyer.company_name,
            draft.total_amount,
        )
        return TaxInvoiceResult(
            success=True,
            status=InvoiceStatus.ISSUED,
            nts_id=nts_id,
            provider_id=f"noop:{uuid.uuid4().hex[:8]}",
            raw_response={"echo": "noop"},
        )

    def cancel(self, provider_id: str, reason: str = "") -> TaxInvoiceResult:
        logger.info("[NoopTaxInvoiceProvider] cancel %s (%s)", provider_id, reason)
        return TaxInvoiceResult(success=True, status=InvoiceStatus.CANCELLED, provider_id=provider_id)

    def check_status(self, provider_id: str) -> InvoiceStatus:
        return InvoiceStatus.SENT


class HometaxProvider:
    """
    홈택스 직접 발행 Provider (향후 구현).

    구현 시 필요 사항:
      - 공인인증서 (.pfx 파일) + 비밀번호
      - Playwright headless 모드
      - 홈택스 로그인 → 전자세금계산서 → 신규 발행 → 양식 입력 → 발행
    """

    name = "Hometax"

    def __init__(self, cert_path: str | None = None, cert_password: str | None = None) -> None:
        self.cert_path = cert_path or os.getenv("HOMETAX_CERT_PATH")
        self.cert_password = cert_password or os.getenv("HOMETAX_CERT_PASSWORD")

    def issue(self, draft: TaxInvoiceDraft) -> TaxInvoiceResult:
        raise NotImplementedError(
            "HometaxProvider.issue는 P8 후속 PR에서 구현. "
            "현재는 NoopTaxInvoiceProvider 사용."
        )

    def cancel(self, provider_id: str, reason: str = "") -> TaxInvoiceResult:
        raise NotImplementedError("HometaxProvider.cancel 미구현")

    def check_status(self, provider_id: str) -> InvoiceStatus:
        raise NotImplementedError("HometaxProvider.check_status 미구현")


class PopbillProvider:
    """
    팝빌 API Provider (향후 구현).

    구현 시 필요 사항:
      - POPBILL_LINK_ID, POPBILL_SECRET_KEY 환경 변수
      - popbill SDK (pip install popbill)
      - 사업자번호 + mgtKey 관리
    """

    name = "Popbill"

    def __init__(self, link_id: str | None = None, secret_key: str | None = None) -> None:
        self.link_id = link_id or os.getenv("POPBILL_LINK_ID")
        self.secret_key = secret_key or os.getenv("POPBILL_SECRET_KEY")

    def issue(self, draft: TaxInvoiceDraft) -> TaxInvoiceResult:
        raise NotImplementedError(
            "PopbillProvider.issue는 P8 후속 PR에서 구현."
        )

    def cancel(self, provider_id: str, reason: str = "") -> TaxInvoiceResult:
        raise NotImplementedError("PopbillProvider.cancel 미구현")

    def check_status(self, provider_id: str) -> InvoiceStatus:
        raise NotImplementedError("PopbillProvider.check_status 미구현")


def get_default_provider() -> ITaxInvoiceProvider:
    """
    환경 변수 TAX_INVOICE_PROVIDER에 따라 Provider 선택.

    값:
      - "popbill" → PopbillProvider
      - "hometax" → HometaxProvider
      - 그 외/미설정 → NoopTaxInvoiceProvider
    """
    choice = (os.getenv("TAX_INVOICE_PROVIDER") or "").lower()
    if choice == "popbill":
        return PopbillProvider()
    if choice == "hometax":
        return HometaxProvider()
    return NoopTaxInvoiceProvider()
