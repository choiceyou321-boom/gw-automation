"""
예실대비현황(사업별) 페이지 구조 탐색 스크립트
- GW 로그인 → BM 모듈 → 예산장부 → 예실대비현황(사업별) 이동
- DatePicker, 사업코드 필드, 그리드 컬럼 등 구조 파악
- 결과를 JSON + 스크린샷으로 저장

환경변수:
  HEADLESS=false  → 브라우저 UI 표시 (디버깅용)
  GW_USER_ID      → 기본 로그인 ID (.env에서 로드)
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "config" / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("explore_budget_by_project")

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")
SCREENSHOT_DIR = PROJECT_ROOT / "data" / "approval_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
ANALYSIS_DIR = PROJECT_ROOT / "data" / "gw_analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

# OBTDataGrid 전체 데이터 추출 JS (budget_crawler.py와 동일)
_EXTRACT_GRID_DATA_JS = """
(() => {
    const grids = document.querySelectorAll('.OBTDataGrid_grid__22Vfl');
    if (!grids.length) return { error: 'grid_not_found', grids_count: 0 };

    const results = [];
    for (let gi = 0; gi < grids.length; gi++) {
        const el = grids[gi];
        const fk = Object.keys(el).find(k =>
            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
        );
        if (!fk) continue;

        let f = el[fk];
        for (let i = 0; i < 3 && f; i++) f = f.return;
        if (!f || !f.stateNode || !f.stateNode.state) continue;

        const iface = f.stateNode.state.interface;
        if (!iface) continue;

        try {
            const rowCount = iface.getRowCount();
            // leaf columns 추출 (그룹 헤더 포함 시 하위 컬럼까지)
            const allCols = iface.getColumns();
            const leafCols = [];
            const extractLeaf = (col) => {
                if (col.columns && col.columns.length > 0) {
                    col.columns.forEach(extractLeaf);
                } else {
                    leafCols.push(col);
                }
            };
            allCols.forEach(extractLeaf);

            const cols = leafCols.map(c => ({
                name: c.name || c.fieldName,
                header: c.header ? (c.header.text || c.header) : (c.name || c.fieldName),
                fieldName: c.fieldName || c.name,
                width: c.width,
                visible: c.visible !== false
            }));

            const rows = [];
            for (let r = 0; r < Math.min(rowCount, 5); r++) {
                const row = {};
                cols.forEach(col => {
                    try { row[col.name] = iface.getValue(r, col.name); } catch(e) {}
                });
                rows.push(row);
            }
            results.push({
                grid_index: gi,
                columns: cols,
                rows: rows,
                row_count: rowCount,
                sample_rows: rows.length
            });
        } catch (e) {
            results.push({ grid_index: gi, error: e.message });
        }
    }
    return { grids_count: grids.length, results: results };
})()
"""


def _save_screenshot(page, name: str):
    """디버그 스크린샷 저장"""
    try:
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path))
        logger.info(f"스크린샷: {path}")
    except Exception as e:
        logger.warning(f"스크린샷 저장 실패: {e}")


def _dismiss_alerts(page, max_tries=3):
    """OBTAlert 팝업 닫기"""
    for _ in range(max_tries):
        try:
            alert_btn = page.locator(
                ".OBTAlert_alertBoxStyle__WdE7R button, "
                ".OBTButton_labelText__1s2qO:has-text('확인')"
            )
            if alert_btn.count() > 0:
                alert_btn.first.click(timeout=2000)
                page.wait_for_timeout(500)
                logger.info("OBTAlert 팝업 닫음")
            else:
                break
        except Exception:
            break


def _close_sidebar(page):
    """좌측 사이드바 닫기"""
    try:
        page.evaluate("""
            () => {
                const sw = document.getElementById('sideWrap');
                if (sw && sw.classList.contains('on')) {
                    sw.classList.remove('on');
                }
                const toggle = document.querySelector('.sidebar-toggle, .gnb-toggle, [class*="hamburger"]');
                if (toggle) toggle.click();
            }
        """)
        logger.info("사이드바 닫기 시도")
    except Exception:
        pass


def explore():
    """예실대비현황(사업별) 페이지 탐색 메인 함수"""
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password

    headless = os.environ.get("HEADLESS", "true").lower() != "false"
    gw_id = os.environ.get("GW_USER_ID")
    if not gw_id:
        logger.error("GW_USER_ID 환경변수가 필요합니다.")
        return

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        gw_pw = os.environ.get("GW_USER_PW")
    if not gw_pw:
        logger.error(f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다.")
        return

    result = {
        "explored_at": datetime.now().isoformat(),
        "page": "예실대비현황(사업별)",
        "navigation": {},
        "datepicker": {},
        "search_fields": {},
        "grid_structure": {},
        "all_inputs": [],
    }

    pw = sync_playwright().start()
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=headless,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        # 1. 메인 페이지 이동
        page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        _dismiss_alerts(page)
        _save_screenshot(page, "explore_byprj_01_main")

        # 2. 예산관리(BM) 모듈 클릭
        bm_link = page.locator("span.module-link.BM")
        if bm_link.count() > 0:
            bm_link.first.click()
            page.wait_for_timeout(4000)
            _dismiss_alerts(page)
            _close_sidebar(page)
            page.wait_for_timeout(1000)
            result["navigation"]["bm_click"] = True
            logger.info(f"BM 모듈 클릭 후 URL: {page.url}")
            _save_screenshot(page, "explore_byprj_02_bm_module")
        else:
            logger.error("BM 모듈 링크를 찾을 수 없습니다.")
            result["navigation"]["bm_click"] = False
            return result

        # 3. 예산장부 메뉴 클릭 (하위 메뉴 펼치기)
        clicked1 = page.evaluate("""
            () => {
                const items = document.querySelectorAll('.nav-text, [class*="menu-text"], [class*="menuText"]');
                for (const el of items) {
                    if (el.textContent.trim() === '예산장부') {
                        el.click();
                        return { found: '예산장부', clicked: true };
                    }
                }
                return {
                    found: null,
                    navTexts: Array.from(items).map(el => el.textContent.trim()).filter(t => t.length > 0)
                };
            }
        """)
        logger.info(f"예산장부 메뉴 클릭 결과: {clicked1}")
        result["navigation"]["budget_book_menu"] = clicked1
        page.wait_for_timeout(2000)

        # 4. 예실대비현황(사업별) 클릭 — "사업별"이 포함된 것 우선
        clicked2 = page.evaluate("""
            () => {
                const items = document.querySelectorAll('.nav-text, [class*="menu-text"], [class*="menuText"], a, span');
                let byProjectMatch = null;
                let allMenus = [];
                for (const el of items) {
                    const txt = el.textContent.trim();
                    allMenus.push(txt);
                    if (txt === '예실대비현황(사업별)') {
                        byProjectMatch = el;
                    }
                }
                if (byProjectMatch) {
                    byProjectMatch.click();
                    return { found: '예실대비현황(사업별)', clicked: true };
                }
                return { found: null, menus: allMenus.filter(t => t.includes('예실') || t.includes('사업')) };
            }
        """)
        logger.info(f"예실대비현황(사업별) 메뉴 클릭 결과: {clicked2}")
        result["navigation"]["by_project_menu"] = clicked2
        page.wait_for_timeout(4000)
        _dismiss_alerts(page)
        _save_screenshot(page, "explore_byprj_03_page_loaded")
        logger.info(f"메뉴 클릭 후 URL: {page.url}")

        # 5. 페이지 내 모든 input 요소 정보 수집
        all_inputs = page.evaluate("""
            () => {
                const inputs = document.querySelectorAll('input');
                return Array.from(inputs).map(el => ({
                    type: el.type,
                    id: el.id,
                    name: el.name,
                    placeholder: el.placeholder,
                    className: el.className.substring(0, 100),
                    value: el.value,
                    disabled: el.disabled,
                    readOnly: el.readOnly,
                    visible: el.offsetParent !== null,
                    parentClass: el.parentElement?.className?.substring(0, 100) || '',
                    grandParentClass: el.parentElement?.parentElement?.className?.substring(0, 100) || '',
                }));
            }
        """)
        result["all_inputs"] = all_inputs
        logger.info(f"페이지 내 input 요소 {len(all_inputs)}개 발견")
        for inp in all_inputs:
            if inp.get("visible"):
                logger.info(f"  input: type={inp['type']}, placeholder='{inp['placeholder']}', "
                           f"value='{inp['value']}', id='{inp['id']}', "
                           f"parentClass='{inp['parentClass'][:60]}'")

        # 6. DatePicker 구조 파악
        datepicker_info = page.evaluate("""
            () => {
                const result = { datepickers: [], dateInputs: [] };

                // OBTDatePicker 컴포넌트 탐색
                const dp = document.querySelectorAll('[class*="OBTDatePicker"], [class*="DatePicker"], [class*="datePicker"]');
                dp.forEach((el, i) => {
                    const inputs = el.querySelectorAll('input');
                    result.datepickers.push({
                        index: i,
                        className: el.className.substring(0, 100),
                        inputCount: inputs.length,
                        inputs: Array.from(inputs).map(inp => ({
                            type: inp.type,
                            value: inp.value,
                            placeholder: inp.placeholder,
                            className: inp.className.substring(0, 80),
                        }))
                    });
                });

                // 날짜 관련 input (type=text에 날짜 형식 값)
                const allInputs = document.querySelectorAll('input[type="text"]');
                allInputs.forEach((inp, i) => {
                    const val = inp.value;
                    const ph = inp.placeholder;
                    // YYYYMMDD 또는 YYYY-MM-DD 패턴 검사
                    if (/^\\d{4}[-/]?\\d{2}[-/]?\\d{2}$/.test(val) ||
                        ph.includes('날짜') || ph.includes('일자') || ph.includes('date') ||
                        ph.includes('기간') || ph.includes('From') || ph.includes('To') ||
                        inp.parentElement?.className?.includes('Date') ||
                        inp.parentElement?.className?.includes('date')) {
                        result.dateInputs.push({
                            index: i,
                            type: inp.type,
                            value: val,
                            placeholder: ph,
                            id: inp.id,
                            className: inp.className.substring(0, 80),
                            parentClass: inp.parentElement?.className?.substring(0, 80) || '',
                        });
                    }
                });

                return result;
            }
        """)
        result["datepicker"] = datepicker_info
        logger.info(f"DatePicker: {len(datepicker_info.get('datepickers', []))}개, "
                    f"날짜 input: {len(datepicker_info.get('dateInputs', []))}개")

        # 7. 사업코드 입력 필드 구조
        search_fields = page.evaluate("""
            () => {
                const result = { searchHelp: [], codeInputs: [] };

                // OBTSearchHelp 컴포넌트
                const helps = document.querySelectorAll('[class*="OBTSearchHelp"], [class*="SearchHelp"]');
                helps.forEach((el, i) => {
                    const inputs = el.querySelectorAll('input');
                    const btns = el.querySelectorAll('button');
                    result.searchHelp.push({
                        index: i,
                        className: el.className.substring(0, 100),
                        inputCount: inputs.length,
                        buttonCount: btns.length,
                        inputs: Array.from(inputs).map(inp => ({
                            placeholder: inp.placeholder,
                            value: inp.value,
                            type: inp.type,
                        })),
                    });
                });

                // 사업코드/프로젝트코드 관련 input
                const allInputs = document.querySelectorAll('input[type="text"]');
                allInputs.forEach((inp, i) => {
                    const ph = (inp.placeholder || '').toLowerCase();
                    const name = (inp.name || '').toLowerCase();
                    if (ph.includes('사업') || ph.includes('프로젝트') || ph.includes('코드') ||
                        name.includes('pjt') || name.includes('mgt') || name.includes('code')) {
                        result.codeInputs.push({
                            index: i,
                            placeholder: inp.placeholder,
                            value: inp.value,
                            name: inp.name,
                            id: inp.id,
                            className: inp.className.substring(0, 80),
                            parentClass: inp.parentElement?.className?.substring(0, 80) || '',
                        });
                    }
                });

                return result;
            }
        """)
        result["search_fields"] = search_fields
        logger.info(f"SearchHelp: {len(search_fields.get('searchHelp', []))}개, "
                    f"코드 입력: {len(search_fields.get('codeInputs', []))}개")

        # 8. OBTDataGrid 구조 추출 (그리드 컬럼명/헤더)
        grid_data = page.evaluate(_EXTRACT_GRID_DATA_JS)
        result["grid_structure"] = grid_data
        if grid_data and grid_data.get("results"):
            for g in grid_data["results"]:
                cols = g.get("columns", [])
                logger.info(f"그리드[{g.get('grid_index')}]: "
                           f"{g.get('row_count', 0)}행, "
                           f"컬럼={[c.get('header', c.get('name', '?')) for c in cols]}")

        # 9. OBTConditionPanel 구조 (조회 조건 패널)
        condition_panel = page.evaluate("""
            () => {
                const panels = document.querySelectorAll('[class*="OBTConditionPanel"]');
                const result = [];
                panels.forEach((panel, i) => {
                    const labels = panel.querySelectorAll('label, [class*="label"], [class*="Label"]');
                    const inputs = panel.querySelectorAll('input');
                    const selects = panel.querySelectorAll('select, [class*="Combo"], [class*="combo"]');
                    result.push({
                        index: i,
                        className: panel.className.substring(0, 100),
                        labels: Array.from(labels).map(l => l.textContent.trim()).filter(t => t),
                        inputCount: inputs.length,
                        selectCount: selects.length,
                    });
                });
                return result;
            }
        """)
        result["condition_panel"] = condition_panel
        logger.info(f"조건 패널: {len(condition_panel)}개")

        _save_screenshot(page, "explore_byprj_04_final")

        # 결과 저장
        output_path = ANALYSIS_DIR / "budget_by_project_structure.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"탐색 결과 저장: {output_path}")

        close_session(browser)
        return result

    except Exception as e:
        logger.error(f"탐색 오류: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        pw.stop()


if __name__ == "__main__":
    explore()
