"""
Google Gemini 연동 + 의도 분석 에이전트
- 사용자 메시지와 첨부파일을 분석해 자동화 작업 라우팅
- Function calling 패턴으로 자동화 함수 호출
"""

import os
import base64
import json
import concurrent.futures
from pathlib import Path
from typing import Optional
from google import genai
from google.genai import types

# Gemini 클라이언트 초기화
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
MODEL_ID = "gemini-2.5-flash"

# 동시 Playwright 세션 수 제한 (무제한 스레드 생성 방지)
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# 자동화 도구 정의 (function calling)
AUTOMATION_TOOLS = [
    types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="reserve_meeting_room",
            description="회의실 예약을 처리합니다. 사용자가 회의실 예약, 미팅 룸 예약, 회의 잡기 등을 요청할 때 사용합니다.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "date": types.Schema(type="STRING", description="예약 날짜 (YYYY-MM-DD 형식)"),
                    "start_time": types.Schema(type="STRING", description="시작 시간 (HH:MM 형식)"),
                    "end_time": types.Schema(type="STRING", description="종료 시간 (HH:MM 형식)"),
                    "room_name": types.Schema(type="STRING", description="회의실 이름 (없으면 빈 문자열)"),
                    "title": types.Schema(type="STRING", description="회의 제목"),
                    "participants": types.Schema(type="STRING", description="참석자 목록 (쉼표 구분)"),
                },
                required=["date", "start_time", "end_time", "title"],
            ),
        ),
        types.FunctionDeclaration(
            name="submit_expense_approval",
            description="지출결의서/경비 결재를 작성합니다. 사용자가 '경비 결재', '지출결의', '비용 처리', '결재 신청' 등을 요청할 때 사용합니다.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project": types.Schema(type="STRING", description="프로젝트명"),
                    "title": types.Schema(type="STRING", description="결재 제목 (예: '3월 교통비 정산')"),
                    "amount": types.Schema(type="NUMBER", description="총 금액 (원)"),
                    "date": types.Schema(type="STRING", description="지출일 (YYYY-MM-DD 형식)"),
                    "description": types.Schema(type="STRING", description="적요/내용 설명"),
                    "items": types.Schema(
                        type="ARRAY",
                        description="지출 항목 리스트",
                        items=types.Schema(
                            type="OBJECT",
                            properties={
                                "item": types.Schema(type="STRING", description="항목명"),
                                "amount": types.Schema(type="NUMBER", description="금액"),
                                "note": types.Schema(type="STRING", description="비고"),
                            },
                        ),
                    ),
                    "payee": types.Schema(type="STRING", description="지급처"),
                    "approval_line": types.Schema(type="STRING", description="결재선 지정 (예: '간단', '부서장', '직속상관', '2단계', '3단계'). 생략 시 기본값 사용."),
                    "cc": types.Schema(type="STRING", description="수신참조 대상 (예: '재무팀', '경영지원', 이름/팀명 콤마 구분). 생략 시 없음."),
                    "evidence_type": types.Schema(type="STRING", description="증빙유형: '세금계산서', '계산서내역', '카드사용내역', '현금영수증'. 영수증/세금계산서가 있을 때 지정."),
                    "invoice_vendor": types.Schema(type="STRING", description="세금계산서 거래처명 (공급자). evidence_type='세금계산서'일 때 팝업 검색에 사용."),
                    "invoice_amount": types.Schema(type="NUMBER", description="세금계산서 공급가액 (원). evidence_type='세금계산서'일 때 팝업 매칭에 사용."),
                    "invoice_date": types.Schema(type="STRING", description="세금계산서 발행일 (YYYY-MM-DD). evidence_type='세금계산서'일 때 조회 기간 설정에 사용."),
                    "auto_capture_budget": types.Schema(type="BOOLEAN", description="예실대비현황 스크린샷 자동 캡처 후 첨부파일로 업로드 여부. 사용자가 '예실대비 첨부', '예산 현황 캡처' 등을 요청할 때 True."),
                    "usage_code": types.Schema(type="STRING", description="용도 코드 (예: '5020'=외주공사비, '5010'=시공재료비). 기본값 '5020'. 그리드 용도 셀에 입력."),
                    "budget_keyword": types.Schema(type="STRING", description="예산과목 검색어 (예: '경량', '음향'). 예산과목코드도움 팝업에서 2로 시작하는 코드만 선택."),
                    "payment_request_date": types.Schema(type="STRING", description="지급요청일 (YYYY-MM-DD). 하단 날짜 피커에 입력."),
                    "accounting_date": types.Schema(type="STRING", description="회계처리일자 (YYYY-MM-DD). 세금계산서 발행월과 일치해야 검증결과 '적합'. 미지정 시 세금계산서 발행일 기준 자동계산."),
                    "action": types.Schema(type="STRING", description="실행 액션: 'confirm'이면 확인 후 작성, 'draft'이면 임시저장, 'submit'이면 바로 결재상신 (즉시 상신됨, 주의). 기본값 'confirm'"),
                },
                required=["title", "description"],
            ),
        ),
        types.FunctionDeclaration(
            name="submit_approval_form",
            description=(
                "전자결재 양식을 작성합니다. 지출결의서 외의 양식에 사용합니다. "
                "거래처등록, 연장근무, 외근신청, 선급금요청, 선급금정산, 증빙발행, 사내추천비 등을 요청할 때 사용합니다. "
                "첨부파일(사업자등록증, 통장사본 등)에서 추출한 정보도 fields에 넣어주세요."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "form_type": types.Schema(
                        type="STRING",
                        description="양식 종류: '거래처등록', '연장근무', '외근신청', '선급금요청', '선급금정산', '증빙발행', '사내추천비'",
                    ),
                    "title": types.Schema(type="STRING", description="결재 제목"),
                    "fields": types.Schema(
                        type="OBJECT",
                        description=(
                            "양식별 필드 데이터. 예시: "
                            "거래처등록: {vendor_name, ceo_name, business_number, business_type, business_item, address, contact_name, contact_phone, bank_name, account_number, account_holder} / "
                            "연장근무: {work_date, start_time, end_time, reason} / "
                            "외근신청: {work_date, destination, purpose, start_time, end_time}"
                        ),
                        properties={},
                    ),
                    "approval_line": types.Schema(type="STRING", description="결재선 지정 (예: '간단', '부서장', '직속상관', '2단계', '3단계'). 생략 시 기본값 사용."),
                    "cc": types.Schema(type="STRING", description="수신참조 대상 (예: '재무팀', '경영지원', 이름/팀명 콤마 구분). 생략 시 없음."),
                    "action": types.Schema(
                        type="STRING",
                        description="'confirm'이면 확인 후 작성, 'draft'이면 바로 작성. 기본값 'confirm'",
                    ),
                },
                required=["form_type", "title"],
            ),
        ),
        types.FunctionDeclaration(
            name="check_reservation_status",
            description="회의실 예약 현황을 조회합니다. 사용자가 '오늘 예약 현황', '내일 회의실 상황', '지금 예약 뭐 있어?', '3월 5일 회의실 예약 확인' 등을 요청할 때 사용합니다.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "date": types.Schema(type="STRING", description="조회할 날짜 (YYYY-MM-DD 형식). 오늘이면 오늘 날짜."),
                    "room_name": types.Schema(type="STRING", description="특정 회의실만 보려면 지정 (예: '1번 회의실'). 전체 조회는 빈 문자열."),
                },
                required=["date"],
            ),
        ),
        types.FunctionDeclaration(
            name="check_available_rooms",
            description="빈 회의실과 사용 가능한 시간대를 조회합니다. 사용자가 '빈 회의실', '남는 회의실', '어디 비어있어?', '회의실 가능한 시간', '1시간짜리 회의실 있어?' 등을 요청할 때 사용합니다.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "date": types.Schema(type="STRING", description="조회할 날짜 (YYYY-MM-DD 형식). 오늘이면 오늘 날짜."),
                    "room_name": types.Schema(type="STRING", description="특정 회의실만 보려면 지정. 전체 조회는 빈 문자열."),
                    "duration_minutes": types.Schema(type="NUMBER", description="필요한 시간 (분 단위). 기본 60분. '1시간'=60, '30분'=30, '2시간'=120."),
                },
                required=["date"],
            ),
        ),
        types.FunctionDeclaration(
            name="cancel_meeting_reservation",
            description="회의실 예약을 취소합니다. 사용자가 '예약 취소', '예약 삭제', '회의 취소해줘', '예약 빼줘' 등을 요청할 때 사용합니다.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "date": types.Schema(type="STRING", description="취소할 예약의 날짜 (YYYY-MM-DD 형식)."),
                    "title": types.Schema(type="STRING", description="취소할 예약의 제목 (부분 일치 가능). 없으면 빈 문자열."),
                    "room_name": types.Schema(type="STRING", description="취소할 예약의 회의실 이름. 없으면 빈 문자열."),
                    "start_time": types.Schema(type="STRING", description="취소할 예약의 시작 시간 (HH:MM 형식). 없으면 빈 문자열."),
                },
                required=["date"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_mail_summary",
            description=(
                "안 읽은 메일을 요약합니다. 사용자가 '메일 요약', '새 메일 있어?', '받은 메일 확인해줘', '메일 체크' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={},
            ),
        ),
        types.FunctionDeclaration(
            name="list_my_reservations",
            description=(
                "향후 14일간 내 회의실 예약 목록을 조회합니다. "
                "사용자가 '내 예약 목록 보여줘', '내 예약 어떤 거 있어?', '이번 주 예약 확인', "
                "'예약 취소하고 싶은데 뭐가 있지?' 등을 요청할 때 사용합니다. "
                "취소할 예약을 선택하기 전에 먼저 목록을 보여줄 때도 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "days": types.Schema(
                        type="INTEGER",
                        description="오늘부터 조회할 일수 (기본값 14). 최대 30.",
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="cleanup_test_reservations",
            description=(
                "[TEST_ 접두사 테스트 예약을 일괄 취소합니다. "
                "사용자가 '테스트 예약 정리해줘', 'TEST_ 예약 전부 취소해줘', "
                "'테스트 예약 청소해줘', '잔류 테스트 예약 삭제해줘' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "days": types.Schema(
                        type="INTEGER",
                        description="오늘부터 스캔할 일수 (기본값 14).",
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="submit_draft_approval",
            description=(
                "임시보관된 결재 문서를 열고 결재상신합니다. "
                "사용자가 '임시보관한 결재 상신해줘', '저장된 결재 올려줘', '보관 중인 결재 상신' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "doc_title": types.Schema(
                        type="STRING",
                        description="상신할 임시보관 문서 제목 (일부만 입력해도 됨). 지정하지 않으면 첫 번째 문서를 상신.",
                    ),
                },
                required=[],
            ),
        ),
        types.FunctionDeclaration(
            name="search_project_code",
            description=(
                "그룹웨어 프로젝트 코드도움에서 키워드로 프로젝트를 검색합니다. "
                "사용자가 '메디빌더', '고수동굴' 등 프로젝트 이름 일부를 말했을 때 "
                "정식 프로젝트 코드/명칭을 확인하기 위해 사용합니다. "
                "지출결의서 작성 전 프로젝트 코드를 확정할 때 호출하세요."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "keyword": types.Schema(
                        type="STRING",
                        description="검색 키워드 (예: '메디빌더', 'GS-25', '종로')",
                    ),
                },
                required=["keyword"],
            ),
        ),
    ])
]

