"""
전자결재 양식 템플릿 정의
- 양식별 필드 매핑, 검색어, 필수 입력 필드 관리
- 결재 HOME 추천양식 기준 (2026-03-02)

양식 사용 현황 (총 66건):
  1. [프로젝트]지출결의서    30건  ← Phase 0 완료
  2. [회계팀] 국내 거래처등록  26건  ← DOM 탐색 필요
  3. 연장근무신청서           3건
  4. 기타                    7건

네비게이션 공통:
  - 결재 HOME → 추천양식에서 양식명 클릭
  - 또는 결재작성 → 양식 검색 → 선택
  - 양식 테이블: table.OBTFormPanel_table__1fRyk
  - 필드 접근: th 라벨 → 형제 td 내 input

보관(임시저장):
  - 상신/보관함 > 임시보관문서에 보관됨
  - 일부 양식에서 "보관" 버튼 존재 (양식별 상이)
"""

# ─────────────────────────────────────────
# 양식 정의
# ─────────────────────────────────────────

FORM_TEMPLATES = {

    # ═══════════════════════════════════════
    # 1. [프로젝트]지출결의서 (30건, Phase 0 완료)
    # ═══════════════════════════════════════
    "지출결의서": {
        "search_keyword": "지출결의서",
        "display_name": "[프로젝트]지출결의서",
        "form_id": "255",
        "form_dtp": "APB1020_00001",
        "status": "verified",  # Phase 0 DOM 확인 완료
        "aliases": [
            "지출 결의서", "지출결의", "지출 결의", "경비 청구",
            "대금 지급", "납품 대금", "선급금 지급", "중도금 지급",
        ],

        "fields": {
            # 상단 테이블 (table[0])
            "accounting_unit": {
                "label": "회계단위",
                "placeholder": "사업장코드",
                "type": "code_help",
                "default": "1000. 주식회사 글로우서울",
                "required": False,
            },
            "accounting_date": {
                "label": "회계처리일자",
                "type": "date",
                "class": "OBTDatePickerRebuild_inputYMD",
                "required": False,
            },
            "project": {
                "label": "프로젝트",
                "placeholder": "프로젝트코드도움",
                "type": "code_help",
                "required": False,
            },
            "title": {
                "label": "제목",
                "type": "text",
                "required": True,
            },
            # 지출내역 그리드
            "expense_grid": {
                "type": "grid",
                "columns": ["용도", "내용", "거래처", "공급가액", "부가세", "합계액", "증빙", "증빙번호"],
                "buttons": {
                    "add": "추가",
                    "delete": "삭제",
                    "card": "카드사용내역",
                    "invoice": "계산서내역",
                    "cash_receipt": "현금영수증",
                },
            },
            # 하단 테이블 (table[7])
            "receipt_date": {
                "label": "증빙일자",
                "type": "date",
                "class": "OBTDatePickerRebuild_inputYMD",
                "required": False,
            },
            "payment_request_date": {
                "label": "지급요청일",
                "type": "date",
                "required": False,
            },
            "employee": {
                "label": "사원",
                "placeholder": "사원코드도움",
                "type": "code_help",
                "required": False,
            },
            "bank": {
                "label": "은행/계좌번호",
                "placeholder": "금융기관코드도움",
                "type": "code_help",
                "required": False,
            },
            "department": {
                "label": "사용부서",
                "placeholder": "부서코드도움",
                "type": "code_help",
                "required": False,
            },
        },

        "actions": {
            "submit": "결재상신",
            "rewrite": "다시쓰기",
            "doc_list": "문서목록",
        },

        "approval_line": {
            "drafter": "auto",
            "agree": "신동관",
            "final": "최기영",
        },
    },

    # ═══════════════════════════════════════
    # 2. [회계팀] 국내 거래처등록 신청서 (26건)
    # ═══════════════════════════════════════
    "거래처등록": {
        "search_keyword": "거래처등록",
        "display_name": "[회계팀] 국내 거래처등록 신청서",
        "aliases": [
            "국내 거래처등록", "거래처 등록", "거래처 신규", "거래처등록 신청",
            "신규 거래처", "업체 등록", "협력사 등록", "거래처 추가",
        ],
        "status": "template_only",  # DOM 탐색 필요

        "fields": {
            "title": {
                "label": "제목",
                "type": "text",
                "required": True,
                "example": "[국내]신규 거래처등록 요청(주식회사 OOO)",
            },
            "vendor_name": {
                "label": "거래처명(상호)",
                "type": "text",
                "required": True,
                "example": "주식회사 OOO",
            },
            "ceo_name": {
                "label": "대표자명",
                "type": "text",
                "required": True,
                "example": "홍길동",
            },
            "business_number": {
                "label": "사업자등록번호",
                "type": "text",
                "required": True,
                "format": "000-00-00000",
                "example": "123-45-67890",
            },
            "business_type": {
                "label": "업태",
                "type": "text",
                "required": True,
                "example": "건설업",
            },
            "business_item": {
                "label": "종목",
                "type": "text",
                "required": True,
                "example": "인테리어",
            },
            "address": {
                "label": "사업장주소",
                "type": "text",
                "required": True,
                "example": "서울특별시 종로구 OO로 123",
            },
            "contact_name": {
                "label": "담당자명",
                "type": "text",
                "required": True,
            },
            "contact_phone": {
                "label": "담당자 연락처",
                "type": "text",
                "required": True,
                "format": "010-0000-0000",
            },
            "contact_email": {
                "label": "담당자 이메일",
                "type": "text",
                "required": False,
            },
            "bank_name": {
                "label": "은행명",
                "type": "text",
                "required": True,
                "example": "국민은행",
            },
            "account_number": {
                "label": "계좌번호",
                "type": "text",
                "required": True,
            },
            "account_holder": {
                "label": "예금주",
                "type": "text",
                "required": True,
            },
            "note": {
                "label": "비고",
                "type": "text",
                "required": False,
            },
        },

        "attachments": {
            "business_cert": {
                "label": "사업자등록증",
                "required": True,
                "format": "PDF/이미지",
            },
            "bankbook_copy": {
                "label": "통장사본",
                "required": True,
                "format": "PDF/이미지",
            },
        },

        "approval_line": {
            "drafter": "auto",
            "agree": "신동관",
            "final": "최기영",
        },
    },

    # ═══════════════════════════════════════
    # 3. [회계팀] 증빙발행 신청서
    # ═══════════════════════════════════════
    "증빙발행": {
        "search_keyword": "증빙발행",
        "display_name": "[회계팀] 증빙발행 신청서",
        "aliases": [
            "증빙 발행", "세금계산서 발행", "계산서 발행",
            "증빙 신청", "세금계산서 신청", "영수증 발행",
            "세금계산서", "증빙발행 신청",
        ],
        "status": "template_only",

        "fields": {
            "title": {
                "label": "제목",
                "type": "text",
                "required": True,
                "example": "[OOO]증빙발행 신청서",
            },
            "issue_type": {
                "label": "발행구분",
                "type": "select",
                "required": True,
                "options": ["세금계산서", "영수증", "계산서"],
                "default": "세금계산서",
            },
            "vendor_name": {
                "label": "발행처(거래처명)",
                "type": "text",
                "required": True,
                "example": "주식회사 OOO",
            },
            "business_number": {
                "label": "사업자번호",
                "type": "text",
                "required": True,
                "format": "000-00-00000",
            },
            "supply_amount": {
                "label": "공급가액",
                "type": "number",
                "required": True,
                "example": 1000000,
            },
            "tax_amount": {
                "label": "세액",
                "type": "number",
                "required": True,
                "example": 100000,
                "note": "공급가액의 10% (부가세)",
            },
            "total_amount": {
                "label": "합계",
                "type": "number",
                "required": False,
                "auto_calc": True,
                "formula": "supply_amount + tax_amount",
            },
            "issue_date": {
                "label": "발행일",
                "type": "date",
                "required": True,
            },
            "item_description": {
                "label": "품목/내용",
                "type": "text",
                "required": True,
                "example": "인테리어 시공비",
            },
            "note": {
                "label": "비고",
                "type": "text",
                "required": False,
            },
        },

        "attachments": {
            "contract": {
                "label": "계약서",
                "required": False,
                "format": "PDF",
            },
        },

        "approval_line": {
            "drafter": "auto",
            "agree": "신동관",
            "final": "최기영",
        },
    },

    # ═══════════════════════════════════════
    # 4. [본사]선급금 요청서
    # ═══════════════════════════════════════
    "선급금요청": {
        "search_keyword": "선급금 요청서",
        "display_name": "[본사]선급금 요청서",
        "aliases": [
            "선급금", "선급금 요청", "선금 요청", "선급금요청서",
            "선급 요청", "계약금 요청", "착수금 요청",
            "선급금 지급 요청", "업체 선급금",
        ],
        "status": "template_only",

        "fields": {
            "title": {
                "label": "제목",
                "type": "text",
                "required": True,
                "example": "GS-25-0088. [종로] 메디빌더 OO업체 선급금 지급의 건",
            },
            "project": {
                "label": "프로젝트",
                "placeholder": "프로젝트코드도움",
                "type": "code_help",
                "required": True,
                "example": "GS-25-0088. [종로] 메디빌더",
            },
            "vendor_name": {
                "label": "거래처",
                "type": "text",
                "required": True,
                "example": "주식회사 OOO",
            },
            "amount": {
                "label": "요청금액",
                "type": "number",
                "required": True,
                "example": 5000000,
            },
            "payment_date": {
                "label": "지급요청일",
                "type": "date",
                "required": True,
            },
            "purpose": {
                "label": "요청사유",
                "type": "text",
                "required": True,
                "example": "OO공사 계약에 따른 선급금 지급",
            },
            "bank_name": {
                "label": "은행명",
                "type": "text",
                "required": True,
                "example": "국민은행",
            },
            "account_number": {
                "label": "계좌번호",
                "type": "text",
                "required": True,
            },
            "account_holder": {
                "label": "예금주",
                "type": "text",
                "required": True,
            },
        },

        "attachments": {
            "contract": {
                "label": "계약서",
                "required": False,
                "format": "PDF",
            },
            "estimate": {
                "label": "견적서",
                "required": False,
                "format": "PDF",
            },
        },

        "approval_line": {
            "drafter": "auto",
            "agree": "신동관",
            "final": "최기영",
        },
    },

    # ═══════════════════════════════════════
    # 5. [본사]선급금 정산서
    # ═══════════════════════════════════════
    "선급금정산": {
        "search_keyword": "선급금 정산서",
        "display_name": "[본사]선급금 정산서",
        "aliases": [
            "선급금 정산", "선금 정산", "선급금정산서",
            "선급 정산", "계약금 정산", "착수금 정산",
        ],
        "status": "template_only",

        "fields": {
            "title": {
                "label": "제목",
                "type": "text",
                "required": True,
                "example": "GS-25-0088. [종로] 메디빌더 OO업체 선급금 정산의 건",
            },
            "project": {
                "label": "프로젝트",
                "placeholder": "프로젝트코드도움",
                "type": "code_help",
                "required": True,
                "example": "GS-25-0088. [종로] 메디빌더",
            },
            "vendor_name": {
                "label": "거래처",
                "type": "text",
                "required": True,
                "example": "주식회사 OOO",
            },
            "original_amount": {
                "label": "선급금액",
                "type": "number",
                "required": True,
                "example": 5000000,
                "note": "기지급한 선급금 총액",
            },
            "used_amount": {
                "label": "사용금액",
                "type": "number",
                "required": True,
                "example": 4500000,
            },
            "return_amount": {
                "label": "반환금액",
                "type": "number",
                "required": False,
                "auto_calc": True,
                "formula": "original_amount - used_amount",
            },
            "description": {
                "label": "정산내역",
                "type": "text",
                "required": True,
                "example": "OO공사 선급금 정산 (계약금액 대비 실 사용 내역)",
            },
        },

        "attachments": {
            "receipt": {
                "label": "증빙자료",
                "required": False,
                "format": "PDF/이미지",
            },
            "settlement_sheet": {
                "label": "정산서",
                "required": False,
                "format": "PDF/Excel",
            },
        },

        "approval_line": {
            "drafter": "auto",
            "agree": "신동관",
            "final": "최기영",
        },
    },

    # ═══════════════════════════════════════
    # 6. 연장근무신청서 (3건)
    # ═══════════════════════════════════════
    "연장근무": {
        "search_keyword": "연장근무신청서",
        "display_name": "연장근무신청서",
        "aliases": [
            "연장근무", "야근 신청", "초과근무", "연장근무 신청",
            "야근", "잔업", "OT 신청", "시간외 근무",
            "연장근무신청", "초과근무 신청",
        ],
        "status": "template_only",

        "fields": {
            "title": {
                "label": "제목",
                "type": "text",
                "required": True,
                "example": "연장근무신청서 - 전태규 (2026-03-02)",
            },
            "work_date": {
                "label": "근무일",
                "type": "date",
                "required": True,
            },
            "start_time": {
                "label": "시작시간",
                "type": "time",
                "required": True,
                "format": "HH:MM",
                "example": "18:00",
                "note": "정규 퇴근시간 이후",
            },
            "end_time": {
                "label": "종료시간",
                "type": "time",
                "required": True,
                "format": "HH:MM",
                "example": "21:00",
            },
            "reason": {
                "label": "사유",
                "type": "text",
                "required": True,
                "example": "프로젝트 납기 대응",
            },
        },

        "approval_line": {
            "drafter": "auto",
            "final": "최기영",
        },
    },

    # ═══════════════════════════════════════
    # 7. 외근신청서(당일)
    # ═══════════════════════════════════════
    "외근신청": {
        "search_keyword": "외근신청서",
        "display_name": "외근신청서(당일)",
        "aliases": [
            "외근", "외근 신청", "외출", "외근신청서",
            "현장 방문", "외부 미팅", "출장", "외근신청",
            "외근 나가기", "현장 출근",
        ],
        "status": "template_only",

        "fields": {
            "title": {
                "label": "제목",
                "type": "text",
                "required": True,
                "example": "외근신청서 - 전태규 (종로 메디빌더 현장)",
            },
            "work_date": {
                "label": "외근일",
                "type": "date",
                "required": True,
            },
            "destination": {
                "label": "방문처",
                "type": "text",
                "required": True,
                "example": "종로 메디빌더 현장",
            },
            "purpose": {
                "label": "외근사유",
                "type": "text",
                "required": True,
                "example": "현장 시공 관리 및 업체 미팅",
            },
            "start_time": {
                "label": "출발시간",
                "type": "time",
                "required": False,
                "format": "HH:MM",
                "example": "09:00",
            },
            "end_time": {
                "label": "복귀시간",
                "type": "time",
                "required": False,
                "format": "HH:MM",
                "example": "18:00",
            },
        },

        "approval_line": {
            "drafter": "auto",
            "final": "최기영",
        },
    },

    # ═══════════════════════════════════════
    # 8. 사내추천비 자금 요청서
    # ═══════════════════════════════════════
    "사내추천비": {
        "search_keyword": "사내추천비",
        "display_name": "사내추천비 자금 요청서",
        "aliases": [
            "추천비", "사내추천비 요청", "사내 추천비",
            "추천비 요청", "추천비 지급", "사내추천비 지급",
            "추천비 자금", "사내추천비 자금 요청",
        ],
        "status": "template_only",

        "fields": {
            "title": {
                "label": "제목",
                "type": "text",
                "required": True,
                "example": "사내추천비 자금 요청서 - OOO건",
            },
            "recommended_person": {
                "label": "추천대상자",
                "type": "text",
                "required": True,
                "example": "홍길동",
                "note": "추천을 통해 입사하게 될 대상자명",
            },
            "recommender": {
                "label": "추천인",
                "type": "text",
                "required": True,
                "example": "전태규",
                "note": "추천한 사내 직원명",
            },
            "amount": {
                "label": "요청금액",
                "type": "number",
                "required": True,
                "example": 500000,
            },
            "purpose": {
                "label": "사용목적",
                "type": "text",
                "required": True,
                "example": "사내추천 제도에 의한 추천비 지급",
            },
            "description": {
                "label": "상세내용",
                "type": "text",
                "required": False,
                "example": "OO팀 OO직급 채용 관련 사내추천비 지급 요청",
            },
        },

        "approval_line": {
            "drafter": "auto",
            "final": "최기영",
        },
    },
}


