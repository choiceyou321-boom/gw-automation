"""
지출결의서 결재상신 클릭 시 팝업 생성 여부 탐색 스크립트

목적: 인라인 지출결의서 폼에서 필수 필드를 채운 후
      결재상신을 클릭했을 때 팝업이 열리는지 확인
      (page.route()로 실제 상신 API를 차단하여 안전하게 테스트)

사용법:
  python scripts/explore_expense_submit_popup.py
"""

import sys
import os
import io
import time
import json
import logging
from pathlib import Path
from datetime import datetime

# Windows cp949 인코딩 문제 방지
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / "config" / ".env")

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("explore_submit_popup")

OUTPUT_DIR = ROOT_DIR / "data" / "dom_explore"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_screenshot(page, name: str):
    """스크린샷 저장"""
    path = OUTPUT_DIR / f"expense_submit_{name}_{datetime.now().strftime('%H%M%S')}.png"
    page.screenshot(path=str(path), full_page=False)
    logger.info(f"스크린샷 저장: {path.name}")


def main():
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context
    from src.approval.approval_automation import ApprovalAutomation

    pw = sync_playwright().start()
    browser, context, page = login_and_get_context(
        playwright_instance=pw, headless=False
    )
    page.set_viewport_size({"width": 1920, "height": 1080})
    logger.info("로그인 완료")

    # ── 결재 API 차단 (실제 상신 방지) ──
    blocked_requests = []

    def block_approval_api(route):
        """결재 상신 API 요청 차단 — 로그만 남기고 abort"""
        url = route.request.url
        logger.warning(f"[BLOCKED] 결재 API 차단: {url}")
        blocked_requests.append({
            "url": url,
            "method": route.request.method,
            "post_data": route.request.post_data[:500] if route.request.post_data else None,
        })
        route.abort("blockedbyclient")

    # 상신 관련 API 패턴 차단
    page.route("**/gw/APIHandler/UBA*", block_approval_api)
    page.route("**/gw/APIHandler/EAA*", block_approval_api)
    logger.info("결재 API 차단 설정 완료")

    # ── 지출결의서 폼 열기 + 필드 채우기 ──
    automation = ApprovalAutomation(page=page, context=context)

    try:
        automation._navigate_to_approval_home()
        time.sleep(2)
        automation._click_expense_form()
        time.sleep(2)
        automation._wait_for_form_load()
        time.sleep(1)

        # 필수 필드 채우기
        test_data = {
            "title": "[탐색테스트] 결재상신 팝업 확인",
            "description": "탐색 스크립트에서 자동 생성",
            "project": "GS-25-0088",
            "items": [{"item": "테스트 항목", "amount": 1000}],
            "total_amount": 1000,
        }
        automation._fill_expense_fields(test_data)
        time.sleep(1)
        save_screenshot(page, "01_fields_filled")
        logger.info("필드 채우기 완료")

        # ── 결재상신 버튼 확인 ──
        submit_btn = page.locator("button:has-text('결재상신')").first
        if not submit_btn.is_visible(timeout=5000):
            logger.error("결재상신 버튼 미발견!")
            save_screenshot(page, "02_no_submit_btn")
            return

        logger.info("결재상신 버튼 발견 — 클릭 시도")
        save_screenshot(page, "02_before_click")

        # ── 결재상신 클릭 → 팝업 관찰 ──
        popup_page = None
        try:
            with context.expect_page(timeout=10000) as popup_info:
                submit_btn.click(force=True)
            popup_page = popup_info.value
            popup_page.wait_for_load_state("domcontentloaded", timeout=10000)
            logger.info(f"★ 팝업 열림! URL: {popup_page.url}")
        except Exception as e:
            logger.info(f"팝업 대기 타임아웃: {e}")

        time.sleep(3)
        save_screenshot(page, "03_after_click_main")

        # 팝업이 열렸으면 분석
        if popup_page:
            save_screenshot(popup_page, "03_popup")
            # 보관 버튼 확인
            save_btns = popup_page.locator("div.topBtn").all()
            btn_texts = []
            for btn in save_btns:
                try:
                    txt = btn.inner_text().strip()
                    btn_texts.append(txt)
                except Exception:
                    pass
            logger.info(f"팝업 상단 버튼들: {btn_texts}")

            has_save = any("보관" in t for t in btn_texts)
            logger.info(f"★ 보관 버튼 존재: {has_save}")
        else:
            # 팝업 없이 모달이 열렸을 수 있음 — context.pages 확인
            all_pages = context.pages
            logger.info(f"컨텍스트 페이지 수: {len(all_pages)}")
            for i, p in enumerate(all_pages):
                logger.info(f"  page[{i}]: {p.url[:80]}")

            # 모달 확인
            try:
                modal_text = page.evaluate("""() => {
                    let results = [];
                    document.querySelectorAll('*').forEach(el => {
                        const z = parseInt(getComputedStyle(el).zIndex) || 0;
                        if (z > 100 && el.offsetParent !== null && el.textContent?.trim()) {
                            results.push({z, tag: el.tagName, text: el.textContent.trim().substring(0, 200)});
                        }
                    });
                    return results.sort((a,b) => b.z - a.z).slice(0, 5);
                }""")
                logger.info(f"고 z-index 요소: {json.dumps(modal_text, ensure_ascii=False, indent=2)}")
            except Exception as e:
                logger.warning(f"모달 확인 실패: {e}")

        # ── 결과 요약 ──
        result = {
            "popup_opened": popup_page is not None,
            "popup_url": popup_page.url if popup_page else None,
            "blocked_requests": blocked_requests,
            "context_pages": len(context.pages),
        }
        result_path = OUTPUT_DIR / "expense_submit_popup_result.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"결과 저장: {result_path}")

        print("\n" + "=" * 60)
        print("탐색 결과:")
        print(f"  팝업 열림: {result['popup_opened']}")
        if popup_page:
            print(f"  팝업 URL: {popup_page.url[:80]}")
        print(f"  차단된 API: {len(blocked_requests)}건")
        for req in blocked_requests:
            print(f"    - {req['method']} {req['url'][:80]}")
        print("=" * 60)

    except Exception as e:
        logger.error(f"탐색 실패: {e}", exc_info=True)
        save_screenshot(page, "error")

    finally:
        input("\n[Enter]를 누르면 브라우저를 닫습니다...")
        browser.close()
        pw.stop()


if __name__ == "__main__":
    main()
