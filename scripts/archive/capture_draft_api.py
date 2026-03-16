"""
거래처등록 보관 API 캡처 v4 — CDP Network 도메인 사용

Playwright route()가 iframe 요청을 놓칠 수 있으므로
CDP를 직접 사용하여 모든 네트워크 요청을 캡처

사용법:
  python scripts/capture_draft_api.py
"""

import sys
import os
import io
import time
import json
import logging
import base64
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
logger = logging.getLogger("capture_draft_api")

OUTPUT_DIR = ROOT_DIR / "data" / "dom_explore"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GW_URL = "https://gw.glowseoul.co.kr"


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

    automation = ApprovalAutomation(page=page, context=context)

    # ── 거래처등록 실제 작성 → 보관 API 캡처 ──
    logger.info("=== 거래처등록 실제 작성 후 보관 API 캡처 ===")

    test_data = {
        "title": "[API캡처] 거래처등록 테스트",
        "vendor_name": "테스트캡처용(삭제예정)",
        "ceo_name": "홍길동",
        "business_number": "000-00-00000",
        "business_type": "테스트",
        "business_item": "테스트",
        "address": "서울시 종로구",
        "bank_name": "테스트은행",
        "account_number": "0000000000",
        "account_holder": "홍길동",
    }

    # 실제 create_vendor_registration 실행하되, _save_draft_in_popup 직전에 CDP 캡처 시작
    # → 기존 메서드를 그대로 쓰면 캡처 타이밍 제어 불가하므로 수동으로 진행

    automation._navigate_to_approval_home()
    time.sleep(2)
    automation._close_popups()

    # 거래처등록 팝업
    popup_page = None
    form_link = page.locator("text=거래처등록").first
    with context.expect_page(timeout=15000) as popup_info:
        form_link.click(force=True)
    popup_page = popup_info.value
    popup_page.wait_for_load_state("domcontentloaded", timeout=15000)
    logger.info(f"팝업 열림: {popup_page.url[:80]}")
    time.sleep(3)

    # 다이얼로그
    dialog_msgs = []
    popup_page.on("dialog", lambda d: (dialog_msgs.append(d.message), d.accept()))

    # 필드 채우기 — automation 객체의 page를 임시 교체
    original_page = automation.page
    automation.page = popup_page
    try:
        automation._fill_vendor_fields(test_data)
        logger.info("필드 채우기 완료")
    except Exception as e:
        logger.warning(f"필드 채우기 일부 실패: {e}")
    automation.page = original_page
    time.sleep(2)

    # ── CDP 네트워크 캡처 시작 ──
    cdp = context.new_cdp_session(popup_page)
    cdp.send("Network.enable")

    captured_requests = {}  # requestId -> data
    captured_responses = {}

    def on_request_will_be_sent(params):
        req_id = params["requestId"]
        url = params["request"]["url"]
        method = params["request"]["method"]
        post_data = params["request"].get("postData", "")
        if method == "POST":
            captured_requests[req_id] = {
                "url": url,
                "method": method,
                "post_data": post_data[:5000],
                "timestamp": datetime.now().isoformat(),
            }
            logger.info(f"  [CDP] POST {url[:120]}")
            if post_data:
                logger.info(f"         body: {post_data[:500]}")

    def on_response_received(params):
        req_id = params["requestId"]
        status = params["response"]["status"]
        url = params["response"]["url"]
        if req_id in captured_requests:
            captured_requests[req_id]["response_status"] = status

    def on_loading_finished(params):
        req_id = params["requestId"]
        if req_id in captured_requests:
            try:
                body = cdp.send("Network.getResponseBody", {"requestId": req_id})
                resp_body = body.get("body", "")[:5000]
                captured_requests[req_id]["response_body"] = resp_body
            except Exception:
                pass

    cdp.on("Network.requestWillBeSent", on_request_will_be_sent)
    cdp.on("Network.responseReceived", on_response_received)
    cdp.on("Network.loadingFinished", on_loading_finished)

    logger.info("CDP 네트워크 캡처 활성화")

    # ★ 보관 버튼 클릭
    save_btn = None
    for btn in popup_page.locator("div.topBtn").all():
        try:
            if btn.inner_text().strip() == "보관":
                save_btn = btn
                break
        except Exception:
            pass

    if not save_btn:
        logger.error("보관 버튼 없음!")
        browser.close(); pw.stop()
        return

    logger.info("\n★★★ 보관 클릭! ★★★")
    save_btn.click(force=True)
    time.sleep(12)

    # CDP 종료
    try:
        cdp.detach()
    except Exception:
        pass

    # ── 결과 출력 ──
    post_requests = list(captured_requests.values())
    logger.info(f"\n{'='*60}")
    logger.info(f"CDP 캡처된 POST 요청: {len(post_requests)}건")
    logger.info(f"다이얼로그: {dialog_msgs}")
    logger.info(f"{'='*60}")

    for i, req in enumerate(post_requests):
        logger.info(f"\n[{i}] {req['url']}")
        logger.info(f"    status: {req.get('response_status', 'N/A')}")
        if req.get("post_data"):
            try:
                pd = json.loads(req["post_data"])
                logger.info(f"    body: {json.dumps(pd, ensure_ascii=False)[:1000]}")
            except Exception:
                logger.info(f"    body: {req['post_data'][:500]}")
        if req.get("response_body"):
            logger.info(f"    response: {req['response_body'][:500]}")

    # 팝업 상태
    try:
        if popup_page and not popup_page.is_closed():
            popup_page.screenshot(path=str(OUTPUT_DIR / "cdp_after_save_popup.png"))
            logger.info(f"팝업 상태: 열림 — {popup_page.url[:80]}")
        else:
            logger.info("팝업 상태: 닫힘")
    except Exception:
        logger.info("팝업 접근 불가")

    page.screenshot(path=str(OUTPUT_DIR / "cdp_after_save_main.png"))

    # JSON 저장
    result_path = OUTPUT_DIR / "draft_api_capture_v4.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({
            "post_requests": post_requests,
            "dialogs": dialog_msgs,
        }, f, ensure_ascii=False, indent=2)
    logger.info(f"결과 저장: {result_path}")

    # ★ cleanup
    logger.info("\n=== cleanup ===")
    time.sleep(2)
    try:
        # 팝업 닫기
        if popup_page and not popup_page.is_closed():
            popup_page.close()
        time.sleep(1)
        page.on("dialog", lambda d: d.accept())
        draft_url = f"{GW_URL}/#/UB/UB/UBA0000?appCode=approval&viewType=list&menuCode=UBD9999&subMenuCode=UBA1060"
        page.goto(draft_url)
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(2)
        row = page.locator("text=[API캡처]").first
        if row.is_visible(timeout=5000):
            row.click()
            time.sleep(3)
            pages = context.pages
            target = pages[-1] if len(pages) > 1 else page
            target.on("dialog", lambda d: d.accept())
            del_btn = target.locator("div.topBtn:has-text('삭제')")
            if del_btn.is_visible(timeout=3000):
                del_btn.click(force=True)
                time.sleep(3)
                logger.info("임시보관 삭제 완료")
            if len(pages) > 1 and not target.is_closed():
                target.close()
        else:
            logger.info("삭제 대상 없음")
    except Exception as e:
        logger.warning(f"cleanup: {e}")

    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
