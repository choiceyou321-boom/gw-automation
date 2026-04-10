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
        # ── 사전 처리: 용도코드 입력 후 자동 열린 "예입/지출 예산시내역" 모달 닫기 ──
        # 이 모달이 열려 있으면 예산과목 필드 클릭이 방해받아 올바른 모달이 안 열림
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            logger.info("Escape 전송 — 열린 모달 닫기 시도")
        except Exception:
            pass

        # ── 단계 12: 예산과목 필드 클릭 → "공통 예산잔액 조회" 모달 오픈 ──
        budget_input = _click_budget_field(page)
        if not budget_input:
            result["message"] = "예산과목 필드를 찾을 수 없음"
            return result

        # 클릭 직후 2초 대기 후 DOM 상태 진단 (어떤 팝업이 열렸는지 확인)
        page.wait_for_timeout(2000)
        _save_debug_screenshot(page, "budget_12_after_click")
        try:
            _dom_diag = page.evaluate("""() => {
                const allInputs = [...document.querySelectorAll('input[placeholder]')].map(i => ({
                    ph: i.placeholder, y: Math.round(i.getBoundingClientRect().y), vis: i.offsetParent !== null
                })).filter(i => i.vis);
                const allH1 = [...document.querySelectorAll('h1')].map(h => ({
                    txt: h.textContent.trim().slice(0, 40), y: Math.round(h.getBoundingClientRect().y), vis: h.offsetParent !== null
                })).filter(h => h.vis);
                return { inputs: allInputs, h1s: allH1 };
            }""")
            logger.info(f"예산과목 클릭 후 DOM — inputs: {_dom_diag.get('inputs', [])}")
            logger.info(f"예산과목 클릭 후 DOM — h1s: {_dom_diag.get('h1s', [])}")
        except Exception as _de:
            logger.warning(f"DOM 진단 실패: {_de}")

        # ── 단계 13: "공통 예산잔액 조회" 모달 대기 ──
        if not _wait_for_budget_modal(page):
            # 모달이 안 열린 경우 → 예산과목 직접 입력 폴백
            # 예산과목코드를 직접 typing하면 GW가 자동 조회할 수 있음
            if budget_keyword:
                logger.info(f"예산과목 모달 미열림 → 직접 입력 폴백 시도: '{budget_keyword}'")
                try:
                    # 예산과목 필드에 코드 직접 typing
                    from playwright.sync_api import Page as _Page
                    import re as _re
                    # budget_keyword에서 숫자코드 추출 시도 (예: "2200300" 또는 "전기" → 코드 아님)
                    _budget_code = _re.search(r'\d{5,}', budget_keyword)
                    if _budget_code:
                        _code_str = _budget_code.group()
                        if budget_input:
                            budget_input.triple_click()
                            page.wait_for_timeout(100)
                            budget_input.fill(_code_str)
                            page.wait_for_timeout(200)
                            page.keyboard.press("Tab")
                            page.wait_for_timeout(500)
                            logger.info(f"예산과목 직접 입력 폴백: '{_code_str}'")
                            result["code"] = _code_str
                            result["success"] = True
                            return result
                except Exception as _fe:
                    logger.debug(f"예산과목 직접 입력 폴백 실패: {_fe}")
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

        page.wait_for_timeout(500)  # 모달 닫힘 대기
        _save_debug_screenshot(page, "budget_17b_after_main_confirm")

        # 메인 모달이 여전히 열려있으면 Escape로 강제 닫기
        try:
            if page.locator("text=공통 예산잔액 조회").first.is_visible(timeout=500):
                logger.warning("메인 모달이 여전히 열려있음 — Escape로 강제 닫기")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
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
                    _disabled = inp.is_disabled()
                    _editable = inp.is_editable()
                    logger.info(f"예산과목 필드 클릭: {sel} (y={box['y']:.0f}, threshold={y_threshold:.0f}, disabled={_disabled}, editable={_editable})")
                    # 1차 시도: 더블클릭 (GW 코드도움 필드는 더블클릭으로 피커 오픈)
                    try:
                        inp.scroll_into_view_if_needed()  # y=988 등 뷰포트 밖 요소 스크롤
                        page.wait_for_timeout(200)
                        inp.dblclick(force=True)
                        page.wait_for_timeout(500)
                        logger.info("예산과목 더블클릭 시도")
                    except Exception:
                        inp.click(force=True)
                        page.wait_for_timeout(300)
                    # 2차 시도: F4 단축키
                    try:
                        page.keyboard.press("F4")
                        logger.info("예산과목 F4 트리거 시도")
                    except Exception:
                        pass
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
                    inp.scroll_into_view_if_needed()
                    page.wait_for_timeout(200)
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

    # [진단] 찾지 못했을 때 현재 화면의 모든 visible input placeholder 출력
    try:
        _visible_inputs = page.evaluate("""() => {
            return [...document.querySelectorAll('input[placeholder]')]
                .filter(i => i.offsetParent !== null)
                .map(i => ({ph: i.placeholder, y: Math.round(i.getBoundingClientRect().y), x: Math.round(i.getBoundingClientRect().x)}));
        }""")
        logger.warning(f"[진단] 현재 visible inputs: {_visible_inputs[:20]}")
    except Exception:
        pass
    logger.warning(f"예산과목 필드를 찾을 수 없음 (y_threshold={y_threshold:.0f}, viewport_height={viewport_height})")
    return None


