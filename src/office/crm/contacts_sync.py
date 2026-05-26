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
    Google Contacts(People API) 동기화 어댑터.

    인증 방식: Service Account + Domain-wide Delegation
    - config/google_service_account.json 사용
    - delegated_user_email 으로 impersonate (회사 Google Workspace 도메인)
    - 관리자가 사전에 OAuth 클라이언트 ID에 People API 스코프 위임 권한 부여 필요

    환경 변수:
      GOOGLE_SERVICE_ACCOUNT_PATH       — JSON 키 파일 경로 (기본: config/google_service_account.json)
      GOOGLE_CONTACTS_DELEGATED_USER    — impersonate할 사용자 이메일 (기본: 빈 값)
      ENABLE_GOOGLE_CONTACTS_SYNC=1     — get_default_syncer()가 이 어댑터를 선택
    """

    SCOPES = ["https://www.googleapis.com/auth/contacts"]
    DEFAULT_KEY_PATH = "config/google_service_account.json"

    def __init__(
        self,
        credentials_path: str | None = None,
        delegated_user_email: str | None = None,
    ) -> None:
        import os
        self.credentials_path = (
            credentials_path
            or os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH")
            or self.DEFAULT_KEY_PATH
        )
        self.delegated_user_email = (
            delegated_user_email or os.getenv("GOOGLE_CONTACTS_DELEGATED_USER") or ""
        )
        self._service = None  # 지연 초기화

    def _build_service(self):
        """googleapiclient People API 클라이언트 빌드 (지연 초기화)."""
        if self._service is not None:
            return self._service
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as e:
            raise RuntimeError(
                "googleapiclient/google-auth 미설치. "
                "pip install google-api-python-client google-auth"
            ) from e

        from pathlib import Path
        path = Path(self.credentials_path)
        if not path.exists():
            raise FileNotFoundError(f"Service Account 키 파일 없음: {path}")

        credentials = service_account.Credentials.from_service_account_file(
            str(path), scopes=self.SCOPES,
        )
        if self.delegated_user_email:
            credentials = credentials.with_subject(self.delegated_user_email)

        # cache_discovery=False — 작은 환경에서 디스크 캐시 미사용
        self._service = build("people", "v1", credentials=credentials, cache_discovery=False)
        return self._service

    @staticmethod
    def _contact_to_payload(contact: Contact) -> dict:
        """Contact → People API resource 페이로드 변환."""
        payload: dict = {"names": [{"unstructuredName": contact.name}] if contact.name else []}
        org = {}
        if contact.company:
            org["name"] = contact.company
        if contact.title:
            org["title"] = contact.title
        if contact.department:
            org["department"] = contact.department
        if org:
            payload["organizations"] = [org]
        if contact.email:
            payload["emailAddresses"] = [{"value": contact.email}]
        phones = []
        if contact.phone_mobile:
            phones.append({"value": contact.phone_mobile, "type": "mobile"})
        if contact.phone_office:
            phones.append({"value": contact.phone_office, "type": "work"})
        if contact.fax:
            phones.append({"value": contact.fax, "type": "workFax"})
        if phones:
            payload["phoneNumbers"] = phones
        if contact.address:
            payload["addresses"] = [{"formattedValue": contact.address}]
        if contact.website:
            payload["urls"] = [{"value": contact.website}]
        # 빈 키는 People API가 거부할 수 있으므로 제거
        return {k: v for k, v in payload.items() if v}

    def push(self, contact: Contact) -> str:
        """createContact → resource_name 반환 (예: 'people/c12345...')."""
        service = self._build_service()
        body = self._contact_to_payload(contact)
        if not body:
            logger.warning("GoogleContactsSyncer.push: 빈 payload — 스킵")
            return ""
        try:
            created = service.people().createContact(body=body).execute()
            resource_name = created.get("resourceName", "")
            logger.info("Google Contacts push 성공: %s", resource_name)
            return resource_name
        except Exception as e:
            logger.error("Google Contacts push 실패: %s", e)
            raise

    def delete(self, resource_name: str) -> bool:
        if not resource_name:
            return False
        service = self._build_service()
        try:
            service.people().deleteContact(resourceName=resource_name).execute()
            logger.info("Google Contacts delete 성공: %s", resource_name)
            return True
        except Exception as e:
            logger.error("Google Contacts delete 실패: %s", e)
            return False


def get_default_syncer() -> IContactsSyncer:
    """환경 변수 ENABLE_GOOGLE_CONTACTS_SYNC=1 일 때만 Google 어댑터, 그 외 Noop."""
    import os
    if os.getenv("ENABLE_GOOGLE_CONTACTS_SYNC") == "1":
        return GoogleContactsSyncer()
    return NoopContactsSyncer()
