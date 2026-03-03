"""
예산과목 선택 헬퍼 (공통 예산잔액 조회 팝업)
- 지출결의서 하단 테이블의 예산과목 필드 입력 자동화
- 단계 12~17 스크린샷 기반 구현
"""
import time
import logging
from playwright.sync_api import Page

logger = logging.getLogger("budget_helpers")


def select_budget_code(page: Page, project_keyword: str, budget_keyword: str) -> dict:
    """
    예산과목 선택 플로우 실행.

    흐름:
    1. 하단 테이블의 예산과목 필드 클릭 → "공통 예산잔액 조회" 모달 오픈
    2. 모달 내 프로젝트 입력란에 project_keyword 입력 → 자동완성 선택
    3. 예산과목 입력란에 budget_keyword 입력 → 코드도움 아이콘 클릭 → 서브 팝업
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
        modal = _wait_for_budget_modal(page)
        if not modal:
            result["message"] = "공통 예산잔액 조회 모달이 열리지 않음"
            return result
        logger.info("공통 예산잔액 조회 모달 열림")

        # ── 단계 14~15: 모달 내 프로젝트 입력 + 자동완성 선택 ──
        if not _fill_modal_project(page, modal, project_keyword):
            result["message"] = f"모달 프로젝트 입력 실패: '{project_keyword}'"
            return result

        # ── 단계 16: 예산과목 입력 + 코드도움 서브 팝업 ──
        if not _fill_modal_budget_keyword(page, modal, budget_keyword):
            result["message"] = f"예산과목 키워드 입력 실패: '{budget_keyword}'"
            return result

        # ── 단계 16-1~17: 서브 팝업에서 2로 시작하는 코드 선택 ──
        code, name = _select_budget_from_sub_popup(page)
        if not code:
            result["message"] = "서브 팝업에서 2로 시작하는 예산과목코드를 찾지 못함"
            return result

        logger.info(f"예산과목 선택 완료: {code}. {name}")

        # ── 단계 17-확인: 모달 확인 버튼 클릭 ──
        if not _confirm_budget_modal(page, modal):
            result["message"] = "모달 확인 버튼 클릭 실패"
            return result

        result["success"] = True
        result["budget_code"] = code
        result["budget_name"] = name
        result["message"] = f"예산과목 {code}. {name} 설정 완료"
        logger.info(result["message"])
        return result

    except Exception as e:
        logger.error(f"select_budget_code 예외: {e}")
        _save_debug_screenshot(page, "budget_error")
        result["message"] = f"예산과목 선택 중 오류: {e}"
        return result


# ──────────────────────────────────────────────
# 내부 헬퍼 함수
# ──────────────────────────────────────────────


def _click_budget_field(page: Page):
    """단계 12: 하단 테이블의 예산과목 필드 클릭."""
    selectors = [
        "input[placeholder='예산과목']",
        "input[placeholder*='예산과목']",
        "input[placeholder='예산과목코드도움']",
    ]
    for sel in selectors:
        try:
            inputs = page.locator(sel).all()
            for inp in inputs:
                if inp.is_visible(timeout=2000):
                    inp.click(force=True)
                    logger.info(f"예산과목 필드 클릭: {sel}")
                    return inp
        except Exception:
            continue

    # 폴백: "예산과목" 텍스트가 포함된 td/label 옆 input
    try:
        label = page.locator("td:has-text('예산과목'), label:has-text('예산과목')").first
        if label.is_visible(timeout=2000):
            inp = label.locator("xpath=following::input[1]")
            if inp.is_visible(timeout=2000):
                inp.click(force=True)
                logger.info("예산과목 필드 클릭 (label 폴백)")
                return inp
    except Exception:
        pass

    logger.warning("예산과목 필드를 찾을 수 없음")
    return None


def _wait_for_budget_modal(page: Page, timeout_ms: int = 10000):
    """단계 13: '공통 예산잔액 조회' 모달 대기."""
    modal_selectors = [
        "div:has-text('공통 예산잔액 조회')",
        "span:has-text('공통 예산잔액 조회')",
        "div[class*='modal']:has-text('예산잔액')",
        "div[class*='popup']:has-text('예산잔액')",
        "div[class*='layer']:has-text('예산잔액')",
    ]
    for sel in modal_selectors:
        try:
            modal = page.locator(sel).first
            modal.wait_for(state="visible", timeout=timeout_ms)
            if modal.is_visible():
                return modal
        except Exception:
            continue

    logger.warning("공통 예산잔액 조회 모달 감지 실패")
    _save_debug_screenshot(page, "budget_modal_not_found")
    return None


def _fill_modal_project(page: Page, modal, project_keyword: str) -> bool:
    """단계 14~15: 모달 내 프로젝트 입력란에 키워드 입력 후 자동완성 선택."""
    proj_selectors = [
        "input[placeholder='사업코드도움']",
        "input[placeholder*='사업코드']",
        "input[placeholder*='프로젝트']",
    ]

    proj_input = None
    for sel in proj_selectors:
        try:
            inputs = page.locator(sel).all()
            for inp in inputs:
                if inp.is_visible(timeout=2000):
                    proj_input = inp
                    break
            if proj_input:
                break
        except Exception:
            continue

    if not proj_input:
        logger.warning("모달 내 프로젝트 입력란을 찾을 수 없음")
        return False

    # 클릭 → 기존 값 지우기 → 타이핑 (자동완성 트리거용 delay)
    proj_input.click(force=True)
    proj_input.fill("")
    proj_input.type(project_keyword, delay=60)
    logger.info(f"모달 프로젝트 검색어 입력: '{project_keyword}'")

    # 자동완성 드롭다운 대기
    time.sleep(0.8)

    dropdown_selectors = [
        "ul[class*='autocomplete'] li",
        "div[class*='OBTAutoComplete'] li",
        "div[class*='suggest'] li",
        "div[class*='dropdown-menu'] li",
        "div[class*='autoComplete'] li",
    ]
    for sel in dropdown_selectors:
        try:
            item = page.locator(sel).first
            if item.is_visible(timeout=3000):
                item.click()
                logger.info(f"모달 프로젝트 자동완성 선택: {sel}")
                time.sleep(0.3)
                return True
        except Exception:
            continue

    # 폴백: Tab으로 현재 값 확정
    proj_input.press("Tab")
    logger.info("모달 프로젝트 — 드롭다운 미발견, Tab으로 확정")
    time.sleep(0.3)
    return True


def _fill_modal_budget_keyword(page: Page, modal, budget_keyword: str) -> bool:
    """단계 16: 예산과목 입력란에 키워드 입력 + 코드도움 아이콘 클릭."""
    budget_selectors = [
        "input[placeholder='예산과목코드도움']",
        "input[placeholder*='예산과목코드']",
        "input[placeholder*='예산과목']",
    ]

    budget_input = None
    for sel in budget_selectors:
        try:
            # 모달 외에도 같은 placeholder가 있을 수 있으므로 visible 필터
            inputs = page.locator(sel).all()
            for inp in inputs:
                if inp.is_visible(timeout=2000):
                    budget_input = inp
                    break
            if budget_input:
                break
        except Exception:
            continue

    if not budget_input:
        logger.warning("모달 내 예산과목 입력란을 찾을 수 없음")
        return False

    budget_input.click(force=True)
    budget_input.fill("")
    budget_input.type(budget_keyword, delay=60)
    logger.info(f"모달 예산과목 검색어 입력: '{budget_keyword}'")
    time.sleep(0.3)

    # 코드도움 아이콘 클릭 (input 옆 버튼)
    code_help_selectors = [
        "button[class*='codeHelp']",
        "button[class*='CodeHelp']",
        "span[class*='codeHelp']",
        "a[class*='codeHelp']",
        "button[class*='search']",
        "img[alt*='코드도움']",
    ]

    code_help_clicked = False
    for sel in code_help_selectors:
        try:
            # budget_input과 같은 컨테이너 안의 코드도움 버튼 찾기
            parent = budget_input.locator("xpath=ancestor::div[1]")
            btn = parent.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click(force=True)
                code_help_clicked = True
                logger.info(f"예산과목 코드도움 아이콘 클릭: {sel}")
                break
        except Exception:
            continue

    if not code_help_clicked:
        # 폴백: 모든 visible 코드도움 버튼 중 budget_input에 가까운 것
        try:
            for sel in code_help_selectors:
                btns = page.locator(sel).all()
                for btn in btns:
                    if btn.is_visible(timeout=1000):
                        btn.click(force=True)
                        code_help_clicked = True
                        logger.info(f"예산과목 코드도움 폴백 클릭: {sel}")
                        break
                if code_help_clicked:
                    break
        except Exception:
            pass

    if not code_help_clicked:
        # 최종 폴백: Tab으로 서브 팝업 트리거 시도
        budget_input.press("Tab")
        logger.info("코드도움 아이콘 미발견 — Tab 키 폴백")

    time.sleep(1.0)  # 서브 팝업 로딩 대기
    return True


def _select_budget_from_sub_popup(page: Page) -> tuple:
    """
    단계 16-1~17: '예산과목코드도움' 서브 팝업에서 2로 시작하는 행 선택 후 확인.

    Returns:
        (budget_code, budget_name) 또는 ("", "") if 실패
    """
    # 서브 팝업 대기
    sub_popup_selectors = [
        "div:has-text('예산과목코드도움')",
        "span:has-text('예산과목코드도움')",
        "div[class*='modal']:has-text('예산과목코드')",
        "div[class*='popup']:has-text('예산과목코드')",
    ]

    sub_popup = None
    for sel in sub_popup_selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=8000)
            if loc.is_visible():
                sub_popup = loc
                logger.info(f"예산과목코드도움 서브 팝업 감지: {sel}")
                break
        except Exception:
            continue

    if not sub_popup:
        logger.warning("예산과목코드도움 서브 팝업 미발견")
        _save_debug_screenshot(page, "budget_sub_popup_not_found")
        return ("", "")

    time.sleep(0.5)  # 테이블 렌더링 대기

    # 테이블 행에서 2로 시작하는 예산과목코드 찾기
    selected_code = ""
    selected_name = ""

    # 방법 1: 테이블 행(tr/td) 순회
    try:
        rows = page.locator("tr").all()
        for row in rows:
            try:
                cells = row.locator("td").all()
                if len(cells) < 3:
                    continue

                # 예산과목코드는 보통 2번째 컬럼 (0-indexed: 1)
                for col_idx in [1, 2, 0]:
                    cell_text = cells[col_idx].inner_text(timeout=1000).strip()
                    if cell_text and cell_text[0] == "2" and cell_text.isdigit():
                        selected_code = cell_text
                        # 예산과목명은 코드 다음 컬럼
                        name_idx = col_idx + 1
                        if name_idx < len(cells):
                            selected_name = cells[name_idx].inner_text(timeout=1000).strip()
                        # 이 행 클릭
                        row.click()
                        logger.info(f"서브 팝업 행 선택: 코드={selected_code}, 이름={selected_name}")
                        break
                if selected_code:
                    break
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"서브 팝업 테이블 행 순회 실패: {e}")

    # 방법 2: RealGrid/그리드 셀 텍스트 검색 폴백
    if not selected_code:
        try:
            grid_cells = page.locator(
                "div[class*='rg-cell'], td[class*='grid'], span[class*='cell']"
            ).all()
            for i, cell in enumerate(grid_cells):
                try:
                    txt = cell.inner_text(timeout=500).strip()
                    if txt and txt[0] == "2" and txt.isdigit() and len(txt) >= 5:
                        selected_code = txt
                        cell.click()
                        logger.info(f"서브 팝업 그리드 셀 선택 (폴백): {selected_code}")
                        # 이름은 인접 셀에서 시도
                        if i + 1 < len(grid_cells):
                            selected_name = grid_cells[i + 1].inner_text(timeout=500).strip()
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"서브 팝업 그리드 셀 폴백 실패: {e}")

    if not selected_code:
        logger.warning("2로 시작하는 예산과목코드를 찾지 못함")
        _save_debug_screenshot(page, "budget_code_not_found")
        return ("", "")

    time.sleep(0.3)

    # 서브 팝업 확인 버튼 클릭
    confirm_selectors = [
        "button:has-text('확인')",
        "div.btn:has-text('확인')",
        "a:has-text('확인')",
        "input[value='확인']",
    ]
    for sel in confirm_selectors:
        try:
            btns = page.locator(sel).all()
            # 가장 마지막(서브 팝업의) 확인 버튼 클릭
            for btn in reversed(btns):
                if btn.is_visible(timeout=2000):
                    btn.click()
                    logger.info("서브 팝업 확인 버튼 클릭")
                    time.sleep(0.5)
                    return (selected_code, selected_name)
        except Exception:
            continue

    # 확인 버튼 못 찾으면 그래도 코드는 반환
    logger.warning("서브 팝업 확인 버튼 미발견 — 코드는 선택됨")
    return (selected_code, selected_name)


def _confirm_budget_modal(page: Page, modal) -> bool:
    """단계 17-확인: 공통 예산잔액 조회 모달의 확인 버튼 클릭."""
    time.sleep(0.5)  # 예산정보 로딩 대기

    confirm_selectors = [
        "button:has-text('확인')",
        "div.btn:has-text('확인')",
        "a:has-text('확인')",
        "input[value='확인']",
    ]
    for sel in confirm_selectors:
        try:
            btns = page.locator(sel).all()
            # 현재 visible한 확인 버튼 중 마지막 것 (가장 위 레이어)
            for btn in reversed(btns):
                if btn.is_visible(timeout=3000):
                    btn.click()
                    logger.info("공통 예산잔액 조회 모달 확인 버튼 클릭")
                    time.sleep(0.5)
                    return True
        except Exception:
            continue

    logger.warning("모달 확인 버튼을 찾을 수 없음")
    _save_debug_screenshot(page, "budget_modal_confirm_fail")
    return False


def _save_debug_screenshot(page: Page, prefix: str):
    """디버그용 스크린샷 저장."""
    try:
        import os
        screenshot_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "data", "approval_screenshots"
        )
        os.makedirs(screenshot_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(screenshot_dir, f"{prefix}_{timestamp}.png")
        page.screenshot(path=path, full_page=False)
        logger.info(f"디버그 스크린샷 저장: {path}")
    except Exception as e:
        logger.debug(f"스크린샷 저장 실패: {e}")
