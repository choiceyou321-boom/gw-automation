"""CRM DB 단위 테스트 — SQLite 격리 임시 DB 사용."""

from __future__ import annotations

import pytest

from src.office.crm import db
from src.office.crm.models import BusinessCard


@pytest.fixture
def crm_db_path(tmp_path):
    path = tmp_path / "test_crm.db"
    # _initialized_paths 캐시 격리 — 매 테스트마다 새 path
    yield path


@pytest.fixture
def sample_card():
    return BusinessCard(
        name="홍길동",
        company="주식회사 글로우서울",
        department="PM본부",
        title="과장",
        email="gildong@glowseoul.co.kr",
        phone_mobile="010-1234-5678",
        phone_office="02-1234-5678",
        address="서울특별시 용산구 이태원동 164-2",
        raw_text="{}",
        confidence=0.9,
    )


def test_insert_and_get_contact(crm_db_path, sample_card):
    contact_id = db.insert_contact(sample_card, owner_gw_id="tgjeon", db_path=crm_db_path)
    assert contact_id > 0

    contact = db.get_contact(contact_id, db_path=crm_db_path)
    assert contact is not None
    assert contact.name == "홍길동"
    assert contact.company == "주식회사 글로우서울"
    assert contact.email == "gildong@glowseoul.co.kr"
    assert contact.phone_mobile == "010-1234-5678"
    assert contact.owner_gw_id == "tgjeon"
    assert contact.created_at is not None


def test_list_contacts_filter_by_owner(crm_db_path, sample_card):
    db.insert_contact(sample_card, owner_gw_id="tgjeon", db_path=crm_db_path)
    other = BusinessCard(name="다른사람", company="다른회사", phone_mobile="010-0000-0000")
    db.insert_contact(other, owner_gw_id="shyang", db_path=crm_db_path)

    tg_contacts = db.list_contacts(owner_gw_id="tgjeon", db_path=crm_db_path)
    sh_contacts = db.list_contacts(owner_gw_id="shyang", db_path=crm_db_path)
    assert len(tg_contacts) == 1
    assert len(sh_contacts) == 1
    assert tg_contacts[0].name == "홍길동"
    assert sh_contacts[0].name == "다른사람"


def test_list_contacts_filter_by_company(crm_db_path, sample_card):
    db.insert_contact(sample_card, db_path=crm_db_path)
    other = BusinessCard(name="홍길순", company="다른회사", email="x@x.com")
    db.insert_contact(other, db_path=crm_db_path)

    glow = db.list_contacts(company="글로우", db_path=crm_db_path)
    assert len(glow) == 1
    assert glow[0].name == "홍길동"


def test_find_duplicate(crm_db_path, sample_card):
    db.insert_contact(sample_card, db_path=crm_db_path)
    # 동일 이름 + 동일 휴대폰
    dup = db.find_duplicate("홍길동", phone_mobile="010-1234-5678", db_path=crm_db_path)
    assert dup is not None
    assert dup.email == "gildong@glowseoul.co.kr"
    # 다른 이름이면 None
    assert db.find_duplicate("다른사람", phone_mobile="010-1234-5678", db_path=crm_db_path) is None
    # 이름은 같지만 연락처/이메일 모두 다르면 None
    assert db.find_duplicate("홍길동", phone_mobile="010-9999-9999", email="x@x.com", db_path=crm_db_path) is None


def test_update_google_resource(crm_db_path, sample_card):
    contact_id = db.insert_contact(sample_card, db_path=crm_db_path)
    db.update_contact_google_resource(contact_id, "people/c12345", db_path=crm_db_path)
    contact = db.get_contact(contact_id, db_path=crm_db_path)
    assert contact.google_resource_name == "people/c12345"


def test_delete_contact(crm_db_path, sample_card):
    contact_id = db.insert_contact(sample_card, db_path=crm_db_path)
    assert db.delete_contact(contact_id, db_path=crm_db_path) is True
    assert db.get_contact(contact_id, db_path=crm_db_path) is None
    # 두 번째 삭제는 False
    assert db.delete_contact(contact_id, db_path=crm_db_path) is False


def test_tags_and_project_codes_roundtrip(crm_db_path, sample_card):
    contact_id = db.insert_contact(
        sample_card,
        tags=["거래처", "VIP"],
        project_codes=["GS-25-0088", "GS-25-0030"],
        db_path=crm_db_path,
    )
    contact = db.get_contact(contact_id, db_path=crm_db_path)
    assert contact.tags == ["거래처", "VIP"]
    assert contact.project_codes == ["GS-25-0088", "GS-25-0030"]
