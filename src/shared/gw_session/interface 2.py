"""
IGroupwareProvider Protocol — 그룹웨어 어댑터 인터페이스

목적:
  더존 Amaranth10 외에 영림원/이카운트 등 다른 그룹웨어로 코드 변경 없이
  갈아끼울 수 있도록 인터페이스를 표준화한다.

각 메서드는 현재 구현 가능한 범위(메뉴 탐색, Export, 결재, 근태, 자원)만
정의하고, 점진적으로 확장한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable


@dataclass
class Module:
    """GW 모듈 메타데이터 (홈 아이콘 단위)."""
    home_code: str          # 예: 'SET', 'HR', 'EA'
    internal_code: str      # 예: 'UJ', 'HP', 'UB'
    label: str              # 예: '시스템설정', '임직원업무관리'


@dataclass
class GWPage:
    """GW 단일 페이지 메타데이터."""
    key: str                # 예: '예실대비현황_상세'
    url_path: str           # 예: '/#/BN/NCC0630/NCC0630'
    module_code: str        # 예: 'BN'
    has_grid: bool = False
    has_export: bool = False
    # 페이지별 부가 정보 (필요 시 확장)
    note: str = ""


@dataclass
class ExportResult:
    """Export 호출 결과."""
    path: Path
    size_bytes: int
    sheet_count: int = 1
    row_count: int = 0
    columns: list[str] = field(default_factory=list)
    suggested_filename: str = ""


@dataclass
class GWSession:
    """GW 세션 토큰/컨텍스트 (Provider 별 내부 구현 자유)."""
    user_id: str
    is_logged_in: bool = False
    # Provider 별로 자유롭게 확장 (예: Playwright page 핸들 등)
    raw: object | None = None


@runtime_checkable
class IGroupwareProvider(Protocol):
    """그룹웨어 어댑터 표준 인터페이스.

    각 메서드의 호출 패턴:
        provider = get_provider()
        sess = provider.restore_session("tgjeon") or provider.login("tgjeon", pw)
        result = provider.export_xlsx("예실대비현황_상세")
    """

    # ─────────── 세션 라이프사이클 ───────────
    def login(self, user_id: str, password: str) -> GWSession: ...
    def restore_session(self, user_id: str) -> GWSession | None: ...
    def close_session(self, session: GWSession) -> None: ...

    # ─────────── 메뉴 탐색 ───────────
    def list_modules(self) -> list[Module]: ...
    def list_pages(self, module_code: str | None = None) -> list[GWPage]: ...
    def navigate_to(self, page_key: str) -> bool: ...

    # ─────────── 데이터 추출 ───────────
    def export_xlsx(
        self,
        page_key: str,
        filters: dict | None = None,
        save_dir: Path | None = None,
    ) -> ExportResult: ...

    def read_grid(
        self,
        page_key: str,
        filters: dict | None = None,
    ) -> list[dict]: ...

    # ─────────── 결재 ───────────
    def submit_approval(
        self,
        form_type: str,
        data: dict,
        mode: Literal["draft", "submit"] = "draft",
    ) -> dict: ...

    # ─────────── 근태 / HR ───────────
    def get_attendance_summary(self) -> dict: ...

    def request_leave(
        self,
        leave_type: str,
        start: str,
        end: str,
        reason: str = "",
    ) -> dict: ...

    # ─────────── 자원 / 회의실 ───────────
    def list_reservations(self, range_days: int = 7) -> list[dict]: ...

    def reserve_meeting_room(
        self,
        room_code: str,
        start: str,
        end: str,
        title: str,
        description: str = "",
    ) -> dict: ...
