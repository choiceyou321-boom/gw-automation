"""
Gemini Function Calling 도구 스키마 정의
"""

from google.genai import types

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
                    "reference_doc_keyword": types.Schema(type="STRING", description="참조문서 검색어 (예: 선급금 품의서 제목, 문서번호). 지출결의서에 기존 결재문서를 참조문서로 연결할 때 사용. 미지정 시 참조문서 연결 안 함."),
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
                "[TEST_ 또는 [TEST] 접두사 테스트 예약을 일괄 취소합니다. "
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
            name="start_approval_wizard",
            description=(
                "전자결재 작성 마법사를 시작합니다. "
                "사용자가 '전자결재 작성해줘', '결재 올려야 해', '결재 써줘', '결재 신청해줘' 등 "
                "어떤 양식인지 명확히 지정하지 않고 결재 작성을 요청할 때 사용합니다. "
                "지출결의서/거래처등록 등 작성 가능한 양식을 안내하고 단계별 질문으로 정보를 수집합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "initial_hint": types.Schema(
                        type="STRING",
                        description="사용자가 이미 언급한 정보 힌트 (예: '음향공사 결재', '메디빌더 지출'). 없으면 빈 문자열.",
                    ),
                },
                required=[],
            ),
        ),
        types.FunctionDeclaration(
            name="start_contract_wizard",
            description=(
                "계약서 작성 마법사를 시작합니다. "
                "사용자가 '계약서 작성해줘', '계약서 써줘', '협력사 계약서', '하도급 계약서' 등 "
                "계약서 단건 작성을 요청할 때 사용합니다. "
                "자재납품/공사 유형 선택부터 단계별로 정보를 수집합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "hint": types.Schema(
                        type="STRING",
                        description="사용자가 이미 언급한 힌트 (예: '음향공사', '조명 납품'). 없으면 빈 문자열.",
                    ),
                },
                required=[],
            ),
        ),
        types.FunctionDeclaration(
            name="generate_contracts_from_file",
            description=(
                "첨부된 Excel 파일에서 계약서를 일괄 생성합니다. "
                "사용자가 Excel 파일을 첨부하고 '계약서 일괄 생성', '목록으로 계약서 만들어줘' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "file_path": types.Schema(
                        type="STRING",
                        description="첨부된 Excel 파일의 로컬 경로",
                    ),
                },
                required=["file_path"],
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
        types.FunctionDeclaration(
            name="transcribe_audio",
            description=(
                "음성/오디오 파일을 텍스트로 변환(STT)합니다. "
                "사용자가 음성 파일(MP3, WAV, M4A, OGG, FLAC, WebM)을 첨부하거나 "
                "텔레그램 음성 메시지를 보냈을 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "file_path": types.Schema(
                        type="STRING",
                        description="음성 파일의 로컬 경로",
                    ),
                    "language": types.Schema(
                        type="STRING",
                        description="음성 언어 코드 (기본값: 'ko-KR'). 예: 'en-US', 'ja-JP'",
                    ),
                },
                required=["file_path"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_fund_summary",
            description=(
                "프로젝트 자금현황 요약을 조회합니다. "
                "사용자가 '자금현황', '프로젝트 관리', '프로젝트 예산', '수익금', '하도급 현황', "
                "'계약 현황', '지급 현황' 등을 요청할 때 사용합니다. "
                "project_name을 지정하면 해당 프로젝트만, 미지정이면 전체 프로젝트 요약을 보여줍니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project_name": types.Schema(
                        type="STRING",
                        description="프로젝트명 (예: '종로 오블리브'). 미지정이면 전체 프로젝트 요약.",
                    ),
                },
                required=[],
            ),
        ),
        types.FunctionDeclaration(
            name="update_project_info",
            description=(
                "프로젝트 관리 시스템의 프로젝트 정보를 수정합니다. "
                "사용자가 '종로 오블리브 위치 변경해줘', '프로젝트 상태 업데이트', "
                "'시공기간 변경', '이슈 업데이트해줘' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project_name": types.Schema(type="STRING", description="프로젝트명 (부분 일치 가능)"),
                    "field": types.Schema(type="STRING", description="수정할 필드: location, usage, scale, area_pyeong, design_start, design_end, construction_start, construction_end, open_date, current_status, issue_design, issue_schedule, issue_budget, issue_operation, issue_defect, issue_other"),
                    "value": types.Schema(type="STRING", description="새 값"),
                },
                required=["project_name", "field", "value"],
            ),
        ),
        types.FunctionDeclaration(
            name="add_project_note",
            description=(
                "프로젝트에 메모/노트를 추가합니다. "
                "사용자가 '종로 오블리브에 메모 남겨줘', '프로젝트에 기록 추가', "
                "'이 내용 프로젝트에 저장해줘' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project_name": types.Schema(type="STRING", description="프로젝트명"),
                    "title": types.Schema(type="STRING", description="메모 제목"),
                    "content": types.Schema(type="STRING", description="메모 내용"),
                },
                required=["project_name", "content"],
            ),
        ),
        types.FunctionDeclaration(
            name="add_project_subcontract",
            description=(
                "프로젝트에 하도급 업체를 추가합니다. "
                "사용자가 '하도급 업체 추가해줘', '협력사 등록', '음향공사 업체 넣어줘' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project_name": types.Schema(type="STRING", description="프로젝트명"),
                    "company_name": types.Schema(type="STRING", description="업체명"),
                    "trade_name": types.Schema(type="STRING", description="공종명 (예: 음향, 전기, 도장)"),
                    "contract_amount": types.Schema(type="NUMBER", description="계약금액 (원)"),
                },
                required=["project_name", "company_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="update_collection_status",
            description=(
                "프로젝트 수금현황을 업데이트합니다. "
                "사용자가 '수금 완료 처리해줘', '설계 계약금 수금됐어', '시공 중도금 받았어' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project_name": types.Schema(type="STRING", description="프로젝트명"),
                    "stage": types.Schema(type="STRING", description="수금 단계명 (예: '계약금', '중도금1', '잔금')"),
                    "collected": types.Schema(type="BOOLEAN", description="수금 완료 여부 (True/False)"),
                },
                required=["project_name", "stage", "collected"],
            ),
        ),
        types.FunctionDeclaration(
            name="add_project_todo",
            description=(
                "프로젝트에 TODO 할 일을 추가합니다. "
                "사용자가 '할 일 추가해줘', '이거 TODO에 넣어줘', '잊지 말아야 할 것' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project_name": types.Schema(type="STRING", description="프로젝트명 (없으면 전체)"),
                    "content": types.Schema(type="STRING", description="할 일 내용"),
                    "priority": types.Schema(type="STRING", description="우선순위: high, medium, low (기본 medium)"),
                    "category": types.Schema(type="STRING", description="카테고리 (예: 수금, 일정, 계약)"),
                },
                required=["content"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_project_detail",
            description=(
                "프로젝트의 상세 정보를 조회합니다. "
                "사용자가 '프로젝트 상세 보여줘', '종로 오블리브 현황', '프로젝트 정보 확인' 등을 요청할 때 사용합니다. "
                "get_fund_summary보다 더 상세한 정보(개요, 이슈, 마일스톤, TODO, 자료실)를 반환합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project_name": types.Schema(type="STRING", description="프로젝트명"),
                },
                required=["project_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="add_project_contact",
            description=(
                "프로젝트에 거래처 연락처를 추가합니다. "
                "사용자가 '연락처 추가해줘', '업체 전화번호 등록', '거래처 정보 넣어줘' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project_name": types.Schema(type="STRING", description="프로젝트명"),
                    "company_name": types.Schema(type="STRING", description="업체명"),
                    "contact_person": types.Schema(type="STRING", description="담당자명"),
                    "phone": types.Schema(type="STRING", description="연락처"),
                    "email": types.Schema(type="STRING", description="이메일"),
                    "trade_name": types.Schema(type="STRING", description="공종 (예: 음향, 전기)"),
                },
                required=["project_name", "company_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_overdue_items",
            description=(
                "모든 프로젝트의 기한 초과 항목, 미수금, 미완료 TODO를 조회합니다. "
                "사용자가 '지금 뭐가 밀려있어?', '기한 지난 거 확인', '미수금 현황', '밀린 일 확인' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={},
            ),
        ),
        types.FunctionDeclaration(
            name="compare_projects",
            description=(
                "여러 프로젝트의 수금율, 지급율, 이익율 등을 비교 요약합니다. "
                "사용자가 '프로젝트 비교해줘', '어떤 프로젝트가 수금율 높아?', '전체 포트폴리오 현황' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={},
            ),
        ),
        types.FunctionDeclaration(
            name="generate_project_report",
            description=(
                "특정 프로젝트의 종합 보고서를 생성합니다. 수주/수금/지급/이슈/진행상황을 한눈에 정리합니다. "
                "사용자가 '프로젝트 보고서', '현황 보고', '프로젝트 정리해줘', '리포트 만들어줘' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project_name": types.Schema(type="STRING", description="프로젝트명 (일부 이름 가능)"),
                },
                required=["project_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="update_project_milestone",
            description=(
                "프로젝트 진행상황(마일스톤)을 완료 처리하거나 새로 추가합니다. "
                "사용자가 '설계 완료 처리해줘', 'KOM 끝났어', '진행단계 추가해줘' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project_name": types.Schema(type="STRING", description="프로젝트명"),
                    "milestone_name": types.Schema(type="STRING", description="마일스톤 이름 (예: KOM, 설계완료, 착공)"),
                    "action": types.Schema(type="STRING", description="complete (완료처리) 또는 add (신규추가)"),
                    "date": types.Schema(type="STRING", description="날짜 (YYYY-MM-DD, 신규 추가 시 선택)"),
                },
                required=["project_name", "milestone_name", "action"],
            ),
        ),
        types.FunctionDeclaration(
<<<<<<< HEAD
            name="add_cc_to_approval_doc",
            description=(
                "전자결재 기결재 문서에 수신참조(CC)를 추가합니다. "
                "이미 결재가 진행 중이거나 완료된 문서에 수신참조 대상을 추가할 때 사용합니다. "
                "doc_ids(문서 번호)를 알면 바로 사용하고, 모를 경우 doc_title로 문서 제목을 검색해서 처리합니다. "
                "사용자가 '문서에 수신참조 걸어줘', '결재 문서 CC 추가', '수신참조 추가', "
                "'docID XXXX에 홍길동 수신참조', 'GS-24-0025 계약서에 김부장 수신참조' 등을 요청할 때 사용합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "doc_ids": types.Schema(
                        type="ARRAY",
                        description=(
                            "수신참조를 추가할 문서 ID 목록 (예: [55700, 55654]). 단건이면 1개짜리 리스트. "
                            "doc_title 미입력 시 필수."
                        ),
                        items=types.Schema(type="STRING"),
                    ),
                    "doc_title": types.Schema(
                        type="STRING",
                        description=(
                            "문서 제목 키워드로 검색 (예: 'GS-24-0025', '청수당 12월', '경비정산'). "
                            "doc_ids를 모를 때 사용. 입력 시 기안문서함에서 검색하여 매칭 문서에 수신참조 추가."
                        ),
                    ),
                    "cc_name": types.Schema(
                        type="STRING",
                        description="수신참조로 추가할 사람 이름 (예: '임종훈', '이재명'). 한 번에 한 명.",
                    ),
                    "confirm": types.Schema(
                        type="BOOLEAN",
                        description="True이면 즉시 실행. False이거나 생략 시 실행 전 확인 메시지 반환.",
                    ),
                },
                required=["cc_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="analyze_youtube",
            description=(
                "YouTube 영상 또는 재생목록의 내용을 Gemini AI로 분석합니다. "
                "사용자가 '유튜브 요약', '영상 내용 알려줘', '이 영상 설명해줘', "
                "'재생목록 분석', '자막 보여줘' 등을 요청할 때 사용합니다. "
                "yt-dlp로 자막과 메타데이터를 추출하고 Gemini가 요약/분석합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "url": types.Schema(
                        type="STRING",
                        description="YouTube 영상 URL 또는 재생목록 URL"
                    ),
                    "mode": types.Schema(
                        type="STRING",
                        description=(
                            "'summary' (기본값, 핵심 요약) | "
                            "'transcript' (자막 전문 추출) | "
                            "'playlist' (재생목록 일괄 분석)"
                        )
                    ),
                    "instruction": types.Schema(
                        type="STRING",
                        description="분석 지시사항. 예: '핵심 포인트 5가지만', '실업에 바로 쓸 수 있는 구체적인 방법 중심'"
                    ),
                    "limit": types.Schema(
                        type="INTEGER",
                        description="재생목록 모드에서 최대 분석할 영상 수 (기본값 5, 최대 20)"
                    ),
                    "analyze_each": types.Schema(
                        type="BOOLEAN",
                        description="재생목록에서 각 영상을 개별 상세 분석할지 (True이면 느림, False이면 빠름)"
                    ),
                },
                required=["url"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_project_schedule",
            description=(
                "프로젝트의 공정 일정표를 조회합니다. "
                "사용자가 '일정표', '공정 일정', '진행 상황', '언제 끋나', '스케줄' "
                "등을 특정 프로젝트와 함께 요청할 때 사용합니다. "
                "그룹별 일정 항목, 진행상태(완료/진행중/예정/지연), D-day 등을 포함합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "project_name": types.Schema(
                        type="STRING",
                        description="일정표를 볼 프로젝트 이름 (일부만 입력해도 검색 가능)"
                    ),
                },
                required=["project_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_my_schedule",
            description=(
                "개인 일정을 조회합니다. "
                "사용자가 '내 일정', '일정 확인', '일정 보여줘', '오늘 일정', '이번주 일정' "
                "등을 요청할 때 사용합니다. "
                "GW 개인 캘린더에 등록된 일정을 날짜별로 정리해서 보여줍니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "days": types.Schema(
                        type="INTEGER",
                        description="조회할 일수 (기본값 7, 최대 30). 예: '7일치' 또는 '이번 주' = 7"
                    ),
                    "start_date": types.Schema(
                        type="STRING",
                        description="조회 시작일 (YYYY-MM-DD, 기본값 오늘). 예: '다음 주' 조회 시 '다음 주 월요일' 날짜"
                    ),
                },
                required=[],
            ),
        ),
        types.FunctionDeclaration(
            name="request_annual_leave",
            description="연차, 반차, 대체휴가 등 휴가 신청을 합니다.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "leave_type": types.Schema(
                        type="STRING",
                        description="휴가 종류",
                        enum=["연차", "반차(오전)", "반차(오후)", "대체휴가", "대휴반차(오전)", "대휴반차(오후)", "공가(예비군/민방위)", "반반차", "대휴반반차", "건강검진(반차)"],
                    ),
                    "leave_start": types.Schema(type="STRING", description="휴가 시작일 (YYYY-MM-DD)"),
                    "leave_end": types.Schema(type="STRING", description="휴가 종료일 (YYYY-MM-DD)"),
                    "save_mode": types.Schema(type="STRING", enum=["submit", "verify"]),
                },
                required=["leave_start"],
            ),
        ),
        types.FunctionDeclaration(
            name="request_overtime",
            description="연장근무, 야근, 조기근무, 휴일근무 신청을 합니다.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "work_type": types.Schema(type="STRING", enum=["연장근무", "조기근무", "휴일근무"]),
                    "work_date": types.Schema(type="STRING", description="근무 날짜 (YYYY-MM-DD)"),
                    "start_time": types.Schema(type="STRING", description="시작 시간 (HH:MM)"),
                    "end_time": types.Schema(type="STRING", description="종료 시간 (HH:MM)"),
                    "hours": types.Schema(type="INTEGER", description="신청 시간 (시간)"),
                    "minutes": types.Schema(type="INTEGER", description="신청 시간 (분)"),
                    "reason": types.Schema(type="STRING", description="사유"),
                    "save_mode": types.Schema(type="STRING", enum=["submit", "verify"]),
                },
                required=["work_date", "reason"],
            ),
        ),
        types.FunctionDeclaration(
            name="request_outside_work",
            description="외근 신청을 합니다.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "work_type": types.Schema(type="STRING", enum=["종일외근", "외근후출근", "출근후외근"]),
                    "work_date": types.Schema(type="STRING", description="외근 날짜 (YYYY-MM-DD)"),
                    "destination": types.Schema(type="STRING", description="방문처"),
                    "purpose": types.Schema(type="STRING", description="업무내용/외근 사유"),
                    "transportation": types.Schema(type="STRING", description="교통수단"),
                    "save_mode": types.Schema(type="STRING", enum=["submit", "verify"]),
                },
                required=["work_date", "destination", "purpose"],
            ),
        ),
    ])
]
