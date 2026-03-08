"""
증빙발행 신청서 / 사내추천비 지급 요청서 DOM 탐색 스크립트
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright
from src.auth.session_manager import SessionManager

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")
DATA_DIR = Path(__file__).parent.parent / "data" / "gw_analysis"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def explore_form(page, search_keyword: str, click_keyword: str, form_label: str) -> dict:
    """단일 양식 탐색"""
    print(f"\n=== {form_label} 탐색 ===")
    result = {"form_label": form_label}

    try:
        # 전자결재 HOME
        page.goto(f"{GW_URL}/#/HP/HPM0110/HPM0110", wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(1500)

        # 결재작성 클릭
        for sel in ["button:has-text('결재작성')", "text=결재작성"]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    btn.click(force=True)
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                continue

        # 검색창 입력
        for sel in ["input[placeholder*='검색']", "input[type='search']", "input.OBTTextField_input", "input"]:
            try:
                inp = page.locator(sel).first
                if inp.is_visible(timeout=2000):
                    inp.fill(search_keyword)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                continue

        # 결과 클릭
        for kw in [click_keyword, search_keyword]:
            try:
                link = page.locator(f"text={kw}").first
                if link.is_visible(timeout=3000):
                    link.click(force=True)
                    page.wait_for_timeout(3000)
                    print(f"클릭: {kw}")
                    result["click_success"] = kw
                    break
            except Exception:
                continue

        result["url"] = page.url
        print(f"URL: {result['url']}")

        # 팝업 감지
        try:
            popup = page.context.wait_for_event("page", timeout=2000)
            if popup:
                result["opened_as_popup"] = True
                result["popup_url"] = popup.url
                print(f"팝업 열림: {popup.url}")
                page = popup  # 팝업 페이지로 전환
                page.wait_for_timeout(1500)
        except Exception:
            result["opened_as_popup"] = False

        # DOM 탐색
        result["inputs"] = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    r.push({
                        tag: el.tagName, type: el.type || '',
                        name: el.name || '', id: el.id || '',
                        placeholder: el.placeholder || '',
                        className: el.className.substring(0, 60),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}
                    });
                }
            });
            return r;
        }""")

        result["labels"] = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('th, label, .label, td.label-cell, span.label').forEach(el => {
                const text = el.innerText?.trim();
                if (text && text.length < 40 && text.length > 0) r.push(text);
            });
            return [...new Set(r)];
        }""")

        result["buttons"] = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('button, [role=button], .OBTButton').forEach(el => {
                const text = el.innerText?.trim();
                if (text && text.length < 50) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0) r.push({text, rect: {x: Math.round(rect.x), y: Math.round(rect.y)}});
                }
            });
            return r;
        }""")

        result["page_text_sample"] = page.inner_text("body")[:1000] if page else ""

        screenshot_path = DATA_DIR / f"{form_label.replace(' ', '_').replace('/', '_')}_dom.png"
        page.screenshot(path=str(screenshot_path))
        result["screenshot"] = str(screenshot_path)

        print(f"inputs: {len(result['inputs'])}개, labels: {len(result['labels'])}개")

    except Exception as e:
        result["error"] = str(e)
        print(f"오류: {e}")

    return result


def main():
    mgr = SessionManager()
    session = mgr.get_or_create_session()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{session.get('cdp_port', 9222)}")
        context = browser.contexts[0]
        page = context.pages[0]

        results = {}
        results["증빙발행"] = explore_form(page, "증빙발행", "[회계팀] 증빙발행 신청서", "증빙발행신청서")
        results["사내추천비"] = explore_form(page, "사내추천비", "사내추천비 지급 요청서", "사내추천비요청서")

        output_path = DATA_DIR / "remaining_forms2_dom.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    main()