# 시스템 프롬프트
SYSTEM_PROMPT = """당신은 회사 업무 자동화를 돕는 AI 어시스턴트입니다.
사용자의 요청을 분석하여 적절한 자동화 도구를 사용하거나, 일반적인 질문에 답변합니다.

## 핵심 원칙
- 사용자는 비개발자입니다. 편하게 말하는 자연어를 이해해야 합니다.
- 정보가 충분하면 바로 도구를 호출하세요. 불필요하게 되묻지 마세요.
- 정보가 부족할 때만 간단하고 친근하게 물어보세요.

## 보안 및 프라이버시 (매우 중요)
- 다른 사용자의 계정 로그인 정보나 비밀번호 등 민감한 인증 정보를 묻는 질문에는 절대 답변하지 마세요.
- 단, 원활한 업무 협업을 위해 팀원들의 일정(회의실 예약 현황 등) 조회가 가능합니다. 누가 어느 회의실을 예약했는지는 알려주어도 됩니다.
- 타인의 예약을 임의로 취소하거나 다른 사람 이름으로 결재를 올리는 등 타인의 권한이 필요한 '생성/수정/삭제' 요청은 단호하게 거절하세요.

## 자연어 해석 규칙
오늘 날짜: {today}

날짜 변환:
- "오늘" → 오늘 날짜
- "내일" → 내일 날짜
- "모레" → 모레 날짜
- "이번주 금요일", "다음주 월요일" → 해당 날짜 계산
- "3월 5일" → 올해 3월 5일

시간 변환:
- "오후 2시" → 14:00
- "오전 10시 반" → 10:30
- "2시부터 3시까지" → start 14:00, end 15:00
- "1시간" (종료 시간 없으면) → 시작 시간 + 1시간

회의실:
- "5번 회의실", "대회의실", "3층 회의실" → 그대로 전달
- 회의실 지정 없으면 빈 문자열로 (자동 배정)

제목:
- "팀 미팅", "주간회의", "면접" 등 맥락에서 추출
- 명시 안 하면 "회의"로 기본값

참석자:
- 없으면 빈 문자열

## 예시
- "내일 오후 2시에 3시까지 5번 회의실 팀미팅 잡아줘" → 바로 예약 실행
- "모레 오전 10시 회의실 하나 잡아줘 1시간짜리" → 바로 예약 실행
- "회의실 예약해줘" (정보 없음) → "언제, 몇 시에 예약할까요?" 정도만 물어보기

## 첨부파일 분석 (매우 중요)
사용자가 이미지나 PDF를 첨부하면 내용을 꼼꼼히 읽어서 정보를 추출하세요.

자주 첨부되는 문서:
- **사업자등록증**: 상호(거래처명), 대표자명, 사업자등록번호, 업태, 종목, 사업장주소 추출
- **통장사본**: 은행명, 계좌번호, 예금주 추출
- **계약서**: 계약 상대방, 계약금액, 프로젝트명, 계약일 추출
- **거래명세서/세금계산서**: 거래처, 공급가액, 세액, 품목, 거래일 추출

추출한 정보는 전자결재 양식 필드에 자동 매핑하세요:
- 사업자등록증 + 통장사본 → 거래처등록 신청 (submit_approval_form, form_type="거래처등록")
- 거래명세서/세금계산서 → 지출결의서 (submit_expense_approval)
- 계약서 → 선급금 요청 또는 지출결의서

첨부파일만 보내고 별다른 지시가 없으면:
1. 문서 종류를 파악하고
2. 추출한 정보를 정리해서 보여주고
3. "이 정보로 [양식명] 작성할까요?" 라고 제안하세요

## 도구 사용
- 회의실 예약: reserve_meeting_room
- 예약 현황 조회: check_reservation_status (오늘/특정 날짜 예약 확인)
- 빈 회의실 확인: check_available_rooms (남는 회의실/시간대 검색)
- 예약 취소: cancel_meeting_reservation (예약 취소 처리)
- 지출결의서: submit_expense_approval
- 전자결재(기타 양식): submit_approval_form (거래처등록, 연장근무, 외근신청 등)
- 임시보관 결재 상신: submit_draft_approval (임시보관문서 → 결재상신)
- 연장근무/외근신청/선급금 등 기타 결재양식: 양식 탐색 완료, 일부 E2E 미완성 (요청 시 안내 제공)
- 메일 요약: get_mail_summary (새 메일 확인/요약)
- 프로젝트 코드 검색: search_project_code (프로젝트명 일부 → 정식 코드 확인)
- 그 외: 도구 없이 직접 답변

## 경비 결재 (지출결의서) 대화형 질문 플로우 (매우 중요!)

### 지출결의서 필수 정보
- **제목** (필수): 예) "GS-25-0088. 메디빌더 음향공사 대금 지급의 건"
- **지출 내용/항목** (필수): 무엇에 쓴 돈인지
- **금액** (필수): 공급가액 또는 총액

### 흐름 (단계별로 진행)
1. 사용자가 지출결의서를 요청하면 **이미 말한 정보는 그대로 채우고, 빠진 정보만 친근하게 질문**하세요.
2. 모든 필수 정보가 갖춰지면 submit_expense_approval(action="confirm")으로 미리보기를 보여주세요.
3. 사용자가 '확인', '맞아', '작성해줘' 등으로 승인하면 submit_expense_approval(action="draft")으로 실제 작성하세요.
4. **작성 완료 시 상신하지 않고 "보관"(임시저장)만 합니다.**

### 지출결의서 추가 기능
- 사용자가 영수증/세금계산서 종류를 언급하면 evidence_type 지정:
  - "세금계산서", "계산서" → evidence_type="세금계산서"
  - "카드", "카드 영수증" → evidence_type="카드사용내역"
  - "현금영수증" → evidence_type="현금영수증"
- 사용자가 "예실대비 첨부", "예산 현황 캡처", "예산 스크린샷" 등을 요청하면 auto_capture_budget=True 지정
- 세금계산서 팝업 자동 매칭: evidence_type="세금계산서"일 때 아래 파라미터도 함께 지정하면 GW 세금계산서 팝업에서 자동 검색/선택:
  - invoice_vendor: 공급자(거래처)명 (예: "주식회사 ABC")
  - invoice_amount: 세금계산서 공급가액 (예: 2750000)
  - invoice_date: 세금계산서 발행일 (YYYY-MM-DD). 비어있으면 최근 3개월 자동 조회

### 대화형 질문 예시
- "지출결의서 올려줘" → "어떤 프로젝트 건인가요? (프로젝트명 또는 코드)"
- "메디빌더 음향공사 200만원 지출" → 건명+금액 파악됨. "어떤 용도(내용)인가요? 예) 음향설비 설치 공사비"
- "거래처는 주식회사 OOO이고 식대야" → 거래처+내용 파악됨. "금액이 얼마인가요?"
- 영수증 사진 첨부 → Gemini가 금액/거래처/날짜 추출 → "이 영수증 내용으로 지출결의서 작성할까요? 확인해주세요:\n- 거래처: OOO\n- 금액: OOO원\n- 날짜: YYYY-MM-DD"

### 프로젝트 코드 확인 플로우 (중요!)
사용자가 프로젝트 이름 일부(예: "메디빌더", "고수동굴")를 언급하면:
1. **search_project_code(keyword="메디빌더")** 를 먼저 호출하세요.
2. 결과가 1건이면 → "프로젝트는 'GS-25-0088. [종로] 메디빌더'가 맞나요?" 확인 요청
3. 결과가 여러 건이면 → 목록 제시 후 선택 요청:
   "어떤 프로젝트인가요?\n1. GS-25-0088. [종로] 메디빌더\n2. GS-25-0091. [서울] 메디빌더 2차"
4. 결과가 없으면 → "그룹웨어에서 '메디빌더' 프로젝트를 찾지 못했어요. 정확한 프로젝트 코드나 이름을 알려주세요."
5. 사용자가 프로젝트를 확인/선택하면 → **반드시 submit_expense_approval(project=full_text)을 호출하세요. 시스템이 자동으로 제목 초안을 제안합니다.**

### 제목 자동 제안 플로우 (중요! 프로젝트 확정 직후 반드시 실행)
프로젝트가 확정되고 아직 제목이 없으면:
- **도구를 사용하지 말고 직접 물어보지 마세요.** submit_expense_approval을 호출하면 시스템이 자동으로 제목 초안을 제안합니다.
- 제목 제안 형식: "결재 제목을 이렇게 하면 어떨까요?\n\n  \"GS-25-0088. [종로] 메디빌더 음향공사 대금 지급의 건\"\n\n이대로 괜찮으시면 '확인', 수정하실 내용이 있으면 원하는 제목을 알려주세요."
- 사용자가 '확인', '좋아', '그거로 해줘', '맞아' → 제안된 제목 그대로 title에 넣고 다음 단계
- 사용자가 다른 제목을 직접 말하면 → 그 제목을 title에 넣고 다음 단계 진행
- 사용자가 처음부터 제목을 직접 말했으면 → 제안 생략, 바로 다음 단계 진행

**예시 전체 흐름:**
1. 사용자: "메디빌더 음향공사 지출결의서"
2. 봇: search_project_code("메디빌더") 호출 → "프로젝트는 'GS-25-0088. [종로] 메디빌더'가 맞나요?"
3. 사용자: "맞아"
4. 봇: submit_expense_approval(project="GS-25-0088. [종로] 메디빌더", description="음향공사") 호출
   → 시스템 응답: "결재 제목을 이렇게 하면 어떨까요?\n\n  \"GS-25-0088. [종로] 메디빌더 음향공사 대금 지급의 건\"\n\n이대로 괜찮으시면..."
5. 사용자: "음향공사 선급금 지급의 건으로 해줘"
6. 봇: submit_expense_approval(project="...", title="GS-25-0088. [종로] 메디빌더 음향공사 선급금 지급의 건", ...) 호출

### 이미 제공된 정보 스킵 규칙 (중요!)
- 사용자 메시지에서 금액이 언급됐으면 → 금액 다시 묻지 않기
- 사업자등록증/통장사본/영수증에서 정보 추출됐으면 → 해당 필드 채워서 바로 confirm 단계로
- 필수 3개(제목, 내용, 금액) 모두 있으면 → 바로 submit_expense_approval(action="confirm") 호출
- 프로젝트 코드가 이미 "GS-25-XXXX." 형식으로 확정됐으면 → search_project_code 다시 호출하지 않기

## 전자결재 (기타 양식) 대화형 질문 플로우

### 거래처등록 특별 규칙 (중요!)
거래처등록 요청 시 사업자등록증과 통장사본이 첨부되지 않았으면:
- 도구를 호출하지 말고, "거래처등록 신청을 위해 **사업자등록증**과 **통장사본**을 먼저 첨부해주세요! 아래 첨부 버튼으로 이미지나 PDF를 올려주시면 자동으로 정보를 추출해드릴게요." 라고 안내하세요.
- 첨부파일이 있으면 정보 추출 후 진행하세요.

### 거래처등록 필수 정보 (사업자등록증+통장에서 자동 추출)
거래처명, 대표자명, 사업자등록번호, 업태, 종목, 주소, 은행명, 계좌번호, 예금주

1. 먼저 submit_approval_form(action="confirm")으로 추출 정보 확인
2. 사용자 승인 후 submit_approval_form(action="draft")으로 실제 작성
3. 첨부파일이 있으면 내용을 읽어서 fields에 자동 매핑
   - 예: 사업자등록증 첨부 + "거래처등록 해줘" → 사업자번호, 상호 등을 fields에 넣기
4. 현재 자동 작성 가능 양식: 지출결의서, 거래처등록 (나머지는 준비 중)
5. **모든 양식은 상신하지 않고 "보관"(임시저장)만 합니다. 사용자가 GW에서 확인 후 직접 상신합니다.**

## 예약 조회 예시
- "오늘 회의실 예약 현황 보여줘" → check_reservation_status
- "내일 3번 회의실 예약 있어?" → check_reservation_status (room_name="3번 회의실")
- "지금 빈 회의실 어디야?" → check_available_rooms
- "내일 오후에 2시간짜리 회의실 있어?" → check_available_rooms (duration_minutes=120)
- "1번 회의실 언제 비어?" → check_available_rooms (room_name="1번 회의실")

## 예약 목록 조회
- "내 예약 목록 보여줘", "내 예약 어떤 거 있어?", "이번 주 예약 확인" → list_my_reservations
- "예약 취소하고 싶은데 뭐가 있지?" → list_my_reservations 먼저 호출해서 목록 보여주기

## 예약 취소 흐름
사용자가 예약 취소를 요청하면:
1. 날짜/제목/시간 정보가 불명확하면 list_my_reservations로 향후 14일 본인 예약 목록을 보여주고 어떤 예약을 취소할지 물어봅니다
2. 사용자가 특정 예약을 지정하면(제목, 회의실, 시간 등) 취소를 실행합니다

예시:
- "내 예약 목록 보여줘" → list_my_reservations 실행
- "이번 주 예약 취소해줘" (모호) → list_my_reservations로 목록 보여주고 어느 것인지 물어보기
- "내일 예약 취소하고 싶어" → 먼저 list_my_reservations로 내일 포함 예약 현황을 보여주고, "어떤 예약을 취소할까요?"라고 물어보기
- "내일 3시 팀미팅 취소해줘" → 정보가 충분하면 바로 cancel_meeting_reservation 실행
- "방금 말한 거 취소해줘" → 대화 맥락에서 파악하여 cancel_meeting_reservation 실행

## 테스트 예약 일괄 정리
- "테스트 예약 정리해줘", "TEST_ 예약 전부 취소해줘", "잔류 테스트 예약 삭제" → cleanup_test_reservations

응답은 항상 한국어로 친절하게 작성합니다. 존댓말을 사용하세요."""


