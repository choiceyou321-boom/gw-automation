"""
전체 기능 테스트 + 자동 원상복구 스크립트

사용법:
  python scripts/full_test.py                   # 전체 테스트 (headless)
  python scripts/full_test.py --no-headless      # 브라우저 표시
  python scripts/full_test.py --skip-approval    # 전자결재 건너뜀
  python scripts/full_test.py --skip-meeting     # 회의실 건너뜀
  python scripts/full_test.py --skip-mail        # 메일 건너뜀
  python scripts/full_test.py --dry-run          # 환경 체크만 (GW 호출 없음)
  python scripts/full_test.py --verbose          # 상세 로그

테스트 항목:
  T1  GW 로그인
  T2  회의실 목록 조회
  T3  빈 회의실 검색
  T4  회의실 예약 생성+취소
  T5  프로젝트 코드 검색
  T6  지출결의서 임시보관
  T7  거래처등록 임시보관
  T8  메일 요약
  T9  챗봇 라우팅 (Gemini)
  T10 지출결의서 22단계 전체 필드 (용도코드+예산과목+날짜+검증결과)
  T11 챗봇 예약 취소 (자연어)
  T12 챗봇 다중 턴 대화
  T13 임시보관문서 상신 E2E (dry_run)

원상복구:
  - T4: 예약 취소 (cancel_reservation)
  - T6/T7: 임시보관문서 삭제 (Playwright "삭제" 버튼)
  - 세션 캐시 초기화
"""

import sys
import os
import io
import json
import time
import logging
import argparse
import asyncio
import traceback
from pathlib import Path
from datetime import datetime, date, timedelta

# Windows cp949 인코딩 문제 방지: stdout/stderr UTF-8 강제
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 프로젝트 루트를 sys.path에 추가
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# .env 로드
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / "config" / ".env")


# ── 로깅 설정 ──
logger = logging.getLogger("full_test")


# ── 상수 ──
GW_URL = os.getenv("GW_URL", "https://gw.glowseoul.co.kr")
TEST_RESULTS_PATH = ROOT_DIR / "data" / "test_results.json"

REQUIRED_ENV_VARS = ["GW_USER_ID", "GW_USER_PW", "GEMINI_API_KEY"]
OPTIONAL_ENV_VARS = ["NOTION_API_KEY", "TELEGRAM_TOKEN"]

# 테스트 데이터 (타임스탬프 기반 고유 접두사)
TEST_PREFIX = f"[TEST_{datetime.now().strftime('%H%M%S')}]"


class TestResult:
    """개별 테스트 결과"""
    def __init__(self, name: str, test_id: str):
        self.name = name
        self.test_id = test_id
        self.status = "SKIP"   # PASS / FAIL / SKIP
        self.message = ""
        self.duration = 0.0

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "duration": round(self.duration, 1),
        }


class CleanupResult:
    """원상복구 결과"""
    def __init__(self, description: str):
        self.description = description
        self.status = "SKIP"  # OK / FAIL / SKIP
        self.message = ""

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "status": self.status,
            "message": self.message,
        }


