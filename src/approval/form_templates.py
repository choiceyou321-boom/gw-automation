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
from __future__ import annotations

from src.auth.user_db import get_approval_config  # 결재선 DB 조회 (핫패스 동적 import 방지)

# ─────────────────────────────────────────
# 공통 상수
# ─────────────────────────────────────────

DEFAULT_APPROVAL_LINE = {
    "drafter": "auto",      # 기안자 (로그인 사용자 자동)
    "agree": "신동관",       # 검토자
    "final": "최기영",       # 최종 승인자
}

SIMPLE_APPROVAL_LINE = {
    "drafter": "auto",
    "final": "최기영",
}

# 결재선 프리셋 — 사용자가 자연어로 지정 가능
# 예: "부서장 결재로 해줘" → APPROVAL_PRESETS["부서장"]
APPROVAL_PRESETS = {
    "기본": DEFAULT_APPROVAL_LINE,
    "default": DEFAULT_APPROVAL_LINE,
    "간단": SIMPLE_APPROVAL_LINE,
    "simple": SIMPLE_APPROVAL_LINE,
    "2단계": SIMPLE_APPROVAL_LINE,
    "3단계": DEFAULT_APPROVAL_LINE,
    "부서장": {
        "drafter": "auto",
        "final": "최기영",
        # 부서장 결재 = 직속 상위자만
    },
    "직속상관": {
        "drafter": "auto",
        "final": "신동관",
    },
    "팀장": {
        "drafter": "auto",
        "final": "신동관",
    },
}

