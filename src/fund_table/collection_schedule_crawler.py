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
from datetime import datetime

logger = logging.getLogger(__name__)

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# TODO: GW DOM 탐색 후 확인 필요 — 수금 예정 관리 페이지 URL
# 힌트: 수금 모듈(ML) → 수금예정관리 또는 수금현황 메뉴
_GW_COLLECTION_SCHEDULE_URL = (
    GW_URL + "/#/ML/MLB/MLB0000"
    "?specialLnb=Y&moduleCode=ML&menuCode=MLB&pageCode=MLB0000"
)

# TODO: GW DOM 탐색 후 확인 필요 — 수금 예정 그리드 데이터 추출 JS
# 더존 WEHAGO는 OBTDataGrid(React fiber) 또는 RealGrid를 사용할 수 있음
_EXTRACT_COLLECTION_SCHEDULE_JS = """
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

    // 시도 2: RealGrid DataProvider
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


def _map_row_to_schedule(raw: dict) -> dict:
    """
    GW 그리드 행 → 수금 예정 표준 필드 매핑.
    TODO: GW DOM 탐색 후 실제 컬럼명으로 교체 필요
    """
    return {
        # TODO: GW DOM 탐색 후 확인 필요 — 실제 컬럼명 매핑
        "scheduled_date":    raw.get("schedDt")      or raw.get("planDt")      or raw.get("예정일") or "",
        "category":          raw.get("ctgNm")         or raw.get("categoryNm")  or raw.get("구분") or "",
        "stage":             raw.get("stageNm")       or raw.get("stepNm")      or raw.get("단계") or "",
        "expected_amount":   raw.get("planAm")        or raw.get("expectAmt")   or raw.get("예정금액") or 0,
        "collected_amount":  raw.get("rcvAm")         or raw.get("rcvdAmt")     or raw.get("수금액") or 0,
        "status":            raw.get("statusNm")      or raw.get("stCdNm")      or raw.get("처리상태") or "",
        "invoice_number":    raw.get("invoiceNo")     or raw.get("taxInvNo")    or raw.get("세금계산서번호") or "",
        "description":       raw.get("remark")        or raw.get("rmk")         or raw.get("비고") or "",
    }


class CollectionScheduleCrawler:
    """
    GW 수금 예정 내역 크롤러.

    GW 수금 모듈(ML)에서 프로젝트별 수금 예정 스케줄을 수집하여 DB에 저장한다.
    수금 예정일, 예정금액, 수금완료 여부, 단계(설계/시공) 등 정보를 포함한다.
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

    def crawl_collection_schedule(
        self,
        project_id: int,
        gw_project_code: str,
    ) -> list[dict]:
        """
        단일 프로젝트의 수금 예정 내역을 크롤링하여 DB에 저장한다.

        Args:
            project_id:       fund_management.db 프로젝트 ID
            gw_project_code:  GW 사업코드 (예: GS-25-0088)

        Returns:
            list[dict]: 수집된 수금 예정 레코드 목록
        """
        from playwright.sync_api import sync_playwright
        from src.auth.login import login_and_get_context, close_session
        from src.auth.user_db import get_decrypted_password
        from src.fund_table import db

        logger.info(
            f"[CollectionScheduleCrawler] 크롤링 시작: "
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

            items = self._navigate_and_extract(page, gw_project_code)

            if items:
                for item in items:
                    item["project_id"] = project_id
                save_result = db.save_collection_schedule(items, project_id=project_id)
                logger.info(f"[CollectionScheduleCrawler] 저장 완료: {save_result}")
            else:
                logger.warning(
                    f"[CollectionScheduleCrawler] 수집 결과 없음: code={gw_project_code}"
                )

            close_session(browser)
            return items

        except Exception as e:
            logger.error(
                f"[CollectionScheduleCrawler] 크롤링 실패: {e}", exc_info=True
            )
            return []
        finally:
            pw.stop()

    def _navigate_and_extract(self, page, gw_project_code: str) -> list[dict]:
        """
        GW 수금 예정 페이지로 이동 후 데이터를 추출한다.

        TODO: GW DOM 탐색 후 확인 필요
          1. 수금 모듈(ML) 메뉴 구조 파악 (수금예정, 수금현황 등 서브메뉴 확인)
          2. 프로젝트 코드 필터 입력 셀렉터
          3. 기간 필터 조작 방법 (전체 기간 vs 연도별)
          4. 조회 버튼 셀렉터
          5. 그리드 로딩 완료 대기 조건
          6. 데이터 없을 때 표시 패턴 ("데이터가 없습니다" 등)
        """
        try:
            # TODO: GW DOM 탐색 후 확인 필요 — 수금 예정 메뉴 진입
            # 힌트: span.module-link.ML 클릭 → 수금예정관리 메뉴 이동
            logger.debug(
                f"[CollectionScheduleCrawler] 페이지 이동: {_GW_COLLECTION_SCHEDULE_URL}"
            )
            page.goto(_GW_COLLECTION_SCHEDULE_URL)
            page.wait_for_timeout(2000)

            # TODO: GW DOM 탐색 후 확인 필요 — 프로젝트 코드 필터 입력
            # 예시 패턴 (실제 셀렉터는 DOM 탐색 후 교체):
            #   page.fill('input[placeholder*="사업코드"]', gw_project_code)
            #   page.press('input[placeholder*="사업코드"]', 'Enter')

            # TODO: GW DOM 탐색 후 확인 필요 — 조회 버튼 클릭
            #   page.click('button:has-text("조회")')
            #   page.wait_for_timeout(2000)

            # 그리드 데이터 추출
            result = page.evaluate(_EXTRACT_COLLECTION_SCHEDULE_JS)

            if result.get("error"):
                logger.warning(
                    f"[CollectionScheduleCrawler] 그리드 추출 실패: {result['error']}"
                )
                return []

            rows = result.get("rows", [])
            logger.info(f"[CollectionScheduleCrawler] 추출 행 수: {len(rows)}")

            return [_map_row_to_schedule(row) for row in rows]

        except Exception as e:
            logger.error(
                f"[CollectionScheduleCrawler] 페이지 탐색 실패: {e}", exc_info=True
            )
            return []

    # ──────────────────────────────────────────
    # 전체 프로젝트 일괄 크롤링
    # ──────────────────────────────────────────

    def crawl_all_collection_schedule(self, projects: list[dict]) -> dict:
        """
        여러 프로젝트의 수금 예정 내역을 일괄 크롤링한다.
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
                "[CollectionScheduleCrawler] project_code가 있는 프로젝트가 없습니다."
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
                    items = self._navigate_and_extract(page, project_code)
                    if items:
                        for item in items:
                            item["project_id"] = project_id
                        db.save_collection_schedule(items, project_id=project_id)
                    results[project_id] = {"success": True, "count": len(items)}
                    logger.info(
                        f"[CollectionScheduleCrawler] {project_code}: {len(items)}건 수집"
                    )
                except Exception as e:
                    logger.error(
                        f"[CollectionScheduleCrawler] {project_code} 실패: {e}",
                        exc_info=True,
                    )
                    results[project_id] = {"success": False, "error": str(e)}

            close_session(browser)

        except Exception as e:
            logger.error(
                f"[CollectionScheduleCrawler] 일괄 크롤링 실패: {e}", exc_info=True
            )
        finally:
            pw.stop()

        return results
