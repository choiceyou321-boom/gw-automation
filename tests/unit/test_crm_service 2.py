"""CRM service 단위 테스트 — OCR 모킹 + DB 격리."""

from __future__ import annotations

import pytest

from src.office.crm import card_ocr, db, service
from src.office.crm.contacts_sync import IContactsSyncer, NoopContactsSyncer
from src.office.crm.models import BusinessCard, Contact


@pytest.fixture
def crm_db_path(tmp_path, monkeypatch):
    """매 테스트마다 격리된 임시 DB."""
    path = tmp_path / "test_service.db"
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", path)
    return path


@pytest.fixture
def sample_card():
    return BusinessCard(
        name="홍길동",
        company="글로우서울",
        email="gildong@glowseoul.co.kr",
        phone_mobile="010-1234-5678",
    )


def test_save_contact_inserts_to_db(crm_db_path, sample_card):
    contact = service.save_contact(sample_card, owner_gw_id="tgjeon")
    assert contact.id is not None
    assert contact.name == "홍길동"
    # DB에서도 조회되어야 함
    fetched = service.get_contact(contact.id)
    assert fetched is not None
    assert fetched.owner_gw_id == "tgjeon"


def test_save_contact_skips_duplicate(crm_db_path, sample_card):
    first = service.save_contact(sample_card, owner_gw_id="tgjeon")
    second = service.save_contact(sample_card, owner_gw_id="tgjeon")
    # 같은 이름 + 같은 휴대폰 → 중복으로 첫 ID 반환
    assert first.id == second.id


def test_save_contact_with_syncer(crm_db_path, sample_card):
    """syncer.push 호출 후 google_resource_name 업데이트되는지."""

    class TestSyncer:
        def __init__(self):
            self.push_called = 0

        def push(self, contact: Contact) -> str:
            self.push_called += 1
            return f"people/test-{contact.id}"

        def delete(self, resource_name: str) -> bool:
            return True

    syncer = TestSyncer()
    contact = service.save_contact(sample_card, owner_gw_id="tgjeon", syncer=syncer)
    assert syncer.push_called == 1
    assert contact.google_resource_name == f"people/test-{contact.id}"


def test_save_contact_syncer_failure_does_not_break(crm_db_path, sample_card):
    """syncer.push가 예외 던져도 DB는 저장됨."""

    class FailSyncer:
        def push(self, contact: Contact) -> str:
            raise RuntimeError("외부 시스템 다운")

        def delete(self, resource_name: str) -> bool:
            return False

    contact = service.save_contact(sample_card, syncer=FailSyncer())
    assert contact.id is not None
    assert contact.google_resource_name == ""


def test_save_contact_from_image(crm_db_path, tmp_path, monkeypatch, sample_card):
    """이미지 → OCR(mock) → save_contact 통합."""

    def fake_extract(image_path):
        sample_card.image_path = str(image_path)
        return sample_card

    monkeypatch.setattr(service, "extract_from_image", fake_extract)

    img_path = tmp_path / "card.jpg"
    img_path.write_bytes(b"fake")
    contact = service.save_contact_from_image(img_path, owner_gw_id="tgjeon")
    assert contact.name == "홍길동"
    assert contact.image_path == str(img_path)


def test_noop_syncer_push_returns_id_format(sample_card):
    syncer = NoopContactsSyncer()
    contact = Contact(id=42, name=sample_card.name)
    assert syncer.push(contact) == "local:42"
    assert syncer.delete("local:42") is True


def test_list_contacts_via_service(crm_db_path, sample_card):
    service.save_contact(sample_card, owner_gw_id="tgjeon")
    another = BusinessCard(name="홍길순", company="다른회사", email="x@x.com")
    service.save_contact(another, owner_gw_id="tgjeon")
    contacts = service.list_contacts(owner_gw_id="tgjeon")
    assert len(contacts) == 2
