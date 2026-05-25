"""
영수증 파서
- Gemini Vision으로 영수증 이미지에서 날짜/금액/가맹점명/품목 추출
- submit_expense_approval 핸들러가 받는 형식으로 extracted_data 구성
"""

import json
import re
import logging
from typing import Any

from .base_parser import BaseParser, ParseResult

logger = logging.getLogger(__name__)

# 가맹점명 → 카테고리 매핑 (키워드 포함 여부로 판단)
MERCHANT_CATEGORY_MAP = {
    "교통비": ["택시", "버스", "지하철", "기차", "ktx", "korail", "티머니", "카카오택시", "우버", "주차", "고속도로", "통행료"],
    "식대": ["식당", "음식", "치킨", "피자", "햄버거", "카페", "커피", "베이커리", "빵집", "한식", "일식", "중식", "양식",
             "편의점 식품", "도시락", "분식", "냉면", "국밥", "삼겹살", "starbucks", "투썸", "이디야", "맥도날드", "롯데리아"],
    "사무용품": ["gs25", "cu", "세븐일레븐", "편의점", "다이소", "오피스디포", "문구", "복사", "인쇄", "yes24", "알라딘", "교보문고"],
    "숙박비": ["호텔", "모텔", "펜션", "에어비앤비", "숙박", "여관"],
    "유류비": ["주유소", "sk에너지", "gs칼텍스", "현대오일뱅크", "s-oil", "오일"],
}


def _estimate_category(merchant: str) -> str:
    """가맹점명 기반 카테고리 추정"""
    merchant_lower = merchant.lower()
    for category, keywords in MERCHANT_CATEGORY_MAP.items():
        for kw in keywords:
            if kw in merchant_lower:
                return category
    return "기타"


def _normalize_date(date_str: str) -> str:
    """
    다양한 날짜 포맷을 YYYY-MM-DD로 정규화.
    YYYYMMDD, YYYY.MM.DD, YYYY/MM/DD, YYYY-MM-DD 지원.
    변환 불가 시 원문 그대로 반환.
    """
    if not date_str:
        return ""

    # 숫자만 추출
    digits = re.sub(r"\D", "", date_str)
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"

    # 이미 YYYY-MM-DD 형식인지 확인
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str

    return date_str  # 변환 불가 시 원문 반환


def _parse_amount(amount_str: str) -> int:
    """
    금액 문자열에서 int 추출.
    쉼표, '원', '₩' 제거 후 변환. 실패 시 0 반환.
    """
    if not amount_str:
        return 0
    cleaned = re.sub(r"[,\s원₩]", "", str(amount_str))
    # 소수점 있으면 정수 부분만
    cleaned = cleaned.split(".")[0]
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return 0


def _extract_json_from_text(text: str) -> dict:
    """
    Gemini 응답에서 JSON 추출.
    순수 JSON 파싱 실패 시 ```json ... ``` 블록에서 추출 시도.
    """
    # 1차: 직접 파싱
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 2차: ```json ... ``` 코드 블록
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3차: 중괄호 범위 추출
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {}


# Gemini에 전달할 영수증 추출 프롬프트
RECEIPT_PROMPT = """
다음 영수증 이미지를 분석하여 아래 JSON 형식으로 정보를 추출해주세요.
반드시 JSON만 출력하고 다른 설명은 포함하지 마세요.

{
  "date": "YYYY-MM-DD 또는 YYYYMMDD 형식 (예: 2024-03-15)",
  "merchant_name": "가맹점/상호명",
  "items": [
    {"name": "품목명", "quantity": 1, "unit_price": 0, "amount": 0}
  ],
  "total_amount": 0,
  "payment_method": "신용카드|현금|카카오페이|네이버페이|삼성페이|기타",
  "raw_text": "영수증에서 읽은 주요 텍스트 (한 줄 요약)"
}

주의사항:
- 금액은 숫자만 입력 (쉼표/원 제거)
- 날짜를 찾을 수 없으면 빈 문자열("")
- 품목이 없으면 items를 빈 배열([])로
- 합계/총액/결제금액 등의 최종 금액을 total_amount에 입력
"""


