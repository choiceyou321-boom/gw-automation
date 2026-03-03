"""
지출결의서를 팝업 형태로 열기 탐색

인라인 폼에는 보관 버튼이 없지만, 팝업 폼에는 존재할 수 있음.
거래처등록 팝업 URL 패턴(formId=196)을 참고하여 지출결의서(formId=255)도
팝업으로 열 수 있는지 확인.

사용법:
  python scripts/explore_expense_popup_form.py
"""

import sys
import os
import io
import time
import json
import logging
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / "config" / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("explore_popup")

OUTPUT_DIR = ROOT_DIR / "data" / "dom_explore"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GW_URL = "https://gw.glowseoul.co.kr"


def main():
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context

    pw = sync_playwright().start()
    browser, context, page = login_and_get_context(
        playwright_instance=pw, headless=False
    )
    page.set_viewport_size({"width": 1920, "height": 1080})
    logger.info("로그인 완료")

    # ── 방법 1: 팝업 URL 직접 열기 ──
    logger.info("\n=== 방법 1: 팝업 URL로 지출결의서 열기 ===")

    # 거래처등록 팝업 URL 패턴 참고
    # 거래처등록: formId=196, callComp=UBAP001
    # 지출결의서: formId=255, callComp=? (APB1020New가 사용됨)

    popup_url = f"{GW_URL}/#popup?MicroModuleCode=eap&formId=255&callComp=UBAP001"
    popup_page = context.new_page()
    popup_page.set_viewport_size({"width": 1920, "height": 1080})
    popup_page.goto(popup_url)
    try:
        popup_page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(5)

    # 스크린샷
    popup_page.screenshot(path=str(OUTPUT_DIR / "expense_popup_method1.png"))

    # 상단 버튼 확인
    try:
        top_btns = popup_page.locator("div.topBtn").all()
        btn_texts_1 = []
        for btn in top_btns:
            try:
                txt = btn.inner_text().strip()
                btn_texts_1.append(txt)
            except Exception:
                pass
        logger.info(f"방법 1 — div.topBtn: {btn_texts_1}")
    except Exception:
        btn_texts_1 = []

    # 모든 버튼 확인
    try:
        all_btns = popup_page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('button, div.topBtn, [role="button"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.y < 80 && rect.width > 20) {
                    results.push({
                        tag: el.tagName,
                        text: el.textContent?.trim()?.substring(0, 50),
                    });
                }
            });
            return results;
        }""")
        logger.info(f"방법 1 — 모든 상단 버튼: {all_btns}")
    except Exception as e:
        logger.warning(f"버튼 탐색 실패: {e}")

    # 팝업 닫기
    popup_page.close()
    time.sleep(1)

    # ── 방법 2: context.new_page() + JavaScript window.open 시뮬레이션 ──
    logger.info("\n=== 방법 2: 전자결재 양식목록에서 팝업 열기 ===")

    from src.approval.approval_automation import ApprovalAutomation
    automation = ApprovalAutomation(page=page, context=context)
    automation._navigate_to_approval_home()
    time.sleep(2)
    automation._close_popups()

    # 양식목록 전체에서 지출결의서를 찾아 팝업으로 열기 시도
    # JavaScript로 window.open 사용
    popup_page2 = None
    try:
        with context.expect_page(timeout=15000) as popup_info:
            page.evaluate(f"""() => {{
                window.open('{GW_URL}/#popup?MicroModuleCode=eap&formId=255&callComp=UBAP001', '_blank', 'width=1200,height=900');
            }}""")
        popup_page2 = popup_info.value
        popup_page2.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(5)
    except Exception as e:
        logger.warning(f"팝업 열기 실패: {e}")

    if popup_page2:
        popup_page2.screenshot(path=str(OUTPUT_DIR / "expense_popup_method2.png"))
        # 상단 버튼
        try:
            top_btns2 = popup_page2.locator("div.topBtn").all()
            btn_texts_2 = []
            for btn in top_btns2:
                try:
                    txt = btn.inner_text().strip()
                    btn_texts_2.append(txt)
                except Exception:
                    pass
            logger.info(f"방법 2 — div.topBtn: {btn_texts_2}")
        except Exception:
            btn_texts_2 = []

        # 폼 내용 확인
        try:
            title_text = popup_page2.locator("text=지출결의서").first.inner_text()
            logger.info(f"방법 2 — 폼 제목 확인: {title_text}")
        except Exception:
            pass

        try:
            all_btns2 = popup_page2.evaluate("""() => {
                const results = [];
                document.querySelectorAll('button, div.topBtn, [role="button"]').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.y < 80 && rect.width > 20) {
                        results.push({
                            tag: el.tagName,
                            text: el.textContent?.trim()?.substring(0, 50),
                        });
                    }
                });
                return results;
            }""")
            logger.info(f"방법 2 — 모든 상단 버튼: {all_btns2}")
        except Exception:
            pass

        popup_page2.close()
    else:
        btn_texts_2 = []

    # ── 방법 3: 전자결재 양식 선택 메뉴에서 새창 열기 ──
    logger.info("\n=== 방법 3: 양식검색에서 지출결의서 새 창 열기 ===")

    # 전자결재 기안작성에서 양식 선택 → "새창으로 열기" 옵션 확인
    # 기안작성 페이지 직접 이동
    draft_url = f"{GW_URL}/#/HP/APB1020/APB1020?MicroModuleCode=eap"
    page.goto(draft_url)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(3)

    # 양식 목록에서 [프로젝트]지출결의서 항목에 우클릭 메뉴 확인
    form_items = page.locator("text=지출결의서").all()
    form_texts = []
    for item in form_items[:10]:
        try:
            txt = item.inner_text().strip()[:60]
            form_texts.append(txt)
        except Exception:
            pass
    logger.info(f"양식 목록: {form_texts}")

    # ── 결과 요약 ──
    result = {
        "method1_popup_url": {
            "url": popup_url,
            "top_buttons": btn_texts_1,
            "has_save_btn": "보관" in btn_texts_1,
        },
        "method2_window_open": {
            "top_buttons": btn_texts_2,
            "has_save_btn": "보관" in btn_texts_2 if btn_texts_2 else False,
        },
    }
    result_path = OUTPUT_DIR / "expense_popup_form_result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print("탐색 결과:")
    print(f"  방법 1 (팝업 URL): 보관 버튼 = {'보관' in btn_texts_1}")
    print(f"    버튼: {btn_texts_1}")
    print(f"  방법 2 (window.open): 보관 버튼 = {'보관' in btn_texts_2}")
    print(f"    버튼: {btn_texts_2}")
    print(f"{'='*60}")

    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
