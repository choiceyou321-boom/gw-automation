"""
예산과목 선택 헬퍼 (공통 예산잔액 조회 팝업)
- 지출결의서 하단 테이블의 예산과목 필드 입력 자동화
- 세션 XII DOM 분석 기반 구현

모달 DOM 구조 (2026-03-08 분석):
  - 모달 타이틀: H1 태그 "공통 예산잔액 조회" (CSS class 없음)
  - 모달 컨테이너: modal/popup/layer CSS class 없음
  - 프로젝트 입력: input[placeholder='사업코드도움'] (pos ~869,363)
  - 예산과목 입력: input[placeholder='예산과목코드도움'] (pos ~869,404, disabled until project selected)
  - 확인/취소 버튼: 모달 하단
"""
import time
import logging
from datetime import datetime
from pathlib import Path
from playwright.sync_api import Page

# 스크린샷 저장 경로 (모듈 로드 시 한 번만 계산)
_SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "approval_screenshots"

logger = logging.getLogger("budget_helpers")


def select_budget_code(page: Page, project_keyword: str, budget_keyword: str) -> dict:
    """
    예산과목 선택 플로우 실행.

    흐름:
    1. 하단 테이블의 예산과목 필드 클릭 → "공통 예산잔액 조회" 모달 오픈
    2. 모달 내 프로젝트(사업코드도움) 입력 → 자동완성 선택
    3. 예산과목코드도움 활성화 대기 → 키워드 입력 → 코드도움 서브 팝업
    4. 서브 팝업에서 2로 시작하는 예산과목코드 행 선택 → 확인
    5. 모달 확인 버튼 클릭 → 메인 폼 복귀

    Args:
        page: Playwright Page 인스턴스
        project_keyword: 프로젝트 검색어 (예: "메디빌더")
        budget_keyword: 예산과목 검색어 (예: "경량")

    Returns:
        {"success": bool, "budget_code": str, "budget_name": str, "message": str}
    """
    result = {"success": False, "budget_code": "", "budget_name": "", "message": ""}

    try:
        # ── 단계 12: 예산과목 필드 클릭 → 모달 오픈 ──
        budget_input = _click_budget_field(page)
        if not budget_input:
            result["message"] = "예산과목 필드를 찾을 수 없음"
            return result

        # ── 단계 13: "공통 예산잔액 조회" 모달 대기 ──
        if not _wait_for_budget_modal(page):
            result["message"] = "공통 예산잔액 조회 모달이 열리지 않음"
            return result
        logger.info("공통 예산잔액 조회 모달 열림")
        _save_debug_screenshot(page, "budget_13_modal_opened")

        # ── 단계 14~15: 모달 내 프로젝트 입력 + 자동완성 선택 ──
        if not _fill_modal_project(page, project_keyword):
            result["message"] = f"모달 프로젝트 입력 실패: '{project_keyword}'"
            return result
        _save_debug_screenshot(page, "budget_15_after_project")

        # ── 단계 16: 예산과목코드도움 활성화 대기 → 키워드 입력 ──
        if not _fill_modal_budget_keyword(page, budget_keyword):
            result["message"] = f"예산과목 키워드 입력 실패: '{budget_keyword}'"
            return result
        _save_debug_screenshot(page, "budget_16_after_keyword")

        # ── 단계 16-1~17: 서브 팝업에서 2로 시작하는 코드 선택 ──
        code, name = _select_budget_from_sub_popup(page)
        if not code:
            result["message"] = "서브 팝업에서 2로 시작하는 예산과목코드를 찾지 못함"
            return result

        logger.info(f"예산과목 선택 완료: {code}. {name}")

        # ── 단계 17-확인: 모달 확인 버튼 클릭 ──
        _save_debug_screenshot(page, "budget_17_before_main_confirm")
        if not _confirm_budget_modal(page):
            result["message"] = "모달 확인 버튼 클릭 실패"
            return result

        time.sleep(0.5)  # 모달 닫힘 대기
        _save_debug_screenshot(page, "budget_17b_after_main_confirm")

        # 메인 모달이 여전히 열려있으면 Escape로 강제 닫기
        try:
            if page.locator("text=공통 예산잔액 조회").first.is_visible(timeout=500):
                logger.warning("메인 모달이 여전히 열려있음 — Escape로 강제 닫기")
                page.keyboard.press("Escape")
                time.sleep(0.5)
        except Exception:
            pass

        result["success"] = True
        result["budget_code"] = code
        result["budget_name"] = name
        result["message"] = f"예산과목 {code}. {name} 설정 완료"
        logger.info(result["message"])
        return result

    except Exception as e:
        logger.error(f"select_budget_code 예외: {e}", exc_info=True)
        _save_debug_screenshot(page, "budget_error")
        result["message"] = f"예산과목 선택 중 오류: {e}"
        return result


