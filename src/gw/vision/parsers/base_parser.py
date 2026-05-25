"""
Vision 파서 공통 인터페이스 및 결과 데이터클래스
- 모든 파서(영수증/세금계산서/거래처서류)는 BaseParser를 상속
- Gemini 호출은 _call_gemini() 동기 메서드로 통일
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Gemini 클라이언트 lazy 초기화 (agent.py 방식 그대로)
_client = None


def _get_client() -> genai.Client:
    """Gemini 클라이언트 싱글톤 반환"""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        _client = genai.Client(api_key=api_key)
    return _client


@dataclass
class ParseResult:
    """파서 반환 결과 통합 구조체"""
    document_type: str           # "영수증" | "세금계산서" | "거래처서류" | "견적서" | "기타"
    form_type: str | None        # GW 양식명 (None이면 연결 불가)
    extracted_data: dict         # GW 양식 파라미터 형식 데이터
    confidence: float            # 0.0~1.0 (추출 신뢰도)
    raw_text: str = ""           # Gemini가 읽어낸 원문 텍스트
    missing_fields: list = field(default_factory=list)   # 추출 실패 필드 목록
    warnings: list = field(default_factory=list)          # 경고 메시지


class BaseParser:
    """
    Vision 파서 기반 클래스.
    하위 파서는 parse() 메서드를 구현해야 함.
    """

    # 하위 클래스에서 오버라이드
    MODEL_ID: str = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

    async def parse(self, image_bytes: bytes, mime_type: str) -> ParseResult:
        """
        이미지/PDF 바이트를 받아 ParseResult 반환.
        하위 클래스에서 반드시 구현.
        """
        raise NotImplementedError("하위 파서에서 parse()를 구현해야 합니다.")

    def _call_gemini(self, prompt: str, image_bytes: bytes, mime_type: str) -> str:
        """
        Gemini Vision 동기 호출.
        이미지 파트 + 텍스트 프롬프트를 함께 전달하고 응답 텍스트 반환.

        Args:
            prompt: 추출 지시 프롬프트 (한국어)
            image_bytes: 원본 이미지/PDF 바이트
            mime_type: "image/jpeg" | "image/png" | "application/pdf" 등

        Returns:
            Gemini 응답 텍스트 (str)

        Raises:
            Exception: API 오류 시 그대로 전파 (호출처에서 처리)
        """
        client = _get_client()

        # 이미지 파트 구성 (agent.py Part.from_bytes 방식 그대로)
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        text_part = types.Part.from_text(text=prompt)

        response = client.models.generate_content(
            model=self.MODEL_ID,
            contents=[image_part, text_part],
        )

        return response.text or ""
