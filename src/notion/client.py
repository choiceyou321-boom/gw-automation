"""
Notion API 클라이언트
- 페이지에 메일 요약 블록 추가
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / "config" / ".env")

logger = logging.getLogger("notion")

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_PAGE_ID = os.getenv("NOTION_PAGE_ID")
NOTION_VERSION = "2022-06-28"


def _get_headers() -> dict:
    """요청 시점에 API 키를 읽어 헤더 생성 (모듈 로드 시점 None 방지)."""
    key = os.getenv("NOTION_API_KEY") or NOTION_API_KEY
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def append_to_page(page_id: str, blocks: list[dict]) -> dict:
    """Notion 페이지에 블록 추가"""
    if not (os.getenv("NOTION_API_KEY") or NOTION_API_KEY):
        raise RuntimeError("NOTION_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    resp = httpx.patch(url, headers=_get_headers(), json={"children": blocks}, timeout=30)
    resp.raise_for_status()
    logger.info(f"Notion 블록 {len(blocks)}개 추가 완료")
    return resp.json()


def create_mail_summary_blocks(mail: dict) -> list[dict]:
    """메일 요약 정보를 Notion 블록으로 변환"""
    blocks = []

    # 구분선
    blocks.append({"object": "block", "type": "divider", "divider": {}})

    # 제목 (heading_3)
    subject = mail.get("subject", "(제목 없음)")
    blocks.append({
        "object": "block",
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": subject}}]
        },
    })

    # 메타 정보 (발신자, 날짜)
    sender = mail.get("sender", "알 수 없음")
    date = mail.get("date", "")
    meta_text = f"발신: {sender} | 날짜: {date}"
    blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {"type": "text", "text": {"content": meta_text}, "annotations": {"color": "gray"}}
            ]
        },
    })

    # 요약 내용
    summary = mail.get("summary", mail.get("body", "(내용 없음)"))
    # Notion 블록은 2000자 제한
    for i in range(0, len(summary), 2000):
        chunk = summary[i:i + 2000]
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}]
            },
        })

    return blocks


def get_page_url(page_id: str) -> str:
    """Notion 페이지 ID로 공개 URL 생성 (하이픈 제거 후 조합)."""
    clean_id = page_id.replace("-", "")
    return f"https://www.notion.so/{clean_id}"


def save_mail_summaries(mails: list[dict], page_id: str = None) -> str | None:
    """
    여러 메일 요약을 Notion에 저장.
    반환: 저장된 페이지 URL (성공 시) 또는 None (실패/설정 없음)
    """
    target_page = page_id or os.getenv("NOTION_PAGE_ID") or NOTION_PAGE_ID
    if not target_page:
        logger.error("NOTION_PAGE_ID가 설정되지 않았습니다. .env 파일을 확인하세요.")
        return None
    if not (os.getenv("NOTION_API_KEY") or NOTION_API_KEY):
        logger.error("NOTION_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        return None

    all_blocks = []

    # 날짜 헤더
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    all_blocks.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": f"메일 요약 ({today})"}}]
        },
    })

    for mail in mails:
        all_blocks.extend(create_mail_summary_blocks(mail))

    # Notion API는 한 번에 최대 100개 블록
    for i in range(0, len(all_blocks), 100):
        batch = all_blocks[i:i + 100]
        append_to_page(target_page, batch)

    page_url = get_page_url(target_page)
    logger.info(f"메일 요약 Notion 저장 완료: {page_url}")
    return page_url