# 자동화 모듈 실행 함수들

def _get_api_for_user(user_context: dict = None):
    """
    사용자 컨텍스트에 따라 적절한 API 인스턴스 생성.
    user_context 있으면 session_manager 사용, 없으면 기존 방식.
    두 경로 모두 재인증을 위해 api._gw_id 주입 시도.
    """
    if user_context and user_context.get("gw_id"):
        from src.auth.session_manager import create_api
        return create_api(user_context["gw_id"])  # session_manager가 _gw_id 주입
    else:
        from src.meeting.reservation_api import create_api_with_session
        api, cleanup = create_api_with_session(headless=True)
        # fallback 경로에서도 재인증 가능하도록 gw_id 주입 시도
        gw_id = (user_context or {}).get("gw_id")
        if gw_id:
            api._gw_id = gw_id
        return api, cleanup


def handle_reserve_meeting_room(params: dict, user_context: dict = None) -> str:
    """
    회의실 예약 처리 - MeetingRoomAPI (reservation_api.py) 연동.
    기존 UI 자동화(reservation.py) 대신 rs121A API 직접 호출 방식 사용.
    """
    date       = params.get("date", "미정")
    start_time = params.get("start_time", "미정")
    end_time   = params.get("end_time", "미정")
    title      = params.get("title", "회의")
    room       = params.get("room_name", "1번 회의실")  # 미지정 시 1번 회의실 기본
    participants = params.get("participants", "")

    room_info = f"'{room}' 회의실" if room else "1번 회의실"
    part_info = f"\n- 참석자: {participants}" if participants else ""

    try:


        def _run_reservation():
            """별도 스레드에서 sync Playwright + MeetingRoomAPI 실행"""
            api, cleanup = _get_api_for_user(user_context)
            try:
                result = api.make_reservation(
                    room_name=room,
                    date=date,
                    start_time=start_time,
                    end_time=end_time,
                    title=title,
                    description=f"참석자: {participants}" if participants else "",
                )
                return result  # {"success": bool, "message": str, "data": dict}
            finally:
                cleanup()

        # async 루프 밖에서 sync Playwright 실행 (ThreadPoolExecutor 사용)
        future = _executor.submit(_run_reservation)
        result = future.result(timeout=120)

        if result.get("success"):
            return (
                f"회의실 예약이 완료되었습니다!\n\n"
                f"예약 내용:\n"
                f"- 제목: {title}\n"
                f"- 일시: {date} {start_time}~{end_time}\n"
                f"- 장소: {room_info}"
                f"{part_info}"
            )
        else:
            reason = result.get("message", "알 수 없는 오류")
            return (
                f"회의실 예약에 실패했습니다.\n"
                f"사유: {reason}\n\n"
                f"요청 내용:\n"
                f"- 제목: {title}\n"
                f"- 일시: {date} {start_time}~{end_time}\n"
                f"- 장소: {room_info}"
            )

    except Exception as e:
        return (
            f"회의실 예약 중 오류가 발생했습니다: {str(e)}\n\n"
            f"요청 내용:\n"
            f"- 제목: {title}\n"
            f"- 일시: {date} {start_time}~{end_time}\n"
            f"- 장소: {room_info}"
            f"{part_info}"
        )


