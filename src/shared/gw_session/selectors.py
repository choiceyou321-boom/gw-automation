"""
GW 셀렉터 & 페이지 인벤토리 — Track A에서 발견하는 대로 append-only 확장

규칙:
  - 새 페이지/셀렉터는 ADD만 (BREAKING 변경 시 별도 PR)
  - 한 페이지의 셀렉터가 여러 개면 우선순위 리스트로 보관
  - Track A 작업 결과(GW_AUTOMATION_INVENTORY.md)와 동기화

마지막 갱신: 2026-05-25 (v4 P1 신설)
"""

from __future__ import annotations

from src.shared.gw_session.interface import Module, GWPage


# ──────────────────────────────────────────────
# 핵심 셀렉터 (GW 공통)
# ──────────────────────────────────────────────

# 엑셀 다운로드 아이콘 (이미지 src 패턴 기반)
EXCEL_DOWNLOAD = "button:has(img[src*='cel_save'])"
EXCEL_IMG_SRC_PATTERN = "cel_save"

# 홈 화면 모듈 아이콘 (코드 치환 사용)
HOME_MODULE_LINK = "span.module-link.{code}"

# 그리드 컴포넌트 (OBTDataGrid + RealGrid)
OBT_DATA_GRID = "[class*='OBTDataGrid'], [class*='RealGrid']"

# 페이지 타이틀
PAGE_TITLE = "[class*='PageTitle'], [class*='pageTitle'], h1, h2"

# OBT 컴포넌트
OBT_BUTTON = "button[class*='OBTButton']"
OBT_PAGE_BUTTONS = "div[class*='OBTPageContainer_mainButtons']"
OBT_LEFT_MENU = "[class*='OBTLeftMenu'] li"
OBT_ALERT = "[class*='OBTAlert']"

# 좌상단 햄버거(사이드바 펼침)
HAMBURGER_COORDS = (82, 22)

# LNB 영역 X 좌표 범위
LNB_X_RANGE = (60, 280)       # 사이드바 펼친 상태의 LNB 트리
SIDEBAR_X_RANGE = (0, 60)     # 접힌 좁은 사이드바


# ──────────────────────────────────────────────
# 17 모듈 매핑 (홈 코드 ↔ 내부 코드)
# 사이드바 펼친 상태에서 스크롤하면 전체 17개 노출 (2026-05-26 확인)
# ──────────────────────────────────────────────

GW_MODULES: dict[str, Module] = {
    # 핵심 모듈 (자동화 진입 검증됨)
    "SET": Module("SET", "UJ",  "시스템설정"),
    "HR":  Module("HR",  "HP",  "임직원업무관리"),
    "EA":  Module("EA",  "UB",  "전자결재"),
    "ML":  Module("ML",  "UD",  "메일"),
    "CL":  Module("CL",  "UE",  "일정"),
    "RM":  Module("RM",  "UK",  "자원"),
    # 보조 모듈 (사이드바 노출)
    "PER":   Module("PER",   "HM?", "인사관리"),
    "BUDGET":Module("BUDGET","BN",  "예산관리"),
    "BD":  Module("BD",  "UG?", "게시판"),
    "KS":  Module("KS",  "?",   "업무관리"),
    "OF":  Module("OF",  "UO?", "ONEFFICE"),
    "OC":  Module("OC",  "UQ?", "ONECHAMBER"),
    "BPM": Module("BPM", "?",   "프로세스관리"),
    "UT":  Module("UT",  "ext", "오피스케어"),
    # 신규 확인 (2026-05-26 사이드바 스크롤)
    "LOG": Module("LOG", "?",   "물류공통관리"),
    "SAL": Module("SAL", "?",   "영업관리"),
    "PUR": Module("PUR", "?",   "구매/자재관리"),
}


# ──────────────────────────────────────────────
# 페이지 URL 카탈로그 (Track A에서 확장)
# ──────────────────────────────────────────────

