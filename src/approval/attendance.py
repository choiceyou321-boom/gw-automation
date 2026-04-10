"""
근태신청 자동화 (HP 모듈)
- 연차휴가신청서 (formId=36)
- 외근신청서(당일) (formId=41)
- 연장근무신청서 (formId=43)

URL 패턴:
/#/HP/HPD0110/HPD0110?...&formDTp={formDTp}&formId={formId}
"""
import os
import time
import logging
from pathlib import Path
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger("attendance_automation")

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# 스크린샷 저장 디렉토리
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "approval_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# 재시도 설정 (approval_automation.py와 동일)
MAX_RETRIES = 3
RETRY_DELAY = 3  # 초


def _save_debug(page: Page, name: str):
    """디버그용 스크린샷 저장"""
    try:
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path))
        logger.info(f"스크린샷: {path}")
    except Exception as e:
        logger.warning(f"스크린샷 저장 실패: {e}")


class AttendanceMixin:
    """
    근태신청 전용 Mixin 클래스 (HP 모듈)

    사용 방법:
        class MyAutomation(AttendanceMixin):
            def __init__(self, page):
                self.page = page
    """

    # ─────────────────────────────────────────
    # 내부 유틸: 필드 채우기
    # ─────────────────────────────────────────

    def _att_fill_field_by_label(self, label: str, value: str) -> bool:
        """
        테이블 라벨(th) 기반 필드 채우기
        DOM 구조: table > tr > th(라벨) + td(input)
        base.py의 _fill_field_by_label과 동일 로직 (독립 실행 지원)
        """
        page = self.page
        try:
            th_el = page.locator(f"th:has-text('{label}')").first
            if not th_el.is_visible(timeout=2000):
                return False
            td_el = th_el.locator("xpath=following-sibling::td").first
            if not td_el.is_visible():
                return False
            inp = td_el.locator("input:visible").first
            if inp.is_visible():
                inp.click(force=True)
                inp.fill("")
                inp.fill(str(value))
                logger.info(f"필드 '{label}' 입력: {value}")
                return True
        except Exception as e:
            logger.debug(f"필드 '{label}' 입력 실패: {e}")
        return False

    def _att_fill_field_fallback(self, label: str, value: str) -> bool:
        """
        _fill_field_by_label이 정의된 경우 위임, 아니면 _att_fill_field_by_label 직접 호출
        """
        if hasattr(self, "_fill_field_by_label"):
            return self._fill_field_by_label(label, value)
        return self._att_fill_field_by_label(label, value)

    # ─────────────────────────────────────────
    # 근태 모듈 네비게이션
    # ─────────────────────────────────────────

    def _navigate_to_attendance_form(self, form_id: str, form_dtp: str) -> bool:
        """
        근태신청 양식으로 직접 URL 이동.

        Args:
            form_id: 양식 ID (예: "36", "41", "43")
            form_dtp: 양식 타입 코드 (예: "HP_HPD0110_00011")

        Returns:
            True: 이동 성공 및 양식 로드 완료
            False: 이동 실패 (폴백 시도 필요)

        URL 패턴:
            {GW_URL}/#/HP/HPD0110/HPD0110?%2F%23%2FHP%2FHPD0110%2FHPD0110=&MicroModuleCode=eap&docWidth=1035&formDTp={form_dtp}&formId={form_id}
        """
        page = self.page

        # 1차 시도: 직접 URL 이동
        try:
            url = (
                f"{GW_URL}/#/HP/HPD0110/HPD0110"
                f"?%2F%23%2FHP%2FHPD0110%2FHPD0110=&MicroModuleCode=eap"
                f"&docWidth=1035&formDTp={form_dtp}&formId={form_id}"
            )
            logger.info(f"근태신청 직접 URL 이동: {url}")
            page.goto(url)
            page.wait_for_load_state("networkidle", timeout=15000)

            # 양식 로드 확인: 신청정보 텍스트 대기
            try:
                page.locator("text=신청정보").first.wait_for(state="visible", timeout=8000)
                logger.info(f"근태신청 양식 로드 완료 (formId={form_id}, formDTp={form_dtp})")
                return True
            except PlaywrightTimeout:
                logger.warning("'신청정보' 텍스트 미확인 — 폴백 시도")
                _save_debug(page, f"att_nav_no_form_{form_id}")

        except PlaywrightTimeout as e:
            logger.warning(f"직접 URL 이동 타임아웃: {e}")
        except Exception as e:
            logger.warning(f"직접 URL 이동 실패: {e}")

        # 2차 시도(폴백): 근태관리 모듈 아이콘 → 근태신청 메뉴 → 양식 클릭
        try:
            logger.info("폴백: 근태관리 모듈 아이콘 탐색 시작")

            # 근태관리 모듈 아이콘 클릭 (HP 모듈 링크)
            for sel in [
                "span.module-link.HP",
                "a[href*='/HP/']",
                "text=근태관리",
                "text=근태",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        el.click(force=True)
                        page.wait_for_timeout(2000)
                        logger.info(f"근태관리 아이콘 클릭 ({sel})")
                        break
                except Exception:
                    continue

            # 근태신청 메뉴 클릭
            for sel in ["text=근태신청", "a:has-text('근태신청')"]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=3000):
                        el.click(force=True)
                        page.wait_for_timeout(2000)
                        logger.info("근태신청 메뉴 클릭")
                        break
                except Exception:
                    continue

            # 양식명 기반 클릭
            form_name_map = {
                "36": "연차휴가신청서",
                "41": "외근신청서",
                "43": "연장근무신청서",
            }
            form_name = form_name_map.get(form_id, "")
            if form_name:
                for sel in [f"text={form_name}", f"a:has-text('{form_name}')"]:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=3000):
                            el.click(force=True)
                            page.wait_for_timeout(3000)
                            logger.info(f"양식 클릭: {form_name}")
                            break
                    except Exception:
                        continue

            # 폴백 성공 여부 확인
            page.locator("text=신청정보").first.wait_for(state="visible", timeout=8000)
            logger.info("폴백 네비게이션 성공")
            return True

        except Exception as e:
            logger.error(f"폴백 네비게이션도 실패: {e}")
            _save_debug(page, f"att_nav_fallback_fail_{form_id}")
            return False

    # ─────────────────────────────────────────
    # 연차휴가신청서 (formId=36)
    # ─────────────────────────────────────────

    def create_annual_leave_request(self, data: dict) -> dict:
        """
        연차휴가신청서 작성 (HP 모듈 근태신청)

        formId=36, formDTp=HP_HPD0110_00011
        URL: {GW_URL}/#/HP/HPD0110/HPD0110?...&formDTp=HP_HPD0110_00011&formId=36

        Args:
            data: {
                "leave_type": str,          # 기본="연차"
                                            # 연차/반차(오전)/반차(오후)/대체휴가/
                                            # 대휴반차(오전)/대휴반차(오후)/공가(예비군/민방위)/
                                            # 반반차/대휴반반차/건강검진(반차)
                "leave_start": str,         # YYYY-MM-DD, 필수
                "leave_end": str,           # YYYY-MM-DD, 필수 (없으면 leave_start와 동일)
                "start_time": str,          # "HH:MM", 선택 (기본 09:00)
                "end_time": str,            # "HH:MM", 선택 (기본 18:00)
                "save_mode": str,           # "submit" | "verify", 기본="submit"
            }

        Returns:
            {"success": bool, "message": str}
        """
        if not data.get("leave_start"):
            return {"success": False, "message": "leave_start(휴가 시작일)는 필수입니다."}

        page = self.page
        last_error = None

        leave_type = data.get("leave_type", "연차")
        leave_start = data.get("leave_start", "")
        leave_end = data.get("leave_end", leave_start)  # 없으면 시작일과 동일
        start_time = data.get("start_time", "09:00")
        end_time = data.get("end_time", "18:00")
        save_mode = data.get("save_mode", "submit")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(f"연차휴가신청서 작성 시도 {attempt}/{MAX_RETRIES}")

                # 1. 양식 네비게이션
                if not self._navigate_to_attendance_form("36", "HP_HPD0110_00011"):
                    raise Exception("연차휴가신청서 양식 이동 실패")

                _save_debug(page, f"ann_leave_01_form_loaded_attempt{attempt}")

                # 2. 폼 로드 확인 (신청정보 대기)
                try:
                    page.locator("text=신청정보").first.wait_for(state="visible", timeout=8000)
                except PlaywrightTimeout:
                    logger.warning("신청정보 텍스트 미확인, 계속 진행")

                # 3. leave_type 탭 클릭 (기본=연차)
                if leave_type and leave_type != "연차":
                    for sel in [
                        f"text={leave_type}",
                        f"button:has-text('{leave_type}')",
                        f"span:has-text('{leave_type}')",
                        f"td:has-text('{leave_type}')",
                        f"li:has-text('{leave_type}')",
                    ]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                el.click(force=True)
                                page.wait_for_timeout(500)
                                logger.info(f"휴가 유형 선택: {leave_type}")
                                break
                        except Exception:
                            continue
                else:
                    # "연차" 기본값 탭 확인/클릭 (이미 선택되어 있을 수 있음)
                    try:
                        el = page.locator("text=연차").first
                        if el.is_visible(timeout=1500):
                            el.click(force=True)
                            page.wait_for_timeout(300)
                    except Exception:
                        pass

                _save_debug(page, f"ann_leave_02_type_selected_attempt{attempt}")

                # 4. 날짜 입력 (휴가기간 — 단일 th "휴가기간" 아래 2개 input: 시작일/종료일)
                # DOM: th="휴가기간" > td > input[0]=시작일, input[1]=종료일
                date_filled = False
                try:
                    th_el = page.locator("th:has-text('휴가기간')").first
                    if th_el.is_visible(timeout=3000):
                        td_el = th_el.locator("xpath=following-sibling::td").first
                        date_inputs = td_el.locator("input:visible")
                        if date_inputs.count() >= 1:
                            inp0 = date_inputs.nth(0)
                            inp0.click(force=True)
                            inp0.fill("")
                            inp0.fill(leave_start)
                            logger.info(f"휴가 시작일 입력(휴가기간[0]): {leave_start}")
                        if date_inputs.count() >= 2:
                            inp1 = date_inputs.nth(1)
                            inp1.click(force=True)
                            inp1.fill("")
                            inp1.fill(leave_end)
                            logger.info(f"휴가 종료일 입력(휴가기간[1]): {leave_end}")
                        date_filled = True
                except Exception as e:
                    logger.debug(f"휴가기간 th 기반 입력 실패: {e}")

                if not date_filled:
                    # 폴백: 개별 라벨 시도
                    for label in ["휴가시작일", "시작일", "기간(시작)"]:
                        try:
                            if self._att_fill_field_fallback(label, leave_start):
                                logger.info(f"휴가 시작일 입력: {leave_start} (라벨: {label})")
                                break
                        except Exception:
                            continue
                    for label in ["휴가종료일", "종료일", "기간(종료)"]:
                        try:
                            if self._att_fill_field_fallback(label, leave_end):
                                logger.info(f"휴가 종료일 입력: {leave_end} (라벨: {label})")
                                break
                        except Exception:
                            continue

                # 시간 입력 (선택) — DOM: th="시작/종료시간" 아래 단일 td에 오전/시/분 + 오후/시/분 총 6개 input
                # input[0]=오전/오후, input[1]=시작시(HH), input[2]=시작분(MM)
                # input[3]=오전/오후, input[4]=종료시(HH), input[5]=종료분(MM)
                if start_time or end_time:
                    try:
                        th_time = page.locator("th:has-text('시작/종료시간')").first
                        if th_time.is_visible(timeout=2000):
                            td_time = th_time.locator("xpath=following-sibling::td").first
                            time_inputs = td_time.locator("input:visible")
                            if start_time and time_inputs.count() >= 3:
                                hh, mm = (start_time.split(":") + ["00"])[:2]
                                time_inputs.nth(1).fill(hh)
                                time_inputs.nth(2).fill(mm)
                                logger.info(f"시작시간 입력: {start_time}")
                            if end_time and time_inputs.count() >= 6:
                                hh, mm = (end_time.split(":") + ["00"])[:2]
                                time_inputs.nth(4).fill(hh)
                                time_inputs.nth(5).fill(mm)
                                logger.info(f"종료시간 입력: {end_time}")
                    except Exception as e:
                        logger.debug(f"시작/종료시간 입력 실패: {e}")

                _save_debug(page, f"ann_leave_03_fields_filled_attempt{attempt}")

                # 5 & 6. save_mode 처리
                if save_mode == "submit":
                    # 신청완료 버튼 클릭
                    for btn_text in ["신청완료", "완료", "저장", "상신"]:
                        try:
                            btn = page.locator(f"button:has-text('{btn_text}')").first
                            if btn.is_visible(timeout=2000):
                                btn.click(force=True)
                                page.wait_for_timeout(2000)
                                logger.info(f"연차휴가신청서 신청완료: {btn_text}")
                                _save_debug(page, "ann_leave_04_submitted")
                                return {"success": True, "message": "연차휴가신청서가 신청 완료되었습니다."}
                        except Exception:
                            continue
                    return {"success": False, "message": "신청완료 버튼을 찾을 수 없습니다."}
                else:
                    # verify 모드: 스크린샷만 저장
                    _save_debug(page, "ann_leave_verify")
                    return {"success": True, "message": "연차휴가신청서 필드 작성 완료. 내용 확인 후 신청해주세요."}

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"연차휴가신청서 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                _save_debug(page, f"ann_leave_timeout_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
            except Exception as e:
                last_error = e
                logger.error(f"연차휴가신청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(page, f"ann_leave_error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        return {"success": False, "message": f"연차휴가신청서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    # ─────────────────────────────────────────
    # 외근신청서(당일) (formId=41)
    # ─────────────────────────────────────────

    def create_outside_work_request(self, data: dict) -> dict:
        """
        외근신청서(당일) 작성 (HP 모듈 근태신청)

        formId=41, formDTp=HP_HPD0110_00031
        URL: {GW_URL}/#/HP/HPD0110/HPD0110?...&formDTp=HP_HPD0110_00031&formId=41

        Args:
            data: {
                "work_type": str,           # 기본="종일외근"
                                            # 종일외근/외근후출근/출근후외근
                "work_date": str,           # YYYY-MM-DD, 필수
                "work_date_end": str,       # YYYY-MM-DD (없으면 work_date와 동일)
                "start_time": str,          # "HH:MM", 선택
                "end_time": str,            # "HH:MM", 선택
                "transportation": str,      # 교통수단, 선택
                "destination": str,         # 방문처, 필수
                "purpose": str,             # 업무내용, 필수
                "save_mode": str,           # "submit" | "verify", 기본="submit"
            }

        Returns:
            {"success": bool, "message": str}
        """
        if not data.get("work_date"):
            return {"success": False, "message": "work_date(외근일)는 필수입니다."}
        if not data.get("destination"):
            return {"success": False, "message": "destination(방문처)는 필수입니다."}
        if not data.get("purpose"):
            return {"success": False, "message": "purpose(업무내용)는 필수입니다."}

        page = self.page
        last_error = None

        work_type = data.get("work_type", "종일외근")
        work_date = data.get("work_date", "")
        work_date_end = data.get("work_date_end", work_date)
        start_time = data.get("start_time", "")
        end_time = data.get("end_time", "")
        transportation = data.get("transportation", "")
        destination = data.get("destination", "")
        purpose = data.get("purpose", "")
        save_mode = data.get("save_mode", "submit")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(f"외근신청서 작성 시도 {attempt}/{MAX_RETRIES}")

                # 1. 양식 네비게이션
                if not self._navigate_to_attendance_form("41", "HP_HPD0110_00031"):
                    raise Exception("외근신청서 양식 이동 실패")

                _save_debug(page, f"outside_01_form_loaded_attempt{attempt}")

                # 2. 폼 로드 확인
                try:
                    page.locator("text=신청정보").first.wait_for(state="visible", timeout=8000)
                except PlaywrightTimeout:
                    logger.warning("신청정보 텍스트 미확인, 계속 진행")

                # 3. work_type 탭 클릭
                if work_type:
                    for sel in [
                        f"text={work_type}",
                        f"button:has-text('{work_type}')",
                        f"span:has-text('{work_type}')",
                        f"td:has-text('{work_type}')",
                        f"li:has-text('{work_type}')",
                    ]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                el.click(force=True)
                                page.wait_for_timeout(500)
                                logger.info(f"외근구분 선택: {work_type}")
                                break
                        except Exception:
                            continue

                _save_debug(page, f"outside_02_type_selected_attempt{attempt}")

                # 4. 날짜 입력
                for label in ["외근기간", "외근일", "기간(시작)", "날짜", "시작일"]:
                    try:
                        if self._att_fill_field_fallback(label, work_date):
                            logger.info(f"외근 시작일 입력: {work_date} (라벨: {label})")
                            break
                    except Exception:
                        continue

                # 종료일 (시작일과 다를 때만)
                if work_date_end and work_date_end != work_date:
                    for label in ["기간(종료)", "외근종료일", "종료일"]:
                        try:
                            if self._att_fill_field_fallback(label, work_date_end):
                                logger.info(f"외근 종료일 입력: {work_date_end}")
                                break
                        except Exception:
                            continue

                # 시간 입력 — DOM: th="시작/종료시간" 아래 단일 td에 6개 input
                # input[0]=오전/오후, input[1]=시작시(HH), input[2]=시작분(MM)
                # input[3]=오전/오후, input[4]=종료시(HH), input[5]=종료분(MM)
                if start_time or end_time:
                    try:
                        th_time = page.locator("th:has-text('시작/종료시간')").first
                        if th_time.is_visible(timeout=2000):
                            td_time = th_time.locator("xpath=following-sibling::td").first
                            time_inputs = td_time.locator("input:visible")
                            if start_time and time_inputs.count() >= 3:
                                hh, mm = (start_time.split(":") + ["00"])[:2]
                                time_inputs.nth(1).fill(hh)
                                time_inputs.nth(2).fill(mm)
                                logger.info(f"시작시간 입력: {start_time}")
                            if end_time and time_inputs.count() >= 6:
                                hh, mm = (end_time.split(":") + ["00"])[:2]
                                time_inputs.nth(4).fill(hh)
                                time_inputs.nth(5).fill(mm)
                                logger.info(f"종료시간 입력: {end_time}")
                    except Exception as e:
                        logger.debug(f"시작/종료시간 입력 실패: {e}")

                # 5. 방문처 입력 (라벨 "방문처" 기반)
                for label in ["방문처", "목적지"]:
                    try:
                        if self._att_fill_field_fallback(label, destination):
                            logger.info(f"방문처 입력: {destination}")
                            break
                    except Exception:
                        continue

                # 6. 업무내용 입력 (라벨 "업무내용" 기반, 빨간 테두리 필수 필드)
                for label in ["업무내용", "외근사유", "내용", "사유"]:
                    try:
                        if self._att_fill_field_fallback(label, purpose):
                            logger.info(f"업무내용 입력: {purpose}")
                            break
                    except Exception:
                        continue

                # 7. 교통수단 드롭다운 선택 (있으면)
                if transportation:
                    # 먼저 라벨 기반 입력 시도
                    transport_filled = False
                    try:
                        if self._att_fill_field_fallback("교통수단", transportation):
                            transport_filled = True
                    except Exception:
                        pass

                    # 드롭다운 선택 시도
                    if not transport_filled:
                        for sel in [
                            f"select:has-option-text('{transportation}')",
                            "select[name*='transport']",
                            "select[name*='Transport']",
                        ]:
                            try:
                                dd = page.locator(sel).first
                                if dd.is_visible(timeout=1500):
                                    dd.select_option(label=transportation)
                                    logger.info(f"교통수단 드롭다운 선택: {transportation}")
                                    transport_filled = True
                                    break
                            except Exception:
                                continue

                _save_debug(page, f"outside_03_fields_filled_attempt{attempt}")

                # 8. save_mode 처리
                # 외근신청서 제출 버튼: "일정등록" (신청완료 버튼 없음 — DOM 검증 확인)
                if save_mode == "submit":
                    for btn_text in ["일정등록", "신청완료", "완료", "저장", "상신"]:
                        try:
                            btn = page.locator(f"button:has-text('{btn_text}')").first
                            if btn.is_visible(timeout=2000):
                                btn.click(force=True)
                                page.wait_for_timeout(2000)
                                logger.info(f"외근신청서 등록: {btn_text}")
                                _save_debug(page, "outside_04_submitted")
                                return {"success": True, "message": "외근신청서가 등록되었습니다."}
                        except Exception:
                            continue
                    return {"success": False, "message": "일정등록 버튼을 찾을 수 없습니다."}
                else:
                    _save_debug(page, "outside_verify")
                    return {"success": True, "message": "외근신청서 필드 작성 완료. 내용 확인 후 신청해주세요."}

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"외근신청서 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                _save_debug(page, f"outside_timeout_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
            except Exception as e:
                last_error = e
                logger.error(f"외근신청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(page, f"outside_error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        return {"success": False, "message": f"외근신청서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    # ─────────────────────────────────────────
    # 연장근무신청서 (formId=43)
    # ─────────────────────────────────────────

    def create_overtime_request(self, data: dict) -> dict:
        """
        연장근무신청서 작성 (HP 모듈 근태신청)

        formId=43, formDTp=HP_HPD0110_00051
        URL: {GW_URL}/#/HP/HPD0110/HPD0110?...&formDTp=HP_HPD0110_00051&formId=43

        Args:
            data: {
                "work_type": str,           # 기본="연장근무"
                                            # 조기근무/연장근무/휴일근무
                "work_date": str,           # YYYY-MM-DD, 필수
                "work_date_end": str,       # YYYY-MM-DD (없으면 work_date와 동일)
                "write_basis": str,         # 기본="신청시간"
                                            # 태깅시간/시작/종료시간/신청시간
                                            # DOM value: TAGGING_TIME/MANUAL_RANGE/FIXED_DURATION
                                            # 라디오 라벨: 태깅시간/시작/종료시간/신청시간
                "start_time": str,          # "HH:MM", write_basis=시작종료시간일 때 필수
                "end_time": str,            # "HH:MM", write_basis=시작종료시간일 때 필수
                "hours": int,               # write_basis=신청시간일 때 사용
                "minutes": int,             # write_basis=신청시간일 때 사용
                "reason": str,              # 비고/사유, 필수
                "save_mode": str,           # "submit" | "verify", 기본="submit"
            }

        Returns:
            {"success": bool, "message": str}
        """
        if not data.get("work_date"):
            return {"success": False, "message": "work_date(근무일)는 필수입니다."}
        if not data.get("reason"):
            return {"success": False, "message": "reason(사유)은 필수입니다."}

        page = self.page
        last_error = None

        work_type = data.get("work_type", "연장근무")
        work_date = data.get("work_date", "")
        work_date_end = data.get("work_date_end", work_date)
        write_basis = data.get("write_basis", "신청시간")
        start_time = data.get("start_time", "")
        end_time = data.get("end_time", "")
        hours = data.get("hours", None)
        minutes = data.get("minutes", None)
        reason = data.get("reason", "")
        save_mode = data.get("save_mode", "submit")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(f"연장근무신청서 작성 시도 {attempt}/{MAX_RETRIES}")

                # 1. 양식 네비게이션
                if not self._navigate_to_attendance_form("43", "HP_HPD0110_00051"):
                    raise Exception("연장근무신청서 양식 이동 실패")

                _save_debug(page, f"overtime_01_form_loaded_attempt{attempt}")

                # 2. 폼 로드 확인
                try:
                    page.locator("text=신청정보").first.wait_for(state="visible", timeout=8000)
                except PlaywrightTimeout:
                    logger.warning("신청정보 텍스트 미확인, 계속 진행")

                # 3. work_type 탭 클릭 (조기근무/연장근무/휴일근무)
                if work_type:
                    for sel in [
                        f"text={work_type}",
                        f"button:has-text('{work_type}')",
                        f"span:has-text('{work_type}')",
                        f"td:has-text('{work_type}')",
                        f"input[value='{work_type}']",
                    ]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                el.click(force=True)
                                page.wait_for_timeout(500)
                                logger.info(f"근무구분 선택: {work_type}")
                                break
                        except Exception:
                            continue

                _save_debug(page, f"overtime_02_type_selected_attempt{attempt}")

                # 4. write_basis 라디오 선택
                # DOM radio values: TAGGING_TIME / MANUAL_RANGE / FIXED_DURATION
                # 라디오 라벨(parentText): 태깅시간 / 시작/종료시간 / 신청시간
                _write_basis_value_map = {
                    "태깅시간": "TAGGING_TIME",
                    "시작종료시간": "MANUAL_RANGE",   # 구버전 호환
                    "시작/종료시간": "MANUAL_RANGE",
                    "신청시간": "FIXED_DURATION",
                }
                if write_basis:
                    radio_value = _write_basis_value_map.get(write_basis, "")
                    for sel in [
                        f"input[type='radio'][value='{radio_value}']" if radio_value else f"input[type='radio'][value='{write_basis}']",
                        f"text={write_basis}",
                        f"label:has-text('{write_basis}')",
                        f"span:has-text('{write_basis}')",
                    ]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                el.click(force=True)
                                page.wait_for_timeout(500)
                                logger.info(f"작성기준 선택: {write_basis}")
                                break
                        except Exception:
                            continue

                # 5. 날짜 입력 — DOM: th="근무일" 아래 td에 input[0]=시작일, input[1]=종료일
                date_filled = False
                try:
                    th_date = page.locator("th:has-text('근무일')").first
                    if th_date.is_visible(timeout=3000):
                        td_date = th_date.locator("xpath=following-sibling::td").first
                        date_inputs = td_date.locator("input:visible")
                        if date_inputs.count() >= 1:
                            inp0 = date_inputs.nth(0)
                            inp0.click(force=True)
                            inp0.fill("")
                            inp0.fill(work_date)
                            logger.info(f"근무 시작일 입력(근무일[0]): {work_date}")
                        if work_date_end and work_date_end != work_date and date_inputs.count() >= 2:
                            inp1 = date_inputs.nth(1)
                            inp1.click(force=True)
                            inp1.fill("")
                            inp1.fill(work_date_end)
                            logger.info(f"근무 종료일 입력(근무일[1]): {work_date_end}")
                        date_filled = True
                except Exception as e:
                    logger.debug(f"근무일 th 기반 입력 실패: {e}")

                if not date_filled:
                    # 폴백: 개별 라벨 시도
                    for label in ["연장근무시작일", "근무시작일", "근무일", "시작일", "기간(시작)"]:
                        try:
                            if self._att_fill_field_fallback(label, work_date):
                                logger.info(f"근무 시작일 입력: {work_date} (라벨: {label})")
                                break
                        except Exception:
                            continue
                    if work_date_end and work_date_end != work_date:
                        for label in ["근무종료일", "종료일", "기간(종료)"]:
                            try:
                                if self._att_fill_field_fallback(label, work_date_end):
                                    logger.info(f"근무 종료일 입력: {work_date_end}")
                                    break
                            except Exception:
                                continue

                # 6. 시간 입력 (write_basis에 따라 분기)
                # "시작종료시간"은 구버전 호환, 실제 라디오 라벨은 "시작/종료시간"
                if write_basis in ("시작종료시간", "시작/종료시간"):
                    # 시작시간/종료시간 직접 입력
                    if start_time:
                        for label in ["시작시간", "시작"]:
                            try:
                                if self._att_fill_field_fallback(label, start_time):
                                    logger.info(f"시작시간 입력: {start_time}")
                                    break
                            except Exception:
                                continue

                    if end_time:
                        for label in ["종료시간", "종료"]:
                            try:
                                if self._att_fill_field_fallback(label, end_time):
                                    logger.info(f"종료시간 입력: {end_time}")
                                    break
                            except Exception:
                                continue

                elif write_basis == "신청시간":
                    # 시간/분 입력
                    if hours is not None:
                        for label in ["신청시간", "시간"]:
                            try:
                                if self._att_fill_field_fallback(label, str(hours)):
                                    logger.info(f"신청시간(시) 입력: {hours}")
                                    break
                            except Exception:
                                continue

                    if minutes is not None:
                        for label in ["신청분", "분"]:
                            try:
                                if self._att_fill_field_fallback(label, str(minutes)):
                                    logger.info(f"신청시간(분) 입력: {minutes}")
                                    break
                            except Exception:
                                continue

                # 태깅시간은 자동 입력이므로 별도 처리 없음

                # 7. reason 입력 — DOM th: "비고(사유)"
                for label in ["비고(사유)", "비고", "사유", "내용", "근무사유"]:
                    try:
                        if self._att_fill_field_fallback(label, reason):
                            logger.info(f"사유 입력: {reason} (라벨: {label})")
                            break
                    except Exception:
                        continue

                _save_debug(page, f"overtime_03_fields_filled_attempt{attempt}")

                # 8. save_mode 처리
                if save_mode == "submit":
                    for btn_text in ["신청완료", "완료", "저장", "상신"]:
                        try:
                            btn = page.locator(f"button:has-text('{btn_text}')").first
                            if btn.is_visible(timeout=2000):
                                btn.click(force=True)
                                page.wait_for_timeout(2000)
                                logger.info(f"연장근무신청서 신청완료: {btn_text}")
                                _save_debug(page, "overtime_04_submitted")
                                return {"success": True, "message": "연장근무신청서가 신청 완료되었습니다."}
                        except Exception:
                            continue
                    return {"success": False, "message": "신청완료 버튼을 찾을 수 없습니다."}
                else:
                    _save_debug(page, "overtime_verify")
                    return {"success": True, "message": "연장근무신청서 필드 작성 완료. 내용 확인 후 신청해주세요."}

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"연장근무신청서 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                _save_debug(page, f"overtime_timeout_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
            except Exception as e:
                last_error = e
                logger.error(f"연장근무신청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(page, f"overtime_error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        return {"success": False, "message": f"연장근무신청서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}