def _wait_for_budget_modal(page: Page, timeout_ms: int = 10000) -> bool:
    """단계 13: '공통 예산잔액 조회' 모달 대기.

    모달은 H1 태그로 제목 표시, CSS modal/popup class 없음.

    GW 버전에 따라 모달 제목이 다를 수 있음:
      - "공통 예산잔액 조회"
      - "예입/지출 예산시내역"

    감지 전략: input[placeholder*='예산과목코드도움'] 출현 확인
      - 이 input은 예산과목 모달에만 존재 (메인 폼에는 없음)
      - 반면 input[placeholder='사업코드도움']는 메인 폼 상단 프로젝트 입력란과 겹쳐 false positive 발생
    """
    # 1차: 예산과목코드도움 input — 모달 고유 (메인 폼에 없음)
    _budget_code_sel = "input[placeholder*='예산과목코드도움']"
    # 2차: 사업코드도움 input이 x > 700 위치에 있으면 모달 내 입력란으로 판단
    #      (메인 폼 프로젝트 입력란은 왼쪽 영역에 위치)
    _proj_code_sel = "input[placeholder='사업코드도움'], input[placeholder*='사업코드']"

    deadline = timeout_ms
    poll_interval = 300
    elapsed = 0
    while elapsed < deadline:
        try:
            # 1차 확인: 예산과목코드도움 input (모달 고유)
            for inp in page.locator(_budget_code_sel).all():
                try:
                    if inp.is_visible(timeout=300):
                        logger.info("예산과목 모달 감지 (예산과목코드도움 input)")
                        return True
                except Exception:
                    continue
            # 2차 확인: 사업코드도움 input이 x > 700에 있으면 모달 내부로 판단
            for inp in page.locator(_proj_code_sel).all():
                try:
                    if not inp.is_visible(timeout=300):
                        continue
                    box = inp.bounding_box()
                    if box and box["x"] > 700:
                        logger.info(f"예산과목 모달 감지 (사업코드도움 x={box['x']:.0f})")
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        page.wait_for_timeout(poll_interval)
        elapsed += poll_interval

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

    # 기존 값 확인 → 이미 프로젝트가 입력되어 있으면 재입력 생략 (GW 자동완성 상태 유지)
    existing_val = ""
    try:
        existing_val = proj_input.input_value() or ""
    except Exception:
        pass
    if existing_val and len(existing_val) >= 3:
        logger.info(f"모달 프로젝트 기존값 감지: '{existing_val[:30]}' → 재입력 생략, Enter 확정")
        proj_input.press("Enter")
        page.wait_for_timeout(500)
        return True

    # 클릭 → 기존 값 지우기 → 타이핑 (자동완성 트리거용 delay)
    proj_input.click(force=True)
    proj_input.fill("")
    proj_input.type(project_keyword, delay=80)
    logger.info(f"모달 프로젝트 검색어 입력: '{project_keyword}'")

    # 자동완성 드롭다운 대기 (OBT 자동완성 컴포넌트)
    page.wait_for_timeout(3000)

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
                    page.wait_for_timeout(500)
                    return True
        except Exception:
            continue

    # 폴백: Enter/Tab으로 현재 값 확정
    proj_input.press("Enter")
    page.wait_for_timeout(300)
    proj_input.press("Tab")
    logger.info("모달 프로젝트 — 드롭다운 미발견, Enter+Tab으로 확정")
    page.wait_for_timeout(500)
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
                    page.wait_for_timeout(500)
            else:
                page.wait_for_timeout(500)
        except Exception:
            page.wait_for_timeout(500)

    if not budget_input:
        logger.warning("예산과목코드도움 입력란 활성화 실패 (5초 대기)")
        _save_debug_screenshot(page, "budget_field_still_disabled")
        return False

    # 키워드 입력
    budget_input.click(force=True)
    budget_input.fill("")
    budget_input.type(budget_keyword, delay=80)
    logger.info(f"예산과목 검색어 입력: '{budget_keyword}'")
    page.wait_for_timeout(300)

    # 코드도움 트리거: Enter 키 (가장 안정적)
    budget_input.press("Enter")
    logger.info("예산과목 코드도움 트리거 (Enter)")
    page.wait_for_timeout(1500)

    # Enter로 서브 팝업이 안 열리면 코드도움 아이콘 클릭 시도
    sub_popup_visible = False
    try:
        sub_popup_visible = page.locator("text=예산과목코드도움").first.is_visible(timeout=2000)
    except Exception:
        pass

    if not sub_popup_visible:
        # 코드도움 트리거: Enter 키 재시도 (SearchHelp는 Enter로 팝업 열림)
        icon_clicked = False
        try:
            budget_input.press("Enter")
            logger.info("예산과목 코드도움 트리거 재시도 (Enter)")
            page.wait_for_timeout(1500)
            try:
                if page.locator("text=예산과목코드도움").first.is_visible(timeout=2000):
                    icon_clicked = True
                    logger.info("Enter 재시도로 서브 팝업 열림")
            except Exception:
                pass
        except Exception:
            pass

        # 방법 1: input 인접 코드도움 아이콘 CSS 셀렉터 탐색
        if not icon_clicked:
            icon_selectors = [
                "input[placeholder='예산과목코드도움'] + button",
                "input[placeholder='예산과목코드도움'] ~ button",
                "input[placeholder='예산과목코드도움'] + * button",
                "input[placeholder='예산과목코드도움'] ~ [class*='icon']",
                "input[placeholder='예산과목코드도움'] ~ [class*='search']",
                "input[placeholder='예산과목코드도움'] ~ [class*='btn']",
            ]
            for sel in icon_selectors:
                try:
                    icon = page.locator(sel).first
                    if icon.is_visible(timeout=1000):
                        icon.click(force=True)
                        logger.info(f"예산과목 코드도움 아이콘 CSS 클릭: '{sel}'")
                        icon_clicked = True
                        page.wait_for_timeout(1000)
                        break
                except Exception:
                    continue

        # 방법 2: input bounding_box 기반 상대좌표 계산 (폴백)
        if not icon_clicked:
            try:
                box = budget_input.bounding_box()
                if box:
                    # 코드도움 아이콘은 input 오른쪽에 위치
                    icon_x = box["x"] + box["width"] + 15
                    icon_y = box["y"] + box["height"] / 2
                    logger.warning(f"예산과목 코드도움 아이콘 CSS 실패, 상대좌표 폴백: ({icon_x:.0f}, {icon_y:.0f})")
                    page.mouse.click(icon_x, icon_y)
                    logger.info(f"예산과목 코드도움 아이콘 상대좌표 클릭: ({icon_x:.0f}, {icon_y:.0f})")
                    page.wait_for_timeout(1000)
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

    page.wait_for_timeout(1000)  # 테이블 렌더링 대기
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

    page.wait_for_timeout(300)
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
                page.wait_for_timeout(500)
            except Exception as e:
                logger.debug(f"더블클릭 실패: {e}")

    page.wait_for_timeout(800)  # 서브 팝업 닫힘 + 메인 모달 업데이트 대기
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

    # 2. 메인 모달이 아직 열려있는지 확인 (GW 버전별 제목 대응, "/" 파서 이슈 회피)
    _modal_sels = [
        "text=공통 예산잔액 조회",
        "text=예산시내역",   # "예입/지출 예산시내역" 부분 매칭
        "text=예산잔액 조회",
    ]
    main_modal_visible = False
    detected_sel = None
    for _s in _modal_sels:
        try:
            if page.locator(_s).first.is_visible(timeout=1000):
                main_modal_visible = True
                detected_sel = _s
                break
        except Exception:
            continue

    if not main_modal_visible:
        logger.info("예산과목 모달 이미 닫힘 (서브 팝업 확인으로 같이 닫혔을 가능성)")
        return True

    logger.info(f"예산과목 모달 확인 버튼 클릭 ({detected_sel})")
    # 3. 메인 모달 확인 버튼 클릭
    result = _click_confirm_button(page, "예산 모달")

    # 4. 모달 닫힘 대기
    if result:
        for _s in _modal_sels:
            try:
                page.locator(_s).first.wait_for(state="hidden", timeout=5000)
                logger.info(f"예산과목 모달 닫힘 확인: {_s}")
                break
            except Exception:
                continue

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
                    page.wait_for_timeout(500)
                    return True
        except Exception:
            continue

    logger.warning(f"{context_name} 확인 버튼 미발견")
    return False


