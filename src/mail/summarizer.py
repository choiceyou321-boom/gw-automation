"""
Task #3: 안 읽은 메일 요약 → Notion 자동 저장 + 텔레그램 푸시
- 그룹웨어 메일함에서 안 읽은 메일 수집
- Gemini AI로 메일 본문 요약 (단순 추출 방식 fallback)
- Notion에 자동 저장
- 텔레그램으로 요약 푸시 알림
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from playwright.sync_api import Page

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.auth.login import login_and_get_context, close_session, GW_URL, DATA_DIR
from src.notion.client import save_mail_summaries

logger = logging.getLogger("mail")


def fetch_unread_mails(
    page: Page,
    max_count: int = 30,
    to_only: bool = True,
    gw_id: str = None,
) -> list[dict]:
    """
    안 읽은 메일 목록 수집.

    to_only=True (기본값): 수신인(To)이 본인인 메일만 반환.
                           참조(CC) 메일은 제외하여 591건+ 과다 수집 방지.

    처리 순서:
    1. API 방식 (mail019A01) 시도 → toYn 필드로 필터링
    2. API 실패 시 DOM 방식 fallback → 메일 열어서 수신인 확인
    """
    # 1단계: 쿠키 기반 API 직접 호출 시도
    api_mails = _fetch_via_api(page, max_count=max_count, to_only=to_only, gw_id=gw_id)
    if api_mails is not None:
        logger.info(f"API 방식으로 메일 {len(api_mails)}건 수집 완료")
        return api_mails

    # 2단계: DOM 방식 fallback
    logger.info("API 방식 실패 → DOM 방식으로 전환")
    return _fetch_via_dom(page, max_count=max_count, to_only=to_only, gw_id=gw_id)


def _fetch_via_api(
    page: Page,
    max_count: int,
    to_only: bool,
    gw_id: str,
) -> list[dict] | None:
    """
    더존 GW 메일 API(mail019A01) 직접 호출.
    성공 시 메일 목록 반환, 실패 시 None 반환.

    mail019A01: 받은편지함 목록 조회
    - toYn="Y": 수신인(To)이 본인 → 직접 받은 메일
    - toYn="N" or ccYn="Y": 참조(CC) 메일
    """
    try:
        # Playwright 컨텍스트에서 쿠키 추출
        cookies = page.context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}

        import httpx

        base_url = GW_URL  # https://gw.glowseoul.co.kr

        # 받은편지함 목록 조회 (안 읽은 메일)
        # toMailType: "R" = 받은 메일, readYn: "N" = 안 읽음
        endpoint = "/mail/api/mail019A01"
        body = {
            "toMailType": "R",      # 받은 메일함
            "readYn": "N",          # 안 읽은 메일만
            "pageIndex": 1,
            "pageSize": max_count * 3,  # To 필터 후 max_count 확보용 여유분
            "searchType": "",
            "searchKeyword": "",
            "sortType": "S",        # 날짜 내림차순
        }

        with httpx.Client(
            base_url=base_url,
            cookies=cookie_dict,
            timeout=20.0,
            verify=not os.environ.get("GW_SKIP_TLS_VERIFY", "").lower() in ("1", "true"),
        ) as client:
            resp = client.post(endpoint, json=body)
            if not resp.is_success:
                logger.warning(f"mail019A01 실패: HTTP {resp.status_code}")
                return None

            data = resp.json()

        rc = str(data.get("resultCode", ""))
        if rc not in ("0", "200", ""):
            logger.warning(f"mail019A01 resultCode: {rc}")
            return None

        result_data = data.get("resultData", {})
        if isinstance(result_data, dict):
            mail_list = result_data.get("mailList", result_data.get("list", []))
        elif isinstance(result_data, list):
            mail_list = result_data
        else:
            mail_list = []

        # API 응답 캡처 저장
        DATA_DIR.mkdir(exist_ok=True)
        (DATA_DIR / "mail_apis.json").write_text(
            json.dumps({"endpoint": endpoint, "req": body, "resp": data}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if not mail_list:
            logger.info("mail019A01: 안 읽은 메일 없음")
            return []

        logger.info(f"mail019A01: 총 {len(mail_list)}건 조회")

        mails = []
        for item in mail_list:
            # To/CC 필터: toYn 필드 확인
            to_yn = str(item.get("toYn", item.get("recvType", ""))).upper()
            cc_yn = str(item.get("ccYn", "")).upper()

            if to_only:
                # toYn="Y"인 것만 (직접 수신)
                # toYn 필드가 없는 경우 recvType으로 판단 ("T"=To, "C"=CC)
                recv_type = str(item.get("recvType", "")).upper()
                is_to = (to_yn == "Y") or (recv_type == "T") or (not cc_yn and not recv_type)
                if not is_to:
                    logger.debug(f"CC 메일 제외: {item.get('mailTitle', '')[:30]} (toYn={to_yn}, ccYn={cc_yn})")
                    continue

            mail = {
                "subject":   item.get("mailTitle", item.get("subject", "(제목 없음)")),
                "sender":    item.get("fromName", item.get("senderName", item.get("fromAddr", ""))),
                "date":      _parse_api_date(item.get("recvDt", item.get("sendDt", item.get("date", "")))),
                "to_yn":     to_yn,
                "cc_yn":     cc_yn,
                "mail_seq":  str(item.get("mailSeq", item.get("seq", ""))),
                "read_yn":   str(item.get("readYn", "N")),
                "is_unread": str(item.get("readYn", "N")).upper() == "N",
                "body":      "",  # 본문은 별도 API로 조회
                "summary":   "",
                "raw":       item,
            }
            mails.append(mail)

            if len(mails) >= max_count:
                break

        logger.info(f"To 필터 후 {len(mails)}건 (to_only={to_only})")

        # 본문 조회 (mail019A02 또는 상세 API)
        for mail in mails:
            if mail["mail_seq"]:
                body_text = _fetch_mail_body_via_api(client_cookies=cookie_dict, mail_seq=mail["mail_seq"])
                if body_text:
                    mail["body"] = body_text
                    mail["summary"] = _summarize_text(body_text)

        return mails

    except Exception as e:
        logger.warning(f"API 방식 메일 수집 실패: {e}")
        return None


def _fetch_mail_body_via_api(client_cookies: dict, mail_seq: str) -> str:
    """
    메일 상세 본문 조회 API (mail019A02).
    실패 시 빈 문자열 반환.
    """
    try:
        import httpx
        endpoint = "/mail/api/mail019A02"
        body = {"mailSeq": mail_seq}

        with httpx.Client(
            base_url=GW_URL,
            cookies=client_cookies,
            timeout=15.0,
            verify=not os.environ.get("GW_SKIP_TLS_VERIFY", "").lower() in ("1", "true"),
        ) as client:
            resp = client.post(endpoint, json=body)
            if not resp.is_success:
                return ""

            data = resp.json()

        result_data = data.get("resultData", {})
        if isinstance(result_data, dict):
            # 본문은 mailContent, bodyText, content 등의 필드
            content = (
                result_data.get("mailContent")
                or result_data.get("bodyText")
                or result_data.get("content")
                or result_data.get("mailBody")
                or ""
            )
            # HTML 태그 제거
            if content:
                import re
                content = re.sub(r"<[^>]+>", " ", content)
                content = re.sub(r"\s+", " ", content).strip()
            return content

    except Exception as e:
        logger.debug(f"본문 API 조회 실패 (mailSeq={mail_seq}): {e}")

    return ""


def _parse_api_date(raw: str) -> str:
    """API 날짜 문자열 파싱 → 'YYYY-MM-DD HH:MM' 형식."""
    if not raw:
        return ""
    raw = str(raw).strip()
    # YYYYMMDDHHmmss 형식
    if len(raw) >= 8 and raw[:8].isdigit():
        y, mo, d = raw[:4], raw[4:6], raw[6:8]
        h, mi = raw[8:10] if len(raw) >= 10 else "", raw[10:12] if len(raw) >= 12 else ""
        if h and mi:
            return f"{y}-{mo}-{d} {h}:{mi}"
        return f"{y}-{mo}-{d}"
    return raw


def _fetch_via_dom(
    page: Page,
    max_count: int,
    to_only: bool,
    gw_id: str,
) -> list[dict]:
    """
    DOM 방식 메일 수집 (API 실패 시 fallback).
    메일 목록에서 항목 추출 후 각 메일을 열어 수신인(To) 확인.
    """
    mails = []
    api_responses = []

    # 네트워크 인터셉트 - 메일 관련 API 캡처 (분석용)
    def handle_response(response):
        url = response.url.lower()
        if any(kw in url for kw in ["mail", "message", "inbox", "receive"]):
            try:
                body = response.json()
                api_responses.append({"url": response.url, "data": body})
            except Exception:
                pass

    page.on("response", handle_response)

    # 메일 메뉴로 이동
    logger.info("메일함 진입 중...")
    _navigate_to_mail(page)

    # 안 읽은 메일 필터
    _filter_unread(page)

    # 메일 목록 수집
    mail_items = _extract_mail_list(page)
    logger.info(f"DOM: 메일 목록 {len(mail_items)}건 발견")

    # 각 메일 본문 수집 (To 필터 포함)
    collected = 0
    for i, item in enumerate(mail_items):
        if collected >= max_count:
            break

        logger.info(f"메일 {i+1}/{len(mail_items)} 수집: {item.get('subject', '')[:30]}")
        body, recv_info = _get_mail_body_with_recv(page, item, i)
        item["body"] = body
        item["summary"] = _summarize_text(body)

        # To/CC 필터
        if to_only and recv_info:
            is_to = recv_info.get("is_to", True)  # 판별 불가 시 포함
            if not is_to:
                logger.info(f"CC 메일 제외: {item.get('subject', '')[:30]}")
                continue

        item.update(recv_info or {})
        mails.append(item)
        collected += 1

    # API 캡처 저장 (분석용)
    if api_responses:
        DATA_DIR.mkdir(exist_ok=True)
        (DATA_DIR / "mail_apis.json").write_text(
            json.dumps(api_responses[:10], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"메일 API {len(api_responses)}개 캡처 저장")

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


def _get_mail_body_with_recv(page: Page, mail_item: dict, index: int) -> tuple[str, dict]:
    """
    메일 본문 텍스트 + 수신인 정보 추출.
    반환: (body_text, recv_info)
    recv_info: {"is_to": bool, "to_addr": str, "cc_addr": str}
    """
    recv_info = {}
    try:
        # 메일 항목 클릭하여 본문 열기
        rows = page.locator("table tbody tr, .mail-item, .message-item, .list-item").all()
        if index < len(rows):
            rows[index].click()
            page.wait_for_load_state("networkidle", timeout=5000)
        else:
            page.wait_for_timeout(2000)

        # 수신인/참조 정보 추출 (열린 메일 상세 화면)
        recv_info = _extract_recv_info(page)

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
                    frame = page.frame_locator(sel).first
                    body_text = frame.locator("body").inner_text(timeout=3000)
                    if body_text and len(body_text) > 10:
                        return body_text.strip(), recv_info
                else:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1000):
                        body_text = el.inner_text(timeout=3000)
                        if body_text and len(body_text) > 10:
                            return body_text.strip(), recv_info
            except Exception:
                continue

        # 뒤로 가기
        page.go_back()
        page.wait_for_timeout(1000)

    except Exception as e:
        logger.warning(f"본문 추출 실패: {e}")

    return "(본문 추출 실패)", recv_info


def _extract_recv_info(page: Page) -> dict:
    """
    열린 메일 상세 화면에서 수신인(To)/참조(CC) 정보를 추출.
    반환: {"is_to": bool, "to_addr": str, "cc_addr": str}
    """
    # 수신인 필드 셀렉터 패턴 (더존 GW 메일 상세 화면)
    to_selectors = [
        '[class*="recv"] [class*="addr"]',
        '[class*="to"] [class*="addr"]',
        'label:has-text("받는 사람") + *',
        'span:has-text("받는사람") ~ span',
        '.mail-to',
        '.recv-addr',
        '[data-field="to"]',
    ]
    cc_selectors = [
        '[class*="cc"] [class*="addr"]',
        'label:has-text("참조") + *',
        'span:has-text("참조") ~ span',
        '.mail-cc',
        '.cc-addr',
        '[data-field="cc"]',
    ]

    to_text = ""
    cc_text = ""

    for sel in to_selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                to_text = el.inner_text(timeout=1000).strip()
                if to_text:
                    break
        except Exception:
            continue

    for sel in cc_selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                cc_text = el.inner_text(timeout=1000).strip()
                if cc_text:
                    break
        except Exception:
            continue

    # 판별: to_text가 있고 cc_text만 있거나, 아무것도 없으면 To로 간주
    # 사용자 gw_id(tgjeon)가 to_text에 있으면 확실히 To
    is_to = True  # 기본값: 판별 불가 시 포함
    if to_text or cc_text:
        is_to = bool(to_text)  # to 필드에 뭔가 있으면 To

    return {
        "is_to": is_to,
        "to_addr": to_text,
        "cc_addr": cc_text,
    }


# 하위 호환성: 기존 코드에서 _get_mail_body를 참조하는 경우를 위한 래퍼
def _get_mail_body(page: Page, mail_item: dict, index: int) -> str:
    """메일 본문 텍스트 추출 (하위 호환 래퍼)"""
    body, _ = _get_mail_body_with_recv(page, mail_item, index)
    return body


def _summarize_text(text: str, max_length: int = 500) -> str:
    """
    텍스트 요약 (단순 추출 방식 - Gemini 실패 시 fallback).
    첫 문단 + 핵심 문장 추출.
    """
    if not text or text == "(본문 추출 실패)":
        return text

    lines = [line.strip() for line in text.split("\n") if line.strip()]
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


def _summarize_with_gemini(mails: list[dict]) -> list[dict]:
    """
    Gemini AI로 메일 본문을 요약한다.
    API 실패 시 단순 추출(fallback)으로 대체.
    """
    try:
        from google import genai
        from google.genai import types as gtypes

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY 미설정 - 단순 추출 방식으로 대체")
            return mails

        gemini = genai.Client(api_key=api_key)

        # 본문이 있는 메일만 요약
        for mail in mails:
            body = mail.get("body", "")
            if not body or body == "(본문 추출 실패)":
                continue

            # 본문이 너무 짧으면 그대로 사용
            if len(body) < 50:
                mail["summary"] = body
                continue

            # 본문이 너무 길면 앞부분만 전달 (토큰 절약)
            body_truncated = body[:3000] if len(body) > 3000 else body

            prompt = (
                f"다음 업무 메일을 3줄 이내로 한국어로 핵심만 요약해주세요. "
                f"발신자, 주요 요청/내용, 필요한 액션 위주로 간결하게.\n\n"
                f"제목: {mail.get('subject', '')}\n"
                f"발신: {mail.get('sender', '')}\n"
                f"내용:\n{body_truncated}"
            )

            try:
                resp = gemini.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=gtypes.GenerateContentConfig(temperature=0.3),
                )
                if resp.candidates and resp.candidates[0].content:
                    parts = [p.text for p in resp.candidates[0].content.parts if p.text]
                    mail["summary"] = "\n".join(parts).strip()
                    logger.info(f"Gemini 요약 완료: {mail.get('subject', '')[:30]}")
            except Exception as e:
                logger.warning(f"Gemini 요약 실패, fallback 사용: {e}")
                # fallback: 단순 추출
                mail["summary"] = _summarize_text(body)

    except ImportError:
        logger.warning("google-genai 패키지 없음 - 단순 추출 방식 사용")

    return mails


def format_mail_summary_text(mails: list[dict], header: str = None) -> str:
    """
    메일 목록을 텍스트(마크다운)로 포맷팅.
    챗봇 응답 및 텔레그램 푸시 공용.
    """
    count = len(mails)
    lines = [header or f"새 메일 요약 ({count}건):\n"]
    for m in mails:
        sender = m.get("sender", "알수없음")
        subject = m.get("subject", "제목없음")
        date = m.get("date", "")
        summary = m.get("summary", "").replace("\n", " ")

        lines.append(f"• {sender}: {subject}" + (f" ({date})" if date else ""))
        if summary and summary != "(본문 추출 실패)":
            short = summary[:150] + "..." if len(summary) > 150 else summary
            lines.append(f"  요약: {short}")

    return "\n".join(lines)


def run_for_chatbot(user_context: dict = None) -> str:
    """
    챗봇(Gemini Agent)에서 호출하기 위한 메일 요약 함수.
    - Gemini AI로 본문 요약
    - Notion에 저장 (실패해도 계속)
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password

    gw_id = (user_context or {}).get("gw_id")
    if not gw_id:
        return "로그인 정보가 없습니다. 먼저 로그인을 진행해주세요."

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return "저장된 비밀번호를 찾을 수 없습니다. 다시 로그인해주세요."

    pw = sync_playwright().start()
    browser = None
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        mails = fetch_unread_mails(page, max_count=5, to_only=True, gw_id=gw_id)  # 챗봇 응답용: 5건, To만

        if not mails:
            return "현재 안 읽은 새로운 메일이 없습니다."

        # Gemini AI로 요약
        mails = _summarize_with_gemini(mails)

        # Notion에 백그라운드 저장 (실패해도 응답은 반환)
        try:
            from src.notion.client import save_mail_summaries
            page_url = save_mail_summaries(mails)
            if page_url:
                logger.info(f"메일 요약 Notion 저장 완료: {page_url}")
        except Exception as e:
            logger.error(f"Notion 저장 실패: {e}")

        return format_mail_summary_text(mails, header=f"안 읽은 메일 요약 ({len(mails)}건):\n")

    except Exception as e:
        logger.error(f"메일 요약 중 오류: {e}", exc_info=True)
        return "메일 요약 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
    finally:
        if browser:
            close_session(browser)
        try:
            pw.stop()
        except Exception:
            pass