# 수신참조 프리셋
CC_PRESETS = {
    "재무": ["재무전략팀", "재무회계팀"],
    "재무팀": ["재무전략팀", "재무회계팀"],
    "경영지원": ["경영지원팀"],
    "인사": ["인사팀"],
}

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
                "note": "상단 회계처리일자 변경 (세금계산서 발행월과 일치 필요)",
            },
            "project": {
                "label": "프로젝트",
                "placeholder": "프로젝트코드도움",
                "type": "code_help",
                "required": False,
            },
            "usage_code": {
                "label": "용도코드",
                "type": "code_help",
                "default": "5020",
                "required": False,
                "note": "그리드 용도 셀 숫자코드 (예: 5020=외주공사비)",
            },
            "budget_keyword": {
                "label": "예산과목 검색어",
                "type": "text",
                "required": False,
                "note": "예산과목코드도움 검색어 (예: 경량). 2로 시작하는 코드만 선택",
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
                "item_keys": {
                    # agent.py items 키 → 그리드 컬럼 매핑
                    "usage": "용도",
                    "content": "내용",
                    "vendor": "거래처",
                    "supply_amount": "공급가액",
                    "tax_amount": "부가세",
                    # 호환 키 (agent.py 기존 형식)
                    "item": "내용",
                    "amount": "공급가액",
                    "note": "내용",
                },
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
                "class": "OBTDatePickerRebuild_inputYMD",
                "required": False,
                "note": "하단 날짜 피커 (YYYY-MM-DD)",
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

        "approval_line": DEFAULT_APPROVAL_LINE,
    },

    # ═══════════════════════════════════════
    # 2. [회계팀] 국내 거래처등록 신청서 (26건)
    # ═══════════════════════════════════════
    "거래처등록": {
        "search_keyword": "거래처등록",
        "display_name": "[회계팀] 국내 거래처등록 신청서",
        "form_id": "196",
        "aliases": [
            "국내 거래처등록", "거래처 등록", "거래처 신규", "거래처등록 신청",
            "신규 거래처", "업체 등록", "협력사 등록", "거래처 추가",
        ],
        "status": "verified",  # Phase 0 DOM 탐색 완료 (2026-03-02)

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

        "cc_recipients": ["재무전략팀", "재무회계팀"],  # 수신참조 필수

        "editor_type": "dzEditor",  # 본문이 contentEditable (표준 input 아님)

        "actions": {
            "preview": "미리보기",
            "save_draft": "보관",
            "submit": "상신",
        },

        "approval_line": SIMPLE_APPROVAL_LINE,  # 2단계: 전태규→최기영
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
        # Phase 0 탐색 결과 (2026-03-02):
        # - 전자결재 결재작성 → "증빙발행" 검색 → "[회계팀] 증빙발행 신청서" 발견됨
        # - formId 미확인 (검색 결과 선택 시 URL에 formId 미노출)
        # - 추가 탐색 필요: Enter 후 팝업 URL에서 formId 확인
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

        "approval_line": DEFAULT_APPROVAL_LINE,
    },

    # ═══════════════════════════════════════
    # 4. [본사]선급금 요청서
    # ═══════════════════════════════════════
    "선급금요청": {
        "search_keyword": "선급금 요청서",
        "display_name": "[본사]선급금 요청서",
        "form_id": "181",  # Phase 0 탐색 확인 (2026-03-02) — 지출결의서 변형 양식
        "aliases": [
            "선급금", "선급금 요청", "선금 요청", "선급금요청서",
            "선급 요청", "계약금 요청", "착수금 요청",
            "선급금 지급 요청", "업체 선급금",
        ],
        # Phase 0 탐색 결과 (2026-03-02):
        # - 전자결재 결재작성 → "선급금 요청서" 검색 → "[본사]선급금 요청서" 발견
        # - formId=181 (URL에서 확인)
        # - 열기 방식: 인라인 (지출결의서와 동일한 지출결의서작성 화면으로 로드)
        # - 필드 구조: 지출결의서와 유사 (그리드 포함), inputs=20개
        # - 프로젝트코드도움, 금융기관코드도움, 거래처계좌번호, 업무용차량코드도움 placeholder 확인
        "status": "verified",

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

        "approval_line": DEFAULT_APPROVAL_LINE,
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
        # Phase 0 탐색 결과 (2026-03-02):
        # - 전자결재 결재작성 → "선급금 정산서" 검색 → "[본사]선급금 정산서" 발견
        # - formId 미확인 (URL에 미노출) — 선급금요청(181)과 유사한 구조
        # - 열기 방식: 인라인 (지출결의서작성 화면으로 로드, inputs=20개)
        # - 왼쪽 양식목록에 "[본사]선급금 정산서" 항목 표시됨 확인
        "status": "verified",

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

        "approval_line": DEFAULT_APPROVAL_LINE,
    },

    # ═══════════════════════════════════════
    # 6. 연장근무신청서 (3건)
    # ═══════════════════════════════════════
    "연장근무": {
        "search_keyword": "연장근무신청서",
        "display_name": "연장근무신청서",
        "form_id": "43",  # Phase 0 탐색 확인 (2026-03-02)
        "aliases": [
            "연장근무", "야근 신청", "초과근무", "연장근무 신청",
            "야근", "잔업", "OT 신청", "시간외 근무",
            "연장근무신청", "초과근무 신청",
        ],
        # Phase 0 탐색 결과 (2026-03-02):
        # - ★ 전자결재 양식이 아닌 근태관리 모듈(근태신청서) 화면으로 열림
        # - URL: formId=43 (결재작성 검색 URL 기준)
        # - 실제 신청 경로: 근태관리 > 근태신청 > 연장근무신청서 선택
        # - 신청정보 필드: 근무구분(조기근무/연장근무/휴일근무), 작성기준, 연장근무시작일, 시작/종료시간, 비고
        # - 버튼: 연장근무, 야간근무, 법정근무, 추가신청, 신청완료
        # - inputs=14개 (visible)
        # code_ready (2026-04-02): create_overtime_request + _save_overtime_draft 구현, GW DOM 검증 필요
        "status": "code_ready",

        "fields": {
            "title": {
                "label": "제목",
                "type": "text",
                "required": True,
                "example": "연장근무신청서 - 전태규 (2026-03-02)",
            },
            "date": {
                "label": "연장근무일",
                "type": "date",
                "required": True,
            },
            "work_date": {
                "label": "근무일",
                "type": "date",
                "required": False,
                "note": "date 키와 동의어 (내부 호환용)",
            },
            "start_time": {
                "label": "시작시각",
                "type": "time",
                "required": True,
                "format": "HH:MM",
                "example": "18:00",
                "note": "정규 퇴근시간 이후",
            },
            "end_time": {
                "label": "종료시각",
                "type": "time",
                "required": True,
                "format": "HH:MM",
                "example": "21:00",
            },
            "reason": {
                "label": "연장근무 사유",
                "type": "text",
                "required": True,
                "example": "프로젝트 납기 대응",
            },
            "project": {
                "label": "프로젝트명",
                "type": "text",
                "required": False,
                "example": "GS-25-0088. [종로] 메디빌더",
            },
            "work_type": {
                "label": "근무구분",
                "type": "select",
                "required": False,
                "options": ["조기근무", "연장근무", "휴일근무"],
                "default": "연장근무",
            },
        },

        "approval_line": SIMPLE_APPROVAL_LINE,
    },

    # ═══════════════════════════════════════
    # 7. 외근신청서(당일)
    # ═══════════════════════════════════════
    "외근신청": {
        "search_keyword": "외근신청서",
        "display_name": "외근신청서(당일)",
        "form_id": "41",  # Phase 0 탐색 확인 (2026-03-02)
        "aliases": [
            "외근", "외근 신청", "외출", "외근신청서",
            "현장 방문", "외부 미팅", "출장", "외근신청",
            "외근 나가기", "현장 출근",
        ],
        # Phase 0 탐색 결과 (2026-03-02):
        # - ★ 전자결재 양식이 아닌 근태관리 모듈(근태신청서) 화면으로 열림
        # - URL: formId=41 (결재작성 검색 URL 기준)
        # - 실제 신청 경로: 근태관리 > 근태신청 > 외근신청서(당일) 선택
        # - 신청정보 필드: 외근구분(종일외근/외근후출근/출근후외근), 외근기간, 시작/종료시간, 교통수단, 방문처, 대상자, 업무내용
        # - 버튼: 일정등록, 삭제
        # - inputs=13개 (visible)
        # code_ready (2026-04-02): create_outside_work_request + _save_outside_work_draft 구현, GW DOM 검증 필요
        "status": "code_ready",

        "fields": {
            "title": {
                "label": "제목",
                "type": "text",
                "required": True,
                "example": "외근신청서 - 전태규 (종로 메디빌더 현장)",
            },
            "date": {
                "label": "외근일",
                "type": "date",
                "required": True,
            },
            "work_date": {
                "label": "외근일",
                "type": "date",
                "required": False,
                "note": "date 키와 동의어 (내부 호환용)",
            },
            "start_time": {
                "label": "외출시각",
                "type": "time",
                "required": True,
                "format": "HH:MM",
                "example": "09:00",
            },
            "end_time": {
                "label": "복귀시각",
                "type": "time",
                "required": True,
                "format": "HH:MM",
                "example": "18:00",
            },
            "destination": {
                "label": "외근지",
                "type": "text",
                "required": True,
                "example": "종로 메디빌더 현장",
            },
            "reason": {
                "label": "외근 사유",
                "type": "text",
                "required": True,
                "example": "현장 시공 관리 및 업체 미팅",
            },
            "project": {
                "label": "프로젝트명",
                "type": "text",
                "required": False,
                "example": "GS-25-0088. [종로] 메디빌더",
            },
            "purpose": {
                "label": "외근사유",
                "type": "text",
                "required": False,
                "note": "reason 키와 동의어 (내부 호환용)",
            },
            "work_type": {
                "label": "외근구분",
                "type": "select",
                "required": False,
                "options": ["종일외근", "외근후출근", "출근후외근"],
                "default": "종일외근",
            },
            "transport": {
                "label": "교통수단",
                "type": "text",
                "required": False,
                "example": "대중교통",
            },
        },

        "approval_line": SIMPLE_APPROVAL_LINE,
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
        # Phase 0 탐색 결과 (2026-03-02):
        # - 전자결재 결재작성 → "사내추천비" 검색 → "사내추천비 지급 요청서" 발견
        # - formId 미확인 (검색 결과 표시 후 Enter 시 팝업 미발생, URL 변경 없음)
        # - 추가 탐색 필요: 양식 선택 후 실제 작성 화면 URL 확인
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

        "approval_line": SIMPLE_APPROVAL_LINE,
    },
}


