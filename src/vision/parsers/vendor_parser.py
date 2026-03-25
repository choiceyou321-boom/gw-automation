"""
거래처 서류/명함 파서
- Gemini Vision으로 거래처등록 서류·사업자등록증·명함에서 회사 정보 추출
- submit_approval_form 핸들러 + 거래처등록신청서 양식 형식으로 데이터 구성
"""

import json
import re
import logging

from .base_parser import BaseParser, ParseResult

logger = logging.getLogger(__name__)


def _normalize_biz_no(biz_no: str) -> str:
    """사업자번호를 000-00-00000 형식으로 정규화"""
    if not biz_no:
        return ""
    digits = re.sub(r"\D", "", biz_no)
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    return biz_no


def _normalize_phone(phone: str) -> str:
    """전화번호 정규화 (숫자+하이픈만 유지)"""
    if not phone:
        return ""
    # 국제 번호 표기 (+82 등) 처리
    cleaned = re.sub(r"[^\d\-+]", "", phone)
    # +82 → 0 변환
    cleaned = re.sub(r"^\+82", "0", cleaned)
    return cleaned


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


# Gemini에 전달할 거래처 서류 추출 프롬프트
VENDOR_PROMPT = """
다음 이미지(사업자등록증, 명함, 거래처 서류 등)를 분석하여 아래 JSON 형식으로 회사/거래처 정보를 추출해주세요.
반드시 JSON만 출력하고 다른 설명은 포함하지 마세요.

{
  "company_name": "회사/상호명",
  "business_number": "사업자등록번호 (숫자 10자리 또는 000-00-00000 형식)",
  "representative": "대표자명",
  "address": "사업장 주소",
  "business_type": "업태 (예: 건설업, 서비스업)",
  "business_item": "종목 (예: 실내건축공사, 소프트웨어개발)",
  "phone": "대표 전화번호",
  "fax": "팩스번호",
  "email": "이메일 주소",
  "contact_person": "담당자명",
  "contact_phone": "담당자 직통번호",
  "contact_dept": "담당자 부서/직책",
  "establishment_date": "설립일 (YYYY-MM-DD)",
  "document_type": "사업자등록증|명함|거래처서류|기타",
  "raw_text": "문서에서 읽은 핵심 텍스트 요약"
}

주의사항:
- 명함인 경우 개인 정보를 contact_person/contact_phone/contact_dept에 입력
- 찾을 수 없는 필드는 빈 문자열("")로 입력
- 사업자등록번호는 반드시 숫자 10자리로 정리
"""


class VendorParser(BaseParser):
    """거래처 서류/명함 Vision 파서"""

    async def parse(self, image_bytes: bytes, mime_type: str) -> ParseResult:
        """
        거래처 서류·명함 이미지/PDF 파싱.
        회사 정보를 추출하고 거래처등록신청서 양식 형식으로 반환.
        """
        raw_text = ""
        warnings = []
        missing_fields = []

        try:
            # Gemini Vision 호출
            response_text = self._call_gemini(VENDOR_PROMPT, image_bytes, mime_type)
            raw_text = response_text

            # JSON 추출
            data = _extract_json_from_text(response_text)
            if not data:
                warnings.append("Gemini 응답에서 JSON을 파싱할 수 없었습니다. 수동 입력이 필요합니다.")
                return ParseResult(
                    document_type="거래처서류",
                    form_type="거래처등록신청서",
                    extracted_data={"form_type": "거래처등록신청서", "action": "draft"},
                    confidence=0.0,
                    raw_text=raw_text,
                    missing_fields=["company_name", "business_number"],
                    warnings=warnings,
                )

            # 필수 필드 검증
            company_name = data.get("company_name", "")
            if not company_name:
                missing_fields.append("company_name")
                warnings.append("회사명을 인식하지 못했습니다.")

            biz_no_raw = data.get("business_number", "")
            business_number = _normalize_biz_no(biz_no_raw)
            if not business_number:
                missing_fields.append("business_number")
                warnings.append("사업자등록번호를 인식하지 못했습니다.")

            representative = data.get("representative", "")
            if not representative:
                missing_fields.append("representative")

            # 전화번호 정규화
            phone = _normalize_phone(data.get("phone", ""))
            contact_phone = _normalize_phone(data.get("contact_phone", ""))

            # 신뢰도 계산 (회사명 40% + 사업자번호 40% + 대표자 20%)
            confidence = 0.0
            if company_name:
                confidence += 0.4
            if business_number:
                confidence += 0.4
            if representative:
                confidence += 0.2

            # 거래처등록신청서 파라미터 형식 구성
            extracted_data = {
                "form_type": "거래처등록신청서",
                "company_name": company_name,
                "business_number": business_number,
                "representative": representative,
                "address": data.get("address", ""),
                "business_type": data.get("business_type", ""),
                "business_item": data.get("business_item", ""),
                "phone": phone,
                "fax": data.get("fax", ""),
                "email": data.get("email", ""),
                "contact_person": data.get("contact_person", ""),
                "contact_phone": contact_phone,
                "contact_dept": data.get("contact_dept", ""),
                "establishment_date": data.get("establishment_date", ""),
                "action": "draft",  # 기본: 임시저장 후 확인

                # 문서 종류 메타
                "_source_document_type": data.get("document_type", "거래처서류"),
            }

            return ParseResult(
                document_type="거래처서류",
                form_type="거래처등록신청서",
                extracted_data=extracted_data,
                confidence=confidence,
                raw_text=raw_text,
                missing_fields=missing_fields,
                warnings=warnings,
            )

        except Exception as e:
            logger.error(f"[VendorParser] 파싱 오류: {e}", exc_info=True)
            return ParseResult(
                document_type="거래처서류",
                form_type="거래처등록신청서",
                extracted_data={"form_type": "거래처등록신청서", "action": "draft"},
                confidence=0.0,
                raw_text=raw_text,
                missing_fields=["company_name", "business_number"],
                warnings=[f"거래처 서류 파싱 중 오류가 발생했습니다: {e}"],
            )
