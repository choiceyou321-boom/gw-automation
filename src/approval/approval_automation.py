"""
전자결재 자동 작성 모듈 (Playwright 기반)
- 지출결의서 양식 자동 채우기
- 결재상신 지원
- 에러 핸들링: 재시도, 타임아웃, 세션 만료 대응

Phase 0 DOM 탐색 결과 반영 (2026-03-01):
- 네비게이션: span.module-link.EA → 추천양식 "[프로젝트]지출결의서" 직접 클릭
- URL 패턴: /#/HP/APB1020/APB1020?...formDTp=APB1020_00001&formId=255
- 양식 테이블: table.OBTFormPanel_table__1fRyk
- 필드 접근: th 라벨 → 형제 td 내 input (placeholder 기반)
- 액션 버튼: "결재상신" / "상신" (div.topBtn)

이 파일은 mixin 조합 클래스입니다. 실제 구현은 각 mixin 모듈을 참조하세요:
- base.py: 공통 유틸, 네비게이션, 필드 입력, 저장
- approval_line.py: 결재선/수신참조 설정 (신규 문서용)
- cc_manager.py: 기결재 문서 수신참조 추가/수정 (2026-03-26 추가)
- expense.py: 지출결의서 작성
- grid.py: OBTDataGrid 그리드 조작
- vendor.py: 거래처등록
- draft.py: 임시보관 문서 상신
- other_forms.py: 기타 양식 (선급금, 연장근무, 외근 등)
- attendance.py: 근태신청 (연차/외근/연장근무)
"""

from playwright.sync_api import Page, BrowserContext

from src.approval.base import (
    ApprovalBaseMixin,
    GW_URL, MAX_RETRIES, RETRY_DELAY, SCREENSHOT_DIR,
    _GET_GRID_IFACE_JS, _save_debug, _parse_project_text,
)
from src.approval.approval_line import ApprovalLineMixin
from src.approval.cc_manager import CcManagerMixin
from src.approval.expense import ExpenseReportMixin
from src.approval.grid import GridMixin
from src.approval.vendor import VendorRegistrationMixin
from src.approval.draft import DraftSubmissionMixin
from src.approval.other_forms import OtherFormsMixin

try:
    from src.approval.attendance import AttendanceMixin
except ImportError:
    import warnings
    warnings.warn("attendance.py를 찾을 수 없습니다. AttendanceMixin 없이 동작합니다.", ImportWarning)
    AttendanceMixin = object


class ApprovalAutomation(
    ApprovalBaseMixin,
    ApprovalLineMixin,
    CcManagerMixin,
    ExpenseReportMixin,
    GridMixin,
    VendorRegistrationMixin,
    DraftSubmissionMixin,
    OtherFormsMixin,
    AttendanceMixin,
):
    """전자결재 폼 자동화 클래스 (mixin 조합)"""

    def __init__(self, page: Page, context: BrowserContext = None):
        self.page = page
        self.context = context
        # 다이얼로그 자동 수락 (한 번만 등록)
        page.on("dialog", lambda d: d.accept())