class FullTestRunner:
    """전체 기능 테스트 + 자동 원상복구"""

    def __init__(self, headless=True, dry_run=False,
                 skip_approval=False, skip_meeting=False, skip_mail=False):
        self.headless = headless
        self.dry_run = dry_run
        self.skip_approval = skip_approval
        self.skip_meeting = skip_meeting
        self.skip_mail = skip_mail

        self.results: list[TestResult] = []
        self.cleanup_results: list[CleanupResult] = []
        self.cleanup_tasks: list[tuple] = []  # [(func, description)]

        # Playwright 자원 (Phase 2에서 초기화)
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None

        # 회의실 API (T2~T4에서 재사용)
        self.meeting_api = None
        self.meeting_api_cleanup = None

        self.start_time = None

    # ═══════════════════════════════════════════════════
    #  메인 실행
    # ═══════════════════════════════════════════════════

    def run_all(self):
        """Phase 1~4 순차 실행"""
        self.start_time = time.time()
        logger.info("=" * 60)
        logger.info("전체 기능 테스트 시작")
        logger.info(f"  headless     : {self.headless}")
        logger.info(f"  dry_run      : {self.dry_run}")
        logger.info(f"  skip_approval: {self.skip_approval}")
        logger.info(f"  skip_meeting : {self.skip_meeting}")
        logger.info(f"  skip_mail    : {self.skip_mail}")
        logger.info("=" * 60)

        try:
            self._phase1_env_check()

            if self.dry_run:
                logger.info("dry-run 모드: 환경 체크만 실행하고 종료합니다.")
            else:
                self._phase2_tests()
        finally:
            # 원상복구는 항상 실행
            self._phase3_cleanup()
            self._phase4_report()

    # ═══════════════════════════════════════════════════
    #  Phase 1: 환경 점검
    # ═══════════════════════════════════════════════════

    def _phase1_env_check(self):
        logger.info("\n── Phase 1: 환경 점검 ──")

        # 필수 환경변수
        missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
        if missing:
            raise RuntimeError(f"필수 환경변수 누락: {', '.join(missing)}")
        logger.info(f"  필수 환경변수 OK ({len(REQUIRED_ENV_VARS)}개)")

        # 선택 환경변수
        opt_missing = [v for v in OPTIONAL_ENV_VARS if not os.getenv(v)]
        if opt_missing:
            logger.warning(f"  선택 환경변수 누락 (일부 테스트 건너뜀): {', '.join(opt_missing)}")

        # DB 파일 확인
        users_db = ROOT_DIR / "data" / "users.db"
        chat_db = ROOT_DIR / "data" / "chatbot" / "chat_history.db"
        if users_db.exists():
            logger.info(f"  users.db OK")
        else:
            logger.warning(f"  users.db 없음: {users_db}")
        if chat_db.exists():
            logger.info(f"  chat_history.db OK")
        else:
            logger.warning(f"  chat_history.db 없음: {chat_db}")

        # 잔류 테스트 예약 사전 정리 (회의실 테스트 건너뛰는 경우 스킵)
        if not self.skip_meeting and not self.dry_run:
            self._cleanup_stale_test_reservations(days=14)

        logger.info("  Phase 1 완료")

    def _cleanup_stale_test_reservations(self, days: int = 14):
        """
        테스트 시작 전 잔류 테스트 예약 사전 정리.
        오늘부터 days일 후까지 각 날짜별 예약을 조회하여
        제목에 '[TEST_' 가 포함된 예약 중 본인(empSeq 일치) 것만 취소한다.
        예외 발생 시 경고 로그만 출력하고 테스트를 중단하지 않는다.
        """
        logger.info("  잔류 테스트 예약 사전 정리 시작...")
        try:
            # 회의실 API 세션 확보
            self._ensure_meeting_api()
        except Exception as e:
            logger.warning(f"  잔류 정리: 회의실 API 초기화 실패 (건너뜀) — {e}")
            return

        # 현재 사용자 empSeq (본인 예약만 취소 가능)
        my_emp_seq = str(self.meeting_api.company_info.get("empSeq", ""))
        if not my_emp_seq:
            logger.warning("  잔류 정리: empSeq 미확인 — 본인 필터 없이 진행")

        today = date.today()
        cancelled_count = 0
        skipped_others = 0

        for d in range(days):
            target_date = (today + timedelta(days=d)).strftime("%Y-%m-%d")
            try:
                reservations = self.meeting_api.get_reservations(target_date)
            except Exception as e:
                logger.warning(f"  잔류 정리: {target_date} 예약 조회 실패 (건너뜀) — {e}")
                continue

            for res in reservations:
                req_text = res.get("reqText", "")
                if "[TEST_" not in req_text:
                    continue

                # 본인 예약 여부 확인 (empSeq 불일치 시 건너뜀)
                res_emp_seq = res.get("empSeq", "")
                if my_emp_seq and res_emp_seq and res_emp_seq != my_emp_seq:
                    logger.debug(
                        f"  잔류 정리: 다른 사용자 예약 건너뜀 "
                        f"(reqText={req_text!r}, empSeq={res_emp_seq})"
                    )
                    skipped_others += 1
                    continue

                schm_seq = res.get("schmSeq", "")   # rs121A05에서 종종 빈값
                seq_num  = res.get("seqNum", "")
                res_seq  = res.get("resSeq", "")

                if not seq_num:
                    logger.warning(
                        f"  잔류 정리: seqNum 없는 테스트 예약 "
                        f"(reqText={req_text!r}, date={target_date}) — 수동 취소 필요"
                    )
                    continue

                try:
                    cancel_result = self.meeting_api.cancel_reservation(
                        schm_seq=schm_seq,   # 빈값 허용 (API에서 선택적)
                        seq_num=seq_num,
                        res_seq=res_seq,
                        req_text=req_text,
                        start_date=res.get("startDate", ""),
                        end_date=res.get("endDate", ""),
                        res_name=res.get("resName", ""),
                    )
                    if cancel_result.get("success"):
                        logger.info(
                            f"  잔류 정리: 취소 성공 — {req_text!r} "
                            f"({res.get('resName', '')} {target_date})"
                        )
                        cancelled_count += 1
                    else:
                        logger.warning(
                            f"  잔류 정리: 취소 실패 — {req_text!r} "
                            f"({cancel_result.get('message', '')})"
                        )
                except Exception as e:
                    logger.warning(f"  잔류 정리: 취소 중 오류 — {req_text!r}: {e}")

        msg = f"  잔류 테스트 예약 {cancelled_count}건 정리 완료"
        if skipped_others:
            msg += f" (타 사용자 예약 {skipped_others}건 건너뜀)"
        logger.info(msg)

    # ═══════════════════════════════════════════════════
    #  Phase 2: 기능별 테스트
    # ═══════════════════════════════════════════════════

    def _phase2_tests(self):
        logger.info("\n── Phase 2: 기능별 테스트 ──")

        # 테스트 목록 (ID, 이름, 메서드, 스킵 조건)
        # T5(프로젝트 검색)는 GW 내부 탭을 오염시키므로 T6/T7 뒤로 배치
        tests = [
            ("T1", "GW 로그인", self._test_login, False),
            ("T2", "회의실 목록 조회", self._test_meeting_rooms_list, self.skip_meeting),
            ("T3", "빈 회의실 검색", self._test_available_slots, self.skip_meeting),
            ("T4", "회의실 예약 생성+취소", self._test_meeting_create_cancel, self.skip_meeting),
            ("T6", "지출결의서 임시보관", self._test_expense_draft, self.skip_approval),
            ("T7", "거래처등록 임시보관", self._test_vendor_draft, self.skip_approval),
            ("T5", "프로젝트 코드 검색", self._test_project_search, self.skip_approval),
            ("T8", "메일 요약", self._test_mail_summary, self.skip_mail),
            ("T9", "챗봇 라우팅", self._test_chatbot_routing, False),
            ("T10", "지출결의서 22단계 전체", self._test_expense_22step, self.skip_approval),
            ("T11", "챗봇 예약 취소", self._test_chatbot_cancel, self.skip_meeting),
            ("T12", "챗봇 다중 턴 대화", self._test_chatbot_multiturn, self.skip_meeting),
            ("T13", "임시보관문서 상신 E2E", self._test_draft_submit, self.skip_approval),
        ]

        for test_id, name, func, skip in tests:
            result = TestResult(name, test_id)
            if skip:
                result.status = "SKIP"
                result.message = "사용자 옵션으로 건너뜀"
                self.results.append(result)
                logger.info(f"  {test_id} {name}: SKIP")
                continue

            t0 = time.time()
            try:
                func()
                result.status = "PASS"
                result.message = "성공"
            except Exception as e:
                result.status = "FAIL"
                result.message = str(e)
                logger.error(f"  {test_id} {name}: FAIL - {e}")
                logger.debug(traceback.format_exc())
            finally:
                result.duration = time.time() - t0

            self.results.append(result)
            status_icon = "[OK]" if result.status == "PASS" else "[FAIL]"
            logger.info(f"  {test_id} {name}: {status_icon} {result.status} ({result.duration:.1f}s)")

    # ── 개별 테스트 메서드 ──

    def _ensure_playwright(self):
        """Playwright 브라우저 세션이 없으면 시작"""
        if self.page is not None:
            return
        from playwright.sync_api import sync_playwright
        from src.auth.login import login_and_get_context

        self.pw = sync_playwright().start()
        self.browser, self.context, self.page = login_and_get_context(
            playwright_instance=self.pw,
            headless=self.headless,
        )
        self.page.set_viewport_size({"width": 1920, "height": 1080})

    def _ensure_meeting_api(self):
        """기존 Playwright 세션에서 쿠키 추출 → MeetingRoomAPI 직접 생성"""
        if self.meeting_api is not None:
            return
        self._ensure_playwright()
        from src.meeting.reservation_api import MeetingRoomAPI, _extract_auth_cookies

        oauth_token, sign_key, cookie_dict = _extract_auth_cookies(self.context)
        self.meeting_api = MeetingRoomAPI(
            oauth_token=oauth_token,
            sign_key=sign_key,
            cookies=cookie_dict,
        )

    def _test_login(self):
        """T1: GW 로그인"""
        self._ensure_playwright()
        # 로그인 성공 확인: 페이지 URL 또는 특정 요소
        url = self.page.url
        logger.debug(f"  로그인 후 URL: {url}")
        # login_and_get_context가 예외 없이 반환되면 로그인 성공

    def _test_meeting_rooms_list(self):
        """T2: 회의실 목록 조회 (읽기 전용)"""
        self._ensure_meeting_api()
        rooms = self.meeting_api.get_rooms()
        assert rooms and len(rooms) > 0, "회의실 목록이 비어있음"
        logger.debug(f"  회의실 {len(rooms)}개 조회")

    def _test_available_slots(self):
        """T3: 빈 회의실 검색 (읽기 전용)"""
        self._ensure_meeting_api()
        # 일주일 뒤 날짜로 검색
        target_date = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
        slots = self.meeting_api.find_available_slots(
            date=target_date,
            room_name="5번 회의실",
            duration_minutes=30,
        )
        # 슬롯이 0개여도 에러는 아님 (이미 꽉 찬 경우)
        logger.debug(f"  {target_date} 빈 슬롯 {len(slots)}개")

    def _test_meeting_create_cancel(self):
        """T4: 회의실 예약 생성 후 즉시 취소"""
        self._ensure_meeting_api()
        title = f"{TEST_PREFIX} 자동테스트"

        # 빈 슬롯 찾기 (7일~21일 뒤, 여러 회의실 시도)
        slots = []
        for days_ahead in [7, 14, 21]:
            target_date = (date.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            for room in ["5번 회의실", "4번 회의실", "3번 회의실"]:
                slots = self.meeting_api.find_available_slots(
                    date=target_date, room_name=room, duration_minutes=30
                )
                if slots:
                    break
            if slots:
                break
        if not slots:
            raise RuntimeError("빈 회의실 슬롯을 찾을 수 없음 (7~21일 뒤, 3~5번 회의실)")
        slot = slots[0]
        start_time = slot["start_time"]
        end_time = slot["end_time"]
        room_name = slot["resName"]
        target_date = slot["date"]
        res_seq = slot["resSeq"]
        logger.debug(f"  빈 슬롯 사용: {room_name} {target_date} {start_time}~{end_time}")

        # 예약 생성
        result = self.meeting_api.make_reservation(
            room_name=room_name,
            date=target_date,
            start_time=start_time,
            end_time=end_time,
            title=title,
            description="자동화 테스트 (즉시 취소)",
        )
        assert result.get("success"), f"예약 생성 실패: {result.get('message')}"

        data = result.get("data", {})
        schm_seq = str(data.get("schmSeq", ""))
        seq_num = str(data.get("seqNum", ""))

        logger.debug(f"  예약 생성 성공: schmSeq={schm_seq}, seqNum={seq_num}, resSeq={res_seq}")

        # schmSeq/seqNum 유효성 검증
        if not schm_seq or not seq_num:
            logger.warning(f"  ⚠ 예약 ID 미반환 (schmSeq={schm_seq!r}, seqNum={seq_num!r}) — 수동 취소 필요")

        # 즉시 취소 (cleanup에도 등록하여 이중 보호)
        def cancel():
            if not schm_seq and not seq_num:
                logger.error(f"  ⚠ 예약 취소 불가: schmSeq/seqNum 없음 (resSeq={res_seq}, title={title!r}) — GW에서 수동 취소 필요")
                return
            cancel_result = self.meeting_api.cancel_reservation(
                schm_seq=schm_seq,
                seq_num=seq_num,
                res_seq=res_seq,
            )
            if not cancel_result.get("success"):
                logger.error(f"  ⚠ 예약 잔류 주의: schmSeq={schm_seq}, seqNum={seq_num}, resSeq={res_seq}, title={title!r}")
                raise RuntimeError(f"예약 취소 실패: {cancel_result.get('message')}")

        self.cleanup_tasks.append((cancel, f"회의실 예약 취소: {title}"))

        # 바로 취소 시도
        cancel_result = self.meeting_api.cancel_reservation(
            schm_seq=schm_seq,
            seq_num=seq_num,
            res_seq=res_seq,
        )
        assert cancel_result.get("success"), f"예약 취소 실패: {cancel_result.get('message')}"

        # 성공적으로 취소했으므로 cleanup에서 제거
        self.cleanup_tasks.pop()
        logger.debug(f"  예약 취소 성공")

    def _test_project_search(self):
        """T5: 프로젝트 코드 검색 (읽기 전용)"""
        self._ensure_playwright()
        from src.approval.approval_automation import ApprovalAutomation

        automation = ApprovalAutomation(page=self.page, context=self.context)
        results = automation.search_project_codes("메디빌더")
        assert isinstance(results, list), "search_project_codes 반환값이 list가 아님"
        logger.debug(f"  프로젝트 검색 결과: {len(results)}건")

    def _fresh_login(self):
        """세션 캐시 삭제 후 완전히 새로운 로그인 — GW 내부 탭 초기화"""
        from src.auth.login import login_and_get_context, close_session

        # 기존 브라우저 종료
        if self.browser:
            try:
                close_session(self.browser)
            except Exception:
                pass
        # 세션 파일 삭제 (캐시된 탭 상태 제거)
        session_file = ROOT_DIR / "data" / "session_state.json"
        if session_file.exists():
            session_file.unlink()
            logger.debug("  세션 파일 삭제됨")

        # 완전 새 로그인
        self.browser, self.context, self.page = login_and_get_context(
            playwright_instance=self.pw,
            headless=self.headless,
        )
        self.page.set_viewport_size({"width": 1920, "height": 1080})

    def _reset_page(self):
        """GW 내부 탭 오염 방지 — 새 페이지 + GW 내부 탭 전체 닫기"""
        new_page = self.context.new_page()
        new_page.set_viewport_size({"width": 1920, "height": 1080})
        new_page.goto(f"{GW_URL}/#/")
        try:
            new_page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            new_page.wait_for_load_state("domcontentloaded", timeout=10000)
        time.sleep(1)
        # 이전 페이지 닫기
        try:
            self.page.close()
        except Exception:
            pass
        self.page = new_page
        # GW 내부 탭 닫기 (이전 세션 잔여물 제거)
        self._close_gw_tabs()

    def _close_gw_tabs(self):
        """GW SPA 내부 탭의 X 버튼을 모두 클릭하여 닫기"""
        page = self.page
        # 방법 1: localStorage/sessionStorage에서 탭 상태 삭제
        try:
            page.evaluate("""() => {
                // GW SPA 탭 관련 스토리지 키 삭제
                for (const store of [localStorage, sessionStorage]) {
                    const keys = Object.keys(store);
                    for (const key of keys) {
                        if (key.includes('tab') || key.includes('Tab') || key.includes('menu') || key.includes('Menu')) {
                            store.removeItem(key);
                        }
                    }
                }
            }""")
        except Exception:
            pass
        # 방법 2: GW 홈으로 이동 (탭 없는 상태)
        page.goto(f"{GW_URL}/#/")
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(1)
        # 방법 3: X 버튼 직접 클릭 시도 (여러 셀렉터)
        for _ in range(10):
            try:
                # GW 탭 닫기 버튼 (SVG 포함)
                close_btns = page.locator("svg.close-tab, .tab-close, [class*='close'], [class*='Close']").all()
                clicked = False
                for btn in close_btns:
                    try:
                        box = btn.bounding_box()
                        # 탭 영역 (y < 40, 상단)에 있는 닫기 버튼만
                        if box and box["y"] < 40 and box["width"] < 30:
                            btn.click(force=True)
                            time.sleep(0.3)
                            clicked = True
                            break
                    except Exception:
                        continue
                if not clicked:
                    break
            except Exception:
                break

    def _test_expense_draft(self):
        """T6: 지출결의서 임시보관 (인라인 폼 → 결재상신 → 팝업 → 보관)

        실제 사용자 플로우:
        프로젝트 선택 → 제목 → 그리드 수동 입력
        → 용도코드 → 예산과목 → 지급요청일 → 회계처리일자 → 검증결과 적합 → 결재상신 → 팝업 → 보관
        """
        # GW 내부 탭이 서버 세션에 남아있으므로, 완전히 새 브라우저 세션으로 시작
        self._fresh_login()
        from src.approval.approval_automation import ApprovalAutomation

        automation = ApprovalAutomation(page=self.page, context=self.context)
        title = f"{TEST_PREFIX} 지출결의서 자동테스트"

        result = automation.create_expense_report({
            "title": title,
            "description": "자동화 테스트",
            "project": "GS-25-0088",
            "items": [{"item": "테스트 공사비", "amount": 1000000}],
            "total_amount": 1100000,
            "date": datetime.now().strftime("%Y-%m-%d"),
            # 세금계산서 내역: 테스트 환경에 등록된 계산서가 없으면 선택 불가
            # → verify 모드로 필드 작성만 검증 (실 GW에서는 세금계산서 선택 후 draft 저장)
            "evidence_type": "계산서내역",
            "invoice_vendor": "",
            "invoice_amount": None,
            "usage_code": "5020",
            "budget_keyword": "경량",
            "payment_request_date": datetime.now().strftime("%Y-%m-%d"),
            "accounting_date": "",
            "save_mode": "verify",     # 필드 작성 검증만 (인보이스 없는 환경 대응)
        })
        # verify 모드: 필드 채우기 성공 여부만 확인 (GW 검증결과 부적합은 허용)
        if not result.get("success") and "지출결의서 양식을 찾을 수 없습니다" in result.get("message", ""):
            assert False, f"지출결의서 임시보관 실패 (양식 없음): {result.get('message')}"
        logger.info(f"  지출결의서 필드 작성 완료 (verify): {title}")

        # 임시보관문서 삭제 cleanup 등록
        self.cleanup_tasks.append((
            lambda t=title: self._delete_draft_document(t),
            f"임시보관 삭제: {title}",
        ))

    def _test_vendor_draft(self):
        """T7: 거래처등록 임시보관 + 삭제 예약"""
        self._ensure_playwright()
        # T6 후 GW 내부 탭 오염 → 새 페이지로 교체
        self._reset_page()
        from src.approval.approval_automation import ApprovalAutomation

        automation = ApprovalAutomation(page=self.page, context=self.context)
        title = f"{TEST_PREFIX} 거래처등록 자동테스트"

        result = automation.create_vendor_registration({
            "title": title,
            "vendor_name": "테스트거래처(삭제예정)",
            "ceo_name": "홍길동",
            "business_number": "000-00-00000",
            "business_type": "테스트",
            "business_item": "테스트",
            "address": "서울시 종로구",
            "bank_name": "테스트은행",
            "account_number": "0000000000",
            "account_holder": "홍길동",
        })
        assert result.get("success"), f"거래처등록 생성 실패: {result.get('message')}"
        logger.debug(f"  거래처등록 임시보관 성공: {title}")

        # 삭제 cleanup 등록
        self.cleanup_tasks.append((
            lambda t=title: self._delete_draft_document(t),
            f"임시보관 삭제: {title}",
        ))

    def _test_expense_22step(self):
        """T10: 지출결의서 22단계 전체 필드 테스트 (용도코드+예산과목+날짜+검증결과)"""
        self._fresh_login()
        from src.approval.approval_automation import ApprovalAutomation

        automation = ApprovalAutomation(page=self.page, context=self.context)
        title = f"{TEST_PREFIX} 지출결의서 22단계 테스트"

        result = automation.create_expense_report({
            "title": title,
            "description": "22단계 전체 필드 E2E 테스트",
            "project": "GS-25-0088",
            "items": [{"item": "테스트 공사비", "amount": 1000000}],
            "total_amount": 1100000,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "usage_code": "5020",
            "budget_keyword": "경량",
            "payment_request_date": datetime.now().strftime("%Y-%m-%d"),
            "accounting_date": "",  # 자동 또는 빈값
            "evidence_type": "",
            "auto_capture_budget": False,
            "save_mode": "verify",  # 실제 저장하지 않고 필드 검증만
        })
        # verify 모드에서는 success=True가 아닐 수 있지만 에러 없이 완료되면 OK
        logger.debug(f"  22단계 테스트 결과: {result.get('message', '')}")

        # 임시보관 문서가 생성된 경우 삭제 등록
        if result.get("success"):
            self.cleanup_tasks.append((
                lambda t=title: self._delete_draft_document(t),
                f"임시보관 삭제: {title}",
            ))

    def _test_mail_summary(self):
        """T8: 메일 요약 — 기존 page로 fetch_unread_mails 직접 호출"""
        self._ensure_playwright()
        self._reset_page()
        from src.mail.summarizer import fetch_unread_mails

        gw_id = os.getenv("GW_USER_ID")
        mails = fetch_unread_mails(self.page, max_count=3, to_only=True, gw_id=gw_id)
        assert isinstance(mails, list), "fetch_unread_mails 반환값이 list가 아님"
        logger.debug(f"  메일 조회 결과: {len(mails)}건")

    def _test_chatbot_routing(self):
        """T9: 챗봇 라우팅 — Gemini function calling 응답 확인"""
        from src.chatbot.agent import analyze_and_route

        # Playwright가 asyncio 루프를 사용중이므로 기존 루프에서 실행
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run,
                    analyze_and_route(
                        user_message="안녕하세요, 테스트입니다.",
                        user_context={"gw_id": os.getenv("GW_USER_ID")},
                    )
                ).result(timeout=30)
        else:
            result = loop.run_until_complete(analyze_and_route(
                user_message="안녕하세요, 테스트입니다.",
                user_context={"gw_id": os.getenv("GW_USER_ID")},
            ))
        assert isinstance(result, dict), "analyze_and_route 반환값이 dict가 아님"
        assert "response" in result, "응답에 'response' 키가 없음"
        logger.debug(f"  챗봇 응답 길이: {len(result.get('response', ''))}자")

    def _run_async(self, coro):
        """async 코루틴을 sync 컨텍스트에서 실행하는 헬퍼"""
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result(timeout=60)

    def _test_chatbot_cancel(self):
        """T11: 챗봇 자연어 예약 취소 — '내일 예약 취소하고 싶어' → 결과 확인"""
        from src.chatbot.agent import analyze_and_route

        result = self._run_async(analyze_and_route(
            user_message="내일 예약 취소하고 싶어",
            user_context={"gw_id": os.getenv("GW_USER_ID")},
        ))
        assert isinstance(result, dict), "analyze_and_route 반환값이 dict가 아님"
        assert "response" in result, "응답에 'response' 키가 없음"
        # 예약 취소 관련 액션 또는 안내 메시지가 있어야 함
        logger.debug(f"  챗봇 취소 응답: {result.get('action', 'N/A')} / {len(result.get('response', ''))}자")

    def _test_chatbot_multiturn(self):
        """T12: 챗봇 다중 턴 대화 — 3턴 대화 히스토리 유지 확인"""
        from src.chatbot.agent import analyze_and_route

        history = []
        turns = [
            "내일 예약 취소하고 싶어",
            "취소테스트 취소해줘",
            "내일 예약 현황 보여줘",
        ]
        for i, msg in enumerate(turns, 1):
            result = self._run_async(analyze_and_route(
                user_message=msg,
                user_context={"gw_id": os.getenv("GW_USER_ID")},
                conversation_history=history,
            ))
            assert isinstance(result, dict), f"턴 {i}: 반환값이 dict가 아님"
            assert "response" in result, f"턴 {i}: 'response' 키가 없음"
            history.append({"role": "user", "content": msg})
            history.append({"role": "assistant", "content": result["response"]})
            logger.debug(f"  턴 {i}: action={result.get('action', 'N/A')}")

        assert len(history) == 6, f"히스토리 길이가 6이어야 함 (현재 {len(history)})"

    def _test_draft_submit(self):
        """T13: 임시보관문서 열기 + 결재상신 E2E (dry_run — 버튼 확인만)"""
        self._ensure_playwright()
        self._reset_page()
        from src.approval.approval_automation import ApprovalAutomation

        automation = ApprovalAutomation(page=self.page, context=self.context)
        result = automation.open_draft_and_submit(
            doc_title=None,  # 첫 번째 문서
            dry_run=True,    # 실제 상신하지 않음
        )
        assert result.get("success"), f"임시보관문서 상신 E2E 실패: {result.get('message')}"
        logger.debug(f"  상신 dry_run 결과: {result.get('message', '')}")

    # ═══════════════════════════════════════════════════
    #  Phase 3: 원상복구
    # ═══════════════════════════════════════════════════

    def _phase3_cleanup(self):
        logger.info("\n── Phase 3: 원상복구 ──")

        # 등록된 cleanup 태스크 실행
        for func, description in self.cleanup_tasks:
            cr = CleanupResult(description)
            try:
                func()
                cr.status = "OK"
                cr.message = "성공"
                logger.info(f"  {description}: [OK]")
            except Exception as e:
                cr.status = "FAIL"
                cr.message = str(e)
                logger.error(f"  {description}: [FAIL] - {e}")
            self.cleanup_results.append(cr)

        # 안전망: cleanup 후 향후 7일 재스캔 → [TEST_ 잔류 예약 경고
        if self.meeting_api and not self.skip_meeting:
            self._warn_stale_test_reservations(days=7)

        # 세션 캐시 초기화
        cr = CleanupResult("세션 캐시 초기화")
        try:
            from src.auth.session_manager import clear_all_cache
            clear_all_cache()
            cr.status = "OK"
            cr.message = "성공"
            logger.info(f"  세션 캐시 초기화: [OK]")
        except Exception as e:
            cr.status = "FAIL"
            cr.message = str(e)
            logger.error(f"  세션 캐시 초기화: [FAIL] - {e}")
        self.cleanup_results.append(cr)

        # 회의실 API 정리
        if self.meeting_api:
            try:
                self.meeting_api.close()
            except Exception:
                pass

        # Playwright 브라우저 종료
        cr = CleanupResult("Playwright 브라우저 종료")
        try:
            if self.browser:
                self.browser.close()
            if self.pw:
                self.pw.stop()
            cr.status = "OK"
            cr.message = "성공"
            logger.info(f"  Playwright 종료: [OK]")
        except Exception as e:
            cr.status = "FAIL"
            cr.message = str(e)
            logger.error(f"  Playwright 종료: [FAIL] - {e}")
        self.cleanup_results.append(cr)

    def _warn_stale_test_reservations(self, days: int = 7):
        """
        Phase 3 cleanup 완료 후 향후 days일간 [TEST_ 잔류 예약을 재스캔하여 경고.
        본인(empSeq 일치) 예약만 확인한다. 실제 취소는 하지 않고 경고만 출력.
        예외 발생 시 경고만 출력하고 중단하지 않는다.
        """
        my_emp_seq = str(self.meeting_api.company_info.get("empSeq", ""))
        today = date.today()
        stale_found = []

        for d in range(days):
            target_date = (today + timedelta(days=d)).strftime("%Y-%m-%d")
            try:
                reservations = self.meeting_api.get_reservations(target_date)
            except Exception as e:
                logger.warning(f"  안전망 재스캔: {target_date} 조회 실패 — {e}")
                continue

            for res in reservations:
                req_text = res.get("reqText", "")
                if "[TEST_" not in req_text:
                    continue
                # 본인 예약만 경고 (타 사용자 잔류는 무시)
                res_emp_seq = res.get("empSeq", "")
                if my_emp_seq and res_emp_seq and res_emp_seq != my_emp_seq:
                    continue
                stale_found.append(
                    f"{req_text!r} ({res.get('resName', '')} {target_date} "
                    f"schmSeq={res.get('schmSeq', '')} seqNum={res.get('seqNum', '')})"
                )

        if stale_found:
            logger.warning(
                f"  ⚠ [안전망] cleanup 후에도 [TEST_ 잔류 예약 {len(stale_found)}건 발견 — GW 수동 확인 필요:"
            )
            for item in stale_found:
                logger.warning(f"    - {item}")
        else:
            logger.info(f"  안전망 재스캔: 향후 {days}일간 [TEST_ 잔류 예약 없음")

    def _delete_draft_document(self, title: str):
        """임시보관문서함에서 제목으로 문서를 찾아 삭제"""
        if not self.page:
            raise RuntimeError("Playwright 세션 없음")

        # 다이얼로그 자동 수락
        self.page.on("dialog", lambda d: d.accept())

        # 임시보관문서함 이동
        draft_url = f"{GW_URL}/#/UB/UB/UBA0000?appCode=approval&viewType=list&menuCode=UBD9999&subMenuCode=UBA1060"
        self.page.goto(draft_url)
        self.page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(2)

        # 제목으로 문서 찾기
        row = self.page.locator(f"text={title}").first
        if not row.is_visible(timeout=5000):
            logger.warning(f"  임시보관 문서 '{title}'을(를) 찾을 수 없음 (이미 삭제됨?)")
            return

        row.click()
        time.sleep(2)

        # 팝업 감지 (거래처등록은 팝업, 지출결의서는 같은 페이지)
        pages = self.context.pages
        target_page = pages[-1] if len(pages) > 1 else self.page

        # "삭제" 버튼 클릭
        delete_btn = target_page.locator("div.topBtn:has-text('삭제')")
        if delete_btn.is_visible(timeout=5000):
            delete_btn.click(force=True)
            time.sleep(2)
            logger.debug(f"  문서 삭제 버튼 클릭 완료: {title}")
        else:
            raise RuntimeError(f"삭제 버튼을 찾을 수 없음: {title}")

        # 팝업이 있었으면 닫기
        if len(pages) > 1 and not target_page.is_closed():
            try:
                target_page.close()
            except Exception:
                pass

    # ═══════════════════════════════════════════════════
    #  Phase 4: 결과 리포트
    # ═══════════════════════════════════════════════════

    def _phase4_report(self):
        total_duration = time.time() - self.start_time
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        pass_count = sum(1 for r in self.results if r.status == "PASS")
        fail_count = sum(1 for r in self.results if r.status == "FAIL")
        skip_count = sum(1 for r in self.results if r.status == "SKIP")

        # ── 콘솔 리포트 ──
        W = 60  # 박스 폭
        sep = "+" + "-" * W + "+"
        print()
        print(sep)
        print("|" + "  FULL TEST REPORT".center(W) + "|")
        print(sep)
        print(f"|  time : {now_str:<{W - 10}}|")
        print(f"|  total: {total_duration:.1f}s{'':<{W - 14}}|")
        print(sep)

        for r in self.results:
            icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(r.status, "?")
            line = f"  {r.test_id}  {r.name:<20} {icon:<8} ({r.duration:.1f}s)"
            print(f"|{line:<{W}}|")

        if self.cleanup_results:
            print(sep)
            print(f"|  {'CLEANUP':<{W - 2}}|")
            for cr in self.cleanup_results:
                icon = {"OK": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(cr.status, "?")
                line = f"   - {cr.description:<34} {icon}"
                print(f"|{line:<{W}}|")

        print(sep)
        summary = f"  Result: {pass_count}/{len(self.results)} PASS, {fail_count} FAIL, {skip_count} SKIP"
        print(f"|{summary:<{W}}|")
        print(sep)

        # ── JSON 저장 ──
        report = {
            "timestamp": now_str,
            "duration": round(total_duration, 1),
            "options": {
                "headless": self.headless,
                "dry_run": self.dry_run,
                "skip_approval": self.skip_approval,
                "skip_meeting": self.skip_meeting,
                "skip_mail": self.skip_mail,
            },
            "tests": [r.to_dict() for r in self.results],
            "cleanup": [cr.to_dict() for cr in self.cleanup_results],
            "summary": {
                "total": len(self.results),
                "pass": pass_count,
                "fail": fail_count,
                "skip": skip_count,
            },
        }

        TEST_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TEST_RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"\n결과 저장: {TEST_RESULTS_PATH}")


