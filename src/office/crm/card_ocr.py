"""
명함 이미지 OCR — Gemini Vision.

호출 흐름:
    extract_from_image(path) → BusinessCard
    extract_from_bytes(data) → BusinessCard

Gemini API가 없거나 실패해도 BusinessCard(raw_text="", confidence=0)으로
폴백되어 호출 코드가 깨지지 않게 한다. 실제 OCR 정확도 향상은
프롬프트/모델 튜닝 후속 작업.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path

from src.office.crm.models import BusinessCard

logger = logging.getLogger(__name__)

OCR_PROMPT = """\
다음은 명함 사진입니다. 명함에 적힌 정보를 JSON으로 정확히 추출하세요.

스키마(반드시 이 키만 사용, 누락 필드는 빈 문자열):
{
  "name": "...",         // 사람 이름 (성+이름)
  "company": "...",      // 회사/소속 기관명
  "department": "...",   // 부서/팀
  "title": "...",        // 직책 (대표, 과장, 매니저 등)
  "email": "...",        // 이메일 (1개)
  "phone_mobile": "...", // 휴대폰 (한국 형식 010-xxxx-xxxx 우선)
  "phone_office": "...", // 사무실 전화
  "fax": "...",
  "address": "...",      // 주소 전체
  "website": "..."
}

JSON만 반환하세요. 코드 블록(```) 사용하지 마세요. 추출 불가능하면 빈 문자열로.
"""


def _strip_code_fence(text: str) -> str:
    """Gemini가 가끔 ```json ... ``` 으로 감싸는 경우 벗겨낸다."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json_response(text: str) -> dict:
    cleaned = _strip_code_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 첫 { ~ 마지막 } 만 잘라 재시도
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


def _gemini_extract(image_bytes: bytes, mime_type: str = "image/jpeg") -> tuple[str, float]:
    """
    Gemini Vision으로 명함 OCR. (raw_text, confidence) 반환.

    GEMINI_API_KEY 없거나 라이브러리 미설치 시 ("", 0.0) 반환.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY 없음 — OCR 폴백(빈 결과)")
        return "", 0.0

    try:
        import google.generativeai as genai
    except ImportError:
        logger.warning("google-generativeai 미설치 — OCR 폴백")
        return "", 0.0

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(
            [
                {"mime_type": mime_type, "data": image_bytes},
                OCR_PROMPT,
            ]
        )
        text = (getattr(response, "text", "") or "").strip()
        return text, 0.85 if text else 0.0
    except Exception as e:
        logger.error(f"Gemini OCR 실패: {e}")
        return "", 0.0


def extract_from_bytes(image_bytes: bytes, mime_type: str = "image/jpeg") -> BusinessCard:
    """이미지 바이트 → BusinessCard."""
    raw_text, confidence = _gemini_extract(image_bytes, mime_type)
    data = _parse_json_response(raw_text) if raw_text else {}
    return BusinessCard(
        name=str(data.get("name", "")).strip(),
        company=str(data.get("company", "")).strip(),
        department=str(data.get("department", "")).strip(),
        title=str(data.get("title", "")).strip(),
        email=str(data.get("email", "")).strip(),
        phone_mobile=str(data.get("phone_mobile", "")).strip(),
        phone_office=str(data.get("phone_office", "")).strip(),
        fax=str(data.get("fax", "")).strip(),
        address=str(data.get("address", "")).strip(),
        website=str(data.get("website", "")).strip(),
        raw_text=raw_text,
        confidence=confidence if data else 0.0,
    )


def _guess_mime_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".heic": "image/heic", ".heif": "image/heif",
    }.get(ext, "image/jpeg")


def extract_from_image(image_path: str | Path) -> BusinessCard:
    """이미지 파일 경로 → BusinessCard. image_path 필드도 채워서 반환."""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"명함 이미지 없음: {path}")
    data = path.read_bytes()
    card = extract_from_bytes(data, mime_type=_guess_mime_type(path))
    card.image_path = str(path)
    return card
