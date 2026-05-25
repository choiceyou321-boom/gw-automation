# TODO: Phase 0 — GW DOM 탐색 필요
"""
GW 계약관리 모듈 크롤러
- Playwright로 GW 접속 → 계약관리 모듈 이동
- 프로젝트별 계약 목록 추출 → DB 저장

주요 메서드:
  - crawl_contracts()      : 단일 프로젝트 계약 크롤링
  - crawl_all_contracts()  : 전체 프로젝트 일괄 크롤링

GW 경로 힌트:
  - 예산관리(BM) 모듈 → 계약관리 → 하도급계약현황
  - 또는 전자결재(EA) 모듈 내 계약 관련 메뉴
"""

import os
import logging

from src.pm.fund_table.base_crawler import BaseCrawler, STANDARD_GRID_EXTRACT_JS

logger = logging.getLogger(__name__)

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# TODO: GW DOM 탐색 후 확인 필요 — 계약관리 화면 URL
_GW_CONTRACT_URL = (
    GW_URL + "/#/BN/NCA0000/0BN00001"
    "?specialLnb=Y&moduleCode=BM&menuCode=NCA0000&pageCode=NCA0000"
)


def _map_row_to_contract(raw: dict) -> dict:
    """GW 그리드 행 → 계약 표준 필드 매핑."""
    return {
        "contract_no":        raw.get("ctrtNo")      or raw.get("contractNo")  or raw.get("계약번호") or "",
        "contract_date":      raw.get("ctrtDt")      or raw.get("contractDt")  or raw.get("계약일자") or "",
        "contract_type":      raw.get("ctrtTpNm")    or raw.get("contractTp")  or raw.get("계약유형") or "",
        "vendor_name":        raw.get("vendorNm")    or raw.get("ctrtCoNm")    or raw.get("계약업체") or
                              raw.get("suppNm")      or raw.get("거래처명")    or "",
        "vendor_code":        raw.get("vendorCd")    or raw.get("ctrtCoCd")    or raw.get("업체코드") or "",
        "contract_amount":    raw.get("ctrtAm")      or raw.get("contractAm")  or raw.get("계약금액") or 0,
        "supply_amount":      raw.get("supplyAm")    or raw.get("supAmt")      or raw.get("공급가액") or 0,
        "tax_amount":         raw.get("taxAm")       or raw.get("vatAmt")      or raw.get("세액") or 0,
        "start_date":         raw.get("startDt")     or raw.get("ctrtStartDt") or raw.get("착공일") or "",
        "end_date":           raw.get("endDt")       or raw.get("ctrtEndDt")   or raw.get("준공일") or "",
        "trade_name":         raw.get("tradeNm")     or raw.get("공종명")      or "",
        "budget_code":        raw.get("bgtCd")       or raw.get("budgetCd")    or raw.get("예산과목") or "",
        "status":             raw.get("statusNm")    or raw.get("stCdNm")      or raw.get("처리상태") or "",
        "description":        raw.get("remark")      or raw.get("rmk")         or raw.get("비고") or "",
    }


class ContractCrawler(BaseCrawler):
    """GW 계약관리 모듈 크롤러."""

    LOG_TAG = "ContractCrawler"
    GW_URL = _GW_CONTRACT_URL
    EXTRACT_JS = STANDARD_GRID_EXTRACT_JS

    def _map_row(self, raw: dict) -> dict:
        return _map_row_to_contract(raw)

    def _save_records(self, records, project_id):
        from src.pm.fund_table import db
        return db.save_gw_contracts(records, project_id=project_id)

    # ────────────── 공개 인터페이스 (시그니처 유지) ──────────────
    def crawl_contracts(self, project_id: int, gw_project_code: str) -> list[dict]:
        return self._crawl_single(project_id, gw_project_code)

    def crawl_all_contracts(self, projects: list[dict]) -> dict:
        return self._crawl_all(projects)
