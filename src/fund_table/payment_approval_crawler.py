# TODO: Phase 0 — GW DOM 탐색 필요
"""
자금집행 승인 현황 GW 크롤러
- Playwright로 GW 접속 → 임직원업무관리(HR) 모듈 또는 자금집행 승인 화면 이동
- 프로젝트별 자금집행 승인 이력 추출 → DB 저장

주요 메서드:
  - crawl_payment_approvals()     : 단일 프로젝트 자금집행 승인 크롤링
  - crawl_all_payment_approvals() : 전체 프로젝트 일괄 크롤링
"""

import os
import logging

from src.fund_table.base_crawler import BaseCrawler, STANDARD_GRID_EXTRACT_JS

logger = logging.getLogger(__name__)

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# TODO: GW DOM 탐색 후 확인 필요 — 자금집행 승인 화면 URL
_GW_PAYMENT_APPROVAL_URL = (
    GW_URL + "/#/HR/HRA/HRA0000"
    "?specialLnb=Y&moduleCode=HR&menuCode=HRA&pageCode=HRA0000"
)


def _map_row_to_approval(raw: dict) -> dict:
    """GW 그리드 행 → 자금집행 승인 표준 필드 매핑."""
    return {
        "request_date":    raw.get("reqDt")        or raw.get("requestDt")   or raw.get("신청일자") or "",
        "approval_date":   raw.get("aprvDt")       or raw.get("approvalDt")  or raw.get("승인일자") or
                           raw.get("trsfDt")       or raw.get("이체일자")     or "",
        "vendor_name":     raw.get("vendorNm")     or raw.get("payeeNm")     or raw.get("수취인") or
                           raw.get("custNm")       or raw.get("거래처명")     or "",
        "amount":          raw.get("totalAm")      or raw.get("totAmt")      or raw.get("합계금액") or
                           raw.get("trsfAm")       or raw.get("이체금액")     or 0,
        "supply_amount":   raw.get("supplyAm")     or raw.get("supAmt")      or raw.get("공급가액") or 0,
        "tax_amount":      raw.get("taxAm")        or raw.get("vatAmt")      or raw.get("세액") or 0,
        "fund_category":   raw.get("fundCtgNm")    or raw.get("payTpNm")     or raw.get("자금구분") or "",
        "budget_code":     raw.get("bgtCd")        or raw.get("budgetCd")    or raw.get("예산과목") or "",
        "status":          raw.get("statusNm")     or raw.get("stCdNm")      or raw.get("처리상태") or "",
        "requester":       raw.get("reqEmpNm")     or raw.get("requesterNm") or raw.get("신청자") or "",
        "approver":        raw.get("aprvEmpNm")    or raw.get("approverNm")  or raw.get("승인자") or "",
        "description":     raw.get("remark")       or raw.get("rmk")         or raw.get("비고") or "",
    }


class PaymentApprovalCrawler(BaseCrawler):
    """GW 자금집행 승인 현황 크롤러."""

    LOG_TAG = "PaymentApprovalCrawler"
    GW_URL = _GW_PAYMENT_APPROVAL_URL
    EXTRACT_JS = STANDARD_GRID_EXTRACT_JS

    def _map_row(self, raw: dict) -> dict:
        return _map_row_to_approval(raw)

    def _save_records(self, records, project_id):
        from src.fund_table import db
        return db.save_payment_approvals(records, project_id=project_id)

    # ────────────── 공개 인터페이스 (시그니처 유지) ──────────────
    def crawl_payment_approvals(
        self,
        project_id: int,
        gw_project_code: str,
        year: int = None,
    ) -> list[dict]:
        return self._crawl_single(project_id, gw_project_code, year=year)

    def crawl_all_payment_approvals(self, projects: list[dict]) -> dict:
        return self._crawl_all(projects)
