"""
CRM 통합 서비스 — DB + OCR + Sync 조합.

진입점:
    save_contact_from_image(image_path, owner) → Contact
    save_contact(card, owner) → Contact
    list_contacts(...) → list[Contact]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from src.office.crm import db
from src.office.crm.card_ocr import extract_from_image
from src.office.crm.contacts_sync import IContactsSyncer, get_default_syncer
from src.office.crm.models import BusinessCard, Contact

logger = logging.getLogger(__name__)


def save_contact_from_image(
    image_path: str | Path,
    owner_gw_id: str = "",
    tags: Iterable[str] | None = None,
    project_codes: Iterable[str] | None = None,
    note: str = "",
    syncer: IContactsSyncer | None = None,
) -> Contact:
    """명함 이미지 한 장 → OCR → DB 저장 → (선택) Google 동기화."""
    card = extract_from_image(image_path)
    return save_contact(
        card,
        owner_gw_id=owner_gw_id,
        tags=tags,
        project_codes=project_codes,
        note=note,
        syncer=syncer,
    )


def save_contact(
    card: BusinessCard,
    owner_gw_id: str = "",
    tags: Iterable[str] | None = None,
    project_codes: Iterable[str] | None = None,
    note: str = "",
    syncer: IContactsSyncer | None = None,
) -> Contact:
    """BusinessCard → contacts INSERT + 동기화 어댑터 호출."""
    # 중복 가벼운 체크
    dup = db.find_duplicate(card.name, card.phone_mobile, card.email)
    if dup:
        logger.info(f"중복 연락처 발견 (id={dup.id}, name={dup.name}) — INSERT 생략")
        return dup

    contact_id = db.insert_contact(
        card,
        owner_gw_id=owner_gw_id,
        note=note,
        tags=tags or [],
        project_codes=project_codes or [],
    )
    contact = db.get_contact(contact_id)
    if not contact:
        raise RuntimeError(f"insert 직후 get_contact({contact_id}) 실패")

    # 외부 동기화 (실패해도 DB는 유지)
    try:
        syncer = syncer or get_default_syncer()
        resource_name = syncer.push(contact)
        if resource_name:
            db.update_contact_google_resource(contact_id, resource_name)
            contact.google_resource_name = resource_name
    except NotImplementedError:
        logger.debug("Syncer.push 미구현 — DB만 저장")
    except Exception as e:
        logger.warning(f"Syncer.push 실패: {e} (DB는 유지)")

    return contact


def get_contact(contact_id: int) -> Contact | None:
    return db.get_contact(contact_id)


def list_contacts(owner_gw_id: str | None = None, company: str | None = None, limit: int = 100) -> list[Contact]:
    return db.list_contacts(owner_gw_id=owner_gw_id, company=company, limit=limit)
