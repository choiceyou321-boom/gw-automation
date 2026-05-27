"""세금계산서 도메인 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional


class InvoiceStatus(str, Enum):
    """세금계산서 발행 상태."""
    DRAFT = "draft"              # 작성 중 (미발행)
    PENDING = "pending"          # 발행 요청 후 처리 대기
    ISSUED = "issued"            # 발행 성공
    SENT = "sent"                # 국세청 전송 완료
    CANCELLED = "cancelled"      # 발행 취소
    FAILED = "failed"            # 발행 실패


class InvoiceType(str, Enum):
    """과세 구분."""
    TAXABLE = "01"      # 일반(과세)
    ZERO_RATE = "02"    # 영세율
    EXEMPT = "03"       # 면세


@dataclass
class TaxInvoiceLine:
    """세금계산서 품목 라인."""
    item_name: str               # 품목명
    unit: str = ""               # 단위 (예: EA, 식)
    quantity: float = 1.0
    unit_price: int = 0          # 단가 (원)
    supply_amount: int = 0       # 공급가액
    tax_amount: int = 0          # 세액
    note: str = ""

    def auto_calc(self, tax_rate: float = 0.1) -> None:
        """quantity * unit_price → supply_amount + tax_amount 자동 계산."""
        if self.supply_amount == 0 and self.unit_price > 0:
            self.supply_amount = int(self.quantity * self.unit_price)
        if self.tax_amount == 0 and self.supply_amount > 0:
            self.tax_amount = int(self.supply_amount * tax_rate)


@dataclass
class Party:
    """공급자 또는 공급받는자 정보."""
    business_number: str         # 사업자등록번호 (10자리)
    company_name: str            # 상호
    ceo_name: str = ""           # 대표자명
    address: str = ""
    business_type: str = ""      # 업태
    business_item: str = ""      # 종목
    email: str = ""
    contact_name: str = ""
    contact_phone: str = ""


@dataclass
class TaxInvoiceDraft:
    """세금계산서 발행 요청서 (외부 시스템 호출 전 작성된 데이터)."""
    supplier: Party                          # 공급자 (=우리 회사)
    buyer: Party                             # 공급받는자 (=거래처)
    issue_date: date                         # 작성일자
    invoice_type: InvoiceType = InvoiceType.TAXABLE
    lines: list[TaxInvoiceLine] = field(default_factory=list)
    purpose: str = ""                        # 영수/청구 구분 (영수/청구)
    remark: str = ""                         # 비고
    project_code: str = ""                   # 연결된 프로젝트 (GS-25-XXXX)
    document_no: str = ""                    # 내부 문서번호 (선택)

    @property
    def total_supply(self) -> int:
        return sum(l.supply_amount for l in self.lines)

    @property
    def total_tax(self) -> int:
        return sum(l.tax_amount for l in self.lines)

    @property
    def total_amount(self) -> int:
        return self.total_supply + self.total_tax

    def auto_calc_all(self, tax_rate: float = 0.1) -> None:
        for line in self.lines:
            line.auto_calc(tax_rate)


@dataclass
class TaxInvoiceResult:
    """Provider.issue() 반환값."""
    success: bool
    status: InvoiceStatus
    nts_id: str = ""                # 국세청 승인번호
    provider_id: str = ""           # 외부 시스템 식별자 (팝빌 mgtKey 등)
    error_message: str = ""
    raw_response: dict = field(default_factory=dict)


@dataclass
class TaxInvoiceRecord:
    """DB에 저장된 세금계산서 (Draft + Result + 메타)."""
    id: Optional[int] = None
    draft: Optional[TaxInvoiceDraft] = None
    result: Optional[TaxInvoiceResult] = None
    status: InvoiceStatus = InvoiceStatus.DRAFT
    owner_gw_id: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
