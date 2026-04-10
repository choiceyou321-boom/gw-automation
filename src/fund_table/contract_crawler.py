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
from datetime import datetime

logger = logging.getLogger(__name__)

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# TODO: GW DOM 탐색 후 확인 필요 — 계약관리 화면 URL
# 힌트: 예산관리(BM) 모듈 → 계약관리 하위 화면
#   예상: /#/BN/NCA0000/0BN00001 (계약등록현황 등)
_GW_CONTRACT_URL = (
    GW_URL + "/#/BN/NCA0000/0BN00001"
    "?specialLnb=Y&moduleCode=BM&menuCode=NCA0000&pageCode=NCA0000"
)

# TODO: GW DOM 탐색 후 확인 필요 — 계약 그리드 데이터 추출 JS
_EXTRACT_CONTRACT_JS = """
(() => {
    // 시도 0: window.Grids (RealGrid v1.0 DataProvider)
    try {
        const Grids = window.Grids;
        if (Grids && typeof Grids.getActiveGrid === 'function') {
            const grid = Grids.getActiveGrid();
            const dp = grid && grid.getDataProvider ? grid.getDataProvider() : null;
            if (dp) {
                const rowCount = dp.getRowCount ? dp.getRowCount() : 0;
                if (rowCount > 0) {
                    const rows = [];
                    for (let i = 0; i < rowCount; i++) {
                        const row = dp.getJsonRow ? dp.getJsonRow(i) : null;
                        if (row) rows.push(row);
                    }
                    return { source: 'window.Grids.DataProvider', row_count: rows.length, rows: rows };
                }
            }
        }
    } catch (e) { /* RealGrid 없으면 무시 */ }

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

    // 시도 2: RealGrid (복수 그리드 등록 방식)
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
    } catch (e) { /* 없으면 무시 */ }

    return { error: 'no_supported_grid_found' };
})()
"""


def _map_row_to_contract(raw: dict) -> dict:
    """
    GW 그리드 행 → 계약 표준 필드 매핑.
    TODO: GW DOM 탐색 후 실제 컬럼명으로 교체 필요
    """
    return {
        # TODO: GW DOM 탐색 후 확인 필요 — 실제 컬럼명 매핑
        # 계약관리 화면 기준 예상 필드 (실제 필드명은 DOM 탐색 후 확정)
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


class ContractCrawler:
    """
    GW 계약관리 모듈 크롤러.

    예산관리(BM) 모듈의 계약관리 화면에서
    프로젝트별 계약 내역을 수집하여 DB에 저장한다.

    수집 필드:
      - contract_no(계약번호), contract_date(계약일), contract_type(계약유형)
      - vendor_name(업체명), vendor_code(업체코드)
      - contract_amount(계약금액), supply_amount(공급가), tax_amount(세액)
      - start_date(착공일), end_date(준공일), trade_name(공종명)
      - budget_code(예산과목), status(처리상태), description(비고)
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

    def crawl_contracts(
        self,
        project_id: int,
        gw_project_code: str,
    ) -> list[dict]:
        """
        단일 프로젝트의 계약 내역을 크롤링하여 DB에 저장한다.

        Args:
            project_id:       fund_management.db 프로젝트 ID
            gw_project_code:  GW 사업코드 (예: GS-25-0088)

        Returns:
            list[dict]: 수집된 계약 레코드 목록
        """
        from playwright.sync_api import sync_playwright
        from src.auth.login import login_and_get_context, close_session
        from src.auth.user_db import get_decrypted_password
        from src.fund_table import db

        logger.info(
            f"[ContractCrawler] 크롤링 시작: "
            f"project_id={project_id}, code={gw_project_code}"
        )

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

            contracts = self._navigate_and_extract(page, gw_project_code)

            if contracts:
                for contract in contracts:
                    contract["project_id"] = project_id
                save_result = db.save_gw_contracts(
                    contracts, project_id=project_id
                )
                logger.info(f"[ContractCrawler] 저장 완료: {save_result}")
            else:
                logger.warning(
                    f"[ContractCrawler] 수집 결과 없음: code={gw_project_code}"
                )

            close_session(browser)
            return contracts

        except Exception as e:
            logger.error(
                f"[ContractCrawler] 크롤링 실패: {e}", exc_info=True
            )
            return []
        finally:
            pw.stop()

    def _navigate_and_extract(
        self, page, gw_project_code: str
    ) -> list[dict]:
        """
        GW 계약관리 페이지로 이동 후 데이터를 추출한다.

        TODO: GW DOM 탐색 후 확인 필요
          1. 계약관리 메뉴 경로 확인
             - 예산관리(BM) 모듈 → 계약관리 → 하도급계약현황
          2. 프로젝트 코드 필터 입력 셀렉터
             - 예: input[placeholder*="사업코드"] 또는 OBTCodePicker
          3. 조회 버튼 셀렉터
          4. 그리드 로딩 완료 대기 조건
          5. 페이지네이션 처리 필요 여부
        """
        try:
            # TODO: GW DOM 탐색 후 확인 필요 — 계약관리 페이지로 이동
            logger.debug(
                f"[ContractCrawler] 페이지 이동: {_GW_CONTRACT_URL}"
            )
            page.goto(_GW_CONTRACT_URL)
            page.wait_for_timeout(2000)

            # TODO: GW DOM 탐색 후 확인 필요 — 프로젝트 코드 필터 입력
            # 예시 패턴 (실제 셀렉터는 DOM 탐색 후 교체):
            #   page.fill('input[placeholder*="사업코드"]', gw_project_code)
            #   page.press('input[placeholder*="사업코드"]', 'Enter')
            #   page.wait_for_timeout(2000)

            # TODO: GW DOM 탐색 후 확인 필요 — 조회 버튼 클릭
            #   page.click('button:has-text("조회")')
            #   page.wait_for_timeout(2000)

            # 그리드 데이터 추출
            result = page.evaluate(_EXTRACT_CONTRACT_JS)

            if result.get("error"):
                logger.warning(
                    f"[ContractCrawler] 그리드 추출 실패: {result['error']}"
                )
                return []

            rows = result.get("rows", [])
            logger.info(f"[ContractCrawler] 추출 행 수: {len(rows)}")

            return [_map_row_to_contract(row) for row in rows]

        except Exception as e:
            logger.error(
                f"[ContractCrawler] 페이지 탐색 실패: {e}", exc_info=True
            )
            return []

    # ──────────────────────────────────────────
    # 전체 프로젝트 일괄 크롤링
    # ──────────────────────────────────────────

    def crawl_all_contracts(self, projects: list[dict]) -> dict:
        """
        여러 프로젝트의 계약 내역을 일괄 크롤링한다.
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
            logger.warning(
                "[ContractCrawler] project_code가 있는 프로젝트가 없습니다."
            )
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
                    contracts = self._navigate_and_extract(page, project_code)
                    if contracts:
                        for contract in contracts:
                            contract["project_id"] = project_id
                        db.save_gw_contracts(contracts, project_id=project_id)
                    results[project_id] = {"success": True, "count": len(contracts)}
                    logger.info(
                        f"[ContractCrawler] {project_code}: {len(contracts)}건 수집"
                    )
                except Exception as e:
                    logger.error(
                        f"[ContractCrawler] {project_code} 실패: {e}",
                        exc_info=True,
                    )
                    results[project_id] = {"success": False, "error": str(e)}

            close_session(browser)

        except Exception as e:
            logger.error(
                f"[ContractCrawler] 일괄 크롤링 실패: {e}", exc_info=True
            )
        finally:
            pw.stop()

        return results
