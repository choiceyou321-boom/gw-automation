"""
Vision Dispatch 모듈
- 사진/PDF → Gemini Vision 문서 분류 + 데이터 추출
- 메인 진입점: dispatch_document()

사용 예시:
    from src.vision import dispatch_document

    result = await dispatch_document(image_bytes, mime_type="image/jpeg")
    print(result.document_type)   # "영수증"
    print(result.form_type)       # "지출결의서"
    print(result.extracted_data)  # GW 양식 파라미터 딕셔너리
    print(result.confidence)      # 0.85
"""

from .document_classifier import classify_document
from .parsers.receipt_parser import ReceiptParser
from .parsers.tax_invoice_parser import TaxInvoiceParser
from .parsers.vendor_parser import VendorParser
from .parsers.base_parser import ParseResult


async def dispatch_document(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> ParseResult:
    """
    Vision Dispatch 메인 진입점.

    1단계: classify_document()로 문서 타입 분류
    2단계: 문서 타입에 맞는 파서 선택
    3단계: 파서 실행 후 ParseResult 반환

    Args:
        image_bytes: 이미지 또는 PDF 바이트 데이터
        mime_type: MIME 타입 (image/jpeg, image/png, application/pdf 등)

    Returns:
        ParseResult (document_type, form_type, extracted_data, confidence, ...)
    """
    # 1단계: 문서 타입 분류
    classification = await classify_document(image_bytes, mime_type)

    doc_type = classification["document_type"]

    # 2단계: 파서 매핑 (견적서는 아직 전용 파서 없음 → 기타 처리)
    parser_map = {
        "영수증":     ReceiptParser,
        "세금계산서": TaxInvoiceParser,
        "거래처서류": VendorParser,
    }

    parser_cls = parser_map.get(doc_type)

    if not parser_cls:
        # 분류 불가 또는 미지원 타입 → 기본 결과 반환
        return ParseResult(
            document_type=doc_type,
            form_type=classification.get("form_type"),
            extracted_data={},
            confidence=classification["confidence"],
            warnings=[
                f"'{doc_type}' 문서를 자동으로 인식하지 못했습니다. "
                "수동으로 내용을 입력해주세요."
            ],
        )

    # 3단계: 파서 실행
    parser = parser_cls()
    return await parser.parse(image_bytes, mime_type)


__all__ = [
    "dispatch_document",
    "classify_document",
    "ReceiptParser",
    "TaxInvoiceParser",
    "VendorParser",
    "ParseResult",
]