def handle_auto_triggered_popup(page: Page, project_keyword: str, budget_keyword: str, timeout_ms: int = 8000) -> dict:
    """
    용도코드(usage_code) 입력+Enter 후 자동 트리거된 '공통 예산잔액 조회' 팝업 처리.

    select_budget_code()와 달리 예산과목 필드를 클릭하지 않고,
    이미 열린 팝업을 바로 처리한다.

    흐름:
    1. 팝업이 자동으로 열렸는지 확인 (3초 대기)
    2. 모달 내 프로젝트(사업코드도움) 입력 → 자동완성 선택
    3. 예산과목코드도움 입력 → 서브 팝업 → 행 선택 → 확인
    4. 모달 확인 버튼 클릭

    Args:
        page: Playwright Page 인스턴스
        project_keyword: 프로젝트 검색어 (예: "메디빌더")
        budget_keyword: 예산과목 검색어 (예: "냉난방")

    Returns:
        {"success": bool, "budget_code": str, "budget_name": str, "message": str}
        success=False + message 포함 "팝업 미감지" → 자동 트리거 없음, 폴백 필요
    """
    result = {"success": False, "budget_code": "", "budget_name": "", "message": ""}
    try:
        # ── 팝업 자동 트리거 확인 (timeout_ms: 기본 8초, 인보이스 직후 즉시 체크 시 4초) ──
        if not _wait_for_budget_modal(page, timeout_ms=timeout_ms):
            result["message"] = "팝업 미감지 — 자동 트리거 없음, select_budget_code() 폴백 필요"
            return result

        logger.info("공통 예산잔액 조회 자동 트리거 팝업 감지")
        _save_debug_screenshot(page, "auto_popup_13_modal_opened")

        # ── 프로젝트 입력 + 자동완성 선택 ──
        if not _fill_modal_project(page, project_keyword):
            result["message"] = f"모달 프로젝트 입력 실패: '{project_keyword}'"
            return result
        _save_debug_screenshot(page, "auto_popup_15_after_project")

        # ── 예산과목코드도움 입력 → 코드도움 서브 팝업 ──
        if not _fill_modal_budget_keyword(page, budget_keyword):
            result["message"] = f"예산과목 키워드 입력 실패: '{budget_keyword}'"
            return result
        _save_debug_screenshot(page, "auto_popup_16_after_keyword")

        # ── 서브 팝업에서 2로 시작하는 코드 선택 ──
        code, name = _select_budget_from_sub_popup(page)
        if not code:
            result["message"] = "서브 팝업에서 예산과목코드를 찾지 못함"
            return result

        logger.info(f"자동팝업 예산과목 선택 완료: {code}. {name}")

        # ── 메인 모달 확인 버튼 클릭 ──
        _save_debug_screenshot(page, "auto_popup_17_before_confirm")
        if not _confirm_budget_modal(page):
            result["message"] = "모달 확인 버튼 클릭 실패"
            return result

        page.wait_for_timeout(500)
        _save_debug_screenshot(page, "auto_popup_17b_after_confirm")

        # 모달이 여전히 열려있으면 Escape로 강제 닫기
        try:
            if page.locator("text=공통 예산잔액 조회").first.is_visible(timeout=500):
                logger.warning("자동팝업: 확인 후에도 모달 잔존 — Escape로 강제 닫기")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
        except Exception:
            pass

        result["success"] = True
        result["budget_code"] = code
        result["budget_name"] = name
        result["message"] = f"예산과목 {code}. {name} 자동팝업 설정 완료"
        logger.info(result["message"])
        return result

    except Exception as e:
        logger.error(f"handle_auto_triggered_popup 예외: {e}", exc_info=True)
        _save_debug_screenshot(page, "auto_popup_error")
        result["message"] = f"예외: {e}"
        return result