class ReceiptParser(BaseParser):
    """영수증 Vision 파서"""

    async def parse(self, image_bytes: bytes, mime_type: str) -> ParseResult:
        """
        영수증 이미지/PDF 파싱.
        날짜·금액·가맹점명·품목을 추출하고 submit_expense_approval 형식으로 반환.
        """
        raw_text = ""
        warnings = []
        missing_fields = []

        try:
            # Gemini Vision 호출
            response_text = self._call_gemini(RECEIPT_PROMPT, image_bytes, mime_type)
            raw_text = response_text

            # JSON 추출
            data = _extract_json_from_text(response_text)
            if not data:
                warnings.append("Gemini 응답에서 JSON을 파싱할 수 없었습니다. 수동 입력이 필요합니다.")
                return ParseResult(
                    document_type="영수증",
                    form_type="지출결의서",
                    extracted_data={"action": "draft"},
                    confidence=0.0,
                    raw_text=raw_text,
                    missing_fields=["date", "total_amount", "merchant_name"],
                    warnings=warnings,
                )

            # 날짜 정규화
            date_raw = data.get("date", "")
            date_normalized = _normalize_date(date_raw)
            if not date_normalized:
                missing_fields.append("date")
                warnings.append("날짜를 인식하지 못했습니다. 직접 입력해주세요.")

            # 금액 파싱
            total_amount = _parse_amount(data.get("total_amount", 0))
            if total_amount == 0:
                missing_fields.append("total_amount")
                warnings.append("합계 금액을 인식하지 못했습니다. 직접 입력해주세요.")

            # 가맹점명
            merchant = data.get("merchant_name", "")
            if not merchant:
                missing_fields.append("merchant_name")
                warnings.append("가맹점명을 인식하지 못했습니다.")

            # 카테고리 추정
            category = _estimate_category(merchant)

            # 품목 목록 변환 (submit_expense_approval items 형식)
            raw_items = data.get("items", [])
            items = []
            for it in raw_items:
                item_name = it.get("name", "")
                item_amount = _parse_amount(it.get("amount", it.get("unit_price", 0)))
                item_qty = int(it.get("quantity", 1))
                if item_name:
                    items.append({
                        "name": item_name,
                        "amount": item_amount,
                        "quantity": item_qty,
                    })

            # 품목이 없으면 합계 금액으로 단일 항목 생성
            if not items and merchant:
                items = [{"name": f"{merchant} {category}", "amount": total_amount, "quantity": 1}]

            # 신뢰도 계산 (날짜 50% + 금액 50%)
            confidence = 0.0
            if date_normalized:
                confidence += 0.5
            if total_amount > 0:
                confidence += 0.5

            # GW submit_expense_approval 파라미터 형식으로 구성
            extracted_data = {
                "title": f"{merchant} {category}" if merchant else f"영수증 {date_normalized}",
                "date": date_normalized,
                "description": "영수증 자동 인식",
                "items": items,
                "total_amount": total_amount,
                "action": "draft",  # 기본: 임시저장 후 확인

                # 메타 정보 (확인 단계 표시용, GW 전송 시 제외)
                "_merchant": merchant,
                "_category": category,
                "_payment_method": data.get("payment_method", "기타"),
            }

            return ParseResult(
                document_type="영수증",
                form_type="지출결의서",
                extracted_data=extracted_data,
                confidence=confidence,
                raw_text=raw_text,
                missing_fields=missing_fields,
                warnings=warnings,
            )

        except Exception as e:
            logger.error(f"[ReceiptParser] 파싱 오류: {e}", exc_info=True)
            return ParseResult(
                document_type="영수증",
                form_type="지출결의서",
                extracted_data={"action": "draft"},
                confidence=0.0,
                raw_text=raw_text,
                missing_fields=["date", "total_amount", "merchant_name"],
                warnings=[f"영수증 파싱 중 오류가 발생했습니다: {e}"],
            )
