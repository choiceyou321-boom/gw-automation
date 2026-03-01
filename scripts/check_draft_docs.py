"""
임시보관 문서 페이지 확인
URL: /#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1020
"""

import json
import time
import sys
import logging
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from playwright.sync_api import sync_playwright
from src.auth.login import login_and_get_context, close_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = ROOT_DIR / "data" / "approval_drafts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GW_URL = "https://gw.glowseoul.co.kr"
DRAFT_URL = f"{GW_URL}/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1020"


def save_screenshot(page, name):
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path))
    logger.info(f"스크린샷: {path}")


def run():
    pw = sync_playwright().start()
    browser, context, page = login_and_get_context(
        playwright_instance=pw, headless=False
    )
    page.set_viewport_size({"width": 1920, "height": 1080})

    try:
        # 1. 임시보관 문서 URL로 직접 이동
        logger.info(f"임시보관 문서 페이지 이동: {DRAFT_URL}")
        page.goto(DRAFT_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(8)
        save_screenshot(page, "01_draft_page")

        logger.info(f"현재 URL: {page.url}")

        # 2. 페이지 텍스트 수집
        body_text = page.inner_text("body")
        (OUTPUT_DIR / "page_text.txt").write_text(body_text, encoding="utf-8")
        logger.info("페이지 텍스트 저장 완료")

        # 3. 테이블/리스트에서 문서 목록 추출
        docs = []

        # 테이블 행 추출
        rows = page.locator("table tbody tr").all()
        logger.info(f"테이블 행: {len(rows)}개")
        for i, row in enumerate(rows[:200]):
            try:
                text = row.inner_text(timeout=2000).strip()
                if text and len(text) > 3:
                    cells = [c.strip() for c in text.split("\t") if c.strip()]
                    if not cells:
                        cells = [c.strip() for c in text.split("\n") if c.strip()]
                    docs.append({"index": i, "cells": cells, "raw": text[:500]})
            except Exception:
                continue

        # OBT 그리드 추출
        if not docs:
            try:
                grid_cells = page.locator("[class*='OBTGrid'] [class*='cell'], [class*='grid'] td").all()
                logger.info(f"그리드 셀: {len(grid_cells)}개")
                row_data = []
                for cell in grid_cells[:500]:
                    try:
                        txt = cell.inner_text(timeout=1000).strip()
                        if txt:
                            row_data.append(txt)
                    except Exception:
                        continue
                if row_data:
                    docs.append({"type": "grid_cells", "data": row_data})
            except Exception as e:
                logger.warning(f"그리드 추출 실패: {e}")

        (OUTPUT_DIR / "doc_list.json").write_text(
            json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"문서 {len(docs)}건 수집")

        # 4. API 응답 캡쳐
        api_data = []

        def handle_response(response):
            url = response.url
            if any(kw in url.lower() for kw in ["eap", "apb", "uba", "draft", "document", "list", "gw104"]):
                try:
                    body = response.json()
                    api_data.append({"url": url, "status": response.status, "data": body})
                    logger.info(f"API 캡쳐: {url[:120]}")
                except Exception:
                    pass

        page.on("response", handle_response)

        # 페이지 새로고침으로 API 캡쳐
        page.reload(wait_until="domcontentloaded")
        time.sleep(8)

        save_screenshot(page, "02_after_reload")

        if api_data:
            (OUTPUT_DIR / "api_responses.json").write_text(
                json.dumps(api_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(f"API 응답 {len(api_data)}개 캡쳐")

        # 5. 전체 페이지 텍스트 다시 수집
        final_text = page.inner_text("body")
        (OUTPUT_DIR / "final_text.txt").write_text(final_text, encoding="utf-8")

        # 6. HTML 저장
        html = page.content()
        (OUTPUT_DIR / "page.html").write_text(html, encoding="utf-8")

        logger.info("=== 수집 완료 ===")

    except Exception as e:
        logger.error(f"오류: {e}", exc_info=True)
        save_screenshot(page, "error")
    finally:
        close_session(browser)
        pw.stop()


if __name__ == "__main__":
    run()