# ─────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────

def get_template(form_name: str) -> dict | None:
    """양식 템플릿 반환 (이름, 별칭, 부분 일치 모두 지원)"""
    # 정확한 키 매칭
    if form_name in FORM_TEMPLATES:
        return FORM_TEMPLATES[form_name]

    # 별칭(aliases) 매칭
    for key, tmpl in FORM_TEMPLATES.items():
        aliases = tmpl.get("aliases", [])
        if form_name in aliases:
            return tmpl

    # 부분 매칭 (검색어, display_name, 키 이름)
    for key, tmpl in FORM_TEMPLATES.items():
        search_kw = tmpl.get("search_keyword", "")
        display = tmpl.get("display_name", "")
        if (form_name in key or key in form_name
                or form_name in search_kw or search_kw in form_name
                or form_name in display or display in form_name):
            return tmpl

    return None


def get_template_key(form_name: str) -> str | None:
    """양식 키 반환 (이름, 별칭, 부분 일치 모두 지원)"""
    # 정확한 키 매칭
    if form_name in FORM_TEMPLATES:
        return form_name

    # 별칭(aliases) 매칭
    for key, tmpl in FORM_TEMPLATES.items():
        aliases = tmpl.get("aliases", [])
        if form_name in aliases:
            return key

    # 부분 매칭
    for key, tmpl in FORM_TEMPLATES.items():
        search_kw = tmpl.get("search_keyword", "")
        display = tmpl.get("display_name", "")
        if (form_name in key or key in form_name
                or form_name in search_kw or search_kw in form_name
                or form_name in display or display in form_name):
            return key

    return None


def get_required_fields(form_name: str) -> list[str]:
    """필수 필드 목록 반환"""
    tmpl = get_template(form_name)
    if not tmpl:
        return []
    return [
        info.get("label", key)
        for key, info in tmpl["fields"].items()
        if isinstance(info, dict) and info.get("required")
    ]


def get_field_examples(form_name: str) -> dict[str, str]:
    """필드별 예시값 반환"""
    tmpl = get_template(form_name)
    if not tmpl:
        return {}
    return {
        info.get("label", key): info.get("example", "")
        for key, info in tmpl["fields"].items()
        if isinstance(info, dict) and info.get("example")
    }


def list_form_names() -> list[dict]:
    """전체 양식 목록 반환 (이름, 표시명, 상태)"""
    return [
        {
            "key": key,
            "display_name": tmpl["display_name"],
            "status": tmpl.get("status", "unknown"),
        }
        for key, tmpl in FORM_TEMPLATES.items()
    ]
