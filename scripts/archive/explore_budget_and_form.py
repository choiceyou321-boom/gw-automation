"""
GW DOM 탐색 스크립트: 지출결의서 폼 + 예산관리 탭

목적:
1. 지출결의서 폼 - 보관 버튼 위치, 프로젝트 자동완성 DOM, 툴바 버튼 전체 목록
2. 예산관리 탭 - 프로젝트 등록, 예실대비현황(상세), 예실대비현황(사업별) DOM 구조

결과물: data/dom_explore/
"""

import sys
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "config" / ".env")

from playwright.sync_api import sync_playwright

OUTPUT_DIR = PROJECT_ROOT / "data" / "dom_explore"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_json(data, filename):
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  저장: {filename}")


def capture(target, name):
    path = OUTPUT_DIR / name
    try:
        target.screenshot(path=str(path))
        print(f"  스크린샷: {name}")
    except Exception as e:
        print(f"  스크린샷 실패({name}): {e}")


def dump_elements(target, selector, label, max_count=80):
    """요소 정보 추출"""
    try:
        elements = target.locator(selector).all()
        result = []
        for el in elements[:max_count]:
            try:
                result.append({
                    "tag": el.evaluate("e => e.tagName"),
                    "text": (el.inner_text() or "").strip()[:150],
                    "id": el.get_attribute("id") or "",
                    "className": (el.get_attribute("class") or "")[:200],
                    "href": el.get_attribute("href") or "",
                    "placeholder": el.get_attribute("placeholder") or "",
                    "name": el.get_attribute("name") or "",
                    "type": el.get_attribute("type") or "",
                    "value": el.get_attribute("value") or "",
                    "rect": el.bounding_box() or {},
                    "visible": el.is_visible(timeout=500),
                })
            except Exception:
                continue
        print(f"  {label}: {len(result)}개")
        return result
    except Exception as e:
        print(f"  {label} 추출 실패: {e}")
        return []