# ─────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────

def _find_template_key(form_name: str) -> str | None:
    """양식 키 검색 (정확→별칭→부분 일치 순)"""
    # 정확한 키 매칭
    if form_name in FORM_TEMPLATES:
        return form_name

    # 별칭(aliases) 매칭
    for key, tmpl in FORM_TEMPLATES.items():
        aliases = tmpl.get("aliases", [])
        if form_name in aliases:
            return key

    # 부분 매칭 (검색어, display_name, 키 이름)
    for key, tmpl in FORM_TEMPLATES.items():
        search_kw = tmpl.get("search_keyword", "")
        display = tmpl.get("display_name", "")
        if (form_name in key or key in form_name
                or form_name in search_kw or search_kw in form_name
                or form_name in display or display in form_name):
            return key

    return None


def get_template(form_name: str) -> dict | None:
    """양식 템플릿 반환 (이름, 별칭, 부분 일치 모두 지원)"""
    key = _find_template_key(form_name)
    return FORM_TEMPLATES[key] if key else None


def get_template_key(form_name: str) -> str | None:
    """양식 키 반환 (이름, 별칭, 부분 일치 모두 지원)"""
    return _find_template_key(form_name)


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


def resolve_approval_line(custom_line: dict | str | None, form_name: str = None, user_context: dict = None) -> dict:
    """
    결재선 딕셔너리 반환.

    Args:
        custom_line: 사용자가 대화 중 직접 지정한 결재선 (딕셔너리 또는 프리셋 이름 문자열)
        form_name: 양식명 (미지정 시 양식 기본값 사용 불가)
        user_context: 사용자 세션 정보 (gw_id 포함). DB에 저장된 결재선 조회용.

    Returns:
        결재선 딕셔너리 {"drafter": ..., "agree": ...(선택), "final": ...}

    조회 순서:
        1. custom_line (사용자가 대화 중 직접 지정)
        2. user_context → gw_id → DB approval_config → 양식별 or default
        3. 양식 기본값 (FORM_TEMPLATES에 정의된 것)
        4. 팀 전역 기본값 (DEFAULT_APPROVAL_LINE)

    사용 예:
        resolve_approval_line(None, "지출결의서")                    # 양식 기본값
        resolve_approval_line("간단")                                # 프리셋
        resolve_approval_line({"final": "홍길동"})                  # 커스텀
        resolve_approval_line(None, "지출결의서", {"gw_id": "tgjeon"})  # DB 설정 우선
    """
    # 1. 딕셔너리면 그대로 사용 (drafter 기본값 보완)
    if isinstance(custom_line, dict):
        result = {"drafter": "auto", **custom_line}
        return result

    # 2. 문자열이면 프리셋에서 찾기
    if isinstance(custom_line, str):
        preset = APPROVAL_PRESETS.get(custom_line)
        if preset:
            return dict(preset)
        # 부분 매칭
        for key, val in APPROVAL_PRESETS.items():
            if custom_line in key or key in custom_line:
                return dict(val)

    # 3. 사용자별 DB 결재선 설정 조회
    if user_context:
        gw_id = user_context.get("gw_id")
        if gw_id:
            try:
                config = get_approval_config(gw_id)
                if config:
                    # 양식별 키로 먼저 조회 (예: "지출결의서", "거래처등록")
                    form_key = _find_template_key(form_name) if form_name else None
                    line = None
                    if form_key and form_key in config:
                        line = config[form_key]
                    elif form_name and form_name in config:
                        line = config[form_name]
                    elif "default" in config:
                        line = config["default"]
                    if line:
                        return {"drafter": "auto", **line}
            except Exception:
                pass  # DB 조회 실패 시 폴백

    # 4. 양식 기본값 사용
    if form_name:
        tmpl = get_template(form_name)
        if tmpl and "approval_line" in tmpl:
            return dict(tmpl["approval_line"])

    # 5. 전역 기본값
    return dict(DEFAULT_APPROVAL_LINE)


def resolve_cc_recipients(cc_input: list | str | None, form_name: str = None, user_context: dict = None) -> list[str]:
    """
    수신참조 목록 반환.

    Args:
        cc_input: 수신참조 목록 또는 프리셋 이름
        form_name: 양식명 (양식 기본 cc 사용)
        user_context: 사용자 세션 정보 (향후 사용자별 cc 설정 확장용)

    Returns:
        수신참조 이름 리스트
    """
    if isinstance(cc_input, list):
        return cc_input

    if isinstance(cc_input, str):
        preset = CC_PRESETS.get(cc_input)
        if preset:
            return list(preset)
        # 단일 이름이면 리스트로 변환
        return [cc_input]

    # 양식 기본 cc
    if form_name:
        tmpl = get_template(form_name)
        if tmpl:
            return list(tmpl.get("cc_recipients", []))

    return []
