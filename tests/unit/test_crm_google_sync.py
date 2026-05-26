"""GoogleContactsSyncer 단위 테스트 — Google API는 모킹."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.office.crm.contacts_sync import (
    GoogleContactsSyncer,
    NoopContactsSyncer,
    get_default_syncer,
)
from src.office.crm.models import Contact


# ─────────── _contact_to_payload ───────────


def test_payload_full_contact():
    contact = Contact(
        id=1,
        name="홍길동",
        company="㈜글로우서울",
        department="PM본부",
        title="과장",
        email="gildong@glowseoul.co.kr",
        phone_mobile="010-1234-5678",
        phone_office="02-1234-5678",
        fax="02-1234-5679",
        address="서울특별시 용산구",
        website="https://glowseoul.co.kr",
    )
    payload = GoogleContactsSyncer._contact_to_payload(contact)
    assert payload["names"][0]["unstructuredName"] == "홍길동"
    org = payload["organizations"][0]
    assert org["name"] == "㈜글로우서울"
    assert org["title"] == "과장"
    assert org["department"] == "PM본부"
    assert payload["emailAddresses"][0]["value"] == "gildong@glowseoul.co.kr"
    phones = {p["type"]: p["value"] for p in payload["phoneNumbers"]}
    assert phones["mobile"] == "010-1234-5678"
    assert phones["work"] == "02-1234-5678"
    assert phones["workFax"] == "02-1234-5679"
    assert payload["addresses"][0]["formattedValue"] == "서울특별시 용산구"
    assert payload["urls"][0]["value"] == "https://glowseoul.co.kr"


def test_payload_empty_contact():
    """이름만 있는 경우 organizations/emails 같은 빈 키는 제외."""
    payload = GoogleContactsSyncer._contact_to_payload(Contact(id=2, name="홍길순"))
    assert payload == {"names": [{"unstructuredName": "홍길순"}]}


def test_payload_no_name():
    """이름 없으면 names도 빈 리스트라 제외 → 페이로드 비어 있을 수 있음."""
    payload = GoogleContactsSyncer._contact_to_payload(Contact(id=3, name=""))
    assert "names" not in payload


# ─────────── push() ───────────


def test_push_calls_create_contact(monkeypatch):
    """service.people().createContact(body=...).execute() 호출 검증."""
    syncer = GoogleContactsSyncer(credentials_path="/fake/path.json")

    fake_service = MagicMock()
    fake_service.people.return_value.createContact.return_value.execute.return_value = {
        "resourceName": "people/c98765",
    }
    monkeypatch.setattr(syncer, "_build_service", lambda: fake_service)

    contact = Contact(id=10, name="홍길동", company="㈜글로우서울", phone_mobile="010-1111-2222")
    resource = syncer.push(contact)

    assert resource == "people/c98765"
    create_call = fake_service.people.return_value.createContact
    create_call.assert_called_once()
    body = create_call.call_args.kwargs["body"]
    assert body["names"][0]["unstructuredName"] == "홍길동"


def test_push_skips_empty_payload(monkeypatch, caplog):
    """이름/연락처 다 없으면 push는 빈 string 반환 (API 호출 안 함)."""
    syncer = GoogleContactsSyncer(credentials_path="/fake/path.json")
    fake_service = MagicMock()
    monkeypatch.setattr(syncer, "_build_service", lambda: fake_service)

    result = syncer.push(Contact(id=11, name=""))
    assert result == ""
    fake_service.people.return_value.createContact.assert_not_called()


def test_push_propagates_api_error(monkeypatch):
    syncer = GoogleContactsSyncer(credentials_path="/fake/path.json")
    fake_service = MagicMock()
    fake_service.people.return_value.createContact.return_value.execute.side_effect = (
        RuntimeError("People API down")
    )
    monkeypatch.setattr(syncer, "_build_service", lambda: fake_service)

    contact = Contact(id=12, name="홍길동", phone_mobile="010-1111-2222")
    with pytest.raises(RuntimeError, match="People API down"):
        syncer.push(contact)


# ─────────── delete() ───────────


def test_delete_calls_api(monkeypatch):
    syncer = GoogleContactsSyncer(credentials_path="/fake/path.json")
    fake_service = MagicMock()
    monkeypatch.setattr(syncer, "_build_service", lambda: fake_service)

    assert syncer.delete("people/c98765") is True
    fake_service.people.return_value.deleteContact.assert_called_once_with(
        resourceName="people/c98765"
    )


def test_delete_empty_resource_name(monkeypatch):
    """resource_name이 빈 문자열이면 False."""
    syncer = GoogleContactsSyncer(credentials_path="/fake/path.json")
    fake_service = MagicMock()
    monkeypatch.setattr(syncer, "_build_service", lambda: fake_service)

    assert syncer.delete("") is False
    fake_service.people.return_value.deleteContact.assert_not_called()


def test_delete_handles_api_error(monkeypatch):
    syncer = GoogleContactsSyncer(credentials_path="/fake/path.json")
    fake_service = MagicMock()
    fake_service.people.return_value.deleteContact.return_value.execute.side_effect = (
        RuntimeError("404 not found")
    )
    monkeypatch.setattr(syncer, "_build_service", lambda: fake_service)

    # delete는 예외를 swallow 하고 False 반환
    assert syncer.delete("people/c98765") is False


# ─────────── _build_service ───────────


def test_build_service_missing_file(monkeypatch, tmp_path):
    """존재하지 않는 키 파일 경로 → FileNotFoundError."""
    syncer = GoogleContactsSyncer(credentials_path=str(tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError, match="Service Account"):
        syncer._build_service()


def test_build_service_caches(monkeypatch):
    """두 번째 호출은 캐시된 service 그대로."""
    syncer = GoogleContactsSyncer(credentials_path="/fake/path.json")
    fake_service = MagicMock(name="cached")
    syncer._service = fake_service  # 캐시 강제 주입
    assert syncer._build_service() is fake_service


# ─────────── get_default_syncer ───────────


def test_default_syncer_noop_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_GOOGLE_CONTACTS_SYNC", raising=False)
    assert isinstance(get_default_syncer(), NoopContactsSyncer)


def test_default_syncer_google_when_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_GOOGLE_CONTACTS_SYNC", "1")
    assert isinstance(get_default_syncer(), GoogleContactsSyncer)
