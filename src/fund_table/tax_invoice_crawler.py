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
from datetime import datetime

logger = logging.getLogger(__name__)

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# TODO: GW DOM 탐색 후 확인 필요 — 전자세금계산서 모듈 URL
# 힌트: 수금 모듈(ML) 또는 별도 세금계산서 모듈 경로
_GW_TAX_INVOICE_URL = (
    GW_URL + "/#/ML/MLA/MLA0000"
    "?specialLnb=Y&moduleCode=ML&menuCode=MLA&pageCode=MLA0000"
)

# TODO: GW DOM 탐색 후 확인 필요 — 세금계산서 그리드 데이터 추출 JS
# 더존 WEHAGO는 OBTDataGrid(React fiber) 또는 RealGrid를 사용할 수 있음
_EXTRACT_TAX_INVOICE_JS = """
(() => {
    // TODO: GW DOM 탐색 후 확인 필요 — 실제 셀렉터 교체
    // 시도 1: OBTDataGrid (React fiber → depth 3 → stateNode.state.interface)
    const grids = document.querySelectorAll('[class*="OBTDataGrid"]');
    if (!grids.length) return { error: 'grid_not_found' };

    for (const el of grids) {
        const fk = Object.keys(el).find(k =>
            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
        );
        if (!fk) continue;

        let f = el[fk];
        for (let i = 0; i < 3 && f; i++) f = f.return;
        if (!f?.stateNode?.state?.interface) continue;

        const iface = f.stateNode.state.interface;
        try {
            const rowCount = iface.getRowCount();
            if (rowCount === 0) return { error: 'empty_grid' };

            const cols = iface.getColumns().map(c => ({
                name: c.name,
                header: c.header ? (c.header.text || c.header) : c.name
            }));
            const rows = [];
            for (let r = 0; r < rowCount; r++) {
                const row = {};
                cols.forEach(col => { row[col.name] = iface.getValue(r, col.name); });
                rows.push(row);
            }
            return { source: 'OBTDataGrid', row_count: rowCount, columns: cols, rows: rows };
        } catch (e) {
            return { error: e.message };
        }
    }

    // 시도 2: RealGrid DataProvider (예산관리 그리드 패턴)
    try {
        const Grids = window.Grids;
        if (Grids && typeof Grids.getActiveGrid === 'function') {
            const dp = Grids.getActiveGrid().getDataProvider();
            if (dp) {
                const rowCount = dp.getRowCount();
                const rows = [];
                for (let i = 0; i < rowCount; i++) {
                    const row = dp.getJsonRow(i);
                    if (row) rows.push(row);
                }
                return { source: 'RealGrid', row_count: rows.length, rows: rows };
            }
        }
    } catch (e) {
        // RealGrid 없을 경우 무시
    }

    return { error: 'no_supported_grid_found' };
})()
"""


