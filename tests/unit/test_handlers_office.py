"""handlers/office.py 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.chatbot.handlers import office
from src.office.crm import db as crm_db
from src.office.crm.models import BusinessCard
from src.office.tax_invoice import db as tax_db


@pytest.fixture
def crm_db_path(tmp_path, monkeypatch):
    path = tmp_path / "crm.db"
    monkeypatch.setattr(crm_db, "DEFAULT_DB_PATH", path)
    return path


@pytest.fixture
def tax_db_path(tmp_path, monkeypatch):
    path = tmp_path / "tax.db"
    monkeypatch.setattr(tax_db, "DEFAULT_DB_PATH", path)
    return path


# ─────────── save_contact_from_image ───────────


def test_save_contact_missing_image_path():
    result = office.handle_save_contact_from_image({})
    assert "image_path" in result and result.startswith("❌")


def test_save_contact_nonexistent_file():
    result = office.handle_save_contact_from_image({"image_path": "/no/such.jpg"})
    assert result.startswith("❌")


def test_save_contact_success(crm_db_path, tmp_path, monkeypatch):
    """OCR mock으로 명함 등록 성공 경로."""
    fake_card = BusinessCard(
        name="홍길동",
        company="㈜글로우서울",
        title="과장",
        phone_mobile="010-1234-5678",
        email="gildong@glowseoul.co.kr",
    )

    monkeypatch.setattr(
        "src.office.crm.service.extract_from_image",
        lambda path: fake_card,
    )

    img = tmp_path / "card.jpg"
    img.write_bytes(b"fake")
    result = office.handle_save_contact_from_image(
        {"image_path": str(img), "tags": ["거래처"]},
        user_context={"gw_id": "tgjeon"},
    )
    assert "✅" in result
    assert "홍길동" in result
    assert "㈜글로우서울" in result


# ─────────── list_contacts ───────────


def test_list_contacts_empty(crm_db_path):
    assert "없습니다" in office.handle_list_contacts({})


def test_list_contacts_with_data(crm_db_path):
    crm_db.insert_contact(
        BusinessCard(name="홍길동", company="㈜글로우서울", phone_mobile="010-1111-2222"),
        owner_gw_id="tgjeon",
    )
    crm_db.insert_contact(
        BusinessCard(name="다른사람", company="다른회사", email="x@x.com"),
        owner_gw_id="shyang",
    )
    result = office.handle_list_contacts({"limit": 10})
    assert "2건" in result
    assert "홍길동" in result
    assert "다른사람" in result


def test_list_contacts_mine_only(crm_db_path):
    crm_db.insert_contact(
        BusinessCard(name="홍길동", phone_mobile="010-1111-2222"),
        owner_gw_id="tgjeon",
    )
    crm_db.insert_contact(
        BusinessCard(name="다른사람", email="x@x.com"),
        owner_gw_id="shyang",
    )
    result = office.handle_list_contacts(
        {"mine_only": True},
        user_context={"gw_id": "tgjeon"},
    )
    assert "1건" in result
    assert "홍길동" in result
    assert "다른사람" not in result


# ─────────── issue_tax_invoice ───────────


def _valid_invoice_params(**overrides):
    base = {
        "supplier": {
            "business_number": "123-45-67890",
            "company_name": "㈜글로우서울",
        },
        "buyer": {
            "business_number": "987-65-43210",
            "company_name": "㈜메디빌더",
        },
        "issue_date": "2026-05-26",
        "lines": [
            {"item_name": "공사 1차", "quantity": 1, "unit_price": 1_000_000},
        ],
        "project_code": "GS-25-0088",
    }
    base.update(overrides)
    return base


def test_issue_tax_invoice_success(tax_db_path):
    result = office.handle_issue_tax_invoice(
        _valid_invoice_params(),
        user_context={"gw_id": "tgjeon"},
    )
    assert "발행 완료" in result
    assert "1,000,000" in result  # 공급가액
    assert "100,000" in result    # 부가세
    assert "GS-25-0088" not in result  # project_code는 노출 안 함, 별도 list에서만
    assert "NTS-NOOP-" in result


def test_issue_tax_invoice_invalid_biz_no(tax_db_path):
    params = _valid_invoice_params()
    params["supplier"]["business_number"] = "INVALID"
    result = office.handle_issue_tax_invoice(params)
    assert result.startswith("❌")
    assert "사업자등록번호" in result


def test_issue_tax_invoice_no_lines(tax_db_path):
    params = _valid_invoice_params(lines=[])
    result = office.handle_issue_tax_invoice(params)
    assert result.startswith("❌")
    assert "0건" in result or "품목" in result


def test_issue_tax_invoice_bad_date(tax_db_path):
    params = _valid_invoice_params(issue_date="2026/05/26")
    result = office.handle_issue_tax_invoice(params)
    assert result.startswith("❌")
    assert "날짜" in result


# ─────────── list_tax_invoices ───────────


def test_list_tax_invoices_empty(tax_db_path):
    assert "없습니다" in office.handle_list_tax_invoices({})


def test_list_tax_invoices_with_data(tax_db_path):
    office.handle_issue_tax_invoice(
        _valid_invoice_params(project_code="GS-25-0088"),
        user_context={"gw_id": "tgjeon"},
    )
    office.handle_issue_tax_invoice(
        _valid_invoice_params(project_code="GS-25-0030"),
        user_context={"gw_id": "tgjeon"},
    )
    result = office.handle_list_tax_invoices({})
    assert "2건" in result
    assert "GS-25-0088" in result and "GS-25-0030" in result


def test_list_tax_invoices_filter_project(tax_db_path):
    office.handle_issue_tax_invoice(
        _valid_invoice_params(project_code="GS-25-0088"),
    )
    office.handle_issue_tax_invoice(
        _valid_invoice_params(project_code="GS-25-0030"),
    )
    result = office.handle_list_tax_invoices({"project_code": "GS-25-0088"})
    assert "1건" in result
    assert "GS-25-0030" not in result


def test_list_tax_invoices_bad_status(tax_db_path):
    result = office.handle_list_tax_invoices({"status": "BAD"})
    assert result.startswith("❌")


# ─────────── cancel_tax_invoice ───────────


def test_cancel_tax_invoice_missing_id(tax_db_path):
    assert office.handle_cancel_tax_invoice({}).startswith("❌")


def test_cancel_tax_invoice_success(tax_db_path):
    """발행 후 취소."""
    issue_result = office.handle_issue_tax_invoice(_valid_invoice_params())
    # 발행 결과 메시지에서 invoice_id 추출
    import re
    m = re.search(r"세금계산서 #(\d+)", issue_result)
    assert m, f"발행 메시지에서 ID 추출 실패: {issue_result}"
    invoice_id = int(m.group(1))

    result = office.handle_cancel_tax_invoice({"invoice_id": invoice_id, "reason": "테스트"})
    assert "취소" in result and str(invoice_id) in result


def test_cancel_tax_invoice_nonexistent(tax_db_path):
    result = office.handle_cancel_tax_invoice({"invoice_id": 999999})
    assert result.startswith("❌")


# ─────────── TOOLS 매핑 검증 ───────────


def test_office_tools_mapping_complete():
    """선언된 5개 도구가 TOOLS에 모두 등록되어 있는지."""
    expected = {
        "save_contact_from_image",
        "list_contacts",
        "issue_tax_invoice",
        "list_tax_invoices",
        "cancel_tax_invoice",
    }
    assert expected.issubset(office.TOOLS.keys())
    for name, fn in office.TOOLS.items():
        assert callable(fn), f"{name} is not callable"
