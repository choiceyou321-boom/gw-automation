"""tax_invoice 모듈 단위 테스트."""

from __future__ import annotations

from datetime import date

import pytest

from src.office.tax_invoice import db, service
from src.office.tax_invoice.models import (
    InvoiceStatus,
    InvoiceType,
    Party,
    TaxInvoiceDraft,
    TaxInvoiceLine,
)
from src.office.tax_invoice.provider import (
    NoopTaxInvoiceProvider,
    HometaxProvider,
    PopbillProvider,
    get_default_provider,
)
from src.office.tax_invoice.service import TaxInvoiceValidationError


# ─────────── fixtures ───────────


@pytest.fixture
def tax_db_path(tmp_path, monkeypatch):
    path = tmp_path / "test_tax.db"
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", path)
    return path


@pytest.fixture
def glow_supplier():
    return Party(
        business_number="123-45-67890",
        company_name="주식회사 글로우서울",
        ceo_name="유정수",
        address="서울특별시 용산구 이태원동 164-2",
        business_type="건설업",
        business_item="인테리어",
        email="finance@glowseoul.co.kr",
    )


@pytest.fixture
def sample_buyer():
    return Party(
        business_number="987-65-43210",
        company_name="㈜메디빌더",
        ceo_name="김메디",
        business_type="의료업",
    )


@pytest.fixture
def sample_draft(glow_supplier, sample_buyer):
    return TaxInvoiceDraft(
        supplier=glow_supplier,
        buyer=sample_buyer,
        issue_date=date(2026, 5, 26),
        invoice_type=InvoiceType.TAXABLE,
        lines=[
            TaxInvoiceLine(item_name="EHP&환기공조 1차 중도금", quantity=1, unit_price=123_000_000),
        ],
        purpose="청구",
        project_code="GS-25-0088",
    )


# ─────────── models ───────────


def test_auto_calc_line():
    line = TaxInvoiceLine(item_name="공사", quantity=2, unit_price=1_000_000)
    line.auto_calc()
    assert line.supply_amount == 2_000_000
    assert line.tax_amount == 200_000


def test_draft_totals(sample_draft):
    sample_draft.auto_calc_all()
    assert sample_draft.total_supply == 123_000_000
    assert sample_draft.total_tax == 12_300_000
    assert sample_draft.total_amount == 135_300_000


# ─────────── validation ───────────


def test_validate_missing_supplier_name(glow_supplier, sample_buyer):
    glow_supplier.company_name = ""
    draft = TaxInvoiceDraft(
        supplier=glow_supplier, buyer=sample_buyer,
        issue_date=date.today(),
        lines=[TaxInvoiceLine(item_name="X", quantity=1, unit_price=1000)],
    )
    with pytest.raises(TaxInvoiceValidationError, match="공급자 상호"):
        service.issue_invoice(draft)


def test_validate_bad_business_number(glow_supplier, sample_buyer):
    glow_supplier.business_number = "INVALID"
    draft = TaxInvoiceDraft(
        supplier=glow_supplier, buyer=sample_buyer,
        issue_date=date.today(),
        lines=[TaxInvoiceLine(item_name="X", quantity=1, unit_price=1000)],
    )
    with pytest.raises(TaxInvoiceValidationError, match="사업자등록번호 형식"):
        service.issue_invoice(draft)


def test_validate_no_lines(glow_supplier, sample_buyer):
    draft = TaxInvoiceDraft(
        supplier=glow_supplier, buyer=sample_buyer,
        issue_date=date.today(),
        lines=[],
    )
    with pytest.raises(TaxInvoiceValidationError, match="품목 라인 0건"):
        service.issue_invoice(draft)


def test_validate_zero_amount(glow_supplier, sample_buyer):
    draft = TaxInvoiceDraft(
        supplier=glow_supplier, buyer=sample_buyer,
        issue_date=date.today(),
        lines=[TaxInvoiceLine(item_name="X", quantity=1, unit_price=0)],
    )
    with pytest.raises(TaxInvoiceValidationError, match="합계금액"):
        service.issue_invoice(draft)


def test_validate_accepts_10digit_biz_no(glow_supplier, sample_buyer):
    """하이픈 없는 10자리도 허용."""
    glow_supplier.business_number = "1234567890"
    sample_buyer.business_number = "0987654321"
    draft = TaxInvoiceDraft(
        supplier=glow_supplier, buyer=sample_buyer,
        issue_date=date.today(),
        lines=[TaxInvoiceLine(item_name="X", quantity=1, unit_price=1_000_000)],
    )
    # 검증 통과해야 함 (Noop provider가 발행)
    record = service.issue_invoice(draft)
    assert record.status == InvoiceStatus.ISSUED