GW_PAGES: dict[str, GWPage] = {
    # HR — 근태 / 지출
    "근태신청현황":     GWPage("근태신청현황",     "/#/HP/HPD0122/HRD0220", "HP", has_grid=True),
    "지출결의이체현황":  GWPage("지출결의이체현황",  "/#/HP/APB1020/APB1020", "HP", has_grid=True,
                             note="문서분류·진행상태·이체일 컬럼 보유. 본인 기안 이체 처리 현황."),

    # BN — 예산성
    "실행예산신청":         GWPage("실행예산신청",         "/#/BN/NCB0020/NCB0020", "BN", has_grid=True),
    "실행예산마감":         GWPage("실행예산마감",         "/#/BN/NCB0025/NCB0025", "BN", has_grid=True),
    "예산조정신청":         GWPage("예산조정신청",         "/#/BN/NCB0030/NCB0030", "BN", has_grid=True),
    "예산조정마감":         GWPage("예산조정마감",         "/#/BN/NCB0035/NCB0035", "BN", has_grid=True),
    "예산초기이월등록":      GWPage("예산초기이월등록",      "/#/BN/NCB0040/NCB0040", "BN", has_grid=True),
    "예산마감_이월":        GWPage("예산마감_이월",        "/#/BN/NCB0050/NCB0050", "BN", has_grid=True),

    # BN — 기초정보
    "예산과목등록":         GWPage("예산과목등록",         "/#/BN/NCF0030/NCF0030", "BN", has_grid=True),
    "프로젝트등록":         GWPage("프로젝트등록",         "/#/BN/NCF0090/SYB0060", "BN", has_grid=True,
                                note="총 200건 / GS-YY-XXXX 코드 체계"),
    "프로젝트엑셀업로드":     GWPage("프로젝트엑셀업로드",     "/#/BN/NCF0110/SYX0450", "BN"),

    # BN — 보고서 (조회/Export 1순위)
    "예산일계표":         GWPage("예산일계표",         "/#/BN/NCC0230/NCC0230", "BN", has_grid=True),
    "예산월계표":         GWPage("예산월계표",         "/#/BN/NCC0240/NCC0240", "BN", has_grid=True),
    "세출총괄표":         GWPage("세출총괄표",         "/#/BN/NCC0430/NCC0430", "BN", has_grid=True),
    "세입총괄표":         GWPage("세입총괄표",         "/#/BN/NCC0440/NCC0440", "BN", has_grid=True),
    "예실대비현황":        GWPage("예실대비현황",        "/#/BN/NCC0610/NCC0610", "BN", has_grid=True),
    "예산구성비현황":      GWPage("예산구성비현황",      "/#/BN/NCC0620/NCC0620", "BN", has_grid=True),
    "예실대비현황_상세":    GWPage("예실대비현황_상세",    "/#/BN/NCC0630/NCC0630", "BN", has_grid=True,
                              note="프로젝트별 가로 비교. 자금관리 핵심 export 대상."),
    "예실대비현황_사업별":  GWPage("예실대비현황_사업별",  "/#/BN/NCC0631/NCC0631", "BN", has_grid=True,
                              note="단일 프로젝트의 월별 시계열 전개."),
    "예산과목원장":        GWPage("예산과목원장",        "/#/BN/NCC0640/NCC0640", "BN", has_grid=True),

    # UE/UK/UD — 자원/일정/메일
    "자원예약":         GWPage("자원예약",         "/#/UK/UKA/UKA0000", "UK",
                            has_grid=True, has_export=True,
                            note="검증된 export 페이지 (rm_resource.xlsx)"),
    "일정":            GWPage("일정",            "/#/UE/UEA/UEA0000", "UE",
                            has_grid=True, has_export=True,
                            note="검증된 export 페이지 (162행 일정 데이터)"),
    "메일_환경설정":     GWPage("메일_환경설정",     "/#/UD/UDA/UDA0000", "UD"),
}


# ──────────────────────────────────────────────
# 페이지별 조회 버튼 셀렉터 (Track A 시연으로 점진 확장)
# ──────────────────────────────────────────────

INQUIRY_BUTTONS: dict[str, str] = {
    # 기본 추측 (Track A에서 페이지별 정확한 셀렉터로 교체 필요)
    # "예실대비현황_상세": "button.OBTButton:has-text('조회')",
    # "지출결의이체현황":  "...",
}

# 기본 조회 버튼 후보 (페이지별 매핑이 없을 때 폴백)
DEFAULT_INQUIRY_CANDIDATES = [
    "button:has-text('조회')",
    "button:has-text('검색')",
    "button[class*='OBTButton']:has-text('조회')",
]


# ──────────────────────────────────────────────
# 다운로드 옵션 모달 dismiss 패턴
# ──────────────────────────────────────────────

DOWNLOAD_MODAL_BUTTONS = ["확인", "다운로드", "OK", "저장", "전체"]


# ──────────────────────────────────────────────
# 결재 양식 메타 (formId / formDTp / 진입 경로)
# ──────────────────────────────────────────────

APPROVAL_FORMS: dict[str, dict] = {
    "국내거래처등록": {
        "formId": 196,
        "category": "협업관련",
        "popup": True,
        "editor": "dzEditor",
    },
    "연차휴가신청서": {
        "formId": 36,
        "formDTp": "HP_HPD0110_00011",
        "category": "근태신청",
        "popup": False,
    },
    "외근신청서_당일": {
        "formId": 41,
        "formDTp": "HP_HPD0110_00031",
        "category": "근태신청",
        "popup": False,
    },
    "연장근무신청서": {
        "formId": 43,
        "formDTp": "HP_HPD0110_00051",
        "category": "근태신청",
        "popup": False,
    },
}