async def push_mail_summary_to_telegram(
    bot_token: str,
    chat_id: int,
    mails: list[dict],
) -> bool:
    """
    텔레그램 봇으로 메일 요약 푸시.
    챗봇 응답이 아닌 서버 → 유저 방향 알림에 사용.
    반환: True(성공) / False(실패)
    """
    try:
        import httpx
        text = format_mail_summary_text(mails, header=f"새 메일이 {len(mails)}건 도착했습니다:\n")
        # 4096자 텔레그램 제한
        if len(text) > 4000:
            text = text[:4000] + "\n\n(일부 생략)"

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                # parse_mode 생략: 메일 제목/본문에 특수문자(_*`[) 포함 시 파싱 오류 방지
            })
            resp.raise_for_status()
        logger.info(f"텔레그램 푸시 완료: chat_id={chat_id}")
        return True
    except Exception as e:
        logger.error(f"텔레그램 푸시 실패: {e}")
        return False


async def run_mail_push_for_user(
    gw_id: str,
    bot_token: str,
    chat_id: int,
    max_count: int = 5,
) -> dict:
    """
    특정 GW 사용자의 안 읽은 메일을 수집·요약하여 텔레그램으로 푸시.
    스케줄러 또는 텔레그램 /mail 명령어에서 사용.

    반환: {"success": bool, "count": int, "message": str}
    """
    import asyncio
    from src.auth.user_db import get_decrypted_password
    from playwright.sync_api import sync_playwright

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return {"success": False, "count": 0, "message": "비밀번호를 찾을 수 없습니다."}

    # Playwright는 sync이므로 executor에서 실행
    # get_event_loop() 대신 get_running_loop() 사용 (Python 3.10+ 권장)
    loop = asyncio.get_running_loop()

    def _collect():
        pw = sync_playwright().start()
        browser = None
        try:
            browser, ctx, page = login_and_get_context(
                playwright_instance=pw,
                headless=True,
                user_id=gw_id,
                user_pw=gw_pw,
            )
            result_mails = fetch_unread_mails(page, max_count=max_count, to_only=True, gw_id=gw_id)
            return result_mails
        finally:
            if browser:
                close_session(browser)
            try:
                pw.stop()
            except Exception:
                pass

    try:
        mails = await loop.run_in_executor(None, _collect)
    except Exception as e:
        logger.error(f"메일 수집 실패: {e}", exc_info=True)
        return {"success": False, "count": 0, "message": "메일 수집 중 오류가 발생했습니다."}

    if not mails:
        return {"success": True, "count": 0, "message": "안 읽은 메일이 없습니다."}

    # Gemini 요약 (동기 함수 → executor)
    mails = await loop.run_in_executor(None, _summarize_with_gemini, mails)

    # Notion 저장 (실패 무시)
    try:
        from src.notion.client import save_mail_summaries
        page_url = await loop.run_in_executor(None, save_mail_summaries, mails)
        if page_url:
            logger.info(f"메일 요약 Notion 저장 완료: {page_url}")
    except Exception as e:
        logger.error(f"Notion 저장 실패: {e}")

    # 텔레그램 푸시
    sent = await push_mail_summary_to_telegram(bot_token, chat_id, mails)

    return {
        "success": sent,
        "count": len(mails),
        "message": f"메일 {len(mails)}건 요약 완료" + (" 및 전송" if sent else " (전송 실패)"),
    }


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
                page_url = save_mail_summaries(mails)
                if page_url:
                    logger.info(f"메일 요약 Notion 저장 완료: {page_url}")
                else:
                    logger.info("Notion 저장 완료 (URL 반환 없음)")
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
