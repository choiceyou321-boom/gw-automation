"""
상신 문서 목록 수집 스크립트
- 전자결재 → 상신/보관함 이동 → 문서 리스트 캡쳐
- 양식 종류별 분류
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

OUTPUT_DIR = ROOT_DIR / "data" / "approval_docs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_screenshot(page, name: str):
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
        # 1. 전자결재 모듈 이동
        logger.info("전자결재 모듈 이동...")
        ea_link = page.locator("span.module-link.EA").first
        ea_link.click(force=True)
        time.sleep(5)
        save_screenshot(page, "01_approval_home")

        # 2. 결재 HOME에서 "상신문서" 섹션 텍스트 캡쳐 (더보기 클릭 전)
        logger.info("결재 HOME 텍스트 수집...")
        home_text = page.inner_text("body")
        (OUTPUT_DIR / "home_text.txt").write_text(home_text, encoding="utf-8")

        # 3. 사이드바에서 "상신" 또는 "보관" 메뉴 찾기
        logger.info("상신/보관함 메뉴 찾기...")
        sidebar_clicked = False

        for keyword in ["상신/보관함", "상신/보관", "상신함", "기안함"]:
            try:
                links = page.locator(f"text={keyword}").all()
                for link in links:
                    if link.is_visible():
                        link.click(force=True)
                        logger.info(f"사이드바 클릭: '{keyword}'")
                        sidebar_clicked = True
                        time.sleep(5)
                        break
                if sidebar_clicked:
                    break
            except Exception:
                continue

        if not sidebar_clicked:
            # 대안: 사이드바의 모든 메뉴 텍스트 수집
            logger.warning("상신/보관함 직접 클릭 실패, 사이드바 메뉴 수집...")
            try:
                sidebar_items = page.locator(".snb-item, .menu-item, [class*='menu'] a, [class*='Menu'] a, li a").all()
                menu_texts = []
                for item in sidebar_items:
                    try:
                        txt = item.inner_text(timeout=1000).strip()
                        if txt:
                            menu_texts.append(txt)
                    except Exception:
                        pass
                (OUTPUT_DIR / "sidebar_menus.json").write_text(
                    json.dumps(menu_texts, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                logger.info(f"사이드바 메뉴 {len(menu_texts)}개 수집")
            except Exception as e:
                logger.warning(f"사이드바 수집 실패: {e}")

        save_screenshot(page, "02_after_sidebar_click")

        # 4. 현재 URL 확인
        logger.info(f"현재 URL: {page.url}")

        # 5. 문서 목록 캡쳐 - 테이블/리스트에서 추출
        logger.info("문서 목록 수집...")
        docs = []

        # 방법 A: 테이블 행에서 추출
        try:
            rows = page.locator("table tbody tr").all()
            logger.info(f"테이블 행: {len(rows)}개")
            for i, row in enumerate(rows[:100]):  # 최대 100개
                try:
                    text = row.inner_text(timeout=2000).strip()
                    if text:
                        cells = [c.strip() for c in text.split("\t") if c.strip()]
                        if not cells:
                            cells = [c.strip() for c in text.split("\n") if c.strip()]
                        docs.append({"index": i, "cells": cells, "raw": text[:300]})
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"테이블 추출 실패: {e}")

        # 방법 B: 그리드/리스트 아이템에서 추출
        if not docs:
            try:
                items = page.locator("[class*='list'] [class*='item'], [class*='grid'] [class*='row'], [class*='Row']").all()
                logger.info(f"리스트 아이템: {len(items)}개")
                for i, item in enumerate(items[:100]):
                    try:
                        text = item.inner_text(timeout=2000).strip()
                        if text and len(text) > 5:
                            docs.append({"index": i, "raw": text[:300]})
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"리스트 추출 실패: {e}")

        # 방법 C: OBT 그리드 (더존 컴포넌트)
        if not docs:
            try:
                obt_rows = page.locator("[class*='OBTGrid'], [class*='OBTListGrid'], [class*='obt-grid']").all()
                logger.info(f"OBT 그리드: {len(obt_rows)}개")
                for i, row in enumerate(obt_rows[:10]):
                    try:
                        text = row.inner_text(timeout=3000).strip()
                        if text:
                            docs.append({"index": i, "raw": text[:1000]})
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"OBT 그리드 실패: {e}")

        # 결과 저장
        (OUTPUT_DIR / "doc_list.json").write_text(
            json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"문서 {len(docs)}건 수집됨")

        save_screenshot(page, "03_doc_list")

        # 6. 페이지 전체 HTML 저장 (분석용)
        html = page.content()
        (OUTPUT_DIR / "page_content.html").write_text(html, encoding="utf-8")

        # 7. 네트워크 캡쳐 - API 응답에서 문서 목록 데이터 찾기
        logger.info("API 기반 문서 목록 캡쳐 시도...")
        api_data = []

        def handle_response(response):
            url = response.url
            if any(kw in url.lower() for kw in ["eap", "approval", "apb", "draft", "sanction", "document", "list"]):
                try:
                    body = response.json()
                    api_data.append({"url": url, "status": response.status, "data": body})
                    logger.info(f"API 캡쳐: {url[:100]}")
                except Exception:
                    pass

        page.on("response", handle_response)

        # 페이지 새로고침으로 API 캡쳐
        page.reload(wait_until="domcontentloaded")
        time.sleep(8)

        if api_data:
            (OUTPUT_DIR / "api_responses.json").write_text(
                json.dumps(api_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(f"API 응답 {len(api_data)}개 캡쳐")

        save_screenshot(page, "04_after_reload")

        # 8. 상신문서 "더보기" 링크가 있으면 클릭
        try:
            more_links = page.locator("text=더보기").all()
            for link in more_links:
                if link.is_visible():
                    # 주변 텍스트 확인
                    parent_text = link.locator("xpath=..").inner_text(timeout=1000)
                    if "상신" in parent_text or "기안" in parent_text:
                        link.click(force=True)
                        logger.info("상신문서 '더보기' 클릭")
                        time.sleep(5)
                        save_screenshot(page, "05_more_docs")
                        break
        except Exception:
            pass

        # 9. 전체 페이지 텍스트 다시 수집
        final_text = page.inner_text("body")
        (OUTPUT_DIR / "final_page_text.txt").write_text(final_text, encoding="utf-8")

        logger.info("=== 수집 완료 ===")
        logger.info(f"결과: {OUTPUT_DIR}")

    except Exception as e:
        logger.error(f"오류: {e}", exc_info=True)
        save_screenshot(page, "error")
    finally:
        close_session(browser)
        pw.stop()


if __name__ == "__main__":
    run()
