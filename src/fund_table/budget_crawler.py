"""
예실대비현황(상세) GW 크롤러
- Playwright로 GW 접속 → 예산관리(BM) 모듈 → 예실대비현황(상세) 페이지
- 프로젝트별 사업코드 입력 → OBTDataGrid 데이터 추출 → DB 저장

주요 함수:
  - crawl_budget_actual()   : 단일 프로젝트 전체 데이터 크롤링 (기존 함수 유지)
  - crawl_all_projects()    : 모든 프로젝트 일괄 전체 크롤링 (기존 함수 유지)
  - crawl_budget_summary()  : 단일 프로젝트 합계 전용 크롤링 (수입합계/지출합계/총잔액)
  - crawl_all_summary()     : 모든 프로젝트 합계 일괄 크롤링 (경량 버전)
"""

import os
import logging
from datetime import datetime

logger = logging.getLogger("budget_crawler")

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# OBTDataGrid 전체 데이터 추출 JS
_EXTRACT_GRID_DATA_JS = """
(() => {
    // 그리드 요소 찾기 (여러 개일 수 있으므로 모두 탐색)
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
            const cols = iface.getColumns().map(c => ({
                name: c.name,
                header: c.header ? (c.header.text || c.header) : c.name
            }));

            const rows = [];
            for (let r = 0; r < rowCount; r++) {
                const row = {};
                cols.forEach(col => {
                    row[col.name] = iface.getValue(r, col.name);
                });
                rows.push(row);
            }
            results.push({
                grid_index: gi,
                columns: cols,
                rows: rows,
                row_count: rowCount
            });
        } catch (e) {
            results.push({ grid_index: gi, error: e.message });
        }
    }
    return { grids_count: grids.length, results: results };
})()
"""

# RealGridJS 데이터 추출 JS (예실대비현황은 RealGridJS를 사용할 수 있음)
_EXTRACT_REALGRID_DATA_JS = """
(() => {
    // RealGridJS v1.0 패턴: GridView 인스턴스를 찾는다
    // 더존 WEHAGO에서는 React 컴포넌트 내부에 있을 수 있음
    const grids = document.querySelectorAll('[class*="OBTDataGrid"]');
    if (!grids.length) return { error: 'no_grid_element' };

    for (const el of grids) {
        const fk = Object.keys(el).find(k =>
            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
        );
        if (!fk) continue;

        // depth 3에서 interface, depth 12에서 form 데이터 탐색
        let f = el[fk];
        const depths = {};
        for (let i = 0; i < 15 && f; i++) {
            f = f.return;
            if (f && f.stateNode && f.stateNode.state) {
                const state = f.stateNode.state;
                const keys = Object.keys(state);
                depths[i + 1] = keys;
                // interface가 있으면 그리드 API
                if (state.interface) {
                    const iface = state.interface;
                    try {
                        const rowCount = iface.getRowCount();
                        const cols = iface.getColumns().map(c => ({
                            name: c.name,
                            header: c.header ? (c.header.text || c.header) : c.name
                        }));
                        const rows = [];
                        for (let r = 0; r < rowCount; r++) {
                            const row = {};
                            cols.forEach(col => {
                                row[col.name] = iface.getValue(r, col.name);
                            });
                            rows.push(row);
                        }
                        return { depth: i + 1, columns: cols, rows: rows, row_count: rowCount };
                    } catch(e) {
                        return { depth: i + 1, error: e.message };
                    }
                }
            }
        }
        return { error: 'no_interface', depths_found: depths };
    }
    return { error: 'no_react_fiber' };
})()
"""


