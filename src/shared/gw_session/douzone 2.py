"""
DouzoneAmaranth10Provider — 현재 GW(글로우서울 더존 Amaranth10) 구현

구조:
  - 신규 메서드는 기존 src/ 코드를 위임 호출 (얇은 래퍼).
  - 점진적으로 페이지별 export/조회 로직을 내재화해 옮긴다.

현재 단계(P1):
  - login / restore_session / close_session 만 실제 동작.
  - 나머지 메서드는 NotImplementedError 또는 위임으로 placeholder.
  - Track A 작업 결과에 따라 export_xlsx, submit_approval 등 점진적으로 구현.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from src.shared.gw_session.interface import (
    GWPage,
    GWSession,
    ExportResult,
    IGroupwareProvider,
    Module,
)
from src.shared.gw_session.selectors import GW_MODULES, GW_PAGES

logger = logging.getLogger(__name__)


class DouzoneAmaranth10Provider:
    """더존 Amaranth10(글로우서울 GW) 어댑터.

    Playwright 기반. 기존 코드(src/shared/auth/login.py 등)를 위임 호출한다.
    Track A 작업에 따라 페이지별 로직을 점진적으로 내재화한다.
    """

    name = "DouzoneAmaranth10"
    base_url = "https://gw.glowseoul.co.kr"

    # ─────────── 세션 라이프사이클 ───────────
    def login(self, user_id: str, password: str) -> GWSession:
        """기존 login_and_get_context 위임."""
        from src.shared.auth.login import login_and_get_context

        browser, context, page = login_and_get_context(
            headless=True, user_id=user_id, user_pw=password,
        )
        return GWSession(
            user_id=user_id,
            is_logged_in=True,
            raw={"browser": browser, "context": context, "page": page},
        )

    def restore_session(self, user_id: str) -> GWSession | None:
        """저장된 세션이 있으면 복원, 없으면 None."""
        from src.shared.auth.login import login_and_get_context, _get_session_file

        if not _get_session_file(user_id).exists():
            return None
        try:
            browser, context, page = login_and_get_context(
                headless=True, user_id=user_id,
            )
            return GWSession(
                user_id=user_id,
                is_logged_in=True,
                raw={"browser": browser, "context": context, "page": page},
            )
        except Exception as e:
            logger.warning(f"restore_session 실패: {e}")
            return None

    def close_session(self, session: GWSession) -> None:
        if not session or not session.raw:
            return
        try:
            session.raw.get("context") and session.raw["context"].close()
            session.raw.get("browser") and session.raw["browser"].close()
        except Exception as e:
            logger.warning(f"세션 종료 실패: {e}")

    # ─────────── 메뉴 탐색 ───────────
    def list_modules(self) -> list[Module]:
        return list(GW_MODULES.values())

    def list_pages(self, module_code: str | None = None) -> list[GWPage]:
        pages = list(GW_PAGES.values())
        if module_code:
            pages = [p for p in pages if p.module_code == module_code]
        return pages

    def navigate_to(self, page_key: str) -> bool:
        """미구현 — Track A 진행 후 page 핸들 보관 방식으로 구현 예정."""
        raise NotImplementedError(
            "navigate_to는 P2/P3 단계에서 구현. 현재는 기존 라우트 사용."
        )

    # ─────────── 데이터 추출 ───────────
    def export_xlsx(
        self,
        page_key: str,
        filters: dict | None = None,
        save_dir: Path | None = None,
    ) -> ExportResult:
        """미구현 — Track A의 조회 버튼 셀렉터 + 모달 dismiss 매핑 완료 후 구현."""
        raise NotImplementedError(
            f"export_xlsx({page_key!r})는 Track A 셀렉터 매핑 완료 후 구현 예정."
        )

    def read_grid(self, page_key: str, filters: dict | None = None) -> list[dict]:
        """미구현 — fund_table 크롤러를 어댑터로 위임 예정."""
        raise NotImplementedError(
            f"read_grid({page_key!r})는 fund_table 크롤러 이관 후 구현."
        )

    # ─────────── 결재 ───────────
    def submit_approval(
        self,
        form_type: str,
        data: dict,
        mode: Literal["draft", "submit"] = "draft",
    ) -> dict:
        """기존 src/approval/ 의 ApprovalMixin 코드를 위임 호출 예정."""
        raise NotImplementedError(
            f"submit_approval({form_type!r}, mode={mode!r})는 "
            "P3(approval/ → gw/approval 이동) 단계에서 구현."
        )

    # ─────────── 근태 ───────────
    def get_attendance_summary(self) -> dict:
        raise NotImplementedError(
            "get_attendance_summary는 attendance 모듈 이관 후 구현."
        )

    def request_leave(
        self, leave_type: str, start: str, end: str, reason: str = "",
    ) -> dict:
        raise NotImplementedError(
            "request_leave는 attendance 모듈 이관 후 구현."
        )

    # ─────────── 자원 / 회의실 ───────────
    def list_reservations(self, range_days: int = 7) -> list[dict]:
        raise NotImplementedError(
            "list_reservations는 meeting 모듈 이관 후 구현."
        )

    def reserve_meeting_room(
        self, room_code: str, start: str, end: str, title: str, description: str = "",
    ) -> dict:
        raise NotImplementedError(
            "reserve_meeting_room는 meeting 모듈 이관 후 구현."
        )


# Protocol 적합성 정적 검사 (선택)
_PROTOCOL_CHECK: IGroupwareProvider = DouzoneAmaranth10Provider()
