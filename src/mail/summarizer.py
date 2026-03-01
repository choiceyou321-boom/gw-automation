"""
Task #3: 안 읽은 메일 요약 → Notion 자동 저장
- 그룹웨어 메일함에서 안 읽은 메일 수집
- 메일 본문 요약 (간단 추출 방식)
- Notion에 자동 저장
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from playwright.sync_api import Page

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.auth.login import login_and_get_context, close_session, GW_URL, DATA_DIR
from src.notion.client import save_mail_summaries

logger = logging.getLogger("mail")


def fetch_unread_mails(page: Page, max_count: int = 30) -> list[dict]:
    """안 읽은 메일 목록 수집"""
    mails = []
    api_responses = []

    # 네트워크 인터셉트 - 메일 관련 API 캡처
    def handle_response(response):
        url = response.url.lower()
        if any(kw in url for kw in ["mail", "message", "inbox", "receive"]):
            try:
                body = response.json()
                api_responses.append({"url": response.url, "data": body})
                logger.info(f"메일 API 캡처: {response.url[:100]}")
            except Exception:
                pass

    page.on("response", handle_response)

    # 메일 메뉴로 이동
    logger.info("메일함 진입 중...")
    _navigate_to_mail(page)

    # 안 읽은 메일 필터 또는 확인
    _filter_unread(page)

    # 메일 목록 수집
    mail_items = _extract_mail_list(page)
    logger.info(f"메일 목록 {len(mail_items)}건 발견")

    # 각 메일 본문 수집
    for i, item in enumerate(mail_items[:max_count]):
        logger.info(f"메일 {i+1}/{min(len(mail_items), max_count)} 본문 수집: {item.get('subject', '')[:30]}")
        body = _get_mail_body(page, item, i)
        item["body"] = body
        item["summary"] = _summarize_text(body)
        mails.append(item)

    # API 캡처 저장
    if api_responses:
        api_file = DATA_DIR / "mail_apis.json"
        api_file.write_text(json.dumps(api_responses, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"캡처된 메일 API {len(api_responses)}개 저장")

    return mails


def _navigate_to_mail(page: Page):
    """메일 메뉴로 이동"""
    selectors = [
        'a:has-text("메일")',
        'span:has-text("메일")',
        '[data-menu*="mail"]',
        '[href*="mail"]',
        '.menu-item:has-text("메일")',
        'li:has-text("메일")',
        'a:has-text("Mail")',
    ]

    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                page.wait_for_timeout(3000)
                logger.info(f"메일 메뉴 클릭: {sel}")
                return
        except Exception:
            continue

    # URL 직접 이동
    mail_urls = [
        f"{GW_URL}/#/mail",
        f"{GW_URL}/#/app/mail",
        f"{GW_URL}/#/mail/inbox",
    ]
    for url in mail_urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            if "mail" in page.url.lower():
                logger.info(f"URL로 메일 진입: {url}")
                return
        except Exception:
            continue

    page.screenshot(path=str(DATA_DIR / "mail_nav_failed.png"))
    logger.warning("메일 메뉴 진입 실패 - 스크린샷 확인 필요")


def _filter_unread(page: Page):
    """안 읽은 메일 필터링"""
    selectors = [
        'button:has-text("안읽은")',
        'a:has-text("안읽은")',
        'span:has-text("안 읽은")',
        'label:has-text("읽지 않은")',
        '[class*="unread"]',
        'input[type="checkbox"]:near(:text("안읽은"))',
    ]

    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                page.wait_for_timeout(2000)
                logger.info(f"안 읽은 메일 필터: {sel}")
                return
        except Exception:
            continue

    logger.info("안 읽은 메일 필터를 못 찾음 - 전체 목록에서 읽지 않은 항목 식별 시도")


def _extract_mail_list(page: Page) -> list[dict]:
    """메일 목록에서 항목 추출"""
    items = []

    # 테이블 또는 리스트 기반 추출
    row_selectors = [
        "table tbody tr",
        ".mail-item",
        ".message-item",
        ".list-item",
        "[class*='mail'] tr",
        "[class*='inbox'] tr",
    ]

    for sel in row_selectors:
        try:
            rows = page.locator(sel).all()
            if not rows:
                continue

            for row in rows:
                try:
                    text = row.inner_text(timeout=2000)
                    # 읽지 않은 메일 판별 (bold, unread 클래스 등)
                    classes = row.get_attribute("class") or ""
                    is_unread = "unread" in classes or "bold" in classes or "new" in classes

                    cells = [c.strip() for c in text.split("\t") if c.strip()]
                    if not cells:
                        cells = [c.strip() for c in text.split("\n") if c.strip()]

                    if len(cells) >= 1:
                        item = _parse_mail_row(cells, is_unread)
                        if item:
                            items.append(item)
                except Exception:
                    continue

            if items:
                break
        except Exception:
            continue

    if not items:
        page.screenshot(path=str(DATA_DIR / "mail_list_page.png"))
        logger.info("메일 목록 페이지 스크린샷 저장: mail_list_page.png")

    return items


def _parse_mail_row(cells: list[str], is_unread: bool = False) -> dict | None:
    """메일 행을 딕셔너리로 파싱"""
    if len(cells) < 1:
        return None

    item = {"raw_cells": cells, "is_unread": is_unread}

    for cell in cells:
        # 날짜
        if any(sep in cell for sep in ["-", ".", "/"]) and any(c.isdigit() for c in cell) and len(cell) <= 20:
            item.setdefault("date", cell)
        # 긴 텍스트 = 제목
        elif len(cell) > 5 and "subject" not in item:
            item["subject"] = cell
        # 짧은 텍스트 = 발신자
        elif len(cell) <= 20 and "sender" not in item and cell != item.get("subject"):
            item.setdefault("sender", cell)

    if "subject" not in item:
        item["subject"] = cells[0]

    return item


def _get_mail_body(page: Page, mail_item: dict, index: int) -> str:
    """메일 본문 텍스트 추출"""
    try:
        # 메일 항목 클릭하여 본문 열기
        rows = page.locator("table tbody tr, .mail-item, .message-item, .list-item").all()
        if index < len(rows):
            rows[index].click()
            page.wait_for_timeout(2000)

        # 본문 영역 텍스트 추출
        body_selectors = [
            ".mail-body",
            ".message-body",
            ".mail-content",
            ".content-body",
            ".view-body",
            "iframe",  # 메일 본문이 iframe인 경우
            "[class*='body']",
            "[class*='content']",
        ]

        for sel in body_selectors:
            try:
                if sel == "iframe":
                    # iframe 내 본문 추출
                    frame = page.frame_locator(sel).first
                    body_text = frame.locator("body").inner_text(timeout=3000)
                    if body_text and len(body_text) > 10:
                        return body_text.strip()
                else:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1000):
                        body_text = el.inner_text(timeout=3000)
                        if body_text and len(body_text) > 10:
                            return body_text.strip()
            except Exception:
                continue

        # 뒤로 가기
        page.go_back()
        page.wait_for_timeout(1000)

    except Exception as e:
        logger.warning(f"본문 추출 실패: {e}")

    return "(본문 추출 실패)"


def _summarize_text(text: str, max_length: int = 500) -> str:
    """
    텍스트 요약 (단순 추출 방식).
    첫 문단 + 핵심 문장 추출.
    """
    if not text or text == "(본문 추출 실패)":
        return text

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return text[:max_length]

    # 첫 3줄 또는 max_length까지
    summary_lines = []
    total = 0
    for line in lines:
        if total + len(line) > max_length:
            break
        summary_lines.append(line)
        total += len(line)

    return "\n".join(summary_lines) if summary_lines else text[:max_length]


def run():
    """메일 요약 → Notion 저장 메인 실행"""
    logger.info("=" * 50)
    logger.info("Task #3: 안 읽은 메일 요약 → Notion 저장 시작")
    logger.info("=" * 50)

    browser, context, page = login_and_get_context(headless=False)

    try:
        # 안 읽은 메일 수집
        mails = fetch_unread_mails(page)

        if mails:
            # JSON 백업 저장
            json_path = DATA_DIR / "unread_mails.json"
            json_path.write_text(
                json.dumps(mails, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"메일 데이터 저장: {json_path}")

            # Notion에 저장
            try:
                save_mail_summaries(mails)
                logger.info("Notion 저장 완료!")
            except Exception as e:
                logger.error(f"Notion 저장 실패: {e}")
                logger.info("JSON 파일은 로컬에 저장되어 있습니다.")
        else:
            logger.info("안 읽은 메일이 없습니다.")

    finally:
        close_session(browser)

    logger.info("Task #3 완료")


if __name__ == "__main__":
    run()