def login(pw_instance):
    """GW 로그인 — login_and_get_context로 (browser, context, page) 반환"""
    from src.auth.login import login_and_get_context

    print("로그인 시도...")
    browser, context, page = login_and_get_context(
        playwright_instance=pw_instance,
        headless=False,
    )
    print(f"로그인 완료: {page.url}")

    # 팝업 닫기
    time.sleep(2)
    for p in context.pages[1:]:
        try:
            p.close()
        except Exception:
            pass

    return browser, context, page


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 1: 지출결의서 폼 탐색
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def explore_expense_form(page):
    """지출결의서 폼의 보관 버튼, 프로젝트 자동완성 DOM 탐색"""
    print("\n" + "=" * 60)
    print("Phase 1: 지출결의서 폼 탐색")
    print("=" * 60)

    result = {}

    # 전자결재 모듈 진입
    page.goto("https://gw.glowseoul.co.kr/#/", wait_until="domcontentloaded")
    time.sleep(2)

    # 전자결재 클릭
    approval_btn = page.locator("text=전자결재").first
    if approval_btn.is_visible(timeout=3000):
        approval_btn.click()
        time.sleep(2)

    capture(page, "01_approval_home.png")

    # [프로젝트]지출결의서 양식 클릭
    form_btn = page.locator("text=[프로젝트]지출결의서").first
    if form_btn.is_visible(timeout=3000):
        form_btn.click()
        time.sleep(3)
    else:
        # 양식 목록에서 찾기
        form_btn = page.locator("text=지출결의서작성").first
        if form_btn.is_visible(timeout=3000):
            form_btn.click()
            time.sleep(3)

    capture(page, "02_expense_form.png")
    print(f"  현재 URL: {page.url}")

    # ── 1. 툴바 버튼 전체 목록 ──
    print("\n── 1. 툴바 버튼 전체 ──")
    toolbar_btns = dump_elements(page, "div.topBtn", "div.topBtn 버튼")
    result["toolbar_topBtn"] = toolbar_btns

    # 보관 텍스트가 포함된 모든 요소
    save_elements = dump_elements(page, "*:has-text('보관')", "보관 포함 요소", max_count=30)
    result["save_related"] = save_elements

    # 상단 영역 버튼 (넓은 범위)
    all_buttons = dump_elements(page, "button, [role='button'], a.btn, div[class*='Btn'], div[class*='btn']", "전체 버튼류", max_count=100)
    result["all_buttons"] = all_buttons

    # ── 2. 프로젝트 코드도움 input ──
    print("\n── 2. 프로젝트 코드도움 ──")
    proj_inputs = dump_elements(page, "input[placeholder*='프로젝트'], input[placeholder*='코드도움']", "프로젝트 input")
    result["project_inputs"] = proj_inputs

    # 프로젝트 입력 후 자동완성 DOM 탐색
    proj_input = page.locator("input[placeholder*='프로젝트코드도움']").first
    if proj_input.is_visible(timeout=2000):
        proj_input.click(force=True)
        proj_input.fill("")
        proj_input.type("GS-25-0088", delay=80)
        print("  프로젝트 코드 입력 완료, 자동완성 대기 1초...")
        time.sleep(1)

        capture(page, "03_project_autocomplete.png")

        # 자동완성 드롭다운 DOM 탐색
        # 다양한 셀렉터로 탐색
        autocomplete_selectors = [
            "ul[class*='autocomplete']",
            "div[class*='OBTAutoComplete']",
            "div[class*='AutoComplete']",
            "div[class*='suggest']",
            "div[class*='dropdown']",
            "div[class*='layer']",
            "div[class*='popup']",
            "div[class*='combo']",
            "div[class*='List']",
            "ul.list",
            "div[role='listbox']",
            "ul[role='listbox']",
        ]
        autocomplete_result = {}
        for sel in autocomplete_selectors:
            items = dump_elements(page, sel, f"자동완성({sel})", max_count=10)
            if items:
                autocomplete_result[sel] = items

        result["autocomplete_dom"] = autocomplete_result

        # 가시적인 li 요소 전체 (project input 근처)
        all_visible_li = dump_elements(page, "li:visible", "visible li 전체", max_count=50)
        result["visible_li_elements"] = all_visible_li

        # 전체 HTML 중 autocomplete 관련 부분 추출
        try:
            ac_html = page.evaluate("""() => {
                const els = document.querySelectorAll('[class*="auto"], [class*="Auto"], [class*="combo"], [class*="Combo"], [class*="suggest"], [class*="Suggest"], [class*="dropdown"], [class*="Dropdown"]');
                return Array.from(els).map(el => ({
                    tag: el.tagName,
                    className: el.className.substring(0, 200),
                    id: el.id,
                    childCount: el.children.length,
                    innerHTML: el.innerHTML.substring(0, 500),
                    rect: el.getBoundingClientRect().toJSON(),
                    visible: el.offsetParent !== null
                }));
            }""")
            result["autocomplete_raw_dom"] = ac_html
            print(f"  자동완성 관련 DOM 요소: {len(ac_html)}개")
        except Exception as e:
            print(f"  자동완성 DOM 추출 실패: {e}")

        # Escape 눌러서 드롭다운 닫기
        page.keyboard.press("Escape")
        time.sleep(0.3)

    save_json(result, "expense_form_dom.json")
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 2: 예산관리 탭 탐색
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def explore_budget_tab(page):
    """예산관리 탭 구조 탐색"""
    print("\n" + "=" * 60)
    print("Phase 2: 예산관리 탭 탐색")
    print("=" * 60)

    result = {}

    # 예산관리 URL로 직접 이동 (프로세스갤러리)
    budget_url = "https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0020"
    page.goto(budget_url, wait_until="domcontentloaded")
    time.sleep(3)

    capture(page, "10_budget_home.png")
    print(f"  예산관리 URL: {page.url}")

    # ── 1. 사이드바 메뉴 구조 ──
    print("\n── 1. 사이드바 메뉴 구조 ──")
    sidebar_items = dump_elements(page, "div[class*='lnb'] a, div[class*='lnb'] li, div[class*='side'] a, div[class*='menu'] a, nav a", "사이드바 메뉴", max_count=80)
    result["sidebar_menu"] = sidebar_items

    # 예산관리 하위 메뉴 전체 (클릭 가능한 항목)
    clickable_items = dump_elements(page, "li, a, span[class*='menu'], div[class*='treeNode']", "클릭 가능 항목", max_count=100)
    result["clickable_items"] = clickable_items

    # 전체 텍스트 기반 메뉴 찾기
    try:
        menu_structure = page.evaluate("""() => {
            const result = [];
            // LNB 영역 탐색
            const lnb = document.querySelector('[class*="lnb"], [class*="Lnb"], [class*="side"], [class*="Side"], nav');
            if (lnb) {
                const items = lnb.querySelectorAll('a, li, span');
                items.forEach(el => {
                    const text = el.textContent.trim();
                    if (text && text.length < 30) {
                        result.push({
                            tag: el.tagName,
                            text: text,
                            href: el.href || '',
                            className: el.className.substring(0, 150),
                            depth: el.closest('ul') ?
                                (el.closest('ul').closest('ul') ?
                                    (el.closest('ul').closest('ul').closest('ul') ? 3 : 2) : 1) : 0
                        });
                    }
                });
            }
            return result;
        }""")
        result["menu_structure_parsed"] = menu_structure
        print(f"  메뉴 구조: {len(menu_structure)}개 항목")
    except Exception as e:
        print(f"  메뉴 구조 추출 실패: {e}")

    # ── 2. 예산편성 메뉴 펼치기 ──
    print("\n── 2. 예산편성 / 예산장부 메뉴 펼치기 ──")
    for menu_name in ["예산편성", "예산기초정보설정", "예산장부"]:
        try:
            menu_el = page.locator(f"text={menu_name}").first
            if menu_el.is_visible(timeout=2000):
                menu_el.click()
                time.sleep(1)
                print(f"  '{menu_name}' 클릭 완료")
        except Exception as e:
            print(f"  '{menu_name}' 클릭 실패: {e}")

    capture(page, "11_budget_menus_expanded.png")

    # 펼쳐진 후 하위 메뉴 재탐색
    expanded_items = dump_elements(page, "a, li > span, li > a, div[class*='tree'] span", "펼쳐진 메뉴", max_count=100)
    result["expanded_menu_items"] = expanded_items

    # ── 3. 프로젝트 등록 페이지 ──
    print("\n── 3. 프로젝트 등록 페이지 탐색 ──")
    try:
        proj_link = page.locator("text=프로젝트등록").first
        if not proj_link.is_visible(timeout=2000):
            proj_link = page.locator("text=프로젝트 등록").first
        if proj_link.is_visible(timeout=2000):
            proj_link.click()
            time.sleep(3)
            capture(page, "12_project_registration.png")
            print(f"  프로젝트등록 URL: {page.url}")

            # 페이지 내 필드/테이블 탐색
            proj_fields = dump_elements(page, "input, select, textarea", "프로젝트등록 입력필드")
            result["project_reg_fields"] = proj_fields

            proj_buttons = dump_elements(page, "button, div.topBtn, div[class*='btn'], a[class*='btn']", "프로젝트등록 버튼")
            result["project_reg_buttons"] = proj_buttons

            proj_tables = dump_elements(page, "table, div[class*='grid'], div[class*='Grid']", "프로젝트등록 테이블/그리드")
            result["project_reg_tables"] = proj_tables

            # 그리드 컬럼 헤더
            col_headers = dump_elements(page, "th, div[class*='header'] span, div[class*='Header'] span", "컬럼 헤더", max_count=50)
            result["project_reg_columns"] = col_headers
        else:
            print("  프로젝트등록 메뉴 찾지 못함")
    except Exception as e:
        print(f"  프로젝트등록 탐색 실패: {e}")

    # ── 4. 예실대비현황(상세) ──
    print("\n── 4. 예실대비현황(상세) 탐색 ──")
    try:
        detail_link = page.locator("text=예실대비현황").first
        if not detail_link.is_visible(timeout=2000):
            detail_link = page.locator("a:has-text('예실대비')").first
        if detail_link.is_visible(timeout=2000):
            detail_link.click()
            time.sleep(3)
            capture(page, "13_budget_vs_actual_detail.png")
            print(f"  예실대비현황 URL: {page.url}")

            # 하위 탭/메뉴 확인
            sub_tabs = dump_elements(page, "div[class*='tab'], li[class*='tab'], a[class*='tab'], button[class*='tab']", "하위 탭")
            result["budget_detail_tabs"] = sub_tabs

            # 필터/조건 영역
            detail_fields = dump_elements(page, "input, select, textarea", "상세 조건 필드")
            result["budget_detail_fields"] = detail_fields

            detail_buttons = dump_elements(page, "button, div.topBtn, div[class*='btn']", "상세 버튼")
            result["budget_detail_buttons"] = detail_buttons

            # 그리드/테이블 컬럼
            detail_headers = dump_elements(page, "th, div[class*='header'] span, div[class*='colHeader']", "상세 컬럼", max_count=60)
            result["budget_detail_columns"] = detail_headers
        else:
            print("  예실대비현황 메뉴 찾지 못함")
    except Exception as e:
        print(f"  예실대비현황 탐색 실패: {e}")

    # ── 5. 예실대비현황(사업별) ──
    print("\n── 5. 예실대비현황(사업별) 탐색 ──")
    try:
        # 사업별 탭/링크 찾기
        biz_link = page.locator("text=사업별").first
        if not biz_link.is_visible(timeout=2000):
            biz_link = page.locator("a:has-text('사업별')").first
        if biz_link.is_visible(timeout=2000):
            biz_link.click()
            time.sleep(3)
            capture(page, "14_budget_vs_actual_by_project.png")
            print(f"  사업별 URL: {page.url}")

            biz_fields = dump_elements(page, "input, select, textarea", "사업별 조건 필드")
            result["budget_biz_fields"] = biz_fields

            biz_buttons = dump_elements(page, "button, div.topBtn, div[class*='btn']", "사업별 버튼")
            result["budget_biz_buttons"] = biz_buttons

            biz_headers = dump_elements(page, "th, div[class*='header'] span, div[class*='colHeader']", "사업별 컬럼", max_count=60)
            result["budget_biz_columns"] = biz_headers
        else:
            print("  사업별 메뉴 찾지 못함 — 별도 경로 탐색")
            # 다른 경로 시도
            all_links = dump_elements(page, "a:visible, span:visible", "visible 링크/텍스트", max_count=100)
            result["budget_all_visible_links"] = all_links
    except Exception as e:
        print(f"  사업별 탐색 실패: {e}")

    save_json(result, "budget_tab_dom.json")
    return result


def main():
    print("GW DOM 탐색 시작")
    print(f"출력 디렉토리: {OUTPUT_DIR}")

    with sync_playwright() as pw:
        # 로그인 (browser, context, page 반환)
        browser, context, page = login(pw)

        # Phase 1: 지출결의서 폼 탐색
        expense_result = explore_expense_form(page)

        # Phase 2: 예산관리 탭 탐색
        budget_result = explore_budget_tab(page)

        print("\n" + "=" * 60)
        print("탐색 완료!")
        print(f"결과: {OUTPUT_DIR}")
        print("=" * 60)

        # 브라우저는 열어둠 (수동 확인용)
        input("엔터를 누르면 브라우저를 닫습니다...")
        browser.close()


if __name__ == "__main__":
    main()
