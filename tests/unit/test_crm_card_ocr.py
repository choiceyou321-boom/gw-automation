"""card_ocr 단위 테스트 — JSON 파싱 + 폴백 검증 (Gemini 호출은 monkeypatch)."""

from __future__ import annotations

import json
import pytest

from src.office.crm import card_ocr
from src.office.crm.models import BusinessCard


def test_strip_code_fence_plain():
    assert card_ocr._strip_code_fence("{}") == "{}"


def test_strip_code_fence_with_json_fence():
    text = "```json\n{\"a\": 1}\n```"
    assert card_ocr._strip_code_fence(text) == '{"a": 1}'


def test_strip_code_fence_with_plain_fence():
    text = "```\n{\"a\": 1}\n```"
    assert card_ocr._strip_code_fence(text) == '{"a": 1}'


def test_parse_json_response_valid():
    text = json.dumps({"name": "홍길동", "company": "글로우서울"})
    data = card_ocr._parse_json_response(text)
    assert data["name"] == "홍길동"


def test_parse_json_response_with_prefix_suffix():
    text = "여기 결과입니다: {\"name\": \"홍길동\"} 끝"
    data = card_ocr._parse_json_response(text)
    assert data["name"] == "홍길동"


def test_parse_json_response_invalid_returns_empty():
    assert card_ocr._parse_json_response("이건 JSON 아님") == {}


def test_extract_from_bytes_no_api_key(monkeypatch):
    """GEMINI_API_KEY 없으면 빈 BusinessCard 반환 (raise 안 함)."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    card = card_ocr.extract_from_bytes(b"\x89PNG fake bytes")
    assert isinstance(card, BusinessCard)
    assert card.name == ""
    assert card.confidence == 0.0


def test_extract_from_bytes_with_mocked_gemini(monkeypatch):
    """Gemini 호출을 모킹해 정상 응답 파싱 검증."""

    def fake_gemini(image_bytes, mime_type="image/jpeg"):
        return (
            json.dumps({
                "name": "홍길동",
                "company": "글로우서울",
                "department": "PM본부",
                "title": "과장",
                "email": "gildong@glowseoul.co.kr",
                "phone_mobile": "010-1234-5678",
                "phone_office": "",
                "fax": "",
                "address": "서울시 용산구",
                "website": "",
            }),
            0.85,
        )

    monkeypatch.setattr(card_ocr, "_gemini_extract", fake_gemini)
    card = card_ocr.extract_from_bytes(b"fake")
    assert card.name == "홍길동"
    assert card.company == "글로우서울"
    assert card.title == "과장"
    assert card.email == "gildong@glowseoul.co.kr"
    assert card.phone_mobile == "010-1234-5678"
    assert card.confidence == 0.85


def test_extract_from_image_file_not_found():
    with pytest.raises(FileNotFoundError):
        card_ocr.extract_from_image("/nonexistent/path/card.jpg")


def test_extract_from_image_sets_image_path(tmp_path, monkeypatch):
    """image_path 필드가 절대 경로로 채워지는지."""
    monkeypatch.setattr(card_ocr, "_gemini_extract", lambda b, m="image/jpeg": ("", 0.0))
    img_path = tmp_path / "card.jpg"
    img_path.write_bytes(b"\xff\xd8\xff fake jpeg")
    card = card_ocr.extract_from_image(img_path)
    assert card.image_path == str(img_path)


def test_guess_mime_type():
    from pathlib import Path
    assert card_ocr._guess_mime_type(Path("a.jpg")) == "image/jpeg"
    assert card_ocr._guess_mime_type(Path("a.png")) == "image/png"
    assert card_ocr._guess_mime_type(Path("a.heic")) == "image/heic"
    assert card_ocr._guess_mime_type(Path("a.unknown")) == "image/jpeg"
