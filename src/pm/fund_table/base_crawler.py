"""
GW 크롤러 공통 베이스 클래스
- Playwright 부팅 → 로그인 → 페이지 핸들 → 세션 종료 보일러플레이트를 공통화한다.
- 그리드 추출 JS의 시도 0/1/2 폴백 구조도 표준화한다.

각 크롤러는 다음 항목만 정의하면 된다:
  - LOG_TAG: 로그 prefix (예: "ContractCrawler")
  - GW_URL: 크롤 대상 GW 페이지 URL
  - EXTRACT_JS: 그리드 추출 JS
  - _map_row(raw) -> dict: 행 매핑 함수
  - _save_records(records, project_id) -> Any: DB 저장 함수
  - _navigate(page, gw_project_code, **kwargs): GW 페이지 진입 / 필터 조작
    (기본 구현은 단순 goto + wait_for_timeout)

기존 4개 크롤러 (Contract / TaxInvoice / PaymentApproval / CollectionSchedule)는
모두 동일한 부팅·종료 패턴이라 안전하게 이 베이스를 사용한다.

budget_crawler / project_crawler / budget_crawler_by_project 는 모듈 레벨 함수와
독자 DOM 조작 로직(팝업 닫기, 스크롤 수집, 날짜 범위 설정 등)이 깊게 얽혀 있어
이 베이스로의 통합 대상에서 제외한다.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# 그리드 추출 JS 표준 템플릿 (시도 0/1/2 폴백)
# - 각 크롤러가 이 JS를 그대로 써도 되고, 페이지 전용 JS를 직접 정의해도 된다.
# ──────────────────────────────────────────
STANDARD_GRID_EXTRACT_JS = """
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


class BaseCrawler:
    """
    GW 크롤러 공통 베이스.

    서브클래스는 다음 클래스 변수 / 메서드를 정의한다:
        LOG_TAG (str)        : 로그 prefix
        GW_URL (str)         : 대상 페이지 URL
        EXTRACT_JS (str)     : 그리드 추출 JS (기본 STANDARD_GRID_EXTRACT_JS 가능)
        _map_row(raw) -> dict          : 행 매핑
        _save_records(recs, project_id): DB 저장
        _navigate(page, code, **kw)    : (선택) 페이지 진입 / 필터 조작.
                                          기본 구현은 goto + 2초 대기.
    """

    LOG_TAG: str = "BaseCrawler"
    GW_URL: str = ""
    EXTRACT_JS: str = STANDARD_GRID_EXTRACT_JS

    def __init__(self, gw_id: str, encrypted_pw: str | None = None):
        # encrypted_pw 인자는 일부 호출부 (routes.py) 호환을 위해 받지만 사용하지 않는다.
        # 비밀번호는 _session_context() 안에서 get_decrypted_password(gw_id) 로 가져온다.
        self.gw_id = gw_id
        self.encrypted_pw = encrypted_pw

    # ────────────── 서브클래스가 오버라이드 ──────────────
    def _map_row(self, raw: dict) -> dict:
        raise NotImplementedError

    def _save_records(self, records: list[dict], project_id: int) -> Any:
        raise NotImplementedError

    def _navigate(self, page, gw_project_code: str, **kwargs) -> None:
        """기본 동작: URL 이동 + 2초 대기. 필터/조회 버튼은 서브클래스에서 확장."""
        logger.debug(f"[{self.LOG_TAG}] 페이지 이동: {self.GW_URL}")
        page.goto(self.GW_URL)
        page.wait_for_timeout(2000)

    # ────────────── 공통 세션 관리 ──────────────
    @contextmanager
    def _session_context(self):
        """Playwright 부팅 + 로그인 + cleanup 보장."""
        from playwright.sync_api import sync_playwright
        from src.shared.auth.login import login_and_get_context, close_session
        from src.shared.auth.user_db import get_decrypted_password

        gw_pw = get_decrypted_password(self.gw_id)
        if not gw_pw:
            logger.error(f"비밀번호 복호화 실패: gw_id={self.gw_id}")
            yield None
            return

        pw = sync_playwright().start()
        browser = None
        try:
            browser, context, page = login_and_get_context(
                playwright_instance=pw,
                headless=True,
                user_id=self.gw_id,
                user_pw=gw_pw,
            )
            yield page
            close_session(browser)
        except Exception as e:
            logger.error(f"[{self.LOG_TAG}] 세션 실패: {e}", exc_info=True)
            yield None
        finally:
            pw.stop()

    # ────────────── 공통 추출 ──────────────
    def extract_grid_via_js(self, page, extract_js: str | None = None) -> list[dict]:
        """
        그리드 추출 JS 실행 + 에러 처리 표준화.
        Returns: 원시 row dict 목록 (매핑 전).
        """
        js = extract_js or self.EXTRACT_JS
        result = page.evaluate(js)
        if result.get("error"):
            logger.warning(f"[{self.LOG_TAG}] 그리드 추출 실패: {result['error']}")
            return []
        rows = result.get("rows", [])
        logger.info(f"[{self.LOG_TAG}] 추출 행 수: {len(rows)}")
        return rows

    def _navigate_and_extract(self, page, gw_project_code: str, **kwargs) -> list[dict]:
        """페이지 이동 + 그리드 추출 + 행 매핑 (공통)."""
        try:
            self._navigate(page, gw_project_code, **kwargs)
            rows = self.extract_grid_via_js(page)
            return [self._map_row(r) for r in rows]
        except Exception as e:
            logger.error(f"[{self.LOG_TAG}] 페이지 탐색 실패: {e}", exc_info=True)
            return []

    # ────────────── 공통 단일/일괄 크롤 ──────────────
    def _crawl_single(
        self,
        project_id: int,
        gw_project_code: str,
        **extract_kwargs,
    ) -> list[dict]:
        """단일 프로젝트 크롤 공통 흐름."""
        logger.info(
            f"[{self.LOG_TAG}] 크롤링 시작: "
            f"project_id={project_id}, code={gw_project_code}"
        )
        with self._session_context() as page:
            if page is None:
                return []
            records = self._navigate_and_extract(page, gw_project_code, **extract_kwargs)
            if records:
                for r in records:
                    r["project_id"] = project_id
                save_result = self._save_records(records, project_id)
                logger.info(f"[{self.LOG_TAG}] 저장 완료: {save_result}")
            else:
                logger.warning(
                    f"[{self.LOG_TAG}] 수집 결과 없음: code={gw_project_code}"
                )
            return records

    def _crawl_all(self, projects: list[dict]) -> dict:
        """전체 프로젝트 일괄 크롤 공통 흐름 (세션 1회 재사용)."""
        results: dict = {}
        targets = [p for p in projects if p.get("project_code")]
        if not targets:
            logger.warning(
                f"[{self.LOG_TAG}] project_code가 있는 프로젝트가 없습니다."
            )
            return results

        with self._session_context() as page:
            if page is None:
                return results
            for proj in targets:
                project_id = proj["id"]
                project_code = proj["project_code"]
                try:
                    records = self._navigate_and_extract(page, project_code)
                    if records:
                        for r in records:
                            r["project_id"] = project_id
                        self._save_records(records, project_id)
                    results[project_id] = {"success": True, "count": len(records)}
                    logger.info(
                        f"[{self.LOG_TAG}] {project_code}: {len(records)}건 수집"
                    )
                except Exception as e:
                    logger.error(
                        f"[{self.LOG_TAG}] {project_code} 실패: {e}", exc_info=True
                    )
                    results[project_id] = {"success": False, "error": str(e)}
        return results
