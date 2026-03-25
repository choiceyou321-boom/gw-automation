"""
Gemini Vision 문서 타입 분류기
- 첨부 이미지/PDF를 Gemini Vision으로 분류
- 분류 결과를 GW 양식 타입으로 매핑

분류 결과 → GW 양식 매핑:
  영수증     → 지출결의서
  세금계산서 → 지출결의서 (증빙 첨부 포함)
  거래처서류 → 거래처등록신청서
  견적서     → 선급금요청서
  기타       → None (수동 처리)
"""

import os
import json
import re
import logging

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Gemini 클라이언트 lazy 초기화 (agent.py 방식 그대로)
_client = None

# 환경변수에서 모델 ID 가져오기 (기본값: gemini-2.0-flash)
MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

# 문서 타입 → GW 양식 매핑 테이블
DOCUMENT_FORM_MAP: dict[str, str | None] = {
    "영수증":     "지출결의서",
    "세금계산서": "지출결의서",
    "거래처서류": "거래처등록신청서",
    "견적서":     "선급금요청서",
    "기타":       None,
}

# 유효한 문서 타입 목록
VALID_DOC_TYPES = list(DOCUMENT_FORM_MAP.keys())

# 분류 프롬프트
CLASSIFY_PROMPT = """
다음 이미지/문서를 분석하여 문서 종류를 분류해주세요.
반드시 아래 JSON 형식만 출력하고 다른 설명은 포함하지 마세요.

{
  "document_type": "영수증|세금계산서|거래처서류|견적서|기타",
  "confidence": 0.0~1.0,
  "description": "감지 이유 한 줄 설명 (한국어)"
}

분류 기준:
- 영수증: 카드 영수증, 현금 영수증, POS 출력물, 간이 영수증 등 결제 증빙
- 세금계산서: 전자세금계산서, 종이 세금계산서, 계산서 등 세무 증빙
- 거래처서류: 사업자등록증, 명함, 거래처 등록 서류, 법인등기부 등
- 견적서: 견적서, 제안서, 가격표 등 공급 예정 금액 서류
- 기타: 위 분류에 해당하지 않는 모든 문서

confidence는 분류 확신도 (0.9 이상 = 매우 확실, 0.5~0.9 = 보통, 0.5 미만 = 불확실)
"""


def _get_client() -> genai.Client:
    """Gemini 클라이언트 싱글톤 반환"""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        _client = genai.Client(api_key=api_key)
    return _client


def _extract_json_from_text(text: str) -> dict:
    """Gemini 응답 텍스트에서 JSON 추출 (3단계 폴백)"""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {}


async def classify_document(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> dict:
    """
    첨부 이미지/PDF를 Gemini Vision으로 문서 타입 분류.

    Args:
        image_bytes: 이미지 또는 PDF 바이트 데이터
        mime_type: MIME 타입 (image/jpeg, image/png, application/pdf 등)

    Returns:
        {
            "document_type": "영수증" | "세금계산서" | "거래처서류" | "견적서" | "기타",
            "form_type": "지출결의서" | "거래처등록신청서" | "선급금요청서" | None,
            "confidence": 0.0~1.0,
            "description": "감지된 이유 한 줄 설명"
        }

    오류 발생 시:
        {"document_type": "기타", "form_type": None, "confidence": 0.0, "description": 오류 메시지}
    """
    try:
        client = _get_client()

        # 이미지 파트 구성 (agent.py Part.from_bytes 방식 그대로)
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        text_part = types.Part.from_text(text=CLASSIFY_PROMPT)

        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[image_part, text_part],
        )
        response_text = response.text or ""

        # JSON 추출
        data = _extract_json_from_text(response_text)
        if not data:
            logger.warning(f"[Classifier] JSON 파싱 실패. 응답 원문: {response_text[:200]}")
            return {
                "document_type": "기타",
                "form_type": None,
                "confidence": 0.0,
                "description": f"응답 파싱 실패: {response_text[:100]}",
            }

        # 문서 타입 유효성 검증 (Gemini가 엉뚱한 값 반환 시 "기타"로 폴백)
        doc_type = data.get("document_type", "기타")
        if doc_type not in VALID_DOC_TYPES:
            logger.warning(f"[Classifier] 알 수 없는 문서 타입: {doc_type} → '기타'로 처리")
            doc_type = "기타"

        # confidence 범위 보정 (0.0~1.0)
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        form_type = DOCUMENT_FORM_MAP.get(doc_type)

        return {
            "document_type": doc_type,
            "form_type": form_type,
            "confidence": confidence,
            "description": data.get("description", ""),
        }

    except Exception as e:
        logger.error(f"[Classifier] 문서 분류 오류: {e}", exc_info=True)
        return {
            "document_type": "기타",
            "form_type": None,
            "confidence": 0.0,
            "description": str(e),
        }
