"""
예실대비현황 스크린샷 캡처 헬퍼.

지출결의서 양식 내 하단 예산 잔액 현황 테이블을 스크린샷으로 캡처하여
"예실대비 첨부" 기능을 지원한다. 상세 뷰 전환 + 섹션 캡처 + 폴백 전체화면.

이전에 `ExpenseReportMixin.capture_budget_status_screenshot`로 존재했으나
파일 분할 작업의 일환으로 독립 모듈로 추출됨.
"""
from __future__ import annotations

import datetime
import logging
from playwright.sync_api import Page

from src.approval.base import SCREENSHOT_DIR

logger = logging.getLogger("approval_automation")


def capture_budget_status_screenshot(
    page: Page, output_path: str | None = None, detail_view: bool = True
) -> str | None:
    """예실대비현황(상세) 화면 스크린샷 캡처.

    Args:
        page: Playwright Page (지출결의서 양식 페이지)
        output_path: 저장 경로 (None이면 SCREENSHOT_DIR에 timestamp로 자동 생성)
        detail_view: True이면 "상세" 버튼 클릭 후 캡처 (기본값)
    Returns:
        저장된 파일 경로 (str) 또는 None (실패 시).
    """
    if output_path is None:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(SCREENSHOT_DIR / f"budget_status_{ts}.png")

    if detail_view:
        click_budget_detail_view(page)

    # 하단 예산 영역으로 스크롤 (page height 60% 지점)
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
        page.wait_for_timeout(800)
    except Exception:
        pass

    # 예실대비현황 섹션 element 우선 캡처 (섹션만 crop)
    budget_section_selectors = [
        "text=예실대비현황",
        "div:has(> h3:has-text('예실대비'))",
        "table:has(th:has-text('실행예산'))",
        "table:has(th:has-text('예산잔액'))",
        "table:has(th:has-text('집행액'))",
    ]
    for sel in budget_section_selectors:
        try:
            section = page.locator(sel).first
            if section.is_visible(timeout=1500):
                section.screenshot(path=output_path)
                logger.info(f"예실대비현황 섹션 스크린샷 저장: {output_path} (셀렉터: {sel})")
                return output_path
        except Exception:
            continue

    # 폴백: 전체 화면 캡처
    try:
        page.screenshot(path=output_path, full_page=False)
        logger.info(f"예실대비현황 전체화면 스크린샷 저장: {output_path}")
        return output_path
    except Exception as e:
        logger.warning(f"스크린샷 캡처 실패: {e}")
        return None


def click_budget_detail_view(page: Page) -> bool:
    """예실대비현황 "상세" 뷰 전환 버튼 클릭.

    더존 GW 지출결의서 하단의 "상세" 또는 "예실대비현황(상세)" 탭/버튼 클릭 시
    실행예산액/이월예산액/예산총액/집행액/사용가능여부/예산잔액이 표시된다.

    Returns:
        True if 상세 버튼 클릭 성공, False if 미발견 (일반 뷰로 fallback).
    """
    detail_selectors = [
        "button:has-text('상세')",
        "a:has-text('상세')",
        "span:has-text('상세')",
        "div[class*='tab']:has-text('상세')",
        "li[class*='tab']:has-text('상세')",
        "button:has-text('예실대비현황')",
        "a:has-text('예실대비현황')",
        "[title='상세']",
        "[title='예실대비현황 상세']",
        "[aria-label*='상세']",
    ]
    for sel in detail_selectors:
        try:
            btns = page.locator(sel).all()
            for btn in btns:
                if btn.is_visible(timeout=1000):
                    box = btn.bounding_box()
                    if box:
                        btn.click(force=True)
                        logger.info(f"예실대비현황 상세 버튼 클릭: '{sel}' (y={box['y']:.0f})")
                        page.wait_for_timeout(600)
                        return True
        except Exception:
            continue

    # JS로 "상세" 텍스트 포함 클릭 가능 요소 탐색
    try:
        result = page.evaluate("""() => {
            const candidates = Array.from(
                document.querySelectorAll('button, a, [role="tab"], span[onclick], li[onclick]')
            );
            for (const el of candidates) {
                const text = (el.textContent || '').trim();
                if (text === '상세' || text === '예실대비현황(상세)' || text === '예실대비현황 상세') {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        el.click();
                        return text;
                    }
                }
            }
            return null;
        }""")
        if result:
            logger.info(f"예실대비현황 상세 버튼 JS 클릭: '{result}'")
            page.wait_for_timeout(600)
            return True
    except Exception as e:
        logger.debug(f"예실대비현황 상세 JS 탐색 실패: {e}")

    logger.debug("예실대비현황 상세 버튼 미발견 — 일반 뷰 캡처")
    return False
