"""
근태관리 모듈 탐색 스크립트
- 연장근무신청서 (formId=43)
- 외근신청서(당일) (formId=41)
- 실제 신청 UI 필드 구조 파악
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright
from src.auth.login import login_to_gw
from src.auth.session_manager import SessionManager

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")
DATA_DIR = Path(__file__).parent.parent / "data" / "gw_analysis"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def explore_overtime_forms():
    """연장근무 / 외근 신청 폼 탐색"""
    mgr = SessionManager()
    session = mgr.get_or_create_session()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{session.get('cdp_port', 9222)}")
        context = browser.contexts[0]
        page = context.pages[0]

        result = {}

        # --- 연장근무신청서 / 외근신청서 순서대로 탐색 ---
        for form_name, form_id in [("연장근무신청서", "43"), ("외근신청서(당일)", "41")]:
            print(f"\n=== {form_name} 탐색 ===")
            try:
                # 전자결재 HOME으로 이동
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

                # 검색창에 양식명 입력
                search_input = None
                search_term = form_name.split("(")[0]  # "연장근무신청서" or "외근신청서"
                for sel in ["input[placeholder*='검색']", "input[type='search']", "input.OBTTextField"]:
                    try:
                        inp = page.locator(sel).first
                        if inp.is_visible(timeout=2000):
                            inp.fill(search_term)
                            search_input = inp
                            break
                    except Exception:
                        continue

                if search_input:
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(2000)

                # 검색 결과에서 클릭
                for keyword in [form_name, form_name.split("(")[0]]:
                    try:
                        link = page.locator(f"text={keyword}").first
                        if link.is_visible(timeout=3000):
                            link.click(force=True)
                            page.wait_for_timeout(3000)
                            print(f"클릭: {keyword}")
                            break
                    except Exception:
                        continue

                # 현재 URL 및 DOM 캡처
                current_url = page.url
                print(f"URL: {current_url}")

                # 입력 필드 탐색
                inputs = page.evaluate("""() => {
                    const result = [];
                    document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach(el => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            result.push({
                                tag: el.tagName,
                                type: el.type || '',
                                name: el.name || '',
                                id: el.id || '',
                                placeholder: el.placeholder || '',
                                value: el.value || '',
                                className: el.className.substring(0, 60),
                                rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}
                            });
                        }
                    });
                    return result;
                }""")

                # 라벨 탐색
                labels = page.evaluate("""() => {
                    const result = [];
                    document.querySelectorAll('th, label, .label, .fieldLabel').forEach(el => {
                        const text = el.innerText?.trim();
                        if (text && text.length < 30) result.push(text);
                    });
                    return [...new Set(result)];
                }""")

                # 버튼 탐색
                buttons = page.evaluate("""() => {
                    const result = [];
                    document.querySelectorAll('button, [role=button]').forEach(el => {
                        const text = el.innerText?.trim();
                        if (text && text.length < 50) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0) result.push({text, rect: {x: Math.round(rect.x), y: Math.round(rect.y)}});
                        }
                    });
                    return result;
                }""")

                result[form_name] = {
                    "url": current_url,
                    "inputs": inputs,
                    "labels": labels,
                    "buttons": buttons,
                }

                # 스크린샷
                screenshot_name = "overtime" if "연장" in form_name else "outside"
                screenshot_path = DATA_DIR / f"overtime_{screenshot_name}_form.png"
                page.screenshot(path=str(screenshot_path))
                print(f"스크린샷: {screenshot_path}")
                print(f"inputs: {len(inputs)}개, labels: {len(labels)}개, buttons: {len(buttons)}개")

            except Exception as e:
                print(f"오류: {e}")
                result[form_name] = {"error": str(e)}

        # 결과 저장
        output_path = DATA_DIR / "overtime_forms_dom.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {output_path}")
        return result


if __name__ == "__main__":
    explore_overtime_forms()
