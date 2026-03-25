"""
세금계산서 파서
- Gemini Vision으로 세금계산서에서 공급자/공급가액/세액/품목 추출
- submit_expense_approval 핸들러 형식 + 증빙 첨부 메타 포함
"""

import json
import re
import logging

from .base_parser import BaseParser, ParseResult

logger = logging.getLogger(__name__)


def _normalize_date(date_str: str) -> str:
    """YYYYMMDD, YYYY.MM.DD, YYYY/MM/DD → YYYY-MM-DD 변환"""
    if not date_str:
        return ""
    digits = re.sub(r"\D", "", date_str)
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str
    return date_str


def _parse_amount(amount_str) -> int:
    """금액 문자열 → int 변환 (쉼표/원 제거)"""
    if not amount_str:
        return 0
    cleaned = re.sub(r"[,\s원₩]", "", str(amount_str)).split(".")[0]
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return 0


def _normalize_biz_no(biz_no: str) -> str:
    """사업자번호를 000-00-00000 형식으로 정규화"""
    if not biz_no:
        return ""
    digits = re.sub(r"\D", "", biz_no)
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    return biz_no


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


# Gemini에 전달할 세금계산서 추출 프롬프트
TAX_INVOICE_PROMPT = """
다음 세금계산서 이미지를 분석하여 아래 JSON 형식으로 정보를 추출해주세요.
반드시 JSON만 출력하고 다른 설명은 포함하지 마세요.

{
  "issue_date": "작성일 (YYYY-MM-DD 또는 YYYYMMDD)",
  "supplier_name": "공급자 상호명",
  "supplier_biz_no": "공급자 사업자등록번호",
  "supplier_representative": "공급자 대표자명",
  "recipient_name": "공급받는자 상호명",
  "recipient_biz_no": "공급받는자 사업자등록번호",
  "items": [
    {"name": "품목명", "quantity": 1, "unit_price": 0, "supply_amount": 0, "tax": 0}
  ],
  "supply_amount": 0,
  "tax_amount": 0,
  "total_amount": 0,
  "raw_text": "세금계산서에서 읽은 핵심 텍스트 요약"
}

주의사항:
- 금액은 숫자만 입력 (쉼표/원 제거)
- 공급가액(supply_amount)과 세액(tax_amount)은 별도로 입력
- total_amount = supply_amount + tax_amount
- 찾을 수 없는 필드는 빈 문자열("") 또는 0으로 입력
"""


class TaxInvoiceParser(BaseParser):
    """세금계산서 Vision 파서"""

    async def parse(self, image_bytes: bytes, mime_type: str) -> ParseResult:
        """
        세금계산서 이미지/PDF 파싱.
        공급자 정보·공급가액·세액·품목을 추출하고 submit_expense_approval 형식으로 반환.
        """
        raw_text = ""
        warnings = []
        missing_fields = []

        try:
            # Gemini Vision 호출
            response_text = self._call_gemini(TAX_INVOICE_PROMPT, image_bytes, mime_type)
            raw_text = response_text

            # JSON 추출
            data = _extract_json_from_text(response_text)
            if not data:
                warnings.append("Gemini 응답에서 JSON을 파싱할 수 없었습니다. 수동 입력이 필요합니다.")
                return ParseResult(
                    document_type="세금계산서",
                    form_type="지출결의서",
                    extracted_data={"action": "draft"},
                    confidence=0.0,
                    raw_text=raw_text,
                    missing_fields=["issue_date", "supplier_name", "total_amount"],
                    warnings=warnings,
                )

            # 날짜 정규화
            issue_date = _normalize_date(data.get("issue_date", ""))
            if not issue_date:
                missing_fields.append("issue_date")
                warnings.append("작성일을 인식하지 못했습니다. 직접 입력해주세요.")

            # 공급자 정보
            supplier_name = data.get("supplier_name", "")
            if not supplier_name:
                missing_fields.append("supplier_name")
                warnings.append("공급자 상호명을 인식하지 못했습니다.")

            supplier_biz_no = _normalize_biz_no(data.get("supplier_biz_no", ""))
            supplier_rep = data.get("supplier_representative", "")

            # 금액 파싱
            supply_amount = _parse_amount(data.get("supply_amount", 0))
            tax_amount = _parse_amount(data.get("tax_amount", 0))
            total_amount = _parse_amount(data.get("total_amount", 0))

            # total_amount가 0이면 supply + tax로 계산
            if total_amount == 0 and (supply_amount > 0 or tax_amount > 0):
                total_amount = supply_amount + tax_amount

            if total_amount == 0:
                missing_fields.append("total_amount")
                warnings.append("합계 금액을 인식하지 못했습니다. 직접 입력해주세요.")

            # 품목 목록 변환
            raw_items = data.get("items", [])
            items = []
            for it in raw_items:
                item_name = it.get("name", "")
                # 품목별 공급가액 우선, 없으면 unit_price
                item_amount = _parse_amount(
                    it.get("supply_amount", it.get("unit_price", 0))
                )
                item_qty = int(it.get("quantity", 1))
                if item_name:
                    items.append({
                        "name": item_name,
                        "amount": item_amount,
                        "quantity": item_qty,
                    })

            # 품목이 없으면 공급가액 전체를 단일 항목으로
            if not items:
                item_name = supplier_name or "세금계산서 품목"
                items = [{"name": item_name, "amount": supply_amount or total_amount, "quantity": 1}]

            # 품목명 설명 문자열 (복수 품목 시 첫 번째 + 외 N건)
            if len(items) == 1:
                item_desc = items[0]["name"]
            else:
                item_desc = f"{items[0]['name']} 외 {len(items)-1}건"

            # 신뢰도 계산 (날짜 30% + 공급자명 30% + 금액 40%)
            confidence = 0.0
            if issue_date:
                confidence += 0.3
            if supplier_name:
                confidence += 0.3
            if total_amount > 0:
                confidence += 0.4

            # GW submit_expense_approval 파라미터 형식으로 구성
            extracted_data = {
                "title": f"[세금계산서] {supplier_name}" if supplier_name else "[세금계산서]",
                "date": issue_date,
                "description": f"공급자: {supplier_name} / 품목: {item_desc}",
                "items": items,
                "total_amount": total_amount,
                "action": "draft",  # 기본: 임시저장 후 확인

                # 메타 정보 (확인 단계 표시용, GW 전송 시 제외)
                "_supplier_name": supplier_name,
                "_supplier_biz_no": supplier_biz_no,
                "_supplier_representative": supplier_rep,
                "_supply_amount": supply_amount,
                "_tax_amount": tax_amount,
                "_issue_date": issue_date,
                "_recipient_name": data.get("recipient_name", ""),
                "_recipient_biz_no": _normalize_biz_no(data.get("recipient_biz_no", "")),
            }

            return ParseResult(
                document_type="세금계산서",
                form_type="지출결의서",
                extracted_data=extracted_data,
                confidence=confidence,
                raw_text=raw_text,
                missing_fields=missing_fields,
                warnings=warnings,
            )

        except Exception as e:
            logger.error(f"[TaxInvoiceParser] 파싱 오류: {e}", exc_info=True)
            return ParseResult(
                document_type="세금계산서",
                form_type="지출결의서",
                extracted_data={"action": "draft"},
                confidence=0.0,
                raw_text=raw_text,
                missing_fields=["issue_date", "supplier_name", "total_amount"],
                warnings=[f"세금계산서 파싱 중 오류가 발생했습니다: {e}"],
            )