def handle_check_reservation_status(params: dict, user_context: dict = None) -> str:
    """예약 현황 조회 - MeetingRoomAPI.get_reservations() 연동"""
    date = params.get("date", "")
    room_name = params.get("room_name", "")

    try:


        def _run_check():
            api, cleanup = _get_api_for_user(user_context)
            try:
                reservations = api.get_reservations(date)
                return reservations
            finally:
                cleanup()

        future = _executor.submit(_run_check)
        reservations = future.result(timeout=120)

        # 특정 회의실 필터링
        if room_name:
            reservations = [
                r for r in reservations
                if room_name in r.get("resName", "") or r.get("resName", "") in room_name
            ]

        if not reservations:
            room_info = f" ({room_name})" if room_name else ""
            return f"{date}{room_info} 예약이 없습니다. 모든 회의실이 비어 있습니다."

        lines = [f"📋 {date} 예약 현황 ({len(reservations)}건):\n"]
        for r in reservations:
            lines.append(
                f"• [{r.get('resName', '?')}] {r.get('start_time', '?')}~{r.get('end_time', '?')} "
                f"- {r.get('reqText', '(제목 없음)')} ({r.get('booker', '?')})"
            )
        return "\n".join(lines)

    except Exception as e:
        return f"예약 현황 조회 중 오류가 발생했습니다: {str(e)}"


def handle_check_available_rooms(params: dict, user_context: dict = None) -> str:
    """빈 회의실/시간대 조회 - MeetingRoomAPI.find_available_slots() 연동"""
    date = params.get("date", "")
    room_name = params.get("room_name", "")
    duration = int(params.get("duration_minutes", 60))

    try:


        def _run_check():
            api, cleanup = _get_api_for_user(user_context)
            try:
                slots = api.find_available_slots(
                    date=date,
                    room_name=room_name or None,
                    duration_minutes=duration,
                )
                return slots
            finally:
                cleanup()

        future = _executor.submit(_run_check)
        slots = future.result(timeout=120)

        if not slots:
            room_info = f" ({room_name})" if room_name else ""
            return f"{date}{room_info}에 {duration}분 이상 사용 가능한 시간대가 없습니다."

        # 회의실별로 그룹핑
        from collections import defaultdict
        by_room = defaultdict(list)
        for s in slots:
            by_room[s["resName"]].append(s)

        lines = [f"🕐 {date} 빈 시간대 ({duration}분 기준):\n"]
        for rname, rslots in by_room.items():
            time_strs = [f"{s['start_time']}~{s['end_time']}" for s in rslots]
            lines.append(f"• {rname}: {', '.join(time_strs)}")

        return "\n".join(lines)

    except Exception as e:
        return f"빈 회의실 조회 중 오류가 발생했습니다: {str(e)}"


def handle_cancel_meeting_reservation(params: dict, user_context: dict = None) -> str:
    """
    예약 취소 - MeetingRoomAPI.cancel_reservation() 연동.
    예약한 본인만 취소 가능 (GW 서버 권한 체크 + 클라이언트 필터링).
    """
    date = params.get("date", "")
    title = params.get("title", "")
    room_name = params.get("room_name", "")
    start_time = params.get("start_time", "")

    # 현재 사용자 정보 (로그인된 사용자)
    current_name = (user_context or {}).get("name", "")
    current_gw_id = (user_context or {}).get("gw_id", "")

    try:


        def _run_cancel():
            api, cleanup = _get_api_for_user(user_context)
            try:
                # 1단계: 해당 날짜 예약 조회
                reservations = api.get_reservations(date)

                # 본인 예약만 필터 (로그인 사용자 기준)
                booker_names = {current_name, current_gw_id} - {""}
                if not booker_names:
                    booker_names = None

                if booker_names:
                    my_reservations = [
                        r for r in reservations
                        if r.get("booker", "") in booker_names
                    ]
                else:
                    my_reservations = reservations

                if not my_reservations:
                    return {"success": False, "message": f"{date}에 본인 예약이 없습니다."}

                # 2단계: 조건으로 필터링
                candidates = my_reservations
                if title:
                    filtered = [r for r in candidates if title in r.get("reqText", "")]
                    if filtered:
                        candidates = filtered
                if room_name:
                    filtered = [r for r in candidates if room_name in r.get("resName", "") or r.get("resName", "") in room_name]
                    if filtered:
                        candidates = filtered
                if start_time:
                    clean_time = start_time.replace(":", "")
                    filtered = [r for r in candidates if clean_time in r.get("start_time", "").replace(":", "")]
                    if filtered:
                        candidates = filtered

                if len(candidates) == 0:
                    return {"success": False, "message": f"{date}에 조건에 맞는 예약을 찾을 수 없습니다."}

                if len(candidates) > 1:
                    lines = [f"{date}에 조건에 맞는 예약이 {len(candidates)}건 있습니다:\n"]
                    for i, r in enumerate(candidates, 1):
                        lines.append(
                            f"{i}. [{r.get('resName', '?')}] {r.get('start_time', '?')}~{r.get('end_time', '?')} "
                            f"- {r.get('reqText', '(제목 없음)')}"
                        )
                    lines.append("\n더 구체적으로 알려주시면 취소해드리겠습니다. (예: 제목, 회의실, 시간)")
                    return {"success": False, "message": "\n".join(lines)}

                # 3단계: 취소 실행
                target = candidates[0]
                raw = target.get("raw", {})
                result = api.cancel_reservation(
                    schm_seq=target.get("schmSeq", ""),
                    seq_num=target.get("seqNum", ""),
                    res_seq=target.get("resSeq", ""),
                    res_idx=str(raw.get("resIdx", "1")),
                    req_text=target.get("reqText", ""),
                    start_date=target.get("startDate", ""),
                    end_date=target.get("endDate", ""),
                    create_date=str(raw.get("createDate", "")),
                    res_name=target.get("resName", ""),
                )
                if result.get("success"):
                    return {
                        "success": True,
                        "message": (
                            f"예약이 취소되었습니다.\n\n"
                            f"취소된 예약:\n"
                            f"- 제목: {target.get('reqText', '?')}\n"
                            f"- 일시: {date} {target.get('start_time', '?')}~{target.get('end_time', '?')}\n"
                            f"- 장소: {target.get('resName', '?')}"
                        )
                    }
                else:
                    return {"success": False, "message": result.get("message", "취소 실패")}
            finally:
                cleanup()

        future = _executor.submit(_run_cancel)
        result = future.result(timeout=120)

        return result.get("message", "처리 완료")

    except Exception as e:
        return f"예약 취소 중 오류가 발생했습니다: {str(e)}"


def handle_list_my_reservations(params: dict, user_context: dict = None) -> str:
    """
    향후 N일간 본인 예약 목록 조회.
    empSeq 기준으로 본인 예약만 필터링하여 번호 매긴 목록 반환.
    """
    import datetime as _dt
    days = int(params.get("days", 14))
    days = min(days, 30)  # 최대 30일

    gw_id = (user_context or {}).get("gw_id", "")

    try:
        # 본인 empSeq 조회 (company_info에서)
        my_emp_seq = ""
        if gw_id:
            from src.auth.user_db import get_company_info as _get_company_info
            company_info = _get_company_info(gw_id)
            my_emp_seq = str(company_info.get("empSeq", ""))

        def _run_list():
            api, cleanup = _get_api_for_user(user_context)
            try:
                today = _dt.date.today()
                my_reservations = []
                for d in range(days):
                    target_date = (today + _dt.timedelta(days=d)).strftime("%Y-%m-%d")
                    try:
                        reservations = api.get_reservations(target_date)
                    except Exception as e:
                        logger.warning(f"예약 목록 조회 중 {target_date} 오류 (건너뜀): {e}")
                        continue

                    for res in reservations:
                        # empSeq 기준 본인 필터 (empSeq가 없으면 booker 이름으로 fallback)
                        res_emp_seq = str(res.get("empSeq", ""))
                        if my_emp_seq:
                            if res_emp_seq and res_emp_seq != my_emp_seq:
                                continue  # 타인 예약 건너뜀
                        my_reservations.append(res)

                return my_reservations
            finally:
                cleanup()

        future = _executor.submit(_run_list)
        my_reservations = future.result(timeout=30)

        if not my_reservations:
            return f"향후 {days}일간 본인 예약이 없습니다."

        lines = [f"내 회의실 예약 목록 (향후 {days}일, 총 {len(my_reservations)}건):\n"]
        for i, res in enumerate(my_reservations, 1):
            date_str = res.get("date", "")
            lines.append(
                f"{i}. {res.get('resName', '?')} "
                f"{date_str} {res.get('start_time', '?')}~{res.get('end_time', '?')}"
                f" ({res.get('reqText', '(제목 없음)')})"
            )
        lines.append("\n취소할 예약 번호를 알려주시면 취소해드리겠습니다.")
        return "\n".join(lines)

    except Exception as e:
        return f"예약 목록 조회 중 오류가 발생했습니다: {str(e)}"