def crawl_budget_actual(gw_id: str, project_id: int = None, project_code: str = None):
    """
    단일 프로젝트의 예실대비현황 크롤링.

    Args:
        gw_id: GW 로그인 ID
        project_id: fund_management.db 프로젝트 ID (저장용)
        project_code: GW 사업코드 (예: GS-25-0088)

    Returns:
        dict: { success, message, data?, error? }
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password

    if not project_code:
        return {"success": False, "error": "project_code가 필요합니다."}

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return {"success": False, "error": f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다."}

    pw = sync_playwright().start()
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        result = _navigate_and_extract(page, project_code)

        if result.get("success") and result.get("data"):
            # DB 저장
            from src.fund_table import db
            records = _transform_grid_data(result["data"], project_id, project_code)
            if records:
                # 기존 데이터 삭제 후 새로 삽입 (최신 데이터만 유지)
                _clear_old_budget(project_id)
                save_result = db.save_budget_actual(
                                    records, project_id=project_id,
                                    gw_project_code=project_code,
                                    gisu=9  # 현재 기수 (9기=2026년)
                                )
                result["saved"] = save_result
            else:
                result["message"] = "그리드 데이터를 변환할 수 없습니다."
                result["success"] = False

        close_session(browser)
        return result

    except Exception as e:
        logger.error(f"예실대비 크롤링 실패: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        pw.stop()


def crawl_all_projects(gw_id: str):
    """
    등록된 모든 프로젝트의 예실대비현황 일괄 크롤링.
    project_code가 설정된 프로젝트만 대상.

    Returns:
        dict: { success, results: [{project_id, project_name, status, message}] }
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password
    from src.fund_table import db

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return {"success": False, "error": f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다."}

    projects = db.list_projects()
    targets = [p for p in projects if p.get("project_code")]

    if not targets:
        return {"success": False, "error": "project_code가 설정된 프로젝트가 없습니다."}

    pw = sync_playwright().start()
    results = []
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        for proj in targets:
            pid = proj["id"]
            pcode = proj["project_code"]
            pname = proj.get("name", "")
            logger.info(f"크롤링 시작: {pname} ({pcode})")

            try:
                result = _navigate_and_extract(page, pcode)
                if result.get("success") and result.get("data"):
                    records = _transform_grid_data(result["data"], pid, pcode)
                    if records:
                        _clear_old_budget(pid)
                        db.save_budget_actual(records, project_id=pid)
                        results.append({
                            "project_id": pid, "project_name": pname,
                            "status": "success", "message": f"{len(records)}건 저장",
                        })
                    else:
                        results.append({
                            "project_id": pid, "project_name": pname,
                            "status": "fail", "message": "데이터 변환 실패",
                        })
                else:
                    results.append({
                        "project_id": pid, "project_name": pname,
                        "status": "fail", "message": result.get("error", "추출 실패"),
                    })
            except Exception as e:
                logger.error(f"프로젝트 {pname} 크롤링 오류: {e}")
                results.append({
                    "project_id": pid, "project_name": pname,
                    "status": "error", "message": str(e),
                })

        close_session(browser)
    except Exception as e:
        logger.error(f"일괄 크롤링 실패: {e}", exc_info=True)
        return {"success": False, "error": str(e), "results": results}
    finally:
        pw.stop()

    success_count = sum(1 for r in results if r["status"] == "success")
    return {
        "success": True,
        "message": f"{success_count}/{len(targets)} 프로젝트 크롤링 완료",
        "results": results,
    }


def _dismiss_alerts(page, max_tries=3):
    """OBTAlert 팝업 닫기 (확인 버튼 반복 클릭)"""
    for _ in range(max_tries):
        try:
            alert_btn = page.locator(".OBTAlert_alertBoxStyle__WdE7R button, .OBTButton_labelText__1s2qO:has-text('확인')")
            if alert_btn.count() > 0:
                alert_btn.first.click(timeout=2000)
                page.wait_for_timeout(500)
                logger.info("OBTAlert 팝업 닫음")
            else:
                break
        except Exception:
            break


def _close_sidebar(page):
    """좌측 사이드바 닫기 (오버레이 차단 방지)"""
    try:
        # 사이드바 토글 버튼 또는 sideWrap 비활성화
        page.evaluate("""
            () => {
                const sw = document.getElementById('sideWrap');
                if (sw && sw.classList.contains('on')) {
                    sw.classList.remove('on');
                }
                // 또는 사이드바 토글 버튼 클릭
                const toggle = document.querySelector('.sidebar-toggle, .gnb-toggle, [class*="hamburger"]');
                if (toggle) toggle.click();
            }
        """)
        logger.info("사이드바 닫기 시도")
    except Exception:
        pass


def _navigate_and_extract(page, project_code: str) -> dict:
    """
    예실대비현황(상세) 페이지 네비게이션 + 데이터 추출.
    이미 로그인된 page 객체를 받아 사용.
    """
    try:
        # 방법 A: BM 모듈 메뉴 클릭 네비게이션 (가장 안정적)
        logger.info("예실대비현황(상세) 페이지 이동 중 (BM 모듈 경유)...")
        page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        _dismiss_alerts(page)

        page_loaded = False

        # 예산관리 모듈 클릭
        bm_link = page.locator("span.module-link.BM")
        if bm_link.count() > 0:
            bm_link.first.click()
            page.wait_for_timeout(4000)
            _dismiss_alerts(page)
            logger.info(f"BM 모듈 클릭 후 URL: {page.url}")

            # 사이드바가 오버레이로 클릭을 차단하면 닫기
            _close_sidebar(page)
            page.wait_for_timeout(1000)

            # 좌측 메뉴 탐색 (JS force click으로 오버레이 무시)
            # 예산장부 → 예실대비현황(상세) 순서로 클릭
            clicked = page.evaluate("""
                () => {
                    // 예산장부 메뉴 찾아서 클릭 (하위 메뉴 펼치기)
                    const items = document.querySelectorAll('.nav-text, [class*="menu-text"], [class*="menuText"]');
                    let budgetBook = null;
                    for (const el of items) {
                        if (el.textContent.trim() === '예산장부') {
                            budgetBook = el;
                            break;
                        }
                    }
                    if (budgetBook) {
                        budgetBook.click();
                        return { found: '예산장부', clicked: true };
                    }
                    // 모든 nav-text 목록 반환 (디버깅용)
                    return {
                        found: null,
                        navTexts: Array.from(items).map(el => el.textContent.trim()).filter(t => t.length > 0)
                    };
                }
            """)
            logger.info(f"예산장부 메뉴 JS 클릭 결과: {clicked}")
            page.wait_for_timeout(2000)

            # 예실대비현황(상세) 클릭 — "상세"가 포함된 것을 우선 선택
            clicked2 = page.evaluate("""
                () => {
                    const items = document.querySelectorAll('.nav-text, [class*="menu-text"], [class*="menuText"], a, span');
                    let detailMatch = null;
                    let normalMatch = null;
                    for (const el of items) {
                        const txt = el.textContent.trim();
                        if (txt === '예실대비현황(상세)') {
                            detailMatch = el;
                        } else if (txt === '예실대비현황' && !normalMatch) {
                            normalMatch = el;
                        }
                    }
                    const target = detailMatch || normalMatch;
                    if (target) {
                        target.click();
                        return { found: target.textContent.trim(), clicked: true };
                    }
                    return { found: null };
                }
            """)
            logger.info(f"예실대비현황 메뉴 JS 클릭 결과: {clicked2}")
            page.wait_for_timeout(4000)
            _dismiss_alerts(page)
            _save_screenshot(page, "budget_after_menu_click")
            logger.info(f"메뉴 클릭 후 URL: {page.url}")

            page_loaded = _verify_budget_page(page)
        else:
            logger.warning("BM 모듈 링크를 찾을 수 없습니다.")

        if not page_loaded:
            # 방법 B: iframe 내부 확인 (WEHAGO는 iframe 구조일 수 있음)
            logger.info("메뉴 네비게이션 실패, iframe/탭 확인 중...")
            _save_screenshot(page, "budget_checking_iframes")

            # 모든 iframe 내에서 사업코드 필드 확인
            for i, frame in enumerate(page.frames):
                try:
                    fi = frame.locator("input[placeholder*='사업코드'], [class*='OBTDataGrid']")
                    if fi.count() > 0:
                        logger.info(f"iframe[{i}]에서 예산 페이지 컨텐츠 발견: {frame.url}")
                        page_loaded = True
                        break
                except Exception:
                    continue

        if not page_loaded:
            _save_screenshot(page, "budget_page_not_found")
            # 디버깅: 현재 페이지 구조 수집
            page_info = page.evaluate("""
                () => ({
                    url: location.href,
                    title: document.title,
                    iframes: Array.from(document.querySelectorAll('iframe')).map(f => f.src),
                    modules: Array.from(document.querySelectorAll('.module-link')).map(m => m.className + ':' + m.textContent),
                    menus: Array.from(document.querySelectorAll('[class*="menu"], [class*="Menu"]')).slice(0, 10).map(m => m.className + ':' + m.textContent?.substring(0, 50))
                })
            """)
            logger.warning(f"페이지 구조: {page_info}")
            return {
                "success": False,
                "error": "예실대비현황(상세) 페이지를 찾을 수 없습니다.",
                "url": page.url,
                "page_info": page_info,
            }

        # 프로젝트 코드 입력
        search_result = _search_project(page, project_code)
        if not search_result.get("success"):
            return search_result

        # 조회 실행
        _click_search_button(page)
        page.wait_for_timeout(5000)  # 데이터 로드 대기 (5초)

        # 그리드 데이터 추출
        data = _extract_data(page)
        if data.get("error"):
            _save_screenshot(page, f"budget_extract_error_{project_code}")
            return {"success": False, "error": data["error"], "raw": data}

        if not data.get("rows") and not data.get("results"):
            _save_screenshot(page, f"budget_no_data_{project_code}")
            return {"success": False, "error": "그리드에 데이터가 없습니다.", "raw": data}

        return {"success": True, "data": data, "project_code": project_code}

    except Exception as e:
        _save_screenshot(page, "budget_exception")
        logger.error(f"네비게이션/추출 오류: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _verify_budget_page(page) -> bool:
    """예실대비현황(상세) 페이지 로드 확인 — 실제 컨텐츠 기반"""
    try:
        # 그리드가 있으면 예산 페이지 로드됨
        grid = page.locator("[class*='OBTDataGrid']")
        if grid.count() > 0:
            logger.info("예실대비현황 페이지 확인: OBTDataGrid 발견")
            return True

        # 사업코드 입력 필드 존재 확인
        code_input = page.locator("input[placeholder*='사업코드']")
        if code_input.count() > 0:
            logger.info("예실대비현황 페이지 확인: 사업코드 입력 필드 발견")
            return True

        # 예산 관련 텍스트가 페이지 본문(메뉴/탭 제외)에 있는지
        budget_text = page.locator(".content-area :text('예실대비'), .tab-content :text('예실대비'), .OBTTitle :text('예실대비')")
        if budget_text.count() > 0:
            logger.info("예실대비현황 페이지 확인: 예실대비 텍스트 발견")
            return True

    except Exception as e:
        logger.debug(f"페이지 확인 오류: {e}")

    return False


def _search_project(page, project_code: str) -> dict:
    """사업코드 검색 입력"""
    try:
        _dismiss_alerts(page)

        # 페이지 내 사업코드 입력 필드 탐색 (통합검색 #search_input 제외)
        # 방법 1: placeholder '사업코드도움' 또는 '사업코드'
        search_input = page.locator("input[placeholder*='사업코드']:not(#search_input):not(#searchInput)")
        if search_input.count() == 0:
            # 방법 2: 프로젝트코드 도움 필드
            search_input = page.locator("input[placeholder*='프로젝트']:not(#search_input)")
        if search_input.count() == 0:
            # 방법 3: OBTSearchHelp 컴포넌트 내 input
            search_input = page.locator("[class*='OBTSearchHelp'] input[type='text']")
        if search_input.count() == 0:
            # 방법 4: 조건 패널 내 input (통합검색 제외)
            search_input = page.locator("[class*='OBTConditionPanel'] input[type='text'], [class*='conditionPanel'] input[type='text']")

        if search_input.count() == 0:
            # 디버깅: 페이지의 모든 input 정보 수집
            all_inputs = page.evaluate("""
                () => {
                    const inputs = document.querySelectorAll('input[type="text"]');
                    return Array.from(inputs).map(el => ({
                        placeholder: el.placeholder,
                        id: el.id,
                        name: el.name,
                        className: el.className,
                        value: el.value,
                        visible: el.offsetParent !== null
                    }));
                }
            """)
            logger.warning(f"사업코드 필드 미발견. 페이지 내 text inputs: {all_inputs}")
            _save_screenshot(page, "budget_no_search_input")
            return {"success": False, "error": "사업코드 입력 필드를 찾을 수 없습니다.", "inputs_found": all_inputs}

        logger.info(f"사업코드 입력 필드 {search_input.count()}개 발견")

        # OBTSearchHelp 패턴: 입력 → 엔터 또는 돋보기 클릭 → 팝업에서 선택
        # 방법 1: 입력 후 엔터 (자동완성 트리거)
        search_input.first.click(timeout=5000)
        search_input.first.fill("")
        page.wait_for_timeout(300)
        search_input.first.fill(project_code)
        page.wait_for_timeout(500)
        search_input.first.press("Enter")
        page.wait_for_timeout(2000)
        _dismiss_alerts(page)

        # 도움 팝업/그리드가 뜨면 첫 번째 항목 선택
        popup_selected = _select_search_popup_item(page, project_code)

        if not popup_selected:
            # 방법 2: 돋보기 아이콘 클릭으로 검색 도움 팝업 오픈
            logger.info("엔터 후 팝업 미발생, 돋보기 아이콘 클릭 시도...")
            search_icon = page.evaluate("""
                () => {
                    // 사업코드 입력 필드 근처의 검색 아이콘 버튼
                    const inputs = document.querySelectorAll("input[placeholder*='사업코드']");
                    for (const inp of inputs) {
                        if (inp.id === 'search_input' || inp.id === 'searchInput') continue;
                        // 형제 또는 부모의 검색 버튼
                        const parent = inp.closest('[class*="OBTSearchHelp"], [class*="searchHelp"]') || inp.parentElement;
                        if (parent) {
                            const btn = parent.querySelector('button, [class*="searchIcon"], [class*="SearchIcon"]');
                            if (btn) { btn.click(); return { clicked: true }; }
                        }
                        // 바로 다음 형제 버튼
                        const next = inp.nextElementSibling;
                        if (next && (next.tagName === 'BUTTON' || next.querySelector('button'))) {
                            (next.querySelector('button') || next).click();
                            return { clicked: true };
                        }
                    }
                    // 조건 패널 내 돋보기 버튼 (🔍)
                    const magnifiers = document.querySelectorAll('.OBTConditionPanel_searchIcon, [class*="magnif"], [class*="search-icon"]');
                    if (magnifiers.length > 0) {
                        magnifiers[0].click();
                        return { clicked: true, method: 'magnifier' };
                    }
                    return { clicked: false };
                }
            """)
            logger.info(f"돋보기 클릭 결과: {search_icon}")

            if search_icon.get("clicked"):
                page.wait_for_timeout(2000)
                _dismiss_alerts(page)
                popup_selected = _select_search_popup_item(page, project_code)

        if not popup_selected:
            # 입력 필드에 값이 이미 설정되었는지 확인
            field_value = search_input.first.input_value()
            logger.info(f"현재 사업코드 필드 값: '{field_value}'")

            if project_code in str(field_value):
                logger.info("자동완성으로 프로젝트 코드가 이미 설정됨")
            else:
                # 방법 3: 돋보기 클릭으로 팝업 오픈, 팝업 내 검색 후 선택
                logger.info("사업코드 미설정, 재시도...")
                _save_screenshot(page, "budget_code_not_set")
                return {"success": False, "error": f"사업코드 입력 실패. 필드값: '{field_value}'"}

        # 팝업이 남아있으면 모두 닫기 (ESC 또는 빈 영역 클릭)
        _dismiss_search_popups(page)
        page.wait_for_timeout(500)

        return {"success": True}

    except Exception as e:
        _save_screenshot(page, "budget_search_error")
        return {"success": False, "error": f"프로젝트 검색 오류: {e}"}


def _select_search_popup_item(page, project_code: str) -> bool:
    """
    OBTSearchHelp 팝업의 OBTDataGrid에서 해당 코드 행을 선택.
    팝업 그리드는 OBTDataGrid API를 사용하므로, React fiber로 접근하여
    코드가 일치하는 행을 setSelection + commit으로 선택.
    """
    try:
        # 팝업이 있는지 확인
        portal = page.locator(".OBTPortal_orbitPortalRoot__3FIEo, [class*='OBTDialog'], [class*='OBTPopup']")
        if portal.count() == 0:
            logger.info("검색 도움 팝업 미발견")
            return False

        _save_screenshot(page, "budget_search_popup")
        logger.info(f"검색 팝업 발견: {portal.count()}개")

        # 팝업 내 그리드에서 project_code 행을 찾아 더블클릭
        result = page.evaluate("""
            (code) => {
                // 팝업 내 모든 OBTDataGrid 탐색
                const portals = document.querySelectorAll('.OBTPortal_orbitPortalRoot__3FIEo');
                for (const portal of portals) {
                    const grids = portal.querySelectorAll('[class*="OBTDataGrid"]');
                    for (const el of grids) {
                        const fk = Object.keys(el).find(k =>
                            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                        );
                        if (!fk) continue;

                        let f = el[fk];
                        for (let i = 0; i < 5 && f; i++) f = f.return;
                        if (!f?.stateNode?.state?.interface) {
                            // depth 3 재시도
                            f = el[fk];
                            for (let i = 0; i < 3 && f; i++) f = f.return;
                        }
                        if (!f?.stateNode?.state?.interface) continue;

                        const iface = f.stateNode.state.interface;
                        const rowCount = iface.getRowCount();

                        // mgtCd 또는 pjtCd 컬럼에서 코드 찾기
                        for (let r = 0; r < rowCount; r++) {
                            let val = '';
                            try { val = iface.getValue(r, 'mgtCd'); } catch(e) {}
                            if (!val) try { val = iface.getValue(r, 'pjtCd'); } catch(e) {}

                            if (val === code) {
                                // 해당 행 선택 후 더블클릭 이벤트 발생
                                try {
                                    iface.setSelection({ startRow: r, endRow: r, startColumn: 0, endColumn: 0 });
                                    iface.focus();
                                } catch(e) {}

                                // canvas 더블클릭 (OBTDataGrid는 canvas 기반)
                                const canvas = el.querySelector('canvas');
                                if (canvas) {
                                    // 행 높이 계산 (대략 30px, 헤더 30px)
                                    const y = 30 + r * 30 + 15;
                                    const x = 50;
                                    canvas.dispatchEvent(new MouseEvent('dblclick', {
                                        bubbles: true, clientX: x, clientY: canvas.getBoundingClientRect().top + y
                                    }));
                                }

                                return { found: true, row: r, code: val };
                            }
                        }
                        return { found: false, rowCount: rowCount, searched: code };
                    }
                }
                return { found: false, noGrid: true };
            }
        """, project_code)
        logger.info(f"팝업 그리드 행 선택 결과: {result}")

        if result.get("found"):
            page.wait_for_timeout(1500)
            # 팝업이 닫혔는지 확인, 안 닫혔으면 확인 버튼 클릭
            if portal.count() > 0:
                page.evaluate("""
                    () => {
                        const portals = document.querySelectorAll('.OBTPortal_orbitPortalRoot__3FIEo');
                        for (const p of portals) {
                            const btns = p.querySelectorAll('button');
                            for (const btn of btns) {
                                if (btn.textContent.trim() === '확인' || btn.textContent.trim() === '선택') {
                                    btn.click();
                                    return true;
                                }
                            }
                        }
                        return false;
                    }
                """)
                page.wait_for_timeout(1000)
            return True

        return False

    except Exception as e:
        logger.warning(f"팝업 선택 오류: {e}")
        return False


def _dismiss_search_popups(page):
    """검색 도움 팝업/포탈 모두 닫기"""
    try:
        page.evaluate("""
            () => {
                // OBTPortal 내 닫기/취소 버튼 클릭
                const portals = document.querySelectorAll('.OBTPortal_orbitPortalRoot__3FIEo');
                for (const p of portals) {
                    // 닫기 버튼(X) 찾기
                    const closeBtn = p.querySelector('[class*="close"], [class*="Close"], button[title="닫기"]');
                    if (closeBtn) { closeBtn.click(); continue; }
                    // 취소 버튼
                    const btns = p.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.textContent.trim() === '취소' || btn.textContent.trim() === '닫기') {
                            btn.click();
                            break;
                        }
                    }
                }
            }
        """)
        # ESC로도 닫기 시도
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        logger.info("검색 팝업 닫기 완료")
    except Exception:
        pass


def _click_search_button(page):
    """조회 버튼 클릭 (JS force click으로 숨겨진 버튼도 처리)"""
    result = page.evaluate("""
        () => {
            // OBTConditionPanel 조회 버튼
            const searchBtn = document.querySelector('.OBTConditionPanel_searchButton__2cpwg');
            if (searchBtn) {
                searchBtn.click();
                return { method: 'OBTConditionPanel_searchButton', clicked: true };
            }
            // 일반 조회 버튼
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                const txt = btn.textContent.trim();
                if (txt === '조회' || txt === '검색') {
                    btn.click();
                    return { method: 'text_match', text: txt, clicked: true };
                }
            }
            return { clicked: false };
        }
    """)
    logger.info(f"조회 버튼 JS 클릭: {result}")
    if not result.get("clicked"):
        logger.info("조회 버튼 못 찾음, 엔터 키 사용")
        page.keyboard.press("Enter")


def _extract_data(page) -> dict:
    """
    그리드 데이터 추출 (window.Grids DataProvider → OBTDataGrid → RealGrid 순서 시도).
    예산 관련 컬럼이 있는 그리드만 선택 (팝업 그리드 제외).
    """
    # 시도 0: window.Grids.getActiveGrid().getDataProvider() — RealGrid v1.0 직접 접근
    # GW 예실대비현황(상세) 페이지에서 실제 동작이 확인된 방법
    data0 = page.evaluate("""
        (() => {
            try {
                const Grids = window.Grids;
                if (!Grids || typeof Grids.getActiveGrid !== 'function') {
                    return { error: 'Grids_not_found' };
                }
                const activeGrid = Grids.getActiveGrid();
                if (!activeGrid) return { error: 'no_active_grid' };

                const dp = activeGrid.getDataProvider ? activeGrid.getDataProvider() : null;
                if (!dp) return { error: 'no_data_provider' };

                const rowCount = dp.getRowCount ? dp.getRowCount() : 0;
                if (rowCount === 0) return { error: 'empty_grid', rowCount: 0 };

                const rows = [];
                for (let i = 0; i < rowCount; i++) {
                    const row = dp.getJsonRow ? dp.getJsonRow(i) : null;
                    if (row) rows.push(row);
                }

                // 컬럼 정보
                const cols = rows.length > 0
                    ? Object.keys(rows[0]).map(k => ({ name: k, header: k }))
                    : [];

                return {
                    source: 'window.Grids.DataProvider',
                    row_count: rows.length,
                    columns: cols,
                    rows: rows
                };
            } catch(e) {
                return { error: 'exception: ' + e.message };
            }
        })()
    """)
    if data0 and not data0.get("error") and data0.get("rows"):
        logger.info(f"시도 0 성공 (window.Grids DataProvider): rows={data0.get('row_count')}")
        return data0
    else:
        logger.info(f"시도 0 실패: {data0.get('error') if data0 else 'null'}")

    # 예산 그리드 식별용 키워드
    budget_keywords = {"예산", "집행", "잔액", "대비", "과목", "budget", "actual"}

    def _is_budget_grid(grid):
        """컬럼 헤더에 예산 관련 키워드가 있는지 확인"""
        cols = grid.get("columns", [])
        for col in cols:
            header = str(col.get("header", ""))
            if any(kw in header for kw in budget_keywords):
                return True
        return False

    # 시도 1: OBTDataGrid 패턴
    data = page.evaluate(_EXTRACT_GRID_DATA_JS)
    if data and not data.get("error") and data.get("results"):
        # 예산 그리드를 우선 선택
        for grid in data["results"]:
            if grid.get("rows") and _is_budget_grid(grid):
                logger.info(f"예산 그리드 발견 (grid_index={grid.get('grid_index')})")
                return grid

        # 예산 키워드 없는 그리드 중 데이터 있는 것 (fallback, 빈 그리드는 스킵)
        for grid in data["results"]:
            if grid.get("rows") and len(grid["rows"]) > 0:
                col_headers = [c.get("header", "") for c in grid.get("columns", [])]
                logger.info(f"비예산 그리드 선택 (fallback, headers={col_headers[:5]})")
                return grid

        # 모든 OBTDataGrid가 비어있음 → 시도 2/3으로 진행
        logger.info(f"OBTDataGrid {len(data['results'])}개 모두 빈 그리드, RealGrid 패턴 시도...")

    # 시도 2: RealGridJS v1.0 패턴 (깊은 depth 탐색)
    data2 = page.evaluate(_EXTRACT_REALGRID_DATA_JS)
    if data2 and not data2.get("error") and data2.get("rows"):
        return data2

    # 시도 3: React state에서 detailList/grid1 직접 접근 (depth 12~13)
    data3 = page.evaluate("""
        (() => {
            const grids = document.querySelectorAll('[class*="OBTDataGrid"]');
            for (const el of grids) {
                const fk = Object.keys(el).find(k =>
                    k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                );
                if (!fk) continue;

                let f = el[fk];
                for (let d = 0; d < 15 && f; d++) {
                    f = f.return;
                    if (!f?.stateNode?.state) continue;
                    const state = f.stateNode.state;

                    // detailList가 있으면 예실대비 상세 데이터
                    if (state.detailList && Array.isArray(state.detailList) && state.detailList.length > 0) {
                        const rows = state.detailList;
                        // 첫 번째 행의 키를 컬럼으로 사용
                        const colNames = Object.keys(rows[0]);
                        const columns = colNames.map(k => ({ name: k, header: k }));

                        // 합계 데이터도 가져오기
                        const extra = {};
                        if (state.addSumList) extra.addSumList = state.addSumList;
                        if (state.subSumList) extra.subSumList = state.subSumList;
                        if (state.totSumList) extra.totSumList = state.totSumList;

                        return {
                            depth: d + 1,
                            source: 'state.detailList',
                            columns: columns,
                            rows: rows,
                            row_count: rows.length,
                            summary: extra
                        };
                    }

                    // interface에 getRowCount가 있고 > 0이면 시도
                    if (state.interface && typeof state.interface.getRowCount === 'function') {
                        try {
                            const iface = state.interface;
                            const rowCount = iface.getRowCount();
                            if (rowCount === 0) continue;

                            // DataProvider에서 전체 필드와 JSON 데이터 가져오기
                            let ds = null;
                            try { ds = iface.getDataSource ? iface.getDataSource() : null; } catch(e) {}

                            if (ds && ds.getJsonRows) {
                                // DataProvider.getJsonRows()로 전체 데이터 가져오기
                                try {
                                    const jsonRows = ds.getJsonRows(0, -1);
                                    if (jsonRows && jsonRows.length > 0) {
                                        const fieldNames = Object.keys(jsonRows[0]);
                                        const cols = fieldNames.map(n => ({ name: n, header: n }));
                                        return {
                                            depth: d + 1,
                                            source: 'DataProvider.getJsonRows',
                                            columns: cols,
                                            rows: jsonRows,
                                            row_count: jsonRows.length
                                        };
                                    }
                                } catch(e) {}
                            }

                            // fallback: getFieldNames + getValue
                            let cols = [];
                            if (ds && ds.getFieldNames) {
                                try {
                                    const fieldNames = ds.getFieldNames();
                                    cols = fieldNames.map(n => ({ name: n, header: n }));
                                } catch(e) {}
                            }
                            if (cols.length === 0) {
                                // getColumns()의 leaf columns만 추출
                                try {
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
                                    cols = leafCols.map(c => ({
                                        name: c.name || c.fieldName,
                                        header: c.header ? (c.header.text || c.header) : (c.name || c.fieldName)
                                    }));
                                } catch(e) {}
                            }

                            if (cols.length > 0) {
                                const rows = [];
                                for (let r = 0; r < rowCount; r++) {
                                    const row = {};
                                    cols.forEach(col => {
                                        try { row[col.name] = iface.getValue(r, col.name); } catch(e) {}
                                    });
                                    rows.push(row);
                                }
                                return { depth: d + 1, source: 'interface+fieldNames', columns: cols, rows: rows, row_count: rowCount };
                            }
                        } catch(e) { continue; }
                    }
                }
            }

            return { error: 'no_data_found' };
        })()
    """)
    if data3 and not data3.get("error") and data3.get("rows"):
        logger.info(f"시도 3 성공: depth={data3.get('depth')}, rows={data3.get('row_count')}")
        return data3

    # 둘 다 실패 — 디버깅 정보 수집
    debug_info = page.evaluate("""
        (() => {
            const grids = document.querySelectorAll('[class*="OBTDataGrid"]');
            const info = [];
            for (const el of grids) {
                const fk = Object.keys(el).find(k =>
                    k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                );
                if (!fk) { info.push({no_fiber: true}); continue; }
                let f = el[fk];
                const depths = {};
                for (let d = 0; d < 15 && f; d++) {
                    f = f.return;
                    if (f?.stateNode?.state) {
                        const keys = Object.keys(f.stateNode.state);
                        depths[d+1] = keys;
                        if (f.stateNode.state.interface) {
                            try {
                                depths[d+1 + '_rowCount'] = f.stateNode.state.interface.getRowCount();
                            } catch(e) {
                                depths[d+1 + '_error'] = e.message;
                            }
                        }
                    }
                }
                info.push({depths});
            }
            return info;
        })()
    """)
    logger.warning(f"그리드 디버깅: {debug_info}")

    return {
        "error": "그리드 데이터 추출 실패",
        "obtgrid_result": data,
        "realgrid_result": data2,
        "deep_search": data3,
        "debug": debug_info,
    }


def _transform_grid_data(data: dict, project_id: int, project_code: str) -> list[dict]:
    """
    그리드 원시 데이터를 budget_actual 레코드로 변환.
    컬럼명은 GW 시스템에 따라 다를 수 있으므로 유연하게 매핑.
    """
    rows = data.get("rows", [])
    columns = data.get("columns", [])
    if not rows:
        return []

    # 컬럼명 매핑 (GW 시스템의 실제 컬럼명은 탐색 후 확인 필요)
    col_map = _build_column_mapping(columns)

    records = []
    current_year = datetime.now().year
    for row in rows:
        category = _get_mapped_value(row, col_map, "category", "")
        budget_code = _get_mapped_value(row, col_map, "budget_code", "")
        sub_category = _get_mapped_value(row, col_map, "sub_category", "")
        budget_amt = _parse_number(_get_mapped_value(row, col_map, "budget_amount", 0))
        actual_amt = _parse_number(_get_mapped_value(row, col_map, "actual_amount", 0))
        diff = _parse_number(_get_mapped_value(row, col_map, "difference", 0))
        rate = _parse_float(_get_mapped_value(row, col_map, "execution_rate", 0))

        # GW RealGrid DataProvider 원본 필드 직접 접근
        bgt_cd    = row.get("bgtCd", str(budget_code))
        bgt_nm    = row.get("bgtNm", str(sub_category))
        def_nm    = row.get("defNm", str(category))       # 장/관/항/목
        div_fg    = int(row.get("divFg", 0) or 0)         # 구분 플래그
        is_leaf   = 1 if (row.get("lastYn") == "Y") else 0
        bottom_fg = int(row.get("bottomFg", 1) or 1)

        # 빈 행 스킵 (상위 집계 행 포함, bottomFg=1이면 상위)
        if not bgt_cd and budget_amt == 0 and actual_amt == 0:
            continue

        records.append({
            "project_id": project_id,
            "project_name": project_code,
            "year": current_year,
            "budget_code": bgt_cd,
            "budget_category": def_nm or str(category),
            "budget_sub_category": bgt_nm or str(sub_category),
            "budget_amount": budget_amt,
            "actual_amount": actual_amt,
            "difference": diff if diff != 0 else budget_amt - actual_amt,
            "execution_rate": rate if rate else (actual_amt / budget_amt * 100 if budget_amt else 0),
            # GW 전용 필드
            "gw_project_code": project_code,
            "def_nm": def_nm,
            "div_fg": div_fg,
            "is_leaf": is_leaf,
        })

    return records


def _build_column_mapping(columns: list[dict]) -> dict:
    """
    그리드 컬럼 → 표준 필드 매핑.
    GW 실제 필드명 기반 매핑 (RealGrid DataProvider 필드명).
    """
    mapping = {}

    # GW 예실대비현황(상세) 실제 필드명 직접 매핑
    # defNm=과목구분, bgtCd=예산과목코드, bgtNm=예산과목명
    # abgtSumAm=예산액, unitAm=집행액, subAm=잔액, sumRt=대비(%)
    # T0*=전체프로젝트 기준 (프로젝트 필터 없을 때 동일)
    direct_map = {
        "defNm": "category",
        "bgtCd": "budget_code",          # 예산과목코드 (2xxxxx)
        "bgtNm": "sub_category",
        "abgtSumAm": "budget_amount",
        "unitAm": "actual_amount",
        "subAm": "difference",
        "sumRt": "execution_rate",
    }

    for col in columns:
        name = col.get("name", "")
        header = str(col.get("header", "")).strip()

        # 직접 매핑 (GW 필드명)
        if name in direct_map:
            mapping[direct_map[name]] = name
            continue

        # 헤더 텍스트 기반 매핑 (fallback)
        if any(kw in header for kw in ["과목구분", "구분", "분류"]):
            mapping.setdefault("category", name)
        elif any(kw in header for kw in ["예산과목명", "과목명", "항목명"]):
            mapping.setdefault("sub_category", name)
        elif any(kw in header for kw in ["예산과목코드", "과목코드"]):
            mapping.setdefault("budget_code", name)
        elif any(kw in header for kw in ["예산액", "예산금액", "배정"]):
            mapping.setdefault("budget_amount", name)
        elif any(kw in header for kw in ["집행액", "실행액", "사용"]):
            mapping.setdefault("actual_amount", name)
        elif any(kw in header for kw in ["잔액", "잔여"]):
            mapping.setdefault("difference", name)
        elif any(kw in header for kw in ["대비", "집행률", "비율", "실행율"]):
            mapping.setdefault("execution_rate", name)

    return mapping


def _get_mapped_value(row: dict, col_map: dict, field: str, default):
    """매핑된 컬럼명으로 행에서 값 가져오기"""
    col_name = col_map.get(field)
    if col_name and col_name in row:
        return row[col_name]
    return default


def _parse_number(val) -> int:
    """숫자 파싱 (문자열, 콤마 포함 등)"""
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        cleaned = val.replace(",", "").replace(" ", "").strip()
        if not cleaned or cleaned == "-":
            return 0
        try:
            return int(float(cleaned))
        except ValueError:
            return 0
    return 0


def _parse_float(val) -> float:
    """실수 파싱"""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = val.replace(",", "").replace("%", "").replace(" ", "").strip()
        if not cleaned or cleaned == "-":
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def _clear_old_budget(project_id: int, gisu: int = None):
    """기존 예실대비 데이터 삭제 (최신 데이터로 대체). gisu 지정 시 해당 기수만 삭제."""
    if not project_id:
        return
    from src.fund_table.db import get_db
    conn = get_db()
    try:
        if gisu:
            conn.execute(
                "DELETE FROM budget_actual WHERE project_id = ? AND gisu = ?",
                (project_id, gisu),
            )
        else:
            conn.execute("DELETE FROM budget_actual WHERE project_id = ?", (project_id,))
        conn.commit()
    finally:
        conn.close()


def crawl_budget_summary(gw_id: str, project_id: int = None, project_code: str = None):
    """
    단일 프로젝트의 예실대비현황(상세)에서 합계 데이터만 추출.
    수입합계, 지출합계, 총잔액 행만 추출하여 projects 테이블에 보충 저장.

    Args:
        gw_id: GW 로그인 ID
        project_id: fund_management.db 프로젝트 ID
        project_code: GW 사업코드

    Returns:
        dict: { success, summary: { income_total, expense_total, total_balance }, error? }
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password

    if not project_code:
        return {"success": False, "error": "project_code가 필요합니다."}

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return {"success": False, "error": f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다."}

    pw = sync_playwright().start()
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        result = _navigate_and_extract(page, project_code)

        summary = {"income_total": 0, "expense_total": 0, "total_balance": 0}

        if result.get("success") and result.get("data"):
            data = result["data"]
            rows = data.get("rows", [])
            columns = data.get("columns", [])
            col_map = _build_column_mapping(columns)

            # 합계 행 추출 (defNm이 "합계"인 행, 또는 category에 "합계" 포함)
            for row in rows:
                category = str(_get_mapped_value(row, col_map, "category", ""))
                sub_cat = str(_get_mapped_value(row, col_map, "sub_category", ""))
                budget_amt = _parse_number(_get_mapped_value(row, col_map, "budget_amount", 0))
                actual_amt = _parse_number(_get_mapped_value(row, col_map, "actual_amount", 0))
                diff = _parse_number(_get_mapped_value(row, col_map, "difference", 0))

                label = (category + " " + sub_cat).strip()

                # 수입합계
                if "수입" in label and "합계" in label:
                    summary["income_total"] = budget_amt or actual_amt
                # 지출합계
                elif "지출" in label and "합계" in label:
                    summary["expense_total"] = budget_amt or actual_amt
                # 총잔액 (또는 "합계"만 있는 행)
                elif label == "합계" or "총합계" in label or "총잔액" in label:
                    summary["total_balance"] = diff or (budget_amt - actual_amt)

            # summary 데이터도 가져오기 (data에 summary 필드가 있으면)
            extra = data.get("summary", {})
            if extra.get("totSumList"):
                # totSumList가 있으면 총합계로 사용
                tot = extra["totSumList"]
                if isinstance(tot, list) and len(tot) > 0:
                    tot_row = tot[0] if isinstance(tot[0], dict) else {}
                    if "abgtSumAm" in tot_row:
                        summary["total_balance"] = _parse_number(tot_row.get("subAm", 0))
            if extra.get("addSumList"):
                add = extra["addSumList"]
                if isinstance(add, list) and len(add) > 0:
                    add_row = add[0] if isinstance(add[0], dict) else {}
                    summary["income_total"] = _parse_number(add_row.get("abgtSumAm", 0))
            if extra.get("subSumList"):
                sub = extra["subSumList"]
                if isinstance(sub, list) and len(sub) > 0:
                    sub_row = sub[0] if isinstance(sub[0], dict) else {}
                    summary["expense_total"] = _parse_number(sub_row.get("abgtSumAm", 0))

            # DB에 합계 저장 (budget_summary 필드로 projects 테이블 업데이트)
            if project_id and any(v != 0 for v in summary.values()):
                _save_budget_summary_to_db(project_id, summary)

            close_session(browser)
            return {"success": True, "summary": summary, "project_code": project_code}
        else:
            close_session(browser)
            return {
                "success": False,
                "error": result.get("error", "데이터 추출 실패"),
                "summary": summary,
            }

    except Exception as e:
        logger.error(f"예실대비 합계 크롤링 실패: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        pw.stop()


def crawl_all_summary(gw_id: str):
    """
    모든 프로젝트의 예실대비현황(상세) 합계만 일괄 크롤링 (경량 버전).
    project_code가 설정된 프로젝트만 대상.

    Returns:
        dict: { success, results: [{project_id, project_name, status, summary}] }
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password
    from src.fund_table import db

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return {"success": False, "error": f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다."}

    projects = db.list_projects()
    targets = [p for p in projects if p.get("project_code")]

    if not targets:
        return {"success": False, "error": "project_code가 설정된 프로젝트가 없습니다."}

    pw = sync_playwright().start()
    results = []
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        for proj in targets:
            pid = proj["id"]
            pcode = proj["project_code"]
            pname = proj.get("name", "")
            logger.info(f"합계 크롤링 시작: {pname} ({pcode})")

            try:
                result = _navigate_and_extract(page, pcode)
                summary = {"income_total": 0, "expense_total": 0, "total_balance": 0}

                if result.get("success") and result.get("data"):
                    data = result["data"]
                    rows = data.get("rows", [])
                    columns = data.get("columns", [])
                    col_map = _build_column_mapping(columns)

                    for row in rows:
                        category = str(_get_mapped_value(row, col_map, "category", ""))
                        sub_cat = str(_get_mapped_value(row, col_map, "sub_category", ""))
                        budget_amt = _parse_number(_get_mapped_value(row, col_map, "budget_amount", 0))
                        actual_amt = _parse_number(_get_mapped_value(row, col_map, "actual_amount", 0))
                        diff = _parse_number(_get_mapped_value(row, col_map, "difference", 0))

                        label = (category + " " + sub_cat).strip()
                        if "수입" in label and "합계" in label:
                            summary["income_total"] = budget_amt or actual_amt
                        elif "지출" in label and "합계" in label:
                            summary["expense_total"] = budget_amt or actual_amt
                        elif label == "합계" or "총합계" in label or "총잔액" in label:
                            summary["total_balance"] = diff or (budget_amt - actual_amt)

                    if any(v != 0 for v in summary.values()):
                        _save_budget_summary_to_db(pid, summary)

                    results.append({
                        "project_id": pid, "project_name": pname,
                        "status": "success", "summary": summary,
                    })
                else:
                    results.append({
                        "project_id": pid, "project_name": pname,
                        "status": "fail", "message": result.get("error", "추출 실패"),
                    })
            except Exception as e:
                logger.error(f"프로젝트 {pname} 합계 크롤링 오류: {e}")
                results.append({
                    "project_id": pid, "project_name": pname,
                    "status": "error", "message": str(e),
                })

        close_session(browser)
    except Exception as e:
        logger.error(f"일괄 합계 크롤링 실패: {e}", exc_info=True)
        return {"success": False, "error": str(e), "results": results}
    finally:
        pw.stop()

    success_count = sum(1 for r in results if r["status"] == "success")
    return {
        "success": True,
        "message": f"{success_count}/{len(targets)} 프로젝트 합계 크롤링 완료",
        "results": results,
    }


def _save_budget_summary_to_db(project_id: int, summary: dict):
    """예실대비 합계 데이터를 projects 테이블의 description 또는 별도 필드에 저장"""
    import json
    from src.fund_table.db import get_db
    conn = get_db()
    try:
        # budget_summary 컬럼이 있는지 확인, 없으면 추가
        try:
            conn.execute("SELECT budget_summary FROM projects LIMIT 1")
        except Exception:
            conn.execute("ALTER TABLE projects ADD COLUMN budget_summary TEXT DEFAULT ''")
            conn.commit()

        conn.execute(
            "UPDATE projects SET budget_summary = ? WHERE id = ?",
            (json.dumps(summary, ensure_ascii=False), project_id),
        )
        conn.commit()
        logger.info(f"프로젝트 {project_id} 합계 저장: {summary}")
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────
# 예산변경이력 크롤링
# ──────────────────────────────────────────────────────────────────

# TODO: GW DOM 탐색 후 확인 필요 — 예산변경이력 화면 URL
# 힌트: 예산관리(BM) 모듈 → 예산전용/변경 내역 화면 (정확한 경로 미확인)
#   예상: /#/BN/NCC0640/0BN00001 (예산과목원장) 또는 별도 변경이력 화면
_GW_BUDGET_CHANGE_URL = (
    GW_URL + "/#/BN/NCC0640/0BN00001"
    "?specialLnb=Y&moduleCode=BM&menuCode=NCC0640&pageCode=NCC0640"
)

# TODO: GW DOM 탐색 후 확인 필요 — 예산변경이력 그리드 데이터 추출 JS
_EXTRACT_BUDGET_CHANGE_JS = """
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

    // 시도 1: OBTDataGrid (React fiber → depth 3)
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

    return { error: 'no_supported_grid_found' };
})()
"""


def _map_row_to_budget_change(raw: dict) -> dict:
    """
    GW 그리드 행 → 예산변경이력 표준 필드 매핑.
    TODO: GW DOM 탐색 후 실제 컬럼명으로 교체 필요
    """
    return {
        # TODO: GW DOM 탐색 후 확인 필요 — 실제 컬럼명 매핑
        "change_date":     raw.get("chgDt")       or raw.get("changeDt")   or raw.get("변경일자") or "",
        "budget_code":     raw.get("bgtCd")        or raw.get("budgetCd")   or raw.get("예산과목코드") or "",
        "budget_name":     raw.get("bgtNm")        or raw.get("budgetNm")   or raw.get("예산과목명") or "",
        "before_amount":   raw.get("befAm")        or raw.get("beforeAm")   or raw.get("변경전금액") or 0,
        "after_amount":    raw.get("aftAm")        or raw.get("afterAm")    or raw.get("변경후금액") or 0,
        "change_amount":   raw.get("chgAm")        or raw.get("changeAm")   or raw.get("변경금액") or 0,
        "change_reason":   raw.get("chgRsn")       or raw.get("changeRsn")  or raw.get("변경사유") or "",
        "change_type":     raw.get("chgTpNm")      or raw.get("changeTpNm") or raw.get("변경유형") or "",
        "doc_no":          raw.get("docNo")        or raw.get("문서번호")   or "",
        "requester":       raw.get("reqEmpNm")     or raw.get("신청자")     or "",
        "approver":        raw.get("aprvEmpNm")    or raw.get("승인자")     or "",
        "status":          raw.get("statusNm")     or raw.get("stCdNm")     or raw.get("처리상태") or "",
    }


def crawl_budget_changes(page, project_code: str) -> list[dict]:
    """
    GW 예산변경이력 화면에서 해당 프로젝트의 예산변경 내역을 추출한다.

    이미 열려있는 Playwright page 객체를 받아 사용한다
    (crawl_budget_actual 등과 동일한 세션에서 연속 호출 가능).

    Args:
        page:          Playwright Page 객체 (이미 로그인된 상태)
        project_code:  GW 사업코드 (예: GS-25-0088)

    Returns:
        list[dict]: 예산변경이력 레코드 목록
                    실패 시 빈 리스트 반환

    TODO: GW DOM 탐색 후 아래 항목 확인 필요
      1. 예산변경이력 정확한 메뉴 경로 (예산관리 → 예산변경 또는 전용현황 화면)
      2. 프로젝트 코드 필터 입력 셀렉터
      3. 조회 버튼 셀렉터
      4. 그리드 로딩 완료 대기 조건
    """
    try:
        # TODO: GW DOM 탐색 후 확인 필요 — 예산변경이력 페이지로 이동
        logger.debug(f"[crawl_budget_changes] 페이지 이동: {_GW_BUDGET_CHANGE_URL}")
        page.goto(_GW_BUDGET_CHANGE_URL)
        page.wait_for_timeout(2000)

        # TODO: GW DOM 탐색 후 확인 필요 — 프로젝트 코드 필터 입력
        # 예시 패턴 (실제 셀렉터는 DOM 탐색 후 교체):
        #   page.fill('input[placeholder*="사업코드"]', project_code)
        #   page.press('input[placeholder*="사업코드"]', 'Enter')
        #   page.wait_for_timeout(2000)

        # TODO: GW DOM 탐색 후 확인 필요 — 조회 버튼 클릭
        #   page.click('button:has-text("조회")')
        #   page.wait_for_timeout(2000)

        # 그리드 데이터 추출
        result = page.evaluate(_EXTRACT_BUDGET_CHANGE_JS)

        if result.get("error"):
            logger.warning(f"[crawl_budget_changes] 그리드 추출 실패: {result['error']}")
            return []

        rows = result.get("rows", [])
        logger.info(f"[crawl_budget_changes] {project_code}: {len(rows)}건 추출")

        return [_map_row_to_budget_change(row) for row in rows]

    except Exception as e:
        logger.error(f"[crawl_budget_changes] 페이지 탐색 실패: {e}", exc_info=True)
        return []


def crawl_budget_changes_for_project(
    gw_id: str,
    project_id: int,
    gw_project_code: str,
) -> list[dict]:
    """
    단독 실행용 예산변경이력 크롤링 (별도 Playwright 세션).

    crawl_budget_actual() 등과 별도로 호출할 때 사용.
    배치 처리 시에는 세션을 1회 열고 crawl_budget_changes(page, code)를 직접 호출 권장.

    Args:
        gw_id:            GW 로그인 아이디
        project_id:       fund_management.db 프로젝트 ID
        gw_project_code:  GW 사업코드 (예: GS-25-0088)

    Returns:
        list[dict]: 수집된 예산변경이력 레코드 목록
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password
    from src.fund_table import db

    logger.info(
        f"[crawl_budget_changes_for_project] 시작: "
        f"project_id={project_id}, code={gw_project_code}"
    )

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        logger.error(f"비밀번호 복호화 실패: gw_id={gw_id}")
        return []

    pw = sync_playwright().start()
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        changes = crawl_budget_changes(page, gw_project_code)

        if changes:
            for change in changes:
                change["project_id"] = project_id
            save_result = db.save_budget_changes(
                project_id, gw_project_code, changes
            )
            logger.info(f"[crawl_budget_changes_for_project] 저장: {save_result}")
        else:
            logger.warning(
                f"[crawl_budget_changes_for_project] 수집 결과 없음: {gw_project_code}"
            )

        close_session(browser)
        return changes

    except Exception as e:
        logger.error(
            f"[crawl_budget_changes_for_project] 실패: {e}", exc_info=True
        )
        return []
    finally:
        pw.stop()


def _save_screenshot(page, name: str):
    """디버그 스크린샷 저장"""
    from pathlib import Path
    screenshot_dir = Path(__file__).resolve().parent.parent.parent / "data" / "approval_screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    try:
        path = screenshot_dir / f"{name}.png"
        page.screenshot(path=str(path))
        logger.info(f"스크린샷: {path}")
    except Exception as e:
        logger.warning(f"스크린샷 저장 실패: {e}")