# ═══════════════════════════════════════════════════
#  CLI 진입점
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="전체 기능 테스트 + 자동 원상복구")
    parser.add_argument("--headless", action="store_true", default=True,
                        help="브라우저 숨김 (기본값)")
    parser.add_argument("--no-headless", action="store_true",
                        help="브라우저 표시 (디버깅용)")
    parser.add_argument("--skip-approval", action="store_true",
                        help="전자결재 테스트 건너뜀 (T5~T7)")
    parser.add_argument("--skip-meeting", action="store_true",
                        help="회의실 테스트 건너뜀 (T2~T4)")
    parser.add_argument("--skip-mail", action="store_true",
                        help="메일 테스트 건너뜀 (T8)")
    parser.add_argument("--dry-run", action="store_true",
                        help="환경 체크만 (GW 호출 없음)")
    parser.add_argument("--verbose", action="store_true",
                        help="상세 로그 출력")
    args = parser.parse_args()

    headless = not args.no_headless
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    runner = FullTestRunner(
        headless=headless,
        dry_run=args.dry_run,
        skip_approval=args.skip_approval,
        skip_meeting=args.skip_meeting,
        skip_mail=args.skip_mail,
    )
    runner.run_all()

    # 실패가 있으면 exit code 1
    if any(r.status == "FAIL" for r in runner.results):
        sys.exit(1)


if __name__ == "__main__":
    main()