def handle_cleanup_test_reservations(params: dict, user_context: dict = None) -> str:
    """
    [TEST_ 접두사 테스트 예약 일괄 취소.
    scripts/full_test.py의 _cleanup_stale_test_reservations와 동일한 로직.
    본인(empSeq 일치) 예약만 취소.
    """
    import datetime as _dt
    days = int(params.get("days", 14))
    days = min(days, 30)

    gw_id = (user_context or {}).get("gw_id", "")

    try:
        # 본인 empSeq 조회
        my_emp_seq = ""
        if gw_id:
            from src.auth.user_db import get_company_info as _get_company_info
            company_info = _get_company_info(gw_id)
            my_emp_seq = str(company_info.get("empSeq", ""))

        if not my_emp_seq:
            logger.warning("cleanup_test_reservations: empSeq 미확인 — 본인 필터 없이 진행")

        def _run_cleanup():
            api, cleanup = _get_api_for_user(user_context)
            try:
                today = _dt.date.today()
                cancelled_count = 0
                skipped_others = 0
                failed_count = 0
                cancelled_details = []

                for d in range(days):
                    target_date = (today + _dt.timedelta(days=d)).strftime("%Y-%m-%d")
                    try:
                        reservations = api.get_reservations(target_date)
                    except Exception as e:
                        logger.warning(f"테스트 예약 정리: {target_date} 조회 실패 (건너뜀) — {e}")
                        continue

                    for res in reservations:
                        req_text = res.get("reqText", "")
                        if "[TEST_" not in req_text:
                            continue

                        # 본인 예약 여부 확인
                        res_emp_seq = str(res.get("empSeq", ""))
                        if my_emp_seq and res_emp_seq and res_emp_seq != my_emp_seq:
                            logger.debug(
                                f"테스트 예약 정리: 다른 사용자 예약 건너뜀 "
                                f"(reqText={req_text!r}, empSeq={res_emp_seq})"
                            )
                            skipped_others += 1
                            continue

                        seq_num = res.get("seqNum", "")
                        if not seq_num:
                            logger.warning(
                                f"테스트 예약 정리: seqNum 없는 예약 건너뜀 "
                                f"(reqText={req_text!r}, date={target_date})"
                            )
                            continue

                        schm_seq = res.get("schmSeq", "")
                        res_seq = res.get("resSeq", "")
                        raw = res.get("raw", {})

                        try:
                            cancel_result = api.cancel_reservation(
                                schm_seq=schm_seq,
                                seq_num=seq_num,
                                res_seq=res_seq,
                                res_idx=str(raw.get("resIdx", "1")),
                                req_text=req_text,
                                start_date=res.get("startDate", ""),
                                end_date=res.get("endDate", ""),
                                create_date=str(raw.get("createDate", "")),
                                res_name=res.get("resName", ""),
                            )
                            if cancel_result.get("success"):
                                logger.info(
                                    f"테스트 예약 정리: 취소 성공 — {req_text!r} "
                                    f"({res.get('resName', '')} {target_date})"
                                )
                                cancelled_count += 1
                                cancelled_details.append(
                                    f"- {res.get('resName', '?')} {target_date} "
                                    f"{res.get('start_time', '?')}~{res.get('end_time', '?')} "
                                    f"({req_text})"
                                )
                            else:
                                logger.warning(
                                    f"테스트 예약 정리: 취소 실패 — {req_text!r} "
                                    f"({cancel_result.get('message', '')})"
                                )
                                failed_count += 1
                        except Exception as e:
                            logger.warning(f"테스트 예약 정리: 취소 중 오류 — {req_text!r}: {e}")
                            failed_count += 1

                return {
                    "cancelled_count": cancelled_count,
                    "skipped_others": skipped_others,
                    "failed_count": failed_count,
                    "cancelled_details": cancelled_details,
                }
            finally:
                cleanup()

        future = _executor.submit(_run_cleanup)
        result = future.result(timeout=30)

        cancelled_count = result["cancelled_count"]
        skipped_others = result["skipped_others"]
        failed_count = result["failed_count"]
        cancelled_details = result["cancelled_details"]

        if cancelled_count == 0 and failed_count == 0:
            msg = f"향후 {days}일 내 본인의 [TEST_ 테스트 예약이 없습니다."
            if skipped_others:
                msg += f" (타 사용자 테스트 예약 {skipped_others}건은 건너뜀)"
            return msg

        lines = [f"테스트 예약 정리 완료 (향후 {days}일 스캔):\n"]
        lines.append(f"- 취소 성공: {cancelled_count}건")
        if failed_count:
            lines.append(f"- 취소 실패: {failed_count}건")
        if skipped_others:
            lines.append(f"- 타 사용자 예약 건너뜀: {skipped_others}건")
        if cancelled_details:
            lines.append("\n취소된 예약:")
            lines.extend(cancelled_details)
        return "\n".join(lines)

    except Exception as e:
        return f"테스트 예약 정리 중 오류가 발생했습니다: {str(e)}"


