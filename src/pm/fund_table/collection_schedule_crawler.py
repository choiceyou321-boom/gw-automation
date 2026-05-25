# TODO: Phase 0 — GW DOM 탐색 필요
"""
수금 예정 내역 GW 크롤러
- Playwright로 GW 접속 → 수금 관리 모듈(ML) 이동
- 프로젝트별 수금 예정 스케줄 추출 → DB 저장

주요 메서드:
  - crawl_collection_schedule()     : 단일 프로젝트 수금 예정 크롤링
  - crawl_all_collection_schedule() : 전체 프로젝트 일괄 크롤링
"""

import os
import logging

from src.pm.fund_table.base_crawler import BaseCrawler, STANDARD_GRID_EXTRACT_JS

logger = logging.getLogger(__name__)

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# TODO: GW DOM 탐색 후 확인 필요 — 수금 예정 관리 페이지 URL
_GW_COLLECTION_SCHEDULE_URL = (
    GW_URL + "/#/ML/MLB/MLB0000"
    "?specialLnb=Y&moduleCode=ML&menuCode=MLB&pageCode=MLB0000"
)


def _map_row_to_schedule(raw: dict) -> dict:
    """GW 그리드 행 → 수금 예정 표준 필드 매핑."""
    return {
        "scheduled_date":    raw.get("schedDt")      or raw.get("planDt")      or raw.get("예정일") or "",
        "category":          raw.get("ctgNm")         or raw.get("categoryNm")  or raw.get("구분") or "",
        "stage":             raw.get("stageNm")       or raw.get("stepNm")      or raw.get("단계") or "",
        "expected_amount":   raw.get("planAm")        or raw.get("expectAmt")   or raw.get("예정금액") or 0,
        "collected_amount":  raw.get("rcvAm")         or raw.get("rcvdAmt")     or raw.get("수금액") or 0,
        "status":            raw.get("statusNm")      or raw.get("stCdNm")      or raw.get("처리상태") or "",
        "invoice_number":    raw.get("invoiceNo")     or raw.get("taxInvNo")    or raw.get("세금계산서번호") or "",
        "description":       raw.get("remark")        or raw.get("rmk")         or raw.get("비고") or "",
    }


class CollectionScheduleCrawler(BaseCrawler):
    """GW 수금 예정 내역 크롤러."""

    LOG_TAG = "CollectionScheduleCrawler"
    GW_URL = _GW_COLLECTION_SCHEDULE_URL
    EXTRACT_JS = STANDARD_GRID_EXTRACT_JS

    def _map_row(self, raw: dict) -> dict:
        return _map_row_to_schedule(raw)

    def _save_records(self, records, project_id):
        from src.pm.fund_table import db
        return db.save_collection_schedule(records, project_id=project_id)

    # ────────────── 공개 인터페이스 (시그니처 유지) ──────────────
    def crawl_collection_schedule(
        self,
        project_id: int,
        gw_project_code: str,
    ) -> list[dict]:
        return self._crawl_single(project_id, gw_project_code)

    def crawl_all_collection_schedule(self, projects: list[dict]) -> dict:
        return self._crawl_all(projects)
