"""
전자결재 자동화 — 외근신청서 mixin

분할 출처: other_forms.py (세션 LII)
콜백 주입 패턴: self 메서드 직접 참조 (mixin 클래스로 분리).

포함 메서드:
- create_outside_work_request : 외근신청서(당일) 작성
- _save_outside_work_draft    : 외근신청서(당일) 임시보관 (draft 모드)
"""

import logging
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from src.approval.base import MAX_RETRIES, RETRY_DELAY, _save_debug

logger = logging.getLogger("approval_automation")


class OutsideWorkMixin:
    """외근신청서(당일) 전자결재 mixin"""

    def create_outside_work_request(self, data: dict) -> dict:
        """
        외근신청서(당일) 작성 (근태관리 모듈).

        Args:
            data: {
                "title": "제목",
                "work_date": "YYYY-MM-DD",
                "destination": "방문처",
                "purpose": "외근사유/업무내용",
                "start_time": "HH:MM",         # 선택
                "end_time": "HH:MM",           # 선택
                "work_type": "종일외근",        # 외근구분 (종일외근/외근후출근/출근후외근)
                "transport": "대중교통",         # 교통수단 (선택)
                "save_mode": "submit",
            }
        Returns:
            {"success": bool, "message": str}
        """
        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        page = self.page
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._close_popups()
                self._navigate_to_approval_home()
                self._click_write_approval()
                page.wait_for_timeout(1500)

                # 외근신청서 검색 및 선택
                form_found = False
                for kw in ["외근신청서", "외근신청서(당일)", "외근"]:
                    try:
                        for sel in ["input[placeholder*='검색']", "input[type='search']", "input.OBTTextField"]:
                            try:
                                inp = page.locator(sel).first
                                if inp.is_visible(timeout=2000):
                                    inp.fill(kw)
                                    inp.press("Enter")
                                    page.wait_for_timeout(1500)
                                    break
                            except Exception:
                                continue
                        link = page.locator("text=외근신청서").first
                        if link.is_visible(timeout=3000):
                            link.click(force=True)
                            page.wait_for_timeout(3000)
                            form_found = True
                            logger.info("외근신청서 양식 클릭 완료")
                            break
                    except Exception:
                        continue

                if not form_found:
                    raise Exception("외근신청서 양식을 찾을 수 없습니다.")

                # 필드 채우기 (date / work_date, reason / purpose 동의어 처리)
                work_date = data.get("date") or data.get("work_date", "")
                destination = data.get("destination", "")
                purpose = data.get("reason") or data.get("purpose", "")
                start_time = data.get("start_time", "")
                end_time = data.get("end_time", "")
                work_type = data.get("work_type", "")
                transport = data.get("transport", "")

                # 외근구분 선택
                if work_type:
                    for sel in [f"text={work_type}", f"input[value='{work_type}']"]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                el.click(force=True)
                                logger.info(f"외근구분 선택: {work_type}")
                                break
                        except Exception:
                            continue

                # 날짜
                for label in ["외근기간", "외근일", "날짜"]:
                    try:
                        if work_date and self._fill_field_by_label(label, work_date):
                            logger.info(f"날짜 입력: {work_date}")
                            break
                    except Exception:
                        continue

                # 시간
                if start_time:
                    for label in ["시작시간", "출발시간"]:
                        try:
                            if self._fill_field_by_label(label, start_time):
                                break
                        except Exception:
                            continue
                if end_time:
                    for label in ["종료시간", "복귀시간"]:
                        try:
                            if self._fill_field_by_label(label, end_time):
                                break
                        except Exception:
                            continue

                # 방문처/교통수단/업무내용
                if destination:
                    for label in ["방문처", "목적지"]:
                        try:
                            if self._fill_field_by_label(label, destination):
                                break
                        except Exception:
                            continue
                if transport:
                    for label in ["교통수단"]:
                        try:
                            if self._fill_field_by_label(label, transport):
                                break
                        except Exception:
                            continue
                if purpose:
                    for label in ["업무내용", "외근사유", "내용", "사유"]:
                        try:
                            if self._fill_field_by_label(label, purpose):
                                break
                        except Exception:
                            continue

                save_mode = data.get("save_mode", "verify")
                if save_mode == "submit":
                    for btn_text in ["저장", "신청완료", "상신", "완료"]:
                        try:
                            btn = page.locator(f"button:has-text('{btn_text}')").first
                            if btn.is_visible(timeout=2000):
                                btn.click(force=True)
                                page.wait_for_timeout(2000)
                                logger.info(f"외근신청서 저장 클릭: {btn_text}")
                                return {"success": True, "message": "외근신청서가 신청 완료되었습니다."}
                        except Exception:
                            continue
                    return {"success": False, "message": "저장 버튼을 찾을 수 없습니다. 화면을 확인해주세요."}
                else:
                    _save_debug(page, "outside_work_verify")
                    return {"success": True, "message": "외근신청서 필드 작성이 완료되었습니다. 내용을 확인 후 신청해주세요."}

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"외근신청서 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)
            except Exception as e:
                last_error = e
                logger.error(f"외근신청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

        return {"success": False, "message": f"외근신청서 작성 실패: {str(last_error)}"}

    def _save_outside_work_draft(self, data: dict) -> dict:
        """
        외근신청서(당일) 임시보관 (draft 모드).

        근태관리 모듈은 전자결재 "보관" 버튼 없음.
        저장 버튼을 눌러 저장하는 방식 사용.
        HR 모듈 경로: 임직원업무관리(HR) > 근태신청 > 외근신청서(당일)

        Args:
            data: {
                "date": "YYYY-MM-DD",      # 외근일 (work_date 동의어)
                "work_date": "YYYY-MM-DD", # 외근일 (date 동의어)
                "start_time": "HH:MM",     # 외출시각
                "end_time": "HH:MM",       # 복귀시각
                "destination": "외근지",    # 방문처/목적지
                "reason": "사유",           # 외근 사유 (purpose 동의어)
                "purpose": "사유",          # 외근사유 (reason 동의어)
                "project": "프로젝트명",    # 선택사항
                "work_type": "종일외근",    # 외근구분 (종일외근/외근후출근/출근후외근)
                "transport": "교통수단",    # 선택사항
            }
        Returns:
            {"success": bool, "message": str}
        """
        page = self.page

        try:
            # date / work_date 동의어 처리
            work_date = data.get("date") or data.get("work_date", "")
            start_time = data.get("start_time", "")
            end_time = data.get("end_time", "")
            destination = data.get("destination", "")
            reason = data.get("reason") or data.get("purpose", "")
            project = data.get("project", "")
            work_type = data.get("work_type", "")
            transport = data.get("transport", "")

            self._close_popups()

            # HR 근태관리 페이지 이동 (공통 헬퍼 사용, 외근신청은 UFA1020 추정)
            logger.info("[외근신청 임시저장 1] HR 근태관리 페이지 이동")
            nav_ok = self._navigate_to_hr_attendance(page, "UFA1020")

            if not nav_ok:
                # 최종 폴백: 전자결재 결재작성 경로에서 외근신청서 검색
                logger.info("[외근신청 임시저장 2-폴백] 결재작성 경로 시도")
                self._navigate_to_approval_home()
                self._click_write_approval()
                page.wait_for_timeout(1500)
                for sel in ["input[placeholder*='검색']", "input[type='search']", "input.OBTTextField"]:
                    try:
                        inp = page.locator(sel).first
                        if inp.is_visible(timeout=2000):
                            inp.fill("외근신청서")
                            inp.press("Enter")
                            page.wait_for_timeout(1500)
                            break
                    except Exception:
                        continue
                try:
                    link = page.locator("text=외근신청서").first
                    if link.is_visible(timeout=3000):
                        link.click(force=True)
                        page.wait_for_timeout(3000)
                        nav_ok = True
                except Exception:
                    pass

            if not nav_ok:
                return {"success": False, "message": "외근신청서 양식을 찾을 수 없습니다."}

            # 외근구분 선택
            if work_type:
                for sel in [f"text={work_type}", f"input[value='{work_type}']"]:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=1500):
                            el.click(force=True)
                            page.wait_for_timeout(500)
                            logger.info(f"외근구분 선택: {work_type}")
                            break
                    except Exception:
                        continue

            # 날짜 입력
            logger.info(f"[외근신청 임시저장 3] 날짜 입력: {work_date}")
            if work_date:
                for label in ["외근기간", "외근일", "날짜"]:
                    try:
                        if self._fill_field_by_label(label, work_date):
                            logger.info(f"날짜 필드 '{label}' 입력 완료")
                            break
                    except Exception:
                        continue
                # date input 직접 탐색 폴백
                try:
                    date_inputs = page.locator("input[type='date'], input.OBTDatePickerRebuild_inputYMD").all()
                    if date_inputs:
                        date_inputs[0].fill(work_date)
                        date_inputs[0].press("Tab")
                        page.wait_for_timeout(500)
                        logger.info(f"date input 직접 입력: {work_date}")
                except Exception:
                    pass

            # 시간 입력
            logger.info(f"[외근신청 임시저장 4] 시간 입력: {start_time} ~ {end_time}")
            if start_time:
                for label in ["시작시간", "출발시간"]:
                    try:
                        if self._fill_field_by_label(label, start_time):
                            break
                    except Exception:
                        continue
            if end_time:
                for label in ["종료시간", "복귀시간"]:
                    try:
                        if self._fill_field_by_label(label, end_time):
                            break
                    except Exception:
                        continue

            # 방문처/교통수단/사유 입력
            if destination:
                for label in ["방문처", "목적지"]:
                    try:
                        if self._fill_field_by_label(label, destination):
                            logger.info(f"방문처 입력 완료: {destination}")
                            break
                    except Exception:
                        continue
            if transport:
                for label in ["교통수단"]:
                    try:
                        if self._fill_field_by_label(label, transport):
                            logger.info(f"교통수단 입력 완료: {transport}")
                            break
                    except Exception:
                        continue
            if reason:
                for label in ["업무내용", "외근사유", "내용", "사유", "비고"]:
                    try:
                        if self._fill_field_by_label(label, reason):
                            logger.info(f"사유 입력 완료: {reason[:30]}")
                            break
                    except Exception:
                        continue

            # 프로젝트명 입력 (있는 경우)
            if project:
                for label in ["프로젝트", "프로젝트명"]:
                    try:
                        if self._fill_field_by_label(label, project):
                            logger.info(f"프로젝트 입력 완료: {project}")
                            break
                    except Exception:
                        continue

            # 저장 버튼 클릭
            logger.info("[외근신청 임시저장 5] 저장 버튼 탐색")
            _save_debug(page, "outside_work_draft_before_save")
            saved = False
            for btn_text in ["저장", "신청완료", "완료"]:
                try:
                    btn = page.locator(f"button:has-text('{btn_text}')").first
                    if btn.is_visible(timeout=2000):
                        btn.click(force=True)
                        page.wait_for_timeout(2000)
                        logger.info(f"외근신청서 저장 완료: {btn_text}")
                        saved = True
                        break
                except Exception:
                    continue

            if not saved:
                _save_debug(page, "outside_work_draft_no_save_btn")
                return {
                    "success": False,
                    "message": "저장 버튼을 찾을 수 없습니다. GW 화면을 직접 확인해주세요.",
                }

            _save_debug(page, "outside_work_draft_saved")
            return {"success": True, "message": "외근신청서가 임시저장되었습니다."}

        except Exception as e:
            logger.error(f"외근신청 임시저장 실패: {e}", exc_info=True)
            _save_debug(page, "outside_work_draft_error")
            return {"success": False, "message": f"외근신청서 저장 실패: {str(e)}"}