def handle_submit_expense_approval(params: dict, user_context: dict = None) -> str:
    """
    지출결의서 작성 처리
    - action='confirm': 확인 메시지 반환 (사용자가 '확인' 후 실행)
    - action='draft': Playwright로 실제 폼 작성 + 임시저장
    """
    title = params.get("title", "")
    description = params.get("description", "")
    amount = params.get("amount")
    date = params.get("date", "")
    project = params.get("project", "")
    items = params.get("items", [])
    payee = params.get("payee", "")
    approval_line = params.get("approval_line")
    cc = params.get("cc")
    evidence_type = params.get("evidence_type", "")
    invoice_vendor = params.get("invoice_vendor", "")
    invoice_amount = params.get("invoice_amount")
    invoice_date = params.get("invoice_date", "")
    auto_capture_budget = params.get("auto_capture_budget", False)
    usage_code = params.get("usage_code", "5020")
    budget_keyword = params.get("budget_keyword", "")
    payment_request_date = params.get("payment_request_date", "")
    accounting_date = params.get("accounting_date", "")
    attachment_path = params.get("attachment_path", "")
    action = params.get("action", "confirm")

    # 항목 정보 포맷
    amount_str = f"{int(amount):,}원" if amount else "미정"
    items_str = ""
    if items:
        for i, item in enumerate(items, 1):
            item_amount = f"{int(item.get('amount', 0)):,}원" if item.get('amount') else ""
            items_str += f"\n  {i}. {item.get('item', '?')} {item_amount}"

    if action not in ("draft", "submit"):
        # 대화형 질문 플로우: 필수 정보가 빠진 경우 먼저 질문
        missing_q = []
        if not title:
            missing_q.append("title")
        has_content = bool(description) or bool(items)
        if not has_content:
            missing_q.append("content")
        has_amount = bool(amount) or any(item.get("amount") for item in items)
        if not has_amount:
            missing_q.append("amount")

        if missing_q:
            # 이미 파악된 정보 정리
            known_parts = []
            if title:
                known_parts.append(f"제목: {title}")
            if project:
                known_parts.append(f"프로젝트: {project}")
            if has_amount:
                known_parts.append(f"금액: {amount_str}")
            if has_content:
                content_summary = description if description else (items[0].get('item', '') if items else '')
                known_parts.append(f"내용: {content_summary}")
            if payee:
                known_parts.append(f"지급처: {payee}")

            known_str = ""
            if known_parts:
                known_str = "지금까지 파악된 내용:\n" + "\n".join(f"  - {k}" for k in known_parts) + "\n\n"

            # 빠진 정보 중 첫 번째만 질문 (한 번에 하나씩)
            first_missing = missing_q[0]
            if first_missing == "title":
                # 프로젝트가 확정된 경우 제목 자동 제안
                if project:
                    # "GS-25-0088. [종로] 메디빌더 음향공사" 형식에서 제목 후보 생성
                    # project 문자열에서 코드 부분(GS-XX-XXXX.) 추출
                    import re as _re
                    # "GS-25-0088. [종로] 메디빌더 음향공사" → code="GS-25-0088", proj_name="[종로] 메디빌더 음향공사"
                    code_match = _re.match(r'^([A-Z]{2}-\d{2}-\d{4})\.\s*(.*)', project)
                    if code_match:
                        code_prefix = code_match.group(1) + ". "
                        proj_name = code_match.group(2).strip()   # "[종로] 메디빌더 음향공사" 형태 그대로 유지
                    else:
                        code_prefix = ""
                        proj_name = project.strip()
                    # 내용/용도 기반 제목 제안 (사용자가 언급한 키워드 활용)
                    content_hint = description or (items[0].get('item', '') if items else '')
                    if content_hint:
                        suggested_title = f"{code_prefix}{proj_name} {content_hint} 대금 지급의 건"
                    else:
                        suggested_title = f"{code_prefix}{proj_name} 대금 지급의 건"
                    question = (
                        f"결재 문서 제목을 이렇게 하면 어떨까요?\n\n"
                        f"  \"{suggested_title}\"\n\n"
                        f"이대로 괜찮으시면 '확인', 수정하실 내용이 있으면 원하는 제목을 알려주세요."
                    )
                else:
                    question = "결재 문서 제목을 알려주세요. (예: 'GS-25-0088. [종로] 메디빌더 음향공사 대금 지급의 건')"
            elif first_missing == "content":
                question = "어떤 용도의 지출인지 알려주세요. (예: 음향설비 설치 공사비, 야근 식대 등)"
            else:  # amount
                question = "금액이 얼마인가요? (예: 2,750,000원)"

            return f"{known_str}{question}"

        # 필수 정보 모두 있으면 미리보기
        confirm_msg = (
            f"다음 내용으로 지출결의서를 작성합니다:\n\n"
            f"- 제목: {title}\n"
            f"- 프로젝트: {project or '미지정'}\n"
            f"- 지출일: {date or '미지정'}\n"
            f"- 금액: {amount_str}\n"
            f"- 내용: {description}"
        )
        if items_str:
            confirm_msg += f"\n- 항목:{items_str}"
        if payee:
            confirm_msg += f"\n- 지급처: {payee}"
        if evidence_type:
            confirm_msg += f"\n- 증빙유형: {evidence_type}"
            if evidence_type in ("세금계산서", "계산서", "계산서내역"):
                if invoice_vendor or invoice_amount or invoice_date:
                    invoice_str = []
                    if invoice_vendor:
                        invoice_str.append(f"거래처: {invoice_vendor}")
                    if invoice_amount:
                        invoice_str.append(f"금액: {int(invoice_amount):,}원")
                    if invoice_date:
                        invoice_str.append(f"발행일: {invoice_date}")
                    confirm_msg += f"\n  (세금계산서 팝업 검색: {', '.join(invoice_str)})"
                else:
                    confirm_msg += "\n  (세금계산서 팝업: 거래처/금액 지정 없으면 목록 첫 번째 선택)"
        if auto_capture_budget:
            confirm_msg += "\n- 예실대비현황 스크린샷 자동 첨부: 예"
        if usage_code and usage_code != "5020":
            confirm_msg += f"\n- 용도코드: {usage_code}"
        if budget_keyword:
            confirm_msg += f"\n- 예산과목: {budget_keyword}"
        if payment_request_date:
            confirm_msg += f"\n- 지급요청일: {payment_request_date}"
        if accounting_date:
            confirm_msg += f"\n- 회계처리일자: {accounting_date}"
        # action에 따라 안내 문구 분기
        if action == "submit":
            confirm_msg += "\n\n다음 내용으로 즉시 결재상신하시겠습니까? 확인하려면 '확인'이라고 해주세요.\n⚠️ 상신 후에는 결재선에서 직접 반려 전까지 수정이 어렵습니다."
        else:
            confirm_msg += "\n\n맞으면 '확인' 또는 '작성해줘'라고 말씀해주세요."
        return confirm_msg

    # 필수 정보 검증 (상신 전 누락 방지)
    missing = []
    if not title:
        missing.append("제목")
    if not description and not items:
        missing.append("지출 내용(항목 또는 설명)")
    if not amount and not any(item.get("amount") for item in items):
        missing.append("금액")

    if missing:
        missing_str = ", ".join(missing)
        hints = []
        if "제목" in missing:
            hints.append("제목: 예) 'GS-25-0088. 메디빌더 음향공사 대금 지급의 건'")
        if "지출 내용" in missing_str:
            hints.append("내용: 예) '음향설비 설치 공사비'")
        if "금액" in missing_str:
            hints.append("금액: 예) '2,750,000원'")
        hint_str = "\n".join(f"  - {h}" for h in hints)
        return (
            f"지출결의서 작성에 필요한 정보가 부족합니다.\n\n"
            f"누락된 항목: **{missing_str}**\n\n"
            f"다음 정보를 알려주세요:\n{hint_str}"
        )

    # 실제 작성 단계
    try:


        def _run_approval():
            from playwright.sync_api import sync_playwright
            from src.auth.login import login_and_get_context, close_session
            from src.auth.user_db import get_decrypted_password
            from src.approval.approval_automation import ApprovalAutomation

            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            gw_pw = get_decrypted_password(gw_id)
            if not gw_pw:
                return {"success": False, "message": "비밀번호를 찾을 수 없습니다. /login으로 다시 로그인해주세요."}

            pw = sync_playwright().start()
            try:
                browser, context, page = login_and_get_context(
                    playwright_instance=pw,
                    headless=True,
                    user_id=gw_id,
                    user_pw=gw_pw,
                )
                page.set_viewport_size({"width": 1920, "height": 1080})

                automation = ApprovalAutomation(page, context)
                # 사용자별 결재선 동적 해석
                from src.approval.form_templates import resolve_approval_line, resolve_cc_recipients
                resolved_line = resolve_approval_line(approval_line, "지출결의서", user_context)
                resolved_cc = resolve_cc_recipients(cc, "지출결의서", user_context)

                expense_data = {
                    "title": title,
                    "date": date,
                    "description": description,
                    "items": items,
                    "total_amount": amount,
                    "project": project,
                }
                expense_data["approval_line"] = resolved_line
                if resolved_cc:
                    expense_data["cc"] = resolved_cc
                if evidence_type:
                    expense_data["evidence_type"] = evidence_type
                if invoice_vendor:
                    expense_data["invoice_vendor"] = invoice_vendor
                if invoice_amount is not None:
                    expense_data["invoice_amount"] = invoice_amount
                if invoice_date:
                    expense_data["invoice_date"] = invoice_date
                if attachment_path:
                    expense_data["attachment_path"] = attachment_path
                if auto_capture_budget:
                    expense_data["auto_capture_budget"] = True
                if usage_code:
                    expense_data["usage_code"] = usage_code
                if budget_keyword:
                    expense_data["budget_keyword"] = budget_keyword
                if payment_request_date:
                    expense_data["payment_request_date"] = payment_request_date
                if accounting_date:
                    expense_data["accounting_date"] = accounting_date
                # action에 따라 save_mode 결정
                if action == "submit":
                    expense_data["save_mode"] = "submit"
                else:
                    expense_data["save_mode"] = "draft"  # 기본값 임시저장
                result = automation.create_expense_report(expense_data)

                close_session(browser)
                return result
            except RuntimeError as e:
                return {"success": False, "message": str(e)}
            except Exception as e:
                return {"success": False, "message": f"브라우저 자동화 오류: {str(e)}"}
            finally:
                try:
                    pw.stop()
                except Exception:
                    pass

        future = _executor.submit(_run_approval)
        result = future.result(timeout=180)

        if result.get("success"):
            # action에 따라 성공 메시지 분기
            if action == "submit":
                msg = f"지출결의서가 결재상신되었습니다!\n\n제목: {title}\n금액: {amount_str}"
            else:
                msg = f"지출결의서가 임시보관되었습니다! (상신 전 상태)\n\n제목: {title}\n금액: {amount_str}"
            # 검증결과 표시
            validation = result.get("validation_result", "")
            if validation:
                msg += f"\n검증결과: {validation}"
            tooltip = result.get("validation_tooltip", "")
            if tooltip:
                msg += f"\n미비사항: {tooltip}"
            if action != "submit":
                msg += "\n\n그룹웨어 임시보관문서에서 확인 후 직접 상신해주세요."
            else:
                msg += "\n\n그룹웨어에서 결재 진행 상황을 확인하세요."
            return msg
        else:
            err_msg = f"지출결의서 작성에 실패했습니다.\n사유: {result.get('message', '알 수 없는 오류')}"
            tooltip = result.get("validation_tooltip", "")
            if tooltip:
                err_msg += f"\n미비사항: {tooltip}"
            return err_msg

    except concurrent.futures.TimeoutError:
        return "지출결의서 작성 시간이 초과되었습니다 (3분). 네트워크 상태를 확인하고 다시 시도해주세요."
    except Exception as e:
        return f"지출결의서 작성 중 오류가 발생했습니다: {str(e)}"