def _map_row_to_invoice(raw: dict) -> dict:
    """
    GW 그리드 행 → 세금계산서 표준 필드 매핑.
    TODO: GW DOM 탐색 후 실제 필드명으로 교체 필요
    """
    return {
        # TODO: GW DOM 탐색 후 확인 필요 — 실제 컬럼명 매핑
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


class TaxInvoiceCrawler:
    """
    GW 세금계산서 발행 내역 크롤러.

    GW 수금 모듈(ML) 또는 전자세금계산서 모듈에서
    프로젝트별 세금계산서 발행 이력을 수집하여 DB에 저장한다.
    """

    def __init__(self, gw_id: str):
        """
        Args:
            gw_id: GW 로그인 아이디
        """
        self.gw_id = gw_id

    # ──────────────────────────────────────────
    # 단일 프로젝트 크롤링
    # ──────────────────────────────────────────

    def crawl_tax_invoices(
        self,
        project_id: int,
        gw_project_code: str,
        year: int = None,
    ) -> list[dict]:
        """
        단일 프로젝트의 세금계산서 발행 내역을 크롤링하여 DB에 저장한다.

        Args:
            project_id:       fund_management.db 프로젝트 ID
            gw_project_code:  GW 사업코드 (예: GS-25-0088)
            year:             조회 연도 (None이면 전체)

        Returns:
            list[dict]: 수집된 세금계산서 레코드 목록
        """
        from playwright.sync_api import sync_playwright
        from src.auth.login import login_and_get_context, close_session
        from src.auth.user_db import get_decrypted_password
        from src.fund_table import db

        logger.info(f"[TaxInvoiceCrawler] 크롤링 시작: project_id={project_id}, code={gw_project_code}")

        gw_pw = get_decrypted_password(self.gw_id)
        if not gw_pw:
            logger.error(f"비밀번호 복호화 실패: gw_id={self.gw_id}")
            return []

        pw = sync_playwright().start()
        try:
            browser, context, page = login_and_get_context(
                playwright_instance=pw,
                headless=True,
                user_id=self.gw_id,
                user_pw=gw_pw,
            )

            invoices = self._navigate_and_extract(page, gw_project_code, year)

            if invoices:
                # 프로젝트 ID 주입 후 DB 저장
                for inv in invoices:
                    inv["project_id"] = project_id
                save_result = db.save_tax_invoices(invoices, project_id=project_id)
                logger.info(f"[TaxInvoiceCrawler] 저장 완료: {save_result}")
            else:
                logger.warning(f"[TaxInvoiceCrawler] 수집 결과 없음: code={gw_project_code}")

            close_session(browser)
            return invoices

        except Exception as e:
            logger.error(f"[TaxInvoiceCrawler] 크롤링 실패: {e}", exc_info=True)
            return []
        finally:
            pw.stop()

    def _navigate_and_extract(self, page, gw_project_code: str, year: int = None) -> list[dict]:
        """
        GW 세금계산서 페이지로 이동 후 데이터를 추출한다.

        TODO: GW DOM 탐색 후 확인 필요
          1. 수금 모듈(ML) 또는 전자세금계산서 모듈 진입 경로
          2. 프로젝트 코드 입력 셀렉터
          3. 연도/기간 필터 조작 방법
          4. 조회 버튼 셀렉터
          5. 그리드 로딩 완료 대기 조건
        """
        try:
            # TODO: GW DOM 탐색 후 확인 필요 — 수금 모듈 진입
            # 힌트: span.module-link.ML 클릭 → 세금계산서 메뉴 이동
            logger.debug(f"[TaxInvoiceCrawler] 페이지 이동: {_GW_TAX_INVOICE_URL}")
            page.goto(_GW_TAX_INVOICE_URL)
            page.wait_for_timeout(2000)

            # TODO: GW DOM 탐색 후 확인 필요 — 프로젝트 코드 필터 입력
            # 예시 패턴 (실제 셀렉터는 DOM 탐색 후 교체):
            #   page.fill('input[placeholder*="사업코드"]', gw_project_code)
            #   page.press('input[placeholder*="사업코드"]', 'Enter')

            # TODO: GW DOM 탐색 후 확인 필요 — 연도 필터 (year 파라미터 사용)
            if year:
                pass  # 연도 필터 입력 로직

            # TODO: GW DOM 탐색 후 확인 필요 — 조회 버튼 클릭
            #   page.click('button:has-text("조회")')
            #   page.wait_for_timeout(2000)

            # 그리드 데이터 추출
            result = page.evaluate(_EXTRACT_TAX_INVOICE_JS)

            if result.get("error"):
                logger.warning(f"[TaxInvoiceCrawler] 그리드 추출 실패: {result['error']}")
                return []

            rows = result.get("rows", [])
            logger.info(f"[TaxInvoiceCrawler] 추출 행 수: {len(rows)}")

            # 필드 매핑 및 반환
            return [_map_row_to_invoice(row) for row in rows]

        except Exception as e:
            logger.error(f"[TaxInvoiceCrawler] 페이지 탐색 실패: {e}", exc_info=True)
            return []

    # ──────────────────────────────────────────
    # 전체 프로젝트 일괄 크롤링
    # ──────────────────────────────────────────

    def crawl_all_tax_invoices(self, projects: list[dict]) -> dict:
        """
        여러 프로젝트의 세금계산서 내역을 일괄 크롤링한다.
        세션을 1회만 열어 효율적으로 처리한다.

        Args:
            projects: [{"id": int, "project_code": str, ...}, ...]
                      project_code가 없는 항목은 건너뜀

        Returns:
            dict: { project_id → {"success": bool, "count": int, "error"?: str} }
        """
        from playwright.sync_api import sync_playwright
        from src.auth.login import login_and_get_context, close_session
        from src.auth.user_db import get_decrypted_password
        from src.fund_table import db

        results = {}
        targets = [p for p in projects if p.get("project_code")]

        if not targets:
            logger.warning("[TaxInvoiceCrawler] project_code가 있는 프로젝트가 없습니다.")
            return results

        gw_pw = get_decrypted_password(self.gw_id)
        if not gw_pw:
            logger.error(f"비밀번호 복호화 실패: gw_id={self.gw_id}")
            return results

        pw = sync_playwright().start()
        try:
            browser, context, page = login_and_get_context(
                playwright_instance=pw,
                headless=True,
                user_id=self.gw_id,
                user_pw=gw_pw,
            )

            for proj in targets:
                project_id   = proj["id"]
                project_code = proj["project_code"]
                try:
                    invoices = self._navigate_and_extract(page, project_code)
                    if invoices:
                        for inv in invoices:
                            inv["project_id"] = project_id
                        db.save_tax_invoices(invoices, project_id=project_id)
                    results[project_id] = {"success": True, "count": len(invoices)}
                    logger.info(
                        f"[TaxInvoiceCrawler] {project_code}: {len(invoices)}건 수집"
                    )
                except Exception as e:
                    logger.error(
                        f"[TaxInvoiceCrawler] {project_code} 실패: {e}", exc_info=True
                    )
                    results[project_id] = {"success": False, "error": str(e)}

            close_session(browser)

        except Exception as e:
            logger.error(f"[TaxInvoiceCrawler] 일괄 크롤링 실패: {e}", exc_info=True)
        finally:
            pw.stop()

        return results
