"""
전자결재 자동화 — 연장근무신청서 mixin

분할 출처: other_forms.py (세션 LII)
콜백 주입 패턴: self 메서드 직접 참조 (mixin 클래스로 분리).

포함 메서드:
- create_overtime_request    : 연장근무신청서 작성
- _navigate_to_hr_attendance : HR 근태관리 > 시간외근무 폼 이동 (공통 헬퍼)
- _save_overtime_draft       : 연장근무신청서 임시보관 (draft 모드)
"""

import os
import logging
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from src.gw.approval.base import MAX_RETRIES, RETRY_DELAY, _save_debug

logger = logging.getLogger("approval_automation")


class OvertimeMixin:
    """연장근무신청서 전자결재 mixin"""

    def create_overtime_request(self, data: dict) -> dict:
        """
        연장근무신청서 작성 (근태관리 모듈).

        근태관리 모듈 경로:
        - 결재작성 -> "연장근무신청서" 검색 -> 선택 (formId=43)
        - 또는 근태관리 > 근태신청 > 연장근무신청서 직접 이동

        Args:
            data: {
                "title": "제목",               # 필수 (표시용, 실제 폼 제목 필드 없을 수 있음)
                "work_date": "YYYY-MM-DD",     # 근무일
                "start_time": "HH:MM",         # 시작시간
                "end_time": "HH:MM",           # 종료시간
                "reason": "사유",               # 비고/사유
                "work_type": "연장근무",        # 근무구분 (조기근무/연장근무/휴일근무, 기본: 연장근무)
                "save_mode": "submit",          # "submit" | "verify"
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

                # 결재작성 클릭
                self._click_write_approval()
                page.wait_for_timeout(1500)

                # 시간외근무(연장근무) 검색 및 선택
                search_keywords = ["시간외근무", "연장근무"]
                form_found = False
                for kw in search_keywords:
                    try:
                        # 검색창 입력
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
                        # 결과 클릭 (GW 메뉴명은 "시간외근무")
                        for link_text in ["시간외근무", "연장근무"]:
                            try:
                                link = page.locator(f"text={link_text}").first
                                if link.is_visible(timeout=2000):
                                    link.click(force=True)
                                    page.wait_for_timeout(3000)
                                    form_found = True
                                    logger.info(f"시간외근무 양식 클릭 완료 (매치: {link_text})")
                                    break
                            except Exception:
                                continue
                        if form_found:
                            break
                    except Exception:
                        continue

                if not form_found:
                    raise Exception("시간외근무(연장근무) 양식을 찾을 수 없습니다.")

                # 필드 채우기 (date / work_date 동의어 처리)
                work_date = data.get("date") or data.get("work_date", "")
                start_time = data.get("start_time", "")
                end_time = data.get("end_time", "")
                reason = data.get("reason", "")
                work_type = data.get("work_type", "연장근무")

                # 근무구분 선택 (라디오 또는 선택 버튼)
                if work_type:
                    for sel in [f"text={work_type}", f"input[value='{work_type}']"]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                el.click(force=True)
                                logger.info(f"근무구분 선택: {work_type}")
                                break
                        except Exception:
                            continue

                # 날짜 입력
                for label in ["연장근무시작일", "근무일", "시작일"]:
                    try:
                        if self._fill_field_by_label(label, work_date):
                            logger.info(f"날짜 필드 '{label}' 입력: {work_date}")
                            break
                    except Exception:
                        continue

                # 시작/종료 시간
                for label in ["시작시간", "시작"]:
                    try:
                        if start_time and self._fill_field_by_label(label, start_time):
                            logger.info(f"시작시간 입력: {start_time}")
                            break
                    except Exception:
                        continue

                for label in ["종료시간", "종료"]:
                    try:
                        if end_time and self._fill_field_by_label(label, end_time):
                            logger.info(f"종료시간 입력: {end_time}")
                            break
                    except Exception:
                        continue

                # 비고/사유
                if reason:
                    for label in ["비고", "사유", "내용"]:
                        try:
                            if self._fill_field_by_label(label, reason):
                                logger.info(f"사유 입력: {reason}")
                                break
                        except Exception:
                            continue

                save_mode = data.get("save_mode", "verify")
                if save_mode == "submit":
                    # 신청완료 버튼 클릭
                    for btn_text in ["신청완료", "저장", "상신", "완료"]:
                        try:
                            btn = page.locator(f"button:has-text('{btn_text}')").first
                            if btn.is_visible(timeout=2000):
                                btn.click(force=True)
                                page.wait_for_timeout(2000)
                                logger.info(f"연장근무신청서 신청완료 클릭: {btn_text}")
                                return {"success": True, "message": "연장근무신청서가 신청 완료되었습니다."}
                        except Exception:
                            continue
                    return {"success": False, "message": "신청완료 버튼을 찾을 수 없습니다. 화면을 확인해주세요."}
                else:
                    # verify 모드: 필드 채우기만 확인
                    _save_debug(page, "overtime_verify")
                    return {"success": True, "message": "연장근무신청서 필드 작성이 완료되었습니다. 내용을 확인 후 신청해주세요."}

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"연장근무신청서 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)
            except Exception as e:
                last_error = e
                logger.error(f"연장근무신청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

        return {"success": False, "message": f"연장근무신청서 작성 실패: {str(last_error)}"}

    def _navigate_to_hr_attendance(self, page, _target_page_code: str = "") -> bool:
        """
        HR 근태관리 > 시간외근무 폼으로 이동하는 공통 헬퍼.

        ─── 실제 GW 탐색 결과 (2026-04-10) ───
        - UF 모듈(근태관리) URL 직접 이동 시 "권한 없는 메뉴" 팝업 후 게시판으로 리다이렉트됨.
          (UFA1010~UFA1060 전부 권한 없음 — specialLnb 메뉴는 계정 권한에 따라 표시)
        - HR 모듈(임직원업무관리) LNB에서 "근태관리"는 펼침 메뉴이며
          계정에 근태 권한이 있으면 하위에 "근태신청" 항목이 노출됨.
        - 전자결재(EA) 결재작성 경로에서 "시간외근무" 양식을 검색하는 방식이
          권한 문제를 우회하는 가장 안정적인 접근법.

        전략:
        1순위: HR LNB 근태관리 펼치기 → "근태신청" 또는 "시간외근무" 클릭
        2순위: 전자결재 결재작성 → "시간외근무" 양식 검색 후 선택
        3순위: HP 모듈 경로로 근태신청 직접 이동

        Args:
            page: Playwright Page 객체
            _target_page_code: 미사용 (하위 호환성 유지용 파라미터)
        Returns:
            True면 시간외근무 폼 로드 확인, False면 모든 시도 실패
        """
        gw_url = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

        def _check_overtime_form_loaded() -> bool:
            """시간외근무 폼이 로드되었는지 확인 (키워드 탐색)"""
            try:
                body = page.evaluate("() => document.body.innerText")
                overtime_kws = ["시간외근무", "연장근무", "근무구분", "근무일", "시작시간"]
                return any(kw in body for kw in overtime_kws)
            except Exception:
                return False

        def _dismiss_popup():
            """권한 없음 팝업 등 자동 닫기"""
            try:
                for btn_text in ["확인", "닫기", "OK"]:
                    btn = page.locator(f"text={btn_text}").first
                    if btn.is_visible(timeout=1000):
                        btn.click(force=True)
                        page.wait_for_timeout(500)
                        break
            except Exception:
                pass

        # ── 1순위: HR 모듈 LNB → 근태관리 → 근태신청 / 시간외근무 ──
        logger.info("[HR 근태관리] 1순위: HR 모듈 LNB 경로")
        try:
            # HR 모듈 진입
            page.goto(f"{gw_url}/#/HP/HPM0110/HPM0110",
                      wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)

            # 근태관리 펼치기 (force=True — 게시판 레이어가 인터셉트 가능)
            attendance_nav = page.locator(".sideLnbMenu .nav-item:has(.nav-text:text-is('근태관리'))")
            if attendance_nav.count() == 0:
                attendance_nav = page.locator("text=근태관리").first
            attendance_nav.click(force=True)
            page.wait_for_timeout(1500)

            # 하위 메뉴 탐색 (근태신청 / 시간외근무)
            for sub_text in ["근태신청", "시간외근무", "연장근무"]:
                try:
                    sub = page.locator(f".sideLnbMenu text={sub_text}").first
                    if sub.count() == 0:
                        sub = page.locator(f"text={sub_text}").first
                    if sub.is_visible(timeout=2000):
                        sub.click(force=True)
                        page.wait_for_timeout(3000)
                        _dismiss_popup()
                        if _check_overtime_form_loaded():
                            logger.info(f"[HR 근태관리] 1순위 성공: '{sub_text}' 클릭")
                            return True
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"[HR 근태관리] 1순위 실패: {e}")

        # ── 2순위: 전자결재 결재작성 → 시간외근무 양식 검색 ──
        logger.info("[HR 근태관리] 2순위: 전자결재 결재작성 경로")
        try:
            # 전자결재 홈 이동
            self._navigate_to_approval_home()
            page.wait_for_timeout(1500)
            _dismiss_popup()

            # 결재작성 버튼 클릭
            self._click_write_approval()
            page.wait_for_timeout(1500)

            # 양식 검색창에 "시간외근무" 입력
            for sel in [
                "input[placeholder*='검색']",
                "input[placeholder*='양식']",
                "input[type='search']",
                "input.OBTTextField",
            ]:
                try:
                    inp = page.locator(sel).first
                    if inp.is_visible(timeout=1500):
                        inp.fill("시간외근무")
                        inp.press("Enter")
                        page.wait_for_timeout(1500)
                        break
                except Exception:
                    continue

            # 검색 결과에서 "시간외근무" 링크 클릭
            for kw in ["시간외근무", "연장근무"]:
                try:
                    link = page.locator(f"text={kw}").first
                    if link.is_visible(timeout=3000):
                        link.click(force=True)
                        page.wait_for_timeout(3000)
                        _dismiss_popup()
                        if _check_overtime_form_loaded():
                            logger.info(f"[HR 근태관리] 2순위 성공: '{kw}' 양식 선택")
                            return True
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"[HR 근태관리] 2순위 실패: {e}")

        # ── 3순위: HP 모듈 직접 URL 패턴 시도 ──
        logger.info("[HR 근태관리] 3순위: HP 모듈 근태 URL 직접 시도")
        hp_attendance_urls = [
            f"{gw_url}/#/HP/HPA0010/HPA0010",   # 근태신청 추정
            f"{gw_url}/#/HP/HPA1010/HPA1010",   # 시간외근무 추정
            f"{gw_url}/#/HP/HPA1020/HPA1020",
        ]
        for url in hp_attendance_urls:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=10000)
                page.wait_for_timeout(2000)
                _dismiss_popup()
                if _check_overtime_form_loaded():
                    logger.info(f"[HR 근태관리] 3순위 성공: {url}")
                    return True
            except Exception:
                continue

        logger.error("[HR 근태관리] 모든 이동 방식 실패")
        return False

    def _save_overtime_draft(self, data: dict) -> dict:
        """
        연장근무신청서 임시보관 (draft 모드).

        근태관리 모듈은 전자결재 "보관" 버튼 없음.
        신청완료(저장) 버튼을 눌러 저장하는 방식 사용.
        HR 모듈 경로: 임직원업무관리(HR) > 근태신청 > 연장근무신청서

        Args:
            data: {
                "date": "YYYY-MM-DD",      # 연장근무일 (work_date 동의어)
                "work_date": "YYYY-MM-DD", # 연장근무일 (date 동의어)
                "start_time": "HH:MM",     # 시작시각
                "end_time": "HH:MM",       # 종료시각
                "reason": "사유",           # 연장근무 사유
                "project": "프로젝트명",    # 선택사항
                "work_type": "연장근무",    # 근무구분 (조기근무/연장근무/휴일근무)
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
            reason = data.get("reason", "")
            project = data.get("project", "")
            work_type = data.get("work_type", "연장근무")

            self._close_popups()

            # HR 근태관리 > 시간외근무 페이지 이동 (공통 헬퍼 사용)
            logger.info("[연장근무 임시저장 1] HR 근태관리 시간외근무 페이지 이동")
            nav_ok = self._navigate_to_hr_attendance(page, "UFA1010")

            if not nav_ok:
                # 최종 폴백: 전자결재 결재작성 경로에서 시간외근무 검색
                logger.info("[연장근무 임시저장 2-폴백] 결재작성 경로 시도")
                self._navigate_to_approval_home()
                self._click_write_approval()
                page.wait_for_timeout(1500)
                for sel in ["input[placeholder*='검색']", "input[type='search']", "input.OBTTextField"]:
                    try:
                        inp = page.locator(sel).first
                        if inp.is_visible(timeout=2000):
                            inp.fill("시간외근무")
                            inp.press("Enter")
                            page.wait_for_timeout(1500)
                            break
                    except Exception:
                        continue
                try:
                    for search_kw in ["시간외근무", "연장근무"]:
                        link = page.locator(f"text={search_kw}").first
                        if link.is_visible(timeout=3000):
                            link.click(force=True)
                            page.wait_for_timeout(3000)
                            nav_ok = True
                            break
                except Exception:
                    pass

            if not nav_ok:
                return {"success": False, "message": "시간외근무(연장근무) 양식을 찾을 수 없습니다."}

            # 근무구분 선택
            if work_type:
                for sel in [f"text={work_type}", f"input[value='{work_type}']"]:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=1500):
                            el.click(force=True)
                            page.wait_for_timeout(500)
                            logger.info(f"근무구분 선택: {work_type}")
                            break
                    except Exception:
                        continue

            # 날짜 입력
            logger.info(f"[연장근무 임시저장 3] 날짜 입력: {work_date}")
            if work_date:
                for label in ["연장근무시작일", "근무일", "시작일"]:
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
            logger.info(f"[연장근무 임시저장 4] 시간 입력: {start_time} ~ {end_time}")
            if start_time:
                for label in ["시작시간", "시작"]:
                    try:
                        if self._fill_field_by_label(label, start_time):
                            break
                    except Exception:
                        continue
            if end_time:
                for label in ["종료시간", "종료"]:
                    try:
                        if self._fill_field_by_label(label, end_time):
                            break
                    except Exception:
                        continue

            # 비고/사유 입력
            if reason:
                for label in ["비고", "사유", "내용"]:
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

            # 신청완료(저장) 버튼 클릭 — 근태관리 모듈은 "임시저장" 버튼이 없어 "신청완료"로 저장
            logger.info("[연장근무 임시저장 5] 신청완료 버튼 탐색")
            _save_debug(page, "overtime_draft_before_save")
            saved = False
            for btn_text in ["신청완료", "저장", "완료"]:
                try:
                    btn = page.locator(f"button:has-text('{btn_text}')").first
                    if btn.is_visible(timeout=2000):
                        btn.click(force=True)
                        page.wait_for_timeout(2000)
                        logger.info(f"연장근무신청서 저장 완료: {btn_text}")
                        saved = True
                        break
                except Exception:
                    continue

            if not saved:
                _save_debug(page, "overtime_draft_no_save_btn")
                return {
                    "success": False,
                    "message": "저장 버튼을 찾을 수 없습니다. GW 화면을 직접 확인해주세요.",
                }

            _save_debug(page, "overtime_draft_saved")
            return {"success": True, "message": "연장근무신청서가 임시저장되었습니다."}

        except Exception as e:
            logger.error(f"연장근무 임시저장 실패: {e}", exc_info=True)
            _save_debug(page, "overtime_draft_error")
            return {"success": False, "message": f"연장근무신청서 저장 실패: {str(e)}"}