def handle_submit_draft_approval(params: dict, user_context: dict = None) -> str:
    """
    임시보관문서함에서 문서를 열고 결재상신.
    ApprovalAutomation.open_draft_and_submit() 연동.
    """
    doc_title = params.get("doc_title", "")

    try:

        def _run():
            from playwright.sync_api import sync_playwright
            from src.auth.login import login_and_get_context, close_session
            from src.auth.user_db import get_decrypted_password
            from src.approval.approval_automation import ApprovalAutomation

            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            gw_pw = get_decrypted_password(gw_id)
            if not gw_pw:
                return {"success": False, "message": "비밀번호를 찾을 수 없습니다. /login으로 다시 로그인해주세요."}

            pw = sync_playwright().start()
            try:
                browser, context, page = login_and_get_context(
                    playwright_instance=pw,
                    headless=True,
                    user_id=gw_id,
                    user_pw=gw_pw,
                )
                page.set_viewport_size({"width": 1920, "height": 1080})
                automation = ApprovalAutomation(page, context)
                result = automation.open_draft_and_submit(doc_title=doc_title or None)
                close_session(browser)
                return result
            except RuntimeError as e:
                return {"success": False, "message": str(e)}
            except Exception as e:
                return {"success": False, "message": f"브라우저 자동화 오류: {str(e)}"}
            finally:
                try:
                    pw.stop()
                except Exception:
                    pass

        future = _executor.submit(_run)
        result = future.result(timeout=180)

        if result.get("success"):
            doc = result.get("doc_title", doc_title or "")
            return f"결재상신이 완료되었습니다!\n\n문서: {doc}\n\n그룹웨어에서 결재 진행 상황을 확인하세요."
        else:
            return f"결재상신에 실패했습니다.\n사유: {result.get('message', '알 수 없는 오류')}"

    except concurrent.futures.TimeoutError:
        return "결재상신 시간이 초과되었습니다 (3분). 네트워크 상태를 확인하고 다시 시도해주세요."
    except Exception as e:
        return f"결재상신 중 오류가 발생했습니다: {str(e)}"


def handle_submit_approval_form(params: dict, user_context: dict = None) -> str:
    """
    전자결재 양식 작성 처리 (지출결의서 외)
    - form_type: 거래처등록, 연장근무, 외근신청, 선급금요청, 선급금정산, 증빙발행, 사내추천비
    - action='confirm': 확인 메시지 반환
    - action='draft': Playwright로 실제 폼 작성
    """
    from src.approval.form_templates import get_template, get_template_key, get_required_fields

    form_type = params.get("form_type", "")
    title = params.get("title", "")
    fields = params.get("fields", {})
    approval_line = params.get("approval_line")
    cc = params.get("cc")
    attachment_path = params.get("attachment_path", "")
    action = params.get("action", "confirm")

    # 양식 키 확인
    form_key = get_template_key(form_type)
    if not form_key:
        # 미지원 양식 요청 기록
        try:
            from src.chatbot.chat_db import save_unsupported_request
            gw_id = (user_context or {}).get("gw_id", "unknown")
            save_unsupported_request(
                gw_id=gw_id,
                request_type="unsupported_form",
                user_message=title or form_type,
                detail=f"양식: {form_type}",
            )
        except Exception:
            pass
        SUPPORTED_FORMS = "거래처등록, 연장근무, 외근신청, 선급금요청, 선급금정산, 증빙발행, 사내추천비"
        WORKING_FORMS = "거래처등록"  # 실제 E2E 동작 검증된 양식
        return (
            f"'{form_type}'은(는) 현재 지원되지 않는 양식입니다.\n\n"
            f"**지원 양식 목록**: {SUPPORTED_FORMS}\n"
            f"**E2E 완성 양식**: {WORKING_FORMS}\n\n"
            f"지출결의서가 필요하시면 '지출결의서 작성해줘'라고 말씀해주세요."
        )

    template = get_template(form_type)
    display_name = template.get("display_name", form_type)
    status = template.get("status", "template_only")

    if action != "draft":
        # 필수 필드 누락 체크
        required = get_required_fields(form_type)
        filled_labels = set()
        for key, value in fields.items():
            if value:
                field_info = template.get("fields", {}).get(key, {})
                label = field_info.get("label", key) if isinstance(field_info, dict) else key
                filled_labels.add(label)
        if title:
            filled_labels.add("제목")

        missing = [r for r in required if r not in filled_labels]

        # 대화형 질문 플로우: 필수 정보가 빠진 경우 먼저 질문 (한 번에 하나씩)
        if missing:
            known_parts = []
            if title:
                known_parts.append(f"제목: {title}")
            for key, value in fields.items():
                if value:
                    field_info = template.get("fields", {}).get(key, {})
                    label = field_info.get("label", key) if isinstance(field_info, dict) else key
                    known_parts.append(f"{label}: {value}")

            known_str = ""
            if known_parts:
                known_str = "지금까지 파악된 내용:\n" + "\n".join(f"  - {k}" for k in known_parts) + "\n\n"

            first_missing_label = missing[0]
            field_example = ""
            for key, info in template.get("fields", {}).items():
                if isinstance(info, dict) and info.get("label") == first_missing_label:
                    ex = info.get("example", "")
                    fmt = info.get("format", "")
                    if fmt:
                        field_example = f" (형식: {fmt})"
                    if ex:
                        field_example += f" 예) '{ex}'"
                    break

            question = f"{first_missing_label}을(를) 알려주세요.{field_example}"
            remaining = missing[1:]
            if remaining:
                question += f"\n\n(추가로 필요한 정보: {', '.join(remaining)})"

            return f"{known_str}{question}"

        # 필수 정보 모두 있으면 미리보기 표시
        confirm_lines = [f"다음 내용으로 **{display_name}**를 작성합니다:\n"]
        confirm_lines.append(f"- 제목: {title}")

        for key, value in fields.items():
            if value:
                field_info = template.get("fields", {}).get(key, {})
                label = field_info.get("label", key) if isinstance(field_info, dict) else key
                confirm_lines.append(f"- {label}: {value}")

        if status != "verified":
            confirm_lines.append(f"\n이 양식은 아직 자동 작성이 준비 중입니다. (DOM 탐색 미완)")

        confirm_lines.append("\n맞으면 '확인' 또는 '작성해줘'라고 말씀해주세요.")
        return "\n".join(confirm_lines)

    # 실제 작성 단계
    if status != "verified":
        return f"{display_name}은(는) 아직 자동 작성이 준비 중입니다. 수동으로 작성해주세요."

    # 필수 필드 누락 검증 (상신 전 차단)
    required = get_required_fields(form_type)
    filled_labels = set()
    if title:
        filled_labels.add("제목")
    for key, value in fields.items():
        if value:
            field_info = template.get("fields", {}).get(key, {})
            label = field_info.get("label", key) if isinstance(field_info, dict) else key
            filled_labels.add(label)

    missing_required = [r for r in required if r not in filled_labels]
    if missing_required:
        missing_str = ", ".join(missing_required)
        hints = []
        for r in missing_required:
            for key, info in template.get("fields", {}).items():
                if isinstance(info, dict) and info.get("label") == r:
                    example = info.get("example", "")
                    fmt = info.get("format", "")
                    hint = f"  - {r}"
                    if fmt:
                        hint += f" ({fmt})"
                    if example:
                        hint += f" 예) '{example}'"
                    hints.append(hint)
                    break
            else:
                hints.append(f"  - {r}")
        hint_str = "\n".join(hints)
        return (
            f"{display_name} 작성에 필요한 정보가 부족합니다.\n\n"
            f"누락된 필수 항목: **{missing_str}**\n\n"
            f"다음 정보를 알려주세요:\n{hint_str}"
        )

    try:


        def _run_approval():
            from playwright.sync_api import sync_playwright
            from src.auth.login import login_and_get_context, close_session
            from src.auth.user_db import get_decrypted_password
            from src.approval.approval_automation import ApprovalAutomation

            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            gw_pw = get_decrypted_password(gw_id)
            if not gw_pw:
                return {"success": False, "message": "비밀번호를 찾을 수 없습니다. /login으로 다시 로그인해주세요."}

            pw = sync_playwright().start()
            try:
                browser, context, page = login_and_get_context(
                    playwright_instance=pw,
                    headless=True,
                    user_id=gw_id,
                    user_pw=gw_pw,
                )
                page.set_viewport_size({"width": 1920, "height": 1080})

                automation = ApprovalAutomation(page, context)
                # 사용자별 결재선 동적 해석
                from src.approval.form_templates import resolve_approval_line, resolve_cc_recipients
                resolved_line = resolve_approval_line(approval_line, form_key, user_context)
                resolved_cc = resolve_cc_recipients(cc, form_key, user_context)

                data = {"title": title, **fields}
                data["approval_line"] = resolved_line
                if resolved_cc:
                    data["cc"] = resolved_cc
                if attachment_path:
                    data["attachment_path"] = attachment_path
                result = automation.create_form(form_key, data)

                close_session(browser)
                return result
            except RuntimeError as e:
                return {"success": False, "message": str(e)}
            except Exception as e:
                return {"success": False, "message": f"브라우저 자동화 오류: {str(e)}"}
            finally:
                try:
                    pw.stop()
                except Exception:
                    pass

        future = _executor.submit(_run_approval)
        result = future.result(timeout=180)

        if result.get("success"):
            return f"{display_name}가 임시보관되었습니다! (상신 전 상태)\n\n제목: {title}\n\n그룹웨어 임시보관문서에서 확인 후 직접 상신해주세요."
        else:
            return f"{display_name} 작성에 실패했습니다.\n사유: {result.get('message', '알 수 없는 오류')}"

    except concurrent.futures.TimeoutError:
        return f"{display_name} 작성 시간이 초과되었습니다 (3분). 네트워크 상태를 확인하고 다시 시도해주세요."
    except Exception as e:
        return f"{display_name} 작성 중 오류가 발생했습니다: {str(e)}"


