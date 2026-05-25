# TODO: Phase 0 — GW DOM 탐색 필요
"""
세금계산서 발행 내역 GW 크롤러
- Playwright로 GW 접속 → 수금 모듈(ML) 또는 전자세금계산서 모듈 이동
- 프로젝트별 사업코드 조회 → 세금계산서 내역 추출 → DB 저장

주요 메서드:
  - crawl_tax_invoices()     : 단일 프로젝트 세금계산서 크롤링
  - crawl_all_tax_invoices() : 전체 프로젝트 일괄 크롤링
"""

import os
import logging

from src.pm.fund_table.base_crawler import BaseCrawler, STANDARD_GRID_EXTRACT_JS

logger = logging.getLogger(__name__)

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# TODO: GW DOM 탐색 후 확인 필요 — 전자세금계산서 모듈 URL
_GW_TAX_INVOICE_URL = (
    GW_URL + "/#/ML/MLA/MLA0000"
    "?specialLnb=Y&moduleCode=ML&menuCode=MLA&pageCode=MLA0000"
)


def _map_row_to_invoice(raw: dict) -> dict:
    """GW 그리드 행 → 세금계산서 표준 필드 매핑."""
    return {
        "issue_date":       raw.get("issueDt")       or raw.get("issueDate")  or raw.get("발행일자") or "",
        "invoice_number":   raw.get("invoiceNo")      or raw.get("slipNo")     or raw.get("세금계산서번호") or "",
        "vendor_name":      raw.get("vendorNm")       or raw.get("custNm")     or raw.get("거래처명") or "",
        "vendor_biz_number":raw.get("bizNo")          or raw.get("vendorBizNo") or raw.get("사업자번호") or "",
        "supply_amount":    raw.get("supplyAm")       or raw.get("supAmt")     or raw.get("공급가액") or 0,
        "tax_amount":       raw.get("taxAm")          or raw.get("vatAmt")     or raw.get("세액") or 0,
        "total_amount":     raw.get("totalAm")        or raw.get("totAmt")     or raw.get("합계금액") or 0,
        "invoice_type":     raw.get("invoiceTpNm")    or raw.get("slipTpNm")   or raw.get("발행유형") or "",
        "status":           raw.get("statusNm")       or raw.get("stCdNm")     or raw.get("처리상태") or "",
        "description":      raw.get("remark")         or raw.get("rmk")        or raw.get("비고") or "",
        "project_name":     raw.get("pjtNm")          or raw.get("projectNm")  or raw.get("프로젝트명") or "",
    }


class TaxInvoiceCrawler(BaseCrawler):
    """GW 세금계산서 발행 내역 크롤러."""

    LOG_TAG = "TaxInvoiceCrawler"
    GW_URL = _GW_TAX_INVOICE_URL
    EXTRACT_JS = STANDARD_GRID_EXTRACT_JS

    def _map_row(self, raw: dict) -> dict:
        return _map_row_to_invoice(raw)

    def _save_records(self, records, project_id):
        from src.pm.fund_table import db
        return db.save_tax_invoices(records, project_id=project_id)

    # ────────────── 공개 인터페이스 (시그니처 유지) ──────────────
    def crawl_tax_invoices(
        self,
        project_id: int,
        gw_project_code: str,
        year: int = None,
    ) -> list[dict]:
        return self._crawl_single(project_id, gw_project_code, year=year)

    def crawl_all_tax_invoices(self, projects: list[dict]) -> dict:
        return self._crawl_all(projects)