# ─────────── provider ───────────


def test_noop_provider_issue(sample_draft):
    sample_draft.auto_calc_all()
    result = NoopTaxInvoiceProvider().issue(sample_draft)
    assert result.success
    assert result.status == InvoiceStatus.ISSUED
    assert result.nts_id.startswith("NTS-NOOP-")


def test_noop_provider_cancel():
    result = NoopTaxInvoiceProvider().cancel("noop:abc", reason="고객 요청")
    assert result.success
    assert result.status == InvoiceStatus.CANCELLED


def test_hometax_provider_raises_not_implemented(sample_draft):
    with pytest.raises(NotImplementedError):
        HometaxProvider().issue(sample_draft)


def test_popbill_provider_raises_not_implemented(sample_draft):
    with pytest.raises(NotImplementedError):
        PopbillProvider().issue(sample_draft)


def test_get_default_provider_noop(monkeypatch):
    monkeypatch.delenv("TAX_INVOICE_PROVIDER", raising=False)
    assert isinstance(get_default_provider(), NoopTaxInvoiceProvider)


def test_get_default_provider_popbill(monkeypatch):
    monkeypatch.setenv("TAX_INVOICE_PROVIDER", "popbill")
    assert isinstance(get_default_provider(), PopbillProvider)


def test_get_default_provider_hometax(monkeypatch):
    monkeypatch.setenv("TAX_INVOICE_PROVIDER", "hometax")
    assert isinstance(get_default_provider(), HometaxProvider)


# ─────────── service ───────────


def test_issue_invoice_persists(tax_db_path, sample_draft):
    record = service.issue_invoice(sample_draft, owner_gw_id="tgjeon")
    assert record.id is not None
    assert record.status == InvoiceStatus.ISSUED
    assert record.result.nts_id.startswith("NTS-NOOP-")

    fetched = service.get_invoice(record.id)
    assert fetched is not None
    assert fetched.owner_gw_id == "tgjeon"
    assert fetched.draft.total_amount == 135_300_000


def test_list_invoices_filter(tax_db_path, sample_draft, glow_supplier, sample_buyer):
    service.issue_invoice(sample_draft, owner_gw_id="tgjeon")
    other = TaxInvoiceDraft(
        supplier=glow_supplier, buyer=sample_buyer,
        issue_date=date.today(),
        lines=[TaxInvoiceLine(item_name="다른 거", quantity=1, unit_price=5_000_000)],
        project_code="GS-25-0030",
    )
    service.issue_invoice(other, owner_gw_id="tgjeon")

    by_owner = service.list_invoices(owner_gw_id="tgjeon")
    assert len(by_owner) == 2

    by_project = service.list_invoices(project_code="GS-25-0088")
    assert len(by_project) == 1
    assert by_project[0].draft.project_code == "GS-25-0088"


def test_provider_exception_persists_failed_status(tax_db_path, sample_draft):
    """Provider.issue가 RuntimeError 던지면 DB에 FAILED로 기록."""

    class BoomProvider:
        name = "Boom"

        def issue(self, draft):
            raise RuntimeError("외부 시스템 다운")

        def cancel(self, provider_id, reason=""):
            return None

        def check_status(self, provider_id):
            return InvoiceStatus.FAILED

    record = service.issue_invoice(sample_draft, provider=BoomProvider())
    assert record.status == InvoiceStatus.FAILED
    assert "외부 시스템 다운" in (record.result.error_message or "")


def test_cancel_invoice(tax_db_path, sample_draft):
    record = service.issue_invoice(sample_draft, owner_gw_id="tgjeon")
    cancelled = service.cancel_invoice(record.id, reason="테스트")
    assert cancelled is not None
    assert cancelled.status == InvoiceStatus.CANCELLED


def test_cancel_invoice_nonexistent(tax_db_path):
    assert service.cancel_invoice(999999) is None


def test_draft_roundtrip_through_db(tax_db_path, sample_draft):
    """Draft → DB JSON → Draft 복원이 동일한 데이터인지."""
    record = service.issue_invoice(sample_draft, owner_gw_id="tgjeon")
    fetched = service.get_invoice(record.id)
    assert fetched.draft.supplier.business_number == sample_draft.supplier.business_number
    assert fetched.draft.buyer.business_number == sample_draft.buyer.business_number
    assert fetched.draft.invoice_type == InvoiceType.TAXABLE
    assert len(fetched.draft.lines) == 1
    assert fetched.draft.lines[0].item_name == "EHP&환기공조 1차 중도금"
    assert fetched.draft.project_code == "GS-25-0088"
