"""
crm — 명함 OCR + 연락처 동기화.

흐름:
    명함 이미지 → card_ocr.extract_from_image() → BusinessCard
    → crm.service.save_contact() → DB(contacts)
    → contacts_sync.push_to_google() → Google Contacts (선택)
"""

from src.office.crm.models import BusinessCard, Contact
from src.office.crm.service import save_contact, get_contact, list_contacts

__all__ = [
    "BusinessCard", "Contact",
    "save_contact", "get_contact", "list_contacts",
]