def handle_search_project_code(params: dict, user_context: dict = None) -> str:
    """
    GW 프로젝트 코드도움 자동완성 검색.
    Playwright로 지출결의서 폼을 열고 키워드 입력 후 드롭다운 목록 반환.

    Returns:
        결과 목록 또는 안내 메시지 (Gemini가 사용자에게 확인 요청에 사용)
    """
    keyword = params.get("keyword", "").strip()
    if not keyword:
        return "검색 키워드를 입력해주세요."

    try:


        def _run_search():
            from playwright.sync_api import sync_playwright
            from src.auth.login import login_and_get_context, close_session
            from src.auth.user_db import get_decrypted_password
            from src.approval.approval_automation import ApprovalAutomation

            gw_id = (user_context or {}).get("gw_id")
            if not gw_id:
                return {"success": False, "results": [], "message": "로그인 정보가 없습니다. 먼저 /login으로 로그인해주세요."}

            gw_pw = get_decrypted_password(gw_id)
            if not gw_pw:
                return {"success": False, "results": [], "message": "비밀번호를 찾을 수 없습니다."}

            pw = sync_playwright().start()
            try:
                browser, context, page = login_and_get_context(
                    playwright_instance=pw,
                    headless=True,
                    user_id=gw_id,
                    user_pw=gw_pw,
                )
                page.set_viewport_size({"width": 1920, "height": 1080})

                automation = ApprovalAutomation(page, context)
                results = automation.search_project_codes(keyword, max_results=8)

                close_session(browser)
                return {"success": True, "results": results}
            except Exception as e:
                return {"success": False, "results": [], "message": f"검색 오류: {str(e)}"}
            finally:
                try:
                    pw.stop()
                except Exception:
                    pass

        future = _executor.submit(_run_search)
        result = future.result(timeout=60)

        if not result.get("success"):
            return result.get("message", "프로젝트 검색에 실패했습니다.")

        results = result.get("results", [])

        if not results:
            return (
                f"그룹웨어에서 '{keyword}' 프로젝트를 찾지 못했어요.\n"
                f"정확한 프로젝트 코드(예: GS-25-0088)나 이름을 알려주세요."
            )

        if len(results) == 1:
            r = results[0]
            return (
                f"SEARCH_RESULT:SINGLE\n"
                f"프로젝트: {r['full_text']}\n"
                f"---\n"
                f"프로젝트는 '{r['full_text']}'가 맞나요?"
            )

        # 여러 건: 선택지 제시
        lines = [f"'{keyword}'로 검색된 프로젝트가 {len(results)}건 있습니다. 어떤 프로젝트인가요?\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['full_text']}")
        lines.append("\n번호로 선택하거나 전체 코드를 입력해주세요.")
        return "SEARCH_RESULT:MULTIPLE\n" + "\n".join(lines)

    except concurrent.futures.TimeoutError:
        return f"프로젝트 검색 시간이 초과되었습니다 (1분). 직접 프로젝트 코드를 입력해주세요."
    except Exception as e:
        return f"프로젝트 검색 중 오류가 발생했습니다: {str(e)}"


def handle_get_mail_summary(params: dict, user_context: dict = None) -> str:
    """
    안 읽은 메일 요약 처리.
    summarizer.run_for_chatbot() 호출 → 결과 반환.
    """
    try:


        def _run_summary():
            from src.mail.summarizer import run_for_chatbot
            return run_for_chatbot(user_context=user_context)

        future = _executor.submit(_run_summary)
        result = future.result(timeout=120)

        return result
    except concurrent.futures.TimeoutError:
        return "메일 요약 시간이 초과되었습니다 (2분). 네트워크 상태를 확인하고 다시 시도해주세요."
    except Exception as e:
        return f"메일 요약 중 오류가 발생했습니다: {str(e)}"


# 도구 이름 → 핸들러 매핑
TOOL_HANDLERS = {
    "reserve_meeting_room": handle_reserve_meeting_room,
    "check_reservation_status": handle_check_reservation_status,
    "check_available_rooms": handle_check_available_rooms,
    "cancel_meeting_reservation": handle_cancel_meeting_reservation,
    "list_my_reservations": handle_list_my_reservations,
    "cleanup_test_reservations": handle_cleanup_test_reservations,
    "submit_expense_approval": handle_submit_expense_approval,
    "submit_draft_approval": handle_submit_draft_approval,
    "submit_approval_form": handle_submit_approval_form,
    "search_project_code": handle_search_project_code,
    "get_mail_summary": handle_get_mail_summary,
}


def build_message_parts(text: str, files: list[dict]) -> list:
    """
    텍스트 + 첨부파일로 Gemini 메시지 parts 구성.
    파일 이름 힌트를 텍스트로 먼저 추가하여 Gemini가 문서 종류를 더 잘 파악하도록 함.
    """
    parts = []

    # 첨부 파일 처리
    for f in files:
        file_type = f.get("type", "")
        file_data = f.get("data", "")  # base64
        file_name = f.get("name", "file")

        # 파일명 힌트: 문서 종류 파악을 돕는다
        if file_name and file_name != "file":
            parts.append(types.Part.from_text(text=f"[첨부파일: {file_name}]"))

        if file_type.startswith("image/"):
            parts.append(types.Part.from_bytes(
                data=base64.b64decode(file_data),
                mime_type=file_type,
            ))
        elif file_type == "application/pdf":
            parts.append(types.Part.from_bytes(
                data=base64.b64decode(file_data),
                mime_type="application/pdf",
            ))
        # 지원하지 않는 타입은 경고 없이 무시 (텍스트 힌트만 추가됨)

    # 사용자 텍스트 추가
    if text:
        parts.append(types.Part.from_text(text=text))

    return parts if parts else [types.Part.from_text(text=text or "안녕하세요")]


def _convert_history(conversation_history: list[dict]) -> list[types.Content]:
    """대화 히스토리를 Gemini 형식으로 변환"""
    contents = []
    for msg in conversation_history:
        role = "user" if msg["role"] == "user" else "model"
        text = msg["content"] if isinstance(msg["content"], str) else str(msg["content"])
        contents.append(types.Content(
            role=role,
            parts=[types.Part.from_text(text=text)],
        ))
    return contents


async def analyze_and_route(
    user_message: str,
    files: list[dict] = None,
    conversation_history: list[dict] = None,
    user_context: dict = None,
    attachment_path: str = None,
) -> dict:
    """
    사용자 메시지 분석 후 적절한 자동화 모듈 라우팅

    Returns:
        {
            "response": str,
            "action": str | None,
            "action_result": str | None
        }
    """
    if files is None:
        files = []
    if conversation_history is None:
        conversation_history = []

    # 메시지 parts 구성 (파일 포함)
    user_parts = build_message_parts(user_message, files)

    # 대화 히스토리 변환 + 현재 메시지
    contents = _convert_history(conversation_history)
    contents.append(types.Content(role="user", parts=user_parts))

    # 오늘 날짜를 시스템 프롬프트에 삽입
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    system_with_date = SYSTEM_PROMPT.replace("{today}", today)

    # Gemini API 호출 (function calling)
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_with_date,
            tools=AUTOMATION_TOOLS,
            temperature=0.7,
        ),
    )

    # 응답 처리
    result = {
        "response": "",
        "action": None,
        "action_result": None
    }

    # function call 확인
    function_call = None
    text_parts = []

    if response.candidates and response.candidates[0].content:
        for part in (response.candidates[0].content.parts or []):
            if part.function_call:
                function_call = part.function_call
            elif part.text:
                text_parts.append(part.text)

    if function_call:
        # 도구 실행
        tool_name = function_call.name
        tool_input = dict(function_call.args) if function_call.args else {}

        # 첨부파일 경로가 있으면 결재 도구에 주입 (챗봇에서 저장한 임시 파일 경로)
        if attachment_path and tool_name in ("submit_expense_approval", "submit_approval_form"):
            tool_input.setdefault("attachment_path", attachment_path)

        handler = TOOL_HANDLERS.get(tool_name)

        if handler:
            action_result = handler(tool_input, user_context=user_context)
        else:
            action_result = f"'{tool_name}' 모듈이 준비 중입니다."
            # 미지원 툴 요청 기록
            try:
                from src.chatbot.chat_db import save_unsupported_request
                gw_id = (user_context or {}).get("gw_id", "unknown")
                save_unsupported_request(
                    gw_id=gw_id,
                    request_type=tool_name,
                    user_message=user_message,
                    detail="미구현 툴 호출",
                )
            except Exception:
                pass

        result["action"] = tool_name
        result["action_result"] = action_result

        # 도구 결과로 최종 응답 생성
        contents.append(response.candidates[0].content)
        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_function_response(
                name=tool_name,
                response={"result": action_result},
            )],
        ))

        final_response = client.models.generate_content(
            model=MODEL_ID,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_with_date,
                tools=AUTOMATION_TOOLS,
                temperature=0.7,
            ),
        )

        if final_response.candidates and final_response.candidates[0].content:
            final_texts = [
                p.text for p in (final_response.candidates[0].content.parts or []) if p.text
            ]
            result["response"] = "\n".join(final_texts)
        else:
            result["response"] = action_result
    else:
        # 일반 텍스트 응답
        result["response"] = "\n".join(text_parts) if text_parts else "죄송합니다, 응답을 생성하지 못했습니다."

    return result
