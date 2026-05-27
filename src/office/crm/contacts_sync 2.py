"""
Google Contacts 동기화 (인터페이스 + 모킹).

People API 호출은 GoogleContactsSyncer.push() 안에서 처리한다.
현재 단계에서는 인터페이스만 안정화하고 실제 호출은 향후 PR에서 구현
(google-api-python-client 의존성, OAuth 인증 흐름 별도 PR).
"""

from __future__ import annotations

import logging
from typing import Protocol

from src.office.crm.models import Contact

logger = logging.getLogger(__name__)


class IContactsSyncer(Protocol):
    """연락처를 외부 시스템(Google Contacts 등)으로 push하는 어댑터."""

    def push(self, contact: Contact) -> str:
        """저장 성공 시 외부 시스템의 resource_name(또는 ID) 반환."""
        ...

    def delete(self, resource_name: str) -> bool: ...


class NoopContactsSyncer:
    """동기화 비활성 어댑터 (기본). 로그만 남기고 가짜 ID 반환."""

    def push(self, contact: Contact) -> str:
        logger.info(
            "[NoopContactsSyncer] push %s @ %s",
            contact.name or "(이름 없음)",
            contact.company or "(회사 없음)",
        )
        return f"local:{contact.id or 0}"

    def delete(self, resource_name: str) -> bool:
        logger.info("[NoopContactsSyncer] delete %s", resource_name)
        return True


class GoogleContactsSyncer:
    """
    실제 Google Contacts(People API) 동기화 어댑터.

    현재는 스켈레톤이며 push()/delete()는 NotImplementedError.
    구현 시 필요한 것:
      - config/google_service_account.json (이미 존재)
      - scopes: https://www.googleapis.com/auth/contacts
      - googleapiclient.discovery.build("people", "v1", ...)
    """

    def __init__(self, credentials_path: str | None = None) -> None:
        self.credentials_path = credentials_path

    def push(self, contact: Contact) -> str:
        raise NotImplementedError(
            "GoogleContactsSyncer.push는 향후 PR에서 구현. "
            "현재는 NoopContactsSyncer 사용."
        )

    def delete(self, resource_name: str) -> bool:
        raise NotImplementedError(
            "GoogleContactsSyncer.delete는 향후 PR에서 구현."
        )


def get_default_syncer() -> IContactsSyncer:
    """환경 변수 ENABLE_GOOGLE_CONTACTS_SYNC=1 일 때만 Google 어댑터, 그 외 Noop."""
    import os
    if os.getenv("ENABLE_GOOGLE_CONTACTS_SYNC") == "1":
        return GoogleContactsSyncer()
    return NoopContactsSyncer()