# ──────────────────────────────────────────────
# 내부 헬퍼 함수
# ──────────────────────────────────────────────

def _save_debug_screenshot(page: Page, name: str):
    """디버그 스크린샷 저장."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = _SCREENSHOT_DIR / f"{name}_{ts}.png"
    try:
        page.screenshot(path=path)
        logger.info(f"디버그 스크린샷 저장: {path}")
    except Exception:
        pass


def _click_budget_field(page: Page):
    """단계 12: 하단 테이블의 예산과목 필드 클릭.

    풀스크린 모드 대응: y > 800 고정값 대신 화면 높이 비율(60% 이상)로 판단.
    placeholder='예산과목코드도움'(모달 내부) 제외, placeholder='예산과목'(메인 폼) 우선.
    """
    # 메인 폼의 예산과목 input (모달 내부의 '예산과목코드도움'과 구분)
    selectors = [
        "input[placeholder='예산과목']",
        "input[placeholder*='예산과목']",
    ]

    # 화면 높이 기준 y 임계값 동적 계산 (풀스크린 대응)
    try:
        viewport_height = page.viewport_size["height"] if page.viewport_size else 900
    except Exception:
        viewport_height = 900
    # 화면 하단 40% 영역 (예: 900px → y > 540, 1080px → y > 648)
    y_threshold = viewport_height * 0.6

    for sel in selectors:
        try:
            inputs = page.locator(sel).all()
            for inp in inputs:
                if not inp.is_visible(timeout=2000):
                    continue
                # 'placeholder가 예산과목코드도움'인 것은 모달 내부 필드 — 제외
                ph = inp.get_attribute("placeholder") or ""
                if "코드도움" in ph:
                    continue
                box = inp.bounding_box()
                if box and box["y"] > y_threshold:
                    inp.click(force=True)
                    logger.info(f"예산과목 필드 클릭: {sel} (y={box['y']:.0f}, threshold={y_threshold:.0f})")
                    return inp
        except Exception:
            continue

    # 폴백 1: y 임계값 완화 (화면 상단 20% 이상이면 허용)
    y_min = viewport_height * 0.2
    for sel in selectors:
        try:
            inputs = page.locator(sel).all()
            for inp in inputs:
                if not inp.is_visible(timeout=2000):
                    continue
                ph = inp.get_attribute("placeholder") or ""
                if "코드도움" in ph:
                    continue
                box = inp.bounding_box()
                if box and box["y"] > y_min:
                    inp.click(force=True)
                    logger.info(f"예산과목 필드 클릭 (완화 임계값): {sel} (y={box['y']:.0f})")
                    return inp
        except Exception:
            continue

    # 폴백 2: placeholder 무관 첫 번째 visible
    for sel in selectors:
        try:
            inp = page.locator(sel).first
            if inp.is_visible(timeout=2000):
                inp.click(force=True)
                logger.info(f"예산과목 필드 클릭 (최종 폴백): {sel}")
                return inp
        except Exception:
            continue

    logger.warning(f"예산과목 필드를 찾을 수 없음 (y_threshold={y_threshold:.0f}, viewport_height={viewport_height})")
    return None


def _wait_for_budget_modal(page: Page, timeout_ms: int = 10000) -> bool:
    """단계 13: '공통 예산잔액 조회' 모달 대기.

    모달은 H1 태그로 제목 표시, CSS modal/popup class 없음.
    text= 셀렉터가 가장 안정적.
    """
    # 가장 정확한 셀렉터 우선
    try:
        page.locator("text=공통 예산잔액 조회").first.wait_for(state="visible", timeout=timeout_ms)
        logger.info("공통 예산잔액 조회 텍스트 감지")
        return True
    except Exception:
        pass

    # H1 태그 기반 폴백
    try:
        page.locator("h1:has-text('공통 예산잔액 조회')").first.wait_for(state="visible", timeout=5000)
        logger.info("H1 공통 예산잔액 조회 감지")
        return True
    except Exception:
        pass

    logger.warning("공통 예산잔액 조회 모달 감지 실패")
    _save_debug_screenshot(page, "budget_modal_not_found")
    return False


def _fill_modal_project(page: Page, project_keyword: str) -> bool:
    """단계 14~15: 모달 내 프로젝트(사업코드도움) 입력 후 자동완성 선택.

    DOM: input[placeholder='사업코드도움'] at ~(869, 363)
    """
    proj_selectors = [
        "input[placeholder='사업코드도움']",
        "input[placeholder*='사업코드']",
    ]

    proj_input = None
    for sel in proj_selectors:
        try:
            inputs = page.locator(sel).all()
            for inp in inputs:
                if inp.is_visible(timeout=2000):
                    # 모달 내 입력란: x > 800 영역 (모달이 화면 중앙에 위치)
                    box = inp.bounding_box()
                    if box and box["x"] > 700:
                        proj_input = inp
                        break
            if proj_input:
                break
        except Exception:
            continue

    if not proj_input:
        logger.warning("모달 내 사업코드도움 입력란을 찾을 수 없음")
        return False

    # 클릭 → 기존 값 지우기 → 타이핑 (자동완성 트리거용 delay)
    proj_input.click(force=True)
    proj_input.fill("")
    proj_input.type(project_keyword, delay=80)
    logger.info(f"모달 프로젝트 검색어 입력: '{project_keyword}'")

    # 자동완성 드롭다운 대기 (OBT 자동완성 컴포넌트)
    time.sleep(1.0)

    dropdown_selectors = [
        "ul[class*='autocomplete'] li",
        "div[class*='OBTAutoComplete'] li",
        "ul[class*='OBTAutoComplete'] li",
        "div[class*='suggest'] li",
        "div[class*='dropdown'] li",
        "ul li[class*='item']",
    ]
    for sel in dropdown_selectors:
        try:
            items = page.locator(sel).all()
            for item in items:
                if item.is_visible(timeout=2000):
                    item_text = (item.text_content(timeout=1000) or "").strip()
                    item.click()
                    logger.info(f"모달 프로젝트 자동완성 선택: '{item_text[:40]}' ({sel})")
                    time.sleep(0.5)
                    return True
        except Exception:
            continue

    # 폴백: Enter/Tab으로 현재 값 확정
    proj_input.press("Enter")
    time.sleep(0.3)
    proj_input.press("Tab")
    logger.info("모달 프로젝트 — 드롭다운 미발견, Enter+Tab으로 확정")
    time.sleep(0.5)
    return True


def _fill_modal_budget_keyword(page: Page, budget_keyword: str) -> bool:
    """단계 16: 예산과목코드도움 입력란에 키워드 입력 + 코드도움 서브 팝업 트리거.

    DOM: input[placeholder='예산과목코드도움'] at ~(869, 404)
    초기 상태: disabled (프로젝트 미선택 시)
    """
    budget_sel = "input[placeholder='예산과목코드도움']"

    # disabled → enabled 전환 대기 (최대 5초)
    budget_input = None
    for attempt in range(10):
        try:
            inp = page.locator(budget_sel).first
            if inp.is_visible(timeout=1000):
                if not inp.is_disabled(timeout=500):
                    budget_input = inp
                    logger.info("예산과목코드도움 입력란 활성화 확인")
                    break
                else:
                    logger.debug(f"예산과목코드도움 아직 disabled (시도 {attempt+1}/10)")
                    time.sleep(0.5)
            else:
                time.sleep(0.5)
        except Exception:
            time.sleep(0.5)

    if not budget_input:
        logger.warning("예산과목코드도움 입력란 활성화 실패 (5초 대기)")
        _save_debug_screenshot(page, "budget_field_still_disabled")
        return False

    # 키워드 입력
    budget_input.click(force=True)
    budget_input.fill("")
    budget_input.type(budget_keyword, delay=80)
    logger.info(f"예산과목 검색어 입력: '{budget_keyword}'")
    time.sleep(0.3)

    # 코드도움 트리거: Enter 키 (가장 안정적)
    budget_input.press("Enter")
    logger.info("예산과목 코드도움 트리거 (Enter)")
    time.sleep(1.5)

    # Enter로 서브 팝업이 안 열리면 코드도움 아이콘 클릭 시도
    sub_popup_visible = False
    try:
        sub_popup_visible = page.locator("text=예산과목코드도움").first.is_visible(timeout=2000)
    except Exception:
        pass

    if not sub_popup_visible:
        # 코드도움 아이콘 클릭 (input 옆 돋보기/버튼)
        try:
            box = budget_input.bounding_box()
            if box:
                # 코드도움 아이콘은 input 오른쪽에 위치
                icon_x = box["x"] + box["width"] + 15
                icon_y = box["y"] + box["height"] / 2
                page.mouse.click(icon_x, icon_y)
                logger.info(f"예산과목 코드도움 아이콘 좌표 클릭: ({icon_x:.0f}, {icon_y:.0f})")
                time.sleep(1.0)
        except Exception as e:
            logger.debug(f"코드도움 아이콘 클릭 실패: {e}")

    return True


def _select_budget_from_sub_popup(page: Page) -> tuple:
    """
    단계 16-1~17: '예산과목코드도움' 서브 팝업에서 2로 시작하는 행 선택 후 확인.

    Returns:
        (budget_code, budget_name) 또는 ("", "") if 실패
    """
    # 서브 팝업 대기 — H1 또는 text 기반
    sub_popup_found = False
    for sel in ["text=예산과목코드도움", "h1:has-text('예산과목코드도움')"]:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=8000)
            sub_popup_found = True
            logger.info(f"예산과목코드도움 서브 팝업 감지: {sel}")
            break
        except Exception:
            continue

    if not sub_popup_found:
        logger.warning("예산과목코드도움 서브 팝업 미발견")
        _save_debug_screenshot(page, "budget_sub_popup_not_found")
        return ("", "")

    time.sleep(1.0)  # 테이블 렌더링 대기
    _save_debug_screenshot(page, "budget_16b_sub_popup")

    selected_code = ""
    selected_name = ""
    selected_row = None

    # 방법 1: 테이블 행(tr/td) 순회
    try:
        rows = page.locator("tr").all()
        for row in rows:
            try:
                if not row.is_visible(timeout=500):
                    continue
                cells = row.locator("td").all()
                if len(cells) < 2:
                    continue

                for col_idx in [0, 1, 2]:
                    if col_idx >= len(cells):
                        continue
                    cell_text = cells[col_idx].inner_text(timeout=1000).strip()
                    # 예산과목코드: 2로 시작, 5~7자리 숫자 (날짜 20xxxxxx 8자리 제외)
                    if (cell_text and cell_text[0] == "2"
                            and cell_text.replace(".", "").isdigit()
                            and 5 <= len(cell_text) <= 7):
                        selected_code = cell_text
                        name_idx = col_idx + 1
                        if name_idx < len(cells):
                            selected_name = cells[name_idx].inner_text(timeout=1000).strip()
                        selected_row = row
                        row.click()
                        logger.info(f"서브 팝업 행 선택: 코드={selected_code}, 이름={selected_name}")
                        break
                if selected_code:
                    break
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"서브 팝업 테이블 행 순회 실패: {e}")

    # 방법 2: OBTDataGrid 또는 canvas 그리드일 경우 JS로 접근
    if not selected_code:
        try:
            result = page.evaluate("""() => {
                // canvas 그리드의 React fiber 접근
                const grids = document.querySelectorAll('.OBTDataGrid_grid__22Vfl, [class*="OBTDataGrid"]');
                for (const el of grids) {
                    const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                    if (!fk) continue;
                    let f = el[fk];
                    for (let i = 0; i < 3 && f; i++) f = f.return;
                    if (!f || !f.stateNode || !f.stateNode.state) continue;
                    const iface = f.stateNode.state.interface;
                    if (!iface || !iface.getRowCount) continue;
                    const count = iface.getRowCount();
                    for (let r = 0; r < count; r++) {
                        const vals = iface.getValues(r);
                        // 예산과목코드가 2로 시작하는 행 찾기
                        for (const [k, v] of Object.entries(vals || {})) {
                            // 예산과목코드: 2로 시작, 5~7자리 숫자 (날짜 8자리 제외)
                            if (typeof v === 'string' && v.match(/^2\\d{4,6}$/) && v.length <= 7) {
                                iface.setSelection({rowIndex: r, columnName: k});
                                return {code: v, name: vals['BGTACC_NM'] || vals['name'] || '', rowIndex: r};
                            }
                        }
                    }
                }
                return null;
            }""")
            if result:
                selected_code = result["code"]
                selected_name = result.get("name", "")
                logger.info(f"서브 팝업 그리드 API 선택: 코드={selected_code}, 이름={selected_name}")
                # 더블클릭으로 선택 확정
                if "rowIndex" in result:
                    page.evaluate(f"""() => {{
                        const grids = document.querySelectorAll('.OBTDataGrid_grid__22Vfl, [class*="OBTDataGrid"]');
                        for (const el of grids) {{
                            const fk = Object.keys(el).find(k => k.startsWith('__reactFiber'));
                            if (!fk) continue;
                            let f = el[fk];
                            for (let i = 0; i < 3 && f; i++) f = f.return;
                            if (!f || !f.stateNode || !f.stateNode.state) continue;
                            const iface = f.stateNode.state.interface;
                            if (iface) iface.setCheck({result['rowIndex']}, true);
                        }}
                    }}""")
        except Exception as e:
            logger.debug(f"그리드 API 접근 실패: {e}")

    if not selected_code:
        logger.warning("2로 시작하는 예산과목코드를 찾지 못함")
        _save_debug_screenshot(page, "budget_code_not_found")
        return ("", "")

    time.sleep(0.3)
    _save_debug_screenshot(page, "budget_16c_row_selected")

    # 서브 팝업 확인 버튼 클릭 — 서브 팝업 내부 버튼을 우선 타겟팅
    sub_popup_confirmed = _click_sub_popup_confirm(page)
    if not sub_popup_confirmed:
        logger.warning("서브 팝업 확인 버튼 클릭 실패 — 폴백: 더블클릭으로 선택")
        # 더블클릭으로 선택 확정 시도
        if selected_row is not None:
            try:
                selected_row.dblclick()
                logger.info("서브 팝업 행 더블클릭으로 선택 확정")
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"더블클릭 실패: {e}")

    time.sleep(0.8)  # 서브 팝업 닫힘 + 메인 모달 업데이트 대기
    _save_debug_screenshot(page, "budget_16d_after_sub_confirm")
    return (selected_code, selected_name)


def _click_sub_popup_confirm(page: Page) -> bool:
    """서브 팝업('예산과목코드도움') 내부의 확인 버튼을 타겟팅하여 클릭.

    서브 팝업은 '예산과목코드도움' 텍스트를 포함하는 컨테이너.
    메인 모달의 '확인' 버튼과 혼동되지 않도록 서브 팝업 컨테이너를 먼저 찾음.
    """
    # 방법 1: 서브 팝업 제목 텍스트를 포함한 부모 컨테이너 내 확인 버튼 탐색
    popup_container_selectors = [
        "div:has(h1:has-text('예산과목코드도움'))",
        "div:has(> h1:has-text('예산과목코드도움'))",
        "div:has(h2:has-text('예산과목코드도움'))",
        "section:has(:text('예산과목코드도움'))",
    ]
    for container_sel in popup_container_selectors:
        try:
            container = page.locator(container_sel).first
            if container.is_visible(timeout=2000):
                confirm_btn = container.locator("button:has-text('확인')").last
                if confirm_btn.is_visible(timeout=1000):
                    confirm_btn.click()
                    logger.info(f"서브 팝업 컨테이너 내 확인 버튼 클릭: {container_sel}")
                    return True
        except Exception:
            continue

    # 방법 2: 서브 팝업 제목 기준 위치 파악 후 팝업 범위 내 가장 가까운 확인 버튼 클릭
    # 최대 거리 350px 제한 — 서브 팝업 높이를 벗어나는 버튼(메인 모달 버튼 등) 제외
    try:
        title_loc = page.locator("text=예산과목코드도움").first
        title_box = title_loc.bounding_box()
        if title_box:
            btns = page.locator("button:has-text('확인')").all()
            closest_btn = None
            min_dist = float("inf")
            MAX_POPUP_HEIGHT = 350  # 서브 팝업 내부 버튼은 제목 아래 350px 이내에 위치
            for btn in btns:
                try:
                    btn_box = btn.bounding_box()
                    if not btn_box:
                        continue
                    dist = btn_box["y"] - title_box["y"]
                    # 제목 아래, 팝업 범위 내 (350px 이내)
                    if 0 < dist < MAX_POPUP_HEIGHT and dist < min_dist:
                        min_dist = dist
                        closest_btn = btn
                except Exception:
                    continue
            if closest_btn:
                closest_btn.click(force=True)  # OBTDialog 포인터 이벤트 차단 우회
                logger.info(f"서브 팝업 제목 아래 확인 버튼 클릭 force (거리={min_dist:.0f}px)")
                return True
            else:
                logger.debug(f"서브 팝업 범위 내(350px) 확인 버튼 미발견 (최소거리={min_dist:.0f}px)")
    except Exception as e:
        logger.debug(f"서브 팝업 위치 기반 확인 버튼 탐색 실패: {e}")

    # 방법 3: 폴백 — reversed로 마지막 확인 버튼 (기존 방식)
    return _click_confirm_button(page, "서브 팝업 폴백")


def _confirm_budget_modal(page: Page) -> bool:
    """메인 예산잔액 조회 모달의 확인 버튼 클릭.

    서브 팝업이 먼저 닫혀야 메인 모달의 확인 버튼이 정상 동작함.
    """
    # 1. 서브 팝업 닫힘 대기
    try:
        page.locator("text=예산과목코드도움").first.wait_for(state="hidden", timeout=3000)
        logger.info("서브 팝업 닫힘 확인")
    except Exception:
        logger.debug("서브 팝업 닫힘 확인 타임아웃 (이미 닫혔을 수 있음)")

    # 2. 메인 모달이 아직 열려있는지 확인
    main_modal_visible = False
    try:
        main_modal_visible = page.locator("text=공통 예산잔액 조회").first.is_visible(timeout=1000)
    except Exception:
        pass

    if not main_modal_visible:
        logger.info("공통 예산잔액 조회 모달 이미 닫힘 (서브 팝업 확인으로 같이 닫혔을 가능성)")
        return True

    # 3. 메인 모달 확인 버튼 클릭
    result = _click_confirm_button(page, "예산 모달")

    # 4. 모달 닫힘 대기
    if result:
        try:
            page.locator("text=공통 예산잔액 조회").first.wait_for(state="hidden", timeout=5000)
            logger.info("공통 예산잔액 조회 모달 닫힘 확인")
        except Exception:
            logger.warning("공통 예산잔액 조회 모달 닫힘 확인 실패 — 계속 진행")

    return result


def _click_confirm_button(page: Page, context_name: str) -> bool:
    """확인 버튼 클릭 (모달/서브팝업 공통)."""
    confirm_selectors = [
        "button:has-text('확인')",
        "div.btn:has-text('확인')",
        "a:has-text('확인')",
        "input[value='확인']",
    ]
    for sel in confirm_selectors:
        try:
            btns = page.locator(sel).all()
            # 가장 마지막(최상위 레이어의) 확인 버튼 클릭
            for btn in reversed(btns):
                if btn.is_visible(timeout=2000):
                    btn.click()
                    logger.info(f"{context_name} 확인 버튼 클릭: {sel}")
                    time.sleep(0.5)
                    return True
        except Exception:
            continue

    logger.warning(f"{context_name} 확인 버튼 미발견")
    return False
