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
"""
import time
import logging
from pathlib import Path
from playwright.sync_api import Page, BrowserContext, TimeoutError as PlaywrightTimeout
from src.approval.form_templates import resolve_approval_line, resolve_cc_recipients

logger = logging.getLogger("approval_automation")

GW_URL = "https://gw.glowseoul.co.kr"

# 스크린샷 저장 디렉토리
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "approval_screenshots"

# 재시도 설정
MAX_RETRIES = 3
RETRY_DELAY = 3  # 초


def _save_debug(page: Page, name: str):
    """디버그용 스크린샷 저장"""
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path))
        logger.info(f"스크린샷: {path}")
    except Exception as e:
        logger.warning(f"스크린샷 저장 실패: {e}")


def _parse_project_text(text: str) -> dict:
    """
    프로젝트 코드도움 드롭다운 텍스트를 파싱.

    형식 예: "GS-25-0088. [종로] 메디빌더 음향공사"
              "GS-25-0031. [단양] 고수동굴"

    Returns:
        {"code": "GS-25-0088", "name": "[종로] 메디빌더 음향공사", "full_text": "GS-25-0088. [종로] 메디빌더 음향공사"}
    """
    text = text.strip()
    # "코드. 이름" 형식 분리
    if ". " in text:
        parts = text.split(". ", 1)
        code = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else ""
    else:
        code = ""
        name = text
    return {"code": code, "name": name, "full_text": text}


class ApprovalAutomation:
    """전자결재 폼 자동화 클래스"""

    def __init__(self, page: Page, context: BrowserContext = None):
        self.page = page
        self.context = context
        # 다이얼로그 자동 수락 (한 번만 등록)
        page.on("dialog", lambda d: d.accept())

    # ─────────────────────────────────────────
    # 공통 유틸: 세션/팝업/검증
    # ─────────────────────────────────────────

    def _check_session_valid(self) -> bool:
        """세션이 유효한지 확인 (로그인 페이지로 리다이렉트 여부)"""
        try:
            url = self.page.url.lower()
            if "/login" in url:
                logger.error("세션 만료: 로그인 페이지로 리다이렉트됨")
                return False
            return True
        except Exception:
            return False

    def _close_popups(self):
        """열린 팝업 페이지 자동 닫기"""
        if not self.context:
            return
        try:
            main_page = self.page
            for p in self.context.pages:
                if p != main_page:
                    try:
                        p_url = p.url or ""
                        if "popup" in p_url or p_url == "about:blank":
                            p.close()
                            logger.debug(f"팝업 닫기: {p_url[:60]}")
                    except Exception:
                        pass
        except Exception:
            pass

    def _validate_required_fields(self, data: dict, required_keys: list[str], form_name: str) -> dict | None:
        """
        필수 필드 검증. 누락 시 에러 dict 반환, 통과 시 None.
        """
        missing = [k for k in required_keys if not data.get(k)]
        if missing:
            # 키 → 한국어 라벨 변환
            label_map = {
                "title": "제목", "date": "지출일", "amount": "금액",
                "project": "프로젝트", "vendor_name": "거래처명",
                "work_date": "날짜", "reason": "사유",
                "destination": "방문처", "purpose": "사유/목적",
                "start_time": "시작시간", "end_time": "종료시간",
            }
            labels = [label_map.get(k, k) for k in missing]
            msg = f"{form_name} 작성에 필요한 정보가 부족합니다: {', '.join(labels)}"
            return {"success": False, "message": msg}
        return None

    # ─────────────────────────────────────────
    # 결재선 설정
    # ─────────────────────────────────────────

    def set_approval_line(self, page: Page, approval_line: dict) -> bool:
        """
        결재선 동적 설정 (GW 결재선 팝업 조작)

        GW 결재선 UI 흐름:
        1. "결재선" 또는 "결재선 설정" 버튼 클릭 → 팝업 열림
        2. 기존 결재선 초기화 (선택적)
        3. 결재자 검색 입력 → 선택 → 결재 단계 지정
        4. 확인 버튼 클릭

        Args:
            page: 결재 양식 페이지 (팝업 포함)
            approval_line: {
                "drafter": "auto",      # 기안자 (auto=현재 로그인 사용자)
                "agree": "신동관",       # 검토자 (선택)
                "final": "최기영",       # 최종 승인자
                "cc": ["재무전략팀"],    # 수신참조 (선택)
            }

        Returns:
            bool: 설정 성공 여부 (실패해도 기본 결재선 유지)
        """
        if not approval_line:
            return False

        # 기안자는 자동 (로그인 사용자) — 건너뜀
        agree = approval_line.get("agree", "")
        final = approval_line.get("final", "")
        cc_list = approval_line.get("cc", [])

        # 결재선 설정 버튼 탐색
        line_btn = None
        for selector in [
            "div.topBtn:has-text('결재선')",
            "button:has-text('결재선')",
            "a:has-text('결재선')",
            "span:has-text('결재선')",
            "[title*='결재선']",
        ]:
            try:
                candidates = page.locator(selector).all()
                for c in candidates:
                    if c.is_visible(timeout=1000):
                        txt = (c.inner_text() or "").strip()
                        if "결재선" in txt:
                            line_btn = c
                            break
                if line_btn:
                    break
            except Exception:
                continue

        if not line_btn:
            logger.warning("결재선 버튼을 찾을 수 없음 — 기본 결재선 유지")
            return False

        # 결재선 팝업 열기
        pages_before = set(self.context.pages) if self.context else set()
        try:
            line_btn.click(force=True)
            logger.info("결재선 버튼 클릭")
        except Exception as e:
            logger.warning(f"결재선 버튼 클릭 실패: {e}")
            return False

        # 팝업 또는 동적 레이어 대기
        line_page = None
        if self.context:
            for _ in range(10):
                current_pages = set(self.context.pages)
                new_pages = current_pages - pages_before
                for p in new_pages:
                    try:
                        if p.url and p.url != "about:blank":
                            line_page = p
                            break
                    except Exception:
                        continue
                if line_page:
                    break
                page.wait_for_timeout(500)

        # 팝업이 없으면 현재 페이지의 레이어/모달로 처리
        target = line_page or page

        if line_page:
            try:
                line_page.wait_for_load_state("domcontentloaded", timeout=8000)
                line_page.on("dialog", lambda d: d.accept())
            except Exception:
                pass

        logger.info(f"결재선 팝업/레이어 대상: {target.url[:60] if target else 'none'}")

        # 결재자 추가 헬퍼
        def _add_approver(name: str, role: str) -> bool:
            """결재자 검색 후 추가"""
            if not name or name == "auto":
                return True

            # 검색 입력란 찾기
            search_input = None
            for sel in [
                "input[placeholder*='이름']",
                "input[placeholder*='성명']",
                "input[placeholder*='검색']",
                "input[type='text']:visible",
            ]:
                try:
                    inp = target.locator(sel).first
                    if inp.is_visible(timeout=2000):
                        search_input = inp
                        break
                except Exception:
                    continue

            if not search_input:
                logger.warning(f"결재선 검색 입력란 미발견 ({role}: {name})")
                return False

            try:
                search_input.click()
                search_input.fill(name)
                search_input.press("Enter")
                target.wait_for_timeout(1000)

                # 검색 결과에서 이름 클릭
                result_el = target.locator(f"text={name}").first
                if result_el.is_visible(timeout=3000):
                    result_el.click(force=True)
                    logger.info(f"결재선 {role} 추가: {name}")
                    target.wait_for_timeout(500)
                    return True
            except Exception as e:
                logger.warning(f"결재선 {role} '{name}' 추가 실패: {e}")
            return False

        # 검토자 추가
        if agree:
            _add_approver(agree, "검토자")

        # 최종 승인자 추가
        if final:
            _add_approver(final, "최종승인자")

        # 수신참조 추가
        for cc_name in cc_list:
            _add_approver(cc_name, f"수신참조({cc_name})")

        # 확인 버튼 클릭
        for sel in ["button:has-text('확인')", "button:has-text('저장')", "button:has-text('적용')"]:
            try:
                btn = target.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click(force=True)
                    logger.info("결재선 확인 버튼 클릭")
                    target.wait_for_timeout(500)
                    break
            except Exception:
                continue

        # 팝업이면 닫기
        if line_page:
            try:
                if not line_page.is_closed():
                    line_page.close()
            except Exception:
                pass

        return True

    def set_cc_recipients(self, page: Page, cc_list: list[str]) -> bool:
        """
        수신참조(CC) 자동 설정

        Args:
            page: 결재 양식 페이지
            cc_list: 수신참조 이름/팀명 목록

        Returns:
            bool: 설정 성공 여부
        """
        if not cc_list:
            return True

        # 수신참조 버튼 탐색
        cc_btn = None
        for selector in [
            "div.topBtn:has-text('수신참조')",
            "button:has-text('수신참조')",
            "a:has-text('수신참조')",
            "[title*='수신참조']",
            "div.topBtn:has-text('참조')",
            "button:has-text('참조')",
        ]:
            try:
                candidates = page.locator(selector).all()
                for c in candidates:
                    if c.is_visible(timeout=1000):
                        cc_btn = c
                        break
                if cc_btn:
                    break
            except Exception:
                continue

        if not cc_btn:
            logger.warning("수신참조 버튼 미발견 — 수신참조 설정 스킵")
            return False

        try:
            cc_btn.click(force=True)
            page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning(f"수신참조 버튼 클릭 실패: {e}")
            return False

        # 각 수신참조 대상 추가
        success_count = 0
        for cc_name in cc_list:
            try:
                # 검색 입력
                search_input = page.locator("input[placeholder*='검색'], input[placeholder*='이름'], input[type='text']:visible").first
                if search_input.is_visible(timeout=2000):
                    search_input.fill(cc_name)
                    search_input.press("Enter")
                    page.wait_for_timeout(1000)

                    # 결과 클릭
                    result = page.locator(f"text={cc_name}").first
                    if result.is_visible(timeout=2000):
                        result.click(force=True)
                        page.wait_for_timeout(500)
                        success_count += 1
                        logger.info(f"수신참조 추가: {cc_name}")
            except Exception as e:
                logger.warning(f"수신참조 '{cc_name}' 추가 실패: {e}")

        # 확인
        for sel in ["button:has-text('확인')", "button:has-text('저장')"]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click(force=True)
                    break
            except Exception:
                continue

        logger.info(f"수신참조 설정 완료: {success_count}/{len(cc_list)}개")
        return success_count > 0

    # ─────────────────────────────────────────
    # 지출결의서
    # ─────────────────────────────────────────

    def create_expense_report(self, data: dict) -> dict:
        """
        지출결의서 작성 + 보관(임시저장) (재시도 포함)

        Args:
            data: {
                "title": "결의서 제목",           # 필수
                "date": "2026-03-01",             # 증빙일자 (YYYY-MM-DD)
                "receipt_date": "2026-03-01",     # 증빙일자 (date와 동일, 우선)
                "description": "내용 설명",       # 선택
                "project": "GS-25-0088",          # 프로젝트 코드 또는 이름 일부 (상단+하단 모두 입력)
                "items": [                        # 지출내역 그리드
                    {
                        "item": "항목명",         # or "content"
                        "amount": 100000,         # or "supply_amount" (공급가액)
                        "tax_amount": 10000,      # 부가세 (선택)
                        "vendor": "거래처명",     # 선택
                    }
                ],
                "evidence_type": "세금계산서",    # 증빙유형: 세금계산서|계산서내역|카드사용내역|현금영수증
                "attachment_path": "/path.pdf",   # 첨부파일 경로 (선택, 수동 지정)
                "auto_capture_budget": True,      # 예실대비현황 스크린샷 자동 캡처+첨부 (선택)
            }
        Returns:
            {"success": bool, "message": str}
        """
        # 필수 필드 검증
        validation = self._validate_required_fields(data, ["title"], "지출결의서")
        if validation:
            return validation

        # 세션 확인
        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._close_popups()

                # 1. 전자결재 모듈 → 결재 HOME 이동
                self._navigate_to_approval_home()

                # 2. 추천양식에서 "[프로젝트]지출결의서" 클릭
                self._click_expense_form()

                # 3. 양식 로드 대기
                self._wait_for_form_load()

                # 4. 필드 채우기
                self._fill_expense_fields(data)

                # 4-1. 결재선 커스텀 설정 (data에 approval_line 키 있을 때)
                if data.get("approval_line"):
                    resolved_line = resolve_approval_line(data["approval_line"], "지출결의서")
                    self.set_approval_line(self.page, resolved_line)

                # 4-2. 수신참조 설정 (data에 cc 키 있을 때)
                if data.get("cc"):
                    resolved_cc = resolve_cc_recipients(data["cc"], "지출결의서")
                    self.set_cc_recipients(self.page, resolved_cc)

                # 5. 보관 (임시저장)
                return self._save_draft()

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"지출결의서 작성 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                _save_debug(self.page, f"error_timeout_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    # 세션 재확인
                    if not self._check_session_valid():
                        return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}
                    self._close_popups()
                    time.sleep(RETRY_DELAY)

            except Exception as e:
                last_error = e
                logger.error(f"지출결의서 작성 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        # 모든 재시도 실패
        _save_debug(self.page, "error_final")
        return {"success": False, "message": f"지출결의서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def _navigate_to_approval_home(self):
        """전자결재 모듈 HOME으로 이동 (세션 확인 포함)"""
        page = self.page

        # 세션 만료 확인
        if not self._check_session_valid():
            raise RuntimeError("세션이 만료되었습니다.")

        self._close_popups()

        # 전자결재 모듈 아이콘 클릭 (span.module-link.EA)
        ea_link = page.locator("span.module-link.EA").first
        try:
            if ea_link.is_visible(timeout=5000):
                ea_link.click(force=True)
                logger.info("전자결재 모듈 클릭")
            else:
                raise PlaywrightTimeout("전자결재 모듈 링크 미발견")
        except PlaywrightTimeout:
            # 대안: text로 찾기
            try:
                page.locator("text=전자결재").first.click(force=True)
            except Exception:
                raise RuntimeError("전자결재 모듈을 찾을 수 없습니다. 그룹웨어 메인 페이지인지 확인해주세요.")
        except Exception:
            page.locator("text=전자결재").first.click(force=True)

        # 결재 HOME 확인 (클릭 후 페이지 로드 대기)
        try:
            page.wait_for_selector("text=결재 HOME", timeout=12000)
            logger.info("결재 HOME 도달")
        except Exception:
            # 로그인 페이지 리다이렉트 확인
            if not self._check_session_valid():
                raise RuntimeError("세션이 만료되었습니다.")
            logger.warning("결재 HOME 텍스트 미발견, 계속 진행")

        self._close_popups()
        _save_debug(page, "01_approval_home")

    def _click_expense_form(self):
        """추천양식에서 지출결의서 클릭"""
        page = self.page

        # 추천양식에서 "[프로젝트]지출결의서" 찾기
        for keyword in ["[프로젝트]지출결의서", "프로젝트]지출", "지출결의서"]:
            try:
                links = page.locator(f"text={keyword}").all()
                for link in links:
                    if link.is_visible():
                        link.click(force=True)
                        logger.info(f"양식 클릭: '{keyword}'")
                        return
            except Exception:
                continue

        raise Exception("지출결의서 양식을 찾을 수 없습니다.")

    def _wait_for_form_load(self):
        """양식 폼 로드 대기 (URL 변경 + input 요소 확인, 재시도 포함)"""
        page = self.page

        self._close_popups()

        # URL에 양식 페이지 포함될 때까지 대기 (APB1020=지출결의서, HP=양식 전체)
        try:
            page.wait_for_url("**/HP/**", timeout=15000)
            logger.info(f"결재작성 페이지 로드 확인: {page.url[:100]}")
        except PlaywrightTimeout:
            # 세션 만료 확인
            if not self._check_session_valid():
                raise RuntimeError("세션이 만료되었습니다.")
            # HP 패턴 실패해도 팝업으로 열렸을 수 있으므로 계속 진행
            logger.warning(f"HP URL 대기 타임아웃, 현재: {page.url[:100]}")
        except Exception:
            logger.warning(f"URL 대기 중 오류, 현재: {page.url[:100]}")

        self._close_popups()

        # 제목 필드가 보이는지 확인 (최대 20초, 재시도)
        form_loaded = False
        for attempt in range(2):
            try:
                page.locator("th:has-text('제목')").first.wait_for(state="visible", timeout=10000)
                logger.info("양식 필드 로드 완료")
                form_loaded = True
                break
            except PlaywrightTimeout:
                if attempt == 0:
                    logger.info("양식 로드 재시도 중...")
                    self._close_popups()
                    page.wait_for_timeout(2000)

        if not form_loaded:
            _save_debug(page, "error_form_not_loaded")
            raise RuntimeError("양식 로드 실패: 제목 필드를 찾을 수 없습니다. 네트워크 상태를 확인해주세요.")

        _save_debug(page, "02_form_loaded")

    def _fill_field_by_label(self, label: str, value: str) -> bool:
        """
        테이블 라벨(th) 기반 필드 채우기
        DOM 구조: table.OBTFormPanel_table > tr > th(라벨) + td(input)
        """
        page = self.page
        try:
            # th에서 라벨 텍스트 찾기
            th_el = page.locator(f"th:has-text('{label}')").first
            if not th_el.is_visible(timeout=2000):
                return False

            # th의 형제 td에서 input 찾기
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

    def _fill_field_by_placeholder(self, placeholder: str, value: str) -> bool:
        """placeholder 기반 필드 채우기"""
        page = self.page
        try:
            inp = page.locator(f"input[placeholder='{placeholder}']").first
            if inp.is_visible(timeout=2000):
                inp.click(force=True)
                inp.fill("")
                inp.fill(str(value))
                logger.info(f"필드 ph='{placeholder}' 입력: {value}")
                return True
        except Exception as e:
            logger.debug(f"필드 ph='{placeholder}' 입력 실패: {e}")
        return False

    def _fill_expense_fields(self, data: dict):
        """
        지출결의서 필드 채우기

        Phase 0에서 확인된 필드 구조:
        - 테이블 0 (상단): 회계단위, 회계처리일자, 품의서, 첨부파일, 프로젝트, 전표구분, 제목, 자금집행
        - 지출내역 그리드: 용도, 내용, 거래처, 공급가액, 부가세, ...
        - 테이블 7 (하단): 증빙일자, 지급요청일, 사원, 은행/계좌, 예금주, 사용부서, 프로젝트, 예산

        Task #4 추가 필드:
        - project: 프로젝트 코드도움 (상단 + 하단 테이블 모두 입력)
        - receipt_date: 증빙일자 (YYYY-MM-DD)
        - evidence_type: 증빙유형 ('세금계산서'|'계산서내역'|'카드사용내역'|'현금영수증')
        - attachment_path: 첨부파일 경로 (로컬 파일 또는 스크린샷)
        - auto_capture_budget: True이면 예실대비현황 스크린샷 캡처 후 첨부파일로 자동 업로드
        """
        page = self.page
        title = data.get("title", "")
        items = data.get("items", [])

        # 1. 프로젝트 코드도움 입력 (상단, y≈292)
        project = data.get("project", "")
        if project:
            self._fill_project_code(project, y_hint=292)
            _save_debug(page, "03a_after_project_top")

        # 2. 제목 입력 (th="제목" → td > input)
        if title:
            self._fill_field_by_label("제목", title)

        # 3. 제목 못 찾았으면 좌표 기반 (rect y=332 영역)
        if title and not self._check_field_has_value("제목", title):
            try:
                title_inputs = page.locator("table.OBTFormPanel_table__1fRyk input[type='text']:visible").all()
                for inp in title_inputs:
                    val = inp.get_attribute("value") or ""
                    ph = inp.get_attribute("placeholder") or ""
                    if not val and not ph:
                        box = inp.bounding_box()
                        if box and 310 < box["y"] < 360:
                            inp.fill(title)
                            logger.info(f"제목 입력 (좌표 기반): {title}")
                            break
            except Exception:
                pass

        _save_debug(page, "03_after_title")

        # 4. 지출내역 그리드 입력
        if items:
            self._fill_grid_items(items)
            _save_debug(page, "03b_after_grid")

        # 5. 증빙유형 버튼 클릭 (그리드 상단 버튼: 계산서내역, 카드사용내역, 현금영수증)
        evidence_type = data.get("evidence_type", "")
        if evidence_type:
            self._click_evidence_type_button(evidence_type)
            _save_debug(page, "03c_after_evidence")

            # 5-1. 세금계산서 팝업 검색: invoice 정보가 있을 때만 실행
            _is_invoice_type = evidence_type in ("세금계산서", "계산서", "계산서내역")
            invoice_vendor = data.get("invoice_vendor", "")
            invoice_amount = data.get("invoice_amount")
            invoice_date = data.get("invoice_date", "") or data.get("date", "")
            if _is_invoice_type and (invoice_vendor or invoice_amount):
                # 팝업이 열렸을 때만 선택 시도
                self._select_invoice_from_popup(
                    vendor=invoice_vendor,
                    amount=invoice_amount,
                    date_from=invoice_date,
                    date_to=invoice_date,
                )
                _save_debug(page, "03c2_after_invoice_select")

        # 6. 증빙일자 입력 (하단 테이블, y=857)
        receipt_date = data.get("receipt_date", "") or data.get("date", "")
        if receipt_date:
            self._fill_receipt_date(receipt_date)
            _save_debug(page, "03d_after_receipt_date")

        # 7. 하단 테이블 프로젝트 코드도움 입력 (y≈857 근처, 테이블 7)
        if project:
            self._fill_project_code_bottom(project)
            _save_debug(page, "03d2_after_project_bottom")

        # 8. 첨부파일 업로드 (수동 경로 지정)
        attachment_path = data.get("attachment_path", "")
        if attachment_path:
            self._upload_attachment(attachment_path)
            _save_debug(page, "03e_after_attachment")

        # 9. 예실대비현황 자동 캡처 후 첨부 (auto_capture_budget=True 시)
        if data.get("auto_capture_budget") and not attachment_path:
            self._capture_and_attach_budget_screenshot()
            _save_debug(page, "03f_after_budget_capture")

    # ─────────────────────────────────────────
    # 지출내역 그리드 입력
    # ─────────────────────────────────────────

    # 그리드 컬럼 헤더 텍스트 → 인덱스 매핑 (0-based, 체크박스 제외)
    # ─────────────────────────────────────────
    # Task #4: 프로젝트 코드도움 / 증빙유형 / 증빙일자 / 첨부파일
    # ─────────────────────────────────────────

    def _fill_project_code(self, project: str, y_hint: float = None):
        """
        프로젝트 코드도움 자동완성 입력.

        GW 자동완성 위젯 동작:
        1. placeholder="프로젝트코드도움" input 클릭
        2. 검색어 입력 (프로젝트 코드 또는 이름 일부)
        3. 드롭다운 첫 번째 항목 Enter 또는 클릭으로 선택

        DOM 좌표: x=838, y=292 (상단 테이블) / y=857 근처 (하단 테이블)

        Args:
            project: 프로젝트 코드 또는 이름 일부 (예: 'GS-25-0088')
            y_hint: 특정 y좌표 근처 input 선택 시 사용 (None이면 첫 번째 visible)
        """
        page = self.page
        try:
            # placeholder로 input 목록 찾기
            all_proj_inputs = page.locator("input[placeholder='프로젝트코드도움']").all()
            proj_input = None

            if y_hint is not None:
                # y 좌표 힌트에 가장 가까운 input 선택
                best_dist = float("inf")
                for inp in all_proj_inputs:
                    try:
                        box = inp.bounding_box()
                        if box:
                            dist = abs(box["y"] - y_hint)
                            if dist < best_dist:
                                best_dist = dist
                                proj_input = inp
                    except Exception:
                        continue
            else:
                # 첫 번째 visible input 사용
                for inp in all_proj_inputs:
                    try:
                        if inp.is_visible(timeout=1000):
                            proj_input = inp
                            break
                    except Exception:
                        continue

            if proj_input and proj_input.is_visible(timeout=3000):
                proj_input.click(force=True)
                proj_input.fill("")
                proj_input.type(project, delay=60)  # delay=60ms: 자동완성 트리거
                logger.info(f"프로젝트 검색어 입력: {project}")

                # 자동완성 드롭다운 대기 (GW OBT 위젯 셀렉터 다수 시도)
                dropdown_selectors = [
                    "ul[class*='autocomplete'] li",
                    "div[class*='OBTAutoComplete'] li",
                    "div[class*='suggest'] li",
                    "div[class*='dropdown'] li",
                    "div[class*='list'] li",
                    "li[class*='item']",
                ]
                for sel in dropdown_selectors:
                    try:
                        dropdown_item = page.locator(sel).first
                        if dropdown_item.is_visible(timeout=1500):
                            dropdown_item.click()
                            logger.info(f"프로젝트 드롭다운 항목 클릭: {sel}")
                            return True
                    except Exception:
                        continue

                # 폴백: Enter 키로 첫 번째 항목 선택
                proj_input.press("Enter")
                logger.info("프로젝트 Enter 선택")
                # Enter 후 값 확정 대기
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                return True
        except Exception as e:
            logger.debug(f"프로젝트 코드도움 입력 실패 (selector): {e}")

        # 폴백: 좌표 기반
        fallback_y = y_hint if y_hint is not None else 292
        fallback_x = 838
        try:
            page.mouse.click(fallback_x, fallback_y)
            page.keyboard.type(project, delay=60)
            page.keyboard.press("Enter")
            logger.info(f"프로젝트 입력 (좌표 폴백 {fallback_x},{fallback_y}): {project}")
            return True
        except Exception as e:
            logger.warning(f"프로젝트 코드도움 좌표 폴백도 실패: {e}")
        return False

    def _click_evidence_type_button(self, evidence_type: str):
        """
        증빙유형 버튼 클릭 (그리드 상단).

        지원 유형 및 DOM 좌표 (form_frame_buttons.json 기준):
        - '세금계산서' / '계산서내역': x=1476, y=373
        - '카드사용내역': x=1384, y=373
        - '현금영수증': x=1557, y=373

        Args:
            evidence_type: '세금계산서', '계산서내역', '카드사용내역', '현금영수증'
        """
        page = self.page

        # 버튼 텍스트 정규화
        type_map = {
            "세금계산서": "계산서내역",
            "계산서": "계산서내역",
            "계산서내역": "계산서내역",
            "카드": "카드사용내역",
            "카드사용": "카드사용내역",
            "카드사용내역": "카드사용내역",
            "현금영수증": "현금영수증",
            "현금": "현금영수증",
        }
        btn_text = type_map.get(evidence_type, evidence_type)

        # 버튼 좌표 (DOM 데이터 기준)
        coord_map = {
            "계산서내역": (1476, 373),
            "카드사용내역": (1384, 373),
            "현금영수증": (1557, 373),
        }

        # selector로 먼저 시도
        try:
            btns = page.locator(f"button:has-text('{btn_text}')").all()
            for btn in btns:
                if btn.is_visible():
                    box = btn.bounding_box()
                    if box and 340 < box["y"] < 420:
                        btn.click(force=True)
                        logger.info(f"증빙유형 버튼 클릭: '{btn_text}'")
                        return True
        except Exception:
            pass

        # 폴백: 좌표 클릭
        coords = coord_map.get(btn_text)
        if coords:
            try:
                page.mouse.click(*coords)
                logger.info(f"증빙유형 버튼 클릭 (좌표 {coords}): '{btn_text}'")
                return True
            except Exception as e:
                logger.warning(f"증빙유형 좌표 클릭 실패: {e}")

        logger.warning(f"증빙유형 버튼 미발견: '{evidence_type}'")
        return False

    def _select_invoice_from_popup(
        self,
        vendor: str = "",
        amount: float = None,
        date_from: str = "",
        date_to: str = "",
    ) -> bool:
        """
        계산서내역 팝업에서 세금계산서를 검색/선택하여 지출결의서에 연결.

        흐름:
        1. 팝업이 열릴 때까지 대기 (계산서내역 버튼 클릭은 _fill_expense_fields에서 수행)
        2. 기간 확장 설정 (date_from~date_to 또는 당월 ±3개월)
        3. 거래처명 입력 후 검색
        4. 결과 목록에서 vendor/amount 일치 항목 선택
        5. 확인/선택 버튼 클릭 → 팝업 닫힘

        Args:
            vendor:    거래처명 (예: '주식회사 ABC'). 빈 문자열이면 전체 조회.
            amount:    금액 (원). None이면 금액 매칭 건너뜀.
            date_from: 조회 시작일 (YYYYMMDD 또는 YYYY-MM-DD). 빈 문자열이면 자동계산.
            date_to:   조회 종료일 (YYYYMMDD 또는 YYYY-MM-DD). 빈 문자열이면 자동계산.

        Returns:
            True if 세금계산서 선택 성공
        """
        import datetime as _dt

        page = self.page

        # 날짜 포맷 정규화 YYYYMMDD
        def _norm_date(d: str) -> str:
            return d.replace("-", "")[:8]

        # 기본 기간: 당월 기준 ±3개월
        today = _dt.date.today()
        if not date_from:
            start = (today.replace(day=1) - _dt.timedelta(days=60)).replace(day=1)
            date_from = start.strftime("%Y%m%d")
        else:
            date_from = _norm_date(date_from)

        if not date_to:
            # 이번 달 말일
            next_month = today.replace(day=28) + _dt.timedelta(days=4)
            date_to = next_month.replace(day=1) - _dt.timedelta(days=1)
            date_to = date_to.strftime("%Y%m%d")
        else:
            date_to = _norm_date(date_to)

        logger.info(f"계산서내역 팝업 검색 — vendor='{vendor}' amount={amount} 기간={date_from}~{date_to}")

        # 팝업 페이지 대기 (context.pages에 새 팝업 추가 또는 모달 레이어)
        popup_page = None
        if self.context:
            pages_before = set(id(p) for p in self.context.pages)
            for _ in range(20):  # 최대 5초 대기
                current = self.context.pages
                for p in current:
                    if id(p) not in pages_before:
                        popup_page = p
                        break
                if popup_page:
                    break
                page.wait_for_timeout(250)

        target = popup_page or page

        if popup_page:
            try:
                popup_page.wait_for_load_state("domcontentloaded", timeout=10000)
                popup_page.on("dialog", lambda d: d.accept())
                logger.info(f"계산서내역 팝업 열림: {popup_page.url[:80]}")
            except Exception as e:
                logger.warning(f"팝업 로드 대기 실패: {e}")
        else:
            logger.info("계산서내역 팝업 — 현재 페이지에서 모달 처리")
            try:
                target.wait_for_selector(
                    "div[class*='modal'], div[class*='popup'], div[class*='layer']",
                    timeout=5000,
                    state="visible",
                )
            except Exception:
                pass

        # 기간 설정: 시작일
        try:
            date_inputs = target.locator(
                "input[class*='OBTDatePickerRebuild_inputYMD'], "
                "input[class*='datepicker'], "
                "input[type='text'][maxlength='8']"
            ).all()
            if len(date_inputs) >= 2:
                # 첫 번째 = 시작일, 두 번째 = 종료일
                date_inputs[0].click(force=True)
                date_inputs[0].fill(date_from)
                date_inputs[0].press("Tab")
                logger.info(f"팝업 시작일 설정: {date_from}")

                date_inputs[1].click(force=True)
                date_inputs[1].fill(date_to)
                date_inputs[1].press("Tab")
                logger.info(f"팝업 종료일 설정: {date_to}")
            elif len(date_inputs) == 1:
                date_inputs[0].click(force=True)
                date_inputs[0].fill(date_from)
                date_inputs[0].press("Tab")
        except Exception as e:
            logger.warning(f"팝업 날짜 설정 실패: {e}")

        # 거래처명 입력
        if vendor:
            try:
                vendor_selectors = [
                    "input[placeholder*='거래처']",
                    "input[placeholder*='공급자']",
                    "input[placeholder*='업체']",
                    "input[placeholder*='검색']",
                ]
                for sel in vendor_selectors:
                    try:
                        inp = target.locator(sel).first
                        if inp.is_visible(timeout=2000):
                            inp.click(force=True)
                            inp.fill(vendor)
                            logger.info(f"팝업 거래처 입력: {vendor}")
                            break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"팝업 거래처 입력 실패: {e}")

        # 조회/검색 버튼 클릭
        try:
            search_selectors = [
                "button:has-text('조회')",
                "button:has-text('검색')",
                "div.topBtn:has-text('조회')",
                "div[class*='btn']:has-text('조회')",
                "input[value='조회']",
            ]
            for sel in search_selectors:
                try:
                    btn = target.locator(sel).first
                    if btn.is_visible(timeout=2000):
                        btn.click(force=True)
                        logger.info(f"팝업 조회 버튼 클릭: {sel}")
                        break
                except Exception:
                    continue

            # 조회 결과 로드 대기
            try:
                target.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                target.wait_for_timeout(2000)
        except Exception as e:
            logger.warning(f"팝업 조회 버튼 클릭 실패: {e}")

        _save_debug(page, "invoice_popup_search_result")

        # 결과 목록에서 일치 항목 선택
        selected = False
        try:
            # RealGrid 또는 테이블 행 탐색
            row_selectors = [
                "tr[class*='grid']",
                "tr[class*='row']",
                "div[class*='grid-row']",
                "div[class*='gridRow']",
                "table tbody tr",
            ]
            rows = []
            for sel in row_selectors:
                try:
                    candidates = target.locator(sel).all()
                    if candidates:
                        rows = candidates
                        logger.info(f"팝업 결과 행 발견: {sel} ({len(rows)}개)")
                        break
                except Exception:
                    continue

            if not rows:
                logger.warning("팝업 결과 행 없음 — 첫 번째 행 선택 시도")
                # 결과가 하나뿐이면 그냥 선택
                try:
                    first_row_sel = target.locator("table tbody tr").first
                    if first_row_sel.is_visible(timeout=2000):
                        first_row_sel.click(force=True)
                        selected = True
                except Exception:
                    pass
            else:
                # vendor/amount 매칭
                for row in rows[:30]:
                    try:
                        row_text = row.inner_text()
                        # 거래처명 매칭
                        vendor_match = (not vendor) or (vendor in row_text)
                        # 금액 매칭 (쉼표/원 제거 후 비교)
                        amount_match = True
                        if amount is not None:
                            import re as _re
                            nums = _re.findall(r"[\d,]+", row_text)
                            row_amounts = []
                            for n in nums:
                                try:
                                    row_amounts.append(int(n.replace(",", "")))
                                except ValueError:
                                    pass
                            # 공급가액 또는 합계 금액 매칭
                            amount_int = int(amount)
                            amount_match = any(
                                abs(a - amount_int) < max(1000, amount_int * 0.01)
                                for a in row_amounts
                            )

                        if vendor_match and amount_match:
                            row.click(force=True)
                            logger.info(f"계산서내역 행 선택: {row_text[:80]}")
                            selected = True
                            break
                    except Exception:
                        continue

                if not selected and rows:
                    # 매칭 실패 시 첫 번째 행 선택
                    try:
                        rows[0].click(force=True)
                        logger.info("계산서내역 — 매칭 실패, 첫 번째 행 선택")
                        selected = True
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"팝업 결과 행 탐색 실패: {e}")

        _save_debug(page, "invoice_popup_row_selected")

        # 선택/확인 버튼 클릭
        confirm_selectors = [
            "button:has-text('선택')",
            "button:has-text('확인')",
            "button:has-text('적용')",
            "div.topBtn:has-text('선택')",
            "div.topBtn:has-text('확인')",
            "div[class*='btn']:has-text('선택')",
        ]
        for sel in confirm_selectors:
            try:
                btn = target.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click(force=True)
                    logger.info(f"팝업 확인 버튼 클릭: {sel}")
                    # 팝업 닫힘 대기
                    if popup_page:
                        try:
                            popup_page.wait_for_timeout(1000)
                        except Exception:
                            pass
                    return selected
            except Exception:
                continue

        # 확인 버튼 없으면 더블클릭으로 선택 (GW 팝업 패턴)
        if selected and rows:
            try:
                rows[0].dblclick(force=True)
                logger.info("팝업 행 더블클릭으로 선택")
                return True
            except Exception:
                pass

        logger.warning("계산서내역 팝업 확인 버튼 미발견")
        return selected

    def _fill_project_code_bottom(self, project: str) -> bool:
        """
        하단 테이블(테이블 7) 프로젝트 코드도움 입력.

        지출결의서 하단 테이블에는 두 번째 프로젝트 코드도움 필드가 있음.
        상단(y≈292)과 달리 y≈857~950 근처에 위치.

        Args:
            project: 프로젝트 코드 또는 이름 일부
        Returns:
            True if 입력 성공
        """
        page = self.page
        try:
            # 하단 테이블 프로젝트 input 탐색 (y > 800)
            all_proj_inputs = page.locator("input[placeholder='프로젝트코드도움']").all()
            bottom_input = None
            for inp in all_proj_inputs:
                try:
                    box = inp.bounding_box()
                    if box and box["y"] > 800:
                        bottom_input = inp
                        break
                except Exception:
                    continue

            if bottom_input and bottom_input.is_visible(timeout=2000):
                bottom_input.click(force=True)
                bottom_input.fill("")
                bottom_input.type(project, delay=60)
                logger.info(f"하단 프로젝트 코드도움 입력: {project}")

                # 드롭다운 선택
                dropdown_selectors = [
                    "ul[class*='autocomplete'] li",
                    "div[class*='OBTAutoComplete'] li",
                    "div[class*='suggest'] li",
                    "div[class*='dropdown'] li",
                    "li[class*='item']",
                ]
                for sel in dropdown_selectors:
                    try:
                        item = page.locator(sel).first
                        if item.is_visible(timeout=1500):
                            item.click()
                            logger.info(f"하단 프로젝트 드롭다운 선택: {sel}")
                            return True
                    except Exception:
                        continue

                bottom_input.press("Enter")
                logger.info("하단 프로젝트 Enter 선택")
                return True
        except Exception as e:
            logger.debug(f"하단 프로젝트 코드도움 입력 실패: {e}")

        # 폴백: 좌표 기반 (하단 테이블 프로젝트 필드 y≈920)
        try:
            page.mouse.click(838, 920)
            page.keyboard.type(project, delay=60)
            page.keyboard.press("Enter")
            logger.info(f"하단 프로젝트 입력 (좌표 폴백 838,920): {project}")
            return True
        except Exception as e:
            logger.warning(f"하단 프로젝트 좌표 폴백도 실패: {e}")
        return False

    def search_project_codes(self, keyword: str, max_results: int = 10) -> list[dict]:
        """
        프로젝트 코드도움 자동완성 위젯에서 키워드로 검색 후 결과 목록 반환.

        사용 목적: 챗봇에서 사용자가 "메디빌더"라고 입력하면
        정식 프로젝트명(GS-25-0088. [종로] 메디빌더 등)을 검색해 확인을 받기 위함.

        흐름:
        1. 지출결의서 폼 열기
        2. 프로젝트 코드도움 input에 keyword 입력
        3. 자동완성 드롭다운 목록 텍스트 모두 추출
        4. 드롭다운 닫기 (ESC)
        5. 결과 리스트 반환 [{code, name, full_text}, ...]

        Args:
            keyword: 검색 키워드 (예: '메디빌더', 'GS-25')
            max_results: 최대 반환 개수
        Returns:
            [{"code": "GS-25-0088", "name": "[종로] 메디빌더", "full_text": "GS-25-0088. [종로] 메디빌더"}, ...]
        """
        page = self.page
        results = []

        try:
            # 지출결의서 폼으로 이동 (아직 열려있지 않으면 열기)
            try:
                page.wait_for_selector(
                    "input[placeholder='프로젝트코드도움']",
                    timeout=3000,
                    state="visible",
                )
            except Exception:
                self._navigate_to_expense_form()
                page.wait_for_selector(
                    "input[placeholder='프로젝트코드도움']",
                    timeout=10000,
                    state="visible",
                )

            # 상단 프로젝트 코드도움 input 찾기 (y < 500)
            all_proj_inputs = page.locator("input[placeholder='프로젝트코드도움']").all()
            proj_input = None
            for inp in all_proj_inputs:
                try:
                    box = inp.bounding_box()
                    if box and box["y"] < 500 and inp.is_visible(timeout=1000):
                        proj_input = inp
                        break
                except Exception:
                    continue

            if not proj_input:
                logger.warning("프로젝트 코드도움 input을 찾을 수 없음")
                return []

            # 기존 값 지우고 키워드 입력 (delay로 자동완성 트리거)
            proj_input.click(force=True)
            proj_input.fill("")
            proj_input.type(keyword, delay=80)
            logger.info(f"프로젝트 검색 키워드 입력: {keyword}")

            # 자동완성 드롭다운 대기 (최대 3초)
            dropdown_selectors = [
                "ul[class*='autocomplete'] li",
                "div[class*='OBTAutoComplete'] li",
                "div[class*='suggest'] li",
                "div[class*='dropdown-list'] li",
                "ul[role='listbox'] li",
                "div[role='listbox'] div[role='option']",
                "li[class*='item']",
                ".autocomplete-item",
            ]
            dropdown_items = None
            for sel in dropdown_selectors:
                try:
                    locator = page.locator(sel)
                    if locator.first.is_visible(timeout=2000):
                        dropdown_items = locator.all()
                        logger.info(f"드롭다운 발견: {sel} ({len(dropdown_items)}개)")
                        break
                except Exception:
                    continue

            if not dropdown_items:
                logger.info("드롭다운 없음 - Enter로 현재 값 확인 시도")
                # Enter로 현재 선택된 값 확인
                proj_input.press("Escape")
                return []

            # 드롭다운 항목 텍스트 추출
            for item in dropdown_items[:max_results]:
                try:
                    text = item.inner_text().strip()
                    if not text:
                        continue
                    # "GS-25-0088. [종로] 메디빌더" 형식 파싱
                    parsed = _parse_project_text(text)
                    results.append(parsed)
                except Exception:
                    continue

            logger.info(f"프로젝트 검색 결과 {len(results)}건: {[r['full_text'] for r in results]}")

        except Exception as e:
            logger.warning(f"프로젝트 코드 검색 실패: {e}")
        finally:
            # 드롭다운 닫기
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

        return results

    def _capture_and_attach_budget_screenshot(self) -> bool:
        """
        예실대비현황(상세) 스크린샷을 캡처하여 지출결의서 첨부파일 영역에 자동 업로드.

        흐름:
        1. 하단 예산 영역(테이블 7)으로 스크롤
        2. 화면 캡처 (PNG)
        3. 상단 첨부파일 영역으로 스크롤 후 파일 업로드

        Returns:
            True if 캡처 + 업로드 모두 성공
        """
        page = self.page

        # 1. 스크린샷 캡처
        screenshot_path = self.capture_budget_status_screenshot()
        if not screenshot_path:
            logger.warning("예실대비현황 스크린샷 캡처 실패")
            return False

        logger.info(f"예실대비현황 스크린샷 캡처 완료: {screenshot_path}")

        # 2. 상단으로 스크롤 후 첨부파일 업로드
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
        except Exception:
            pass

        success = self._upload_attachment(screenshot_path)
        if success:
            logger.info("예실대비현황 스크린샷 첨부파일 업로드 완료")
        else:
            logger.warning("예실대비현황 스크린샷 첨부파일 업로드 실패")
        return success

    def _fill_receipt_date(self, date_str: str):
        """
        증빙일자 입력 (하단 테이블, OBTDatePicker).

        DOM: x=763, y=857, className=OBTDatePickerRebuild_inputYMD
        형식: YYYY-MM-DD (입력 후 8자리 YYYYMMDD로 자동 변환됨)

        Args:
            date_str: '2026-03-01' 형식
        """
        page = self.page

        # YYYY-MM-DD → YYYYMMDD 변환 (GW 날짜 필드 형식)
        clean_date = date_str.replace("-", "")

        # selector로 찾기: 하단 영역(y>800)의 OBTDatePicker input
        try:
            date_inputs = page.locator(
                "input.OBTDatePickerRebuild_inputYMD__PtxMy, "
                "input[class*='OBTDatePickerRebuild_inputYMD']"
            ).all()
            for inp in date_inputs:
                if inp.is_visible():
                    box = inp.bounding_box()
                    if box and box["y"] > 800:  # 하단 테이블 (증빙일자)
                        inp.click(force=True)
                        inp.fill(clean_date)
                        inp.press("Tab")
                        logger.info(f"증빙일자 입력: {date_str}")
                        return True
        except Exception as e:
            logger.debug(f"증빙일자 selector 입력 실패: {e}")

        # 폴백: 좌표 기반 (x=763, y=857)
        try:
            page.mouse.click(763, 857)
            page.keyboard.type(clean_date)
            page.keyboard.press("Tab")
            logger.info(f"증빙일자 입력 (좌표 763,857): {date_str}")
            return True
        except Exception as e:
            logger.warning(f"증빙일자 좌표 입력 실패: {e}")
        return False

    def _upload_attachment(self, file_path: str) -> bool:
        """
        첨부파일 업로드.

        GW 첨부파일 구조:
        - input[type=file][id=uploadFile] (hidden) — setInputFiles로 직접 처리
        - 또는 placeholder="파일을 첨부해주세요" input 옆 버튼 클릭

        Args:
            file_path: 업로드할 파일의 로컬 절대 경로
        Returns:
            True if 업로드 성공
        """
        page = self.page
        import pathlib
        p = pathlib.Path(file_path)
        if not p.exists():
            logger.warning(f"첨부파일 없음: {file_path}")
            return False

        # 방법 1: hidden file input에 직접 파일 설정
        try:
            file_input = page.locator("input[type='file']#uploadFile, input[type='file'][name='uploadFile']").first
            file_input.set_input_files(str(p))
            logger.info(f"첨부파일 업로드 (hidden input): {p.name}")
            return True
        except Exception:
            pass

        # 방법 2: "선택" 버튼 클릭 → file chooser 처리
        try:
            with page.expect_file_chooser() as fc_info:
                # "선택" 버튼: x=1865, y=246 (DOM 데이터 기준)
                sel_btns = page.locator("button:has-text('선택')").all()
                clicked = False
                for btn in sel_btns:
                    if btn.is_visible():
                        box = btn.bounding_box()
                        if box and 230 < box["y"] < 270:
                            btn.click(force=True)
                            clicked = True
                            break
                if not clicked:
                    # 좌표 폴백
                    page.mouse.click(1865, 246)

            file_chooser = fc_info.value
            file_chooser.set_files(str(p))
            logger.info(f"첨부파일 업로드 (file chooser): {p.name}")
            return True
        except Exception as e:
            logger.warning(f"첨부파일 업로드 실패: {e}")

        return False

    # ─────────────────────────────────────────
    # 예실대비현황 스크린샷 캡처
    # ─────────────────────────────────────────

    def capture_budget_status_screenshot(self, output_path: str = None) -> str | None:
        """
        예실대비현황 화면 스크린샷 캡처.

        GW 예실대비현황: 지출결의서 양식 내 예산 잔액 현황 테이블
        - 하단 테이블 7 영역 (y > 800) 포함
        - full_page=False로 현재 화면만 캡처

        Args:
            output_path: 저장 경로 (None이면 자동 생성)
        Returns:
            저장된 파일 경로 (str) 또는 None
        """
        page = self.page
        if output_path is None:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(SCREENSHOT_DIR / f"budget_status_{ts}.png")

        try:
            # 하단 예산 영역으로 스크롤
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        try:
            page.screenshot(path=output_path, full_page=False)
            logger.info(f"예실대비현황 스크린샷 저장: {output_path}")
            return output_path
        except Exception as e:
            logger.warning(f"스크린샷 캡처 실패: {e}")
            return None

    # 실제 DOM: 체크박스 | 용도 | 내용 | 거래처 | 공급가액 | 부가세 | 합계액 | 증빙 | 증빙번호 ...
    GRID_COL_MAP = {
        "용도": 0,
        "내용": 1,
        "거래처": 2,
        "공급가액": 3,
        "부가세": 4,
        "합계액": 5,
        "증빙": 6,
        "증빙번호": 7,
    }

    # data.items 키 → 그리드 컬럼 매핑
    ITEM_KEY_TO_COL = {
        "usage": "용도",       # 용도 (계정과목 코드도움)
        "content": "내용",     # 내용 (텍스트)
        "vendor": "거래처",    # 거래처 (텍스트)
        "supply_amount": "공급가액",  # 공급가액 (숫자)
        "tax_amount": "부가세",       # 부가세 (숫자)
        # 합계액은 자동 계산
        "item": "내용",        # 호환: agent.py의 "item" → "내용"
        "amount": "공급가액",  # 호환: agent.py의 "amount" → "공급가액"
        "note": "내용",        # 호환: "note"도 내용에 매핑
    }

    def _fill_grid_items(self, items: list[dict]):
        """
        지출내역 그리드에 항목 입력

        그리드는 RealGrid(realgridjs) 커스텀 컴포넌트:
        - 셀 클릭 → 편집 모드 활성화 → input 나타남 → 값 입력 → Tab/Enter로 확정
        - "추가" 버튼으로 새 행 추가 (DOM 기준 x=1808, y=373)
        - 첫 번째 행은 이미 존재 (빈 행)
        - RealGrid API 우선 시도, 실패 시 좌표 기반 폴백

        Args:
            items: [
                {"item": "항목명", "amount": 100000},  # 간단 형식 (agent.py 호환)
                {"content": "내용", "vendor": "거래처", "supply_amount": 50000, "tax_amount": 5000},  # 상세 형식
            ]
        """
        page = self.page

        if not items:
            return

        logger.info(f"지출내역 그리드 입력 시작: {len(items)}개 항목")

        for row_idx, item_data in enumerate(items):
            # 첫 행은 이미 있음, 2번째부터 "추가" 버튼 클릭
            if row_idx > 0:
                self._click_grid_add_button()
                time.sleep(1)

            # 각 필드 입력
            filled_count = 0
            for key, value in item_data.items():
                if not value:
                    continue

                col_name = self.ITEM_KEY_TO_COL.get(key)
                if not col_name:
                    continue

                col_idx = self.GRID_COL_MAP.get(col_name)
                if col_idx is None:
                    continue

                success = self._fill_grid_cell(row_idx, col_idx, col_name, str(value))
                if success:
                    filled_count += 1

            logger.info(f"그리드 행 {row_idx}: {filled_count}개 필드 입력")

        logger.info("지출내역 그리드 입력 완료")

    def _click_grid_add_button(self):
        """그리드 "추가" 버튼 클릭하여 새 행 추가"""
        page = self.page

        # "추가" 버튼: 지출내역 영역 내 버튼
        for selector in [
            "button:has-text('추가')",
            "text=추가",
        ]:
            try:
                btns = page.locator(selector).all()
                for btn in btns:
                    if btn.is_visible():
                        # 지출내역 그리드 영역 근처 버튼만 (y ~ 373)
                        box = btn.bounding_box()
                        if box and 340 < box["y"] < 420:
                            btn.click(force=True)
                            logger.info("그리드 '추가' 버튼 클릭")
                            return True
            except Exception:
                continue

        # 폴백: DOM 데이터 기준 좌표 (x=1808, y=373)
        try:
            page.mouse.click(1808, 373)
            logger.info("그리드 '추가' 버튼 클릭 (좌표 폴백 x=1808, y=373)")
            return True
        except Exception as e:
            logger.warning(f"그리드 '추가' 좌표 폴백도 실패: {e}")

        logger.warning("그리드 '추가' 버튼을 찾지 못했습니다")
        return False

    def _fill_grid_cell(self, row_idx: int, col_idx: int, col_name: str, value: str) -> bool:
        """
        그리드 셀에 값 입력

        RealGrid 동작:
        1. 셀 영역 클릭 → 편집 모드 활성화
        2. 활성화된 input/textarea에 값 입력
        3. Tab 키로 다음 셀 이동 (값 확정)

        Args:
            row_idx: 행 인덱스 (0-based)
            col_idx: 열 인덱스 (0-based, 체크박스 제외)
            col_name: 열 이름 (로깅용)
            value: 입력할 값
        """
        page = self.page

        try:
            # 방법 1: RealGrid JavaScript API로 값 직접 설정
            # RealGrid는 canvas 기반으로 표준 DOM 접근이 불가하므로 JS API 우선
            if self._fill_grid_cell_via_realgrid_api(row_idx, col_idx, col_name, value):
                return True

            # 방법 2: div[role="row"] 기반 탐색 (일부 그리드)
            grid_rows = page.locator("div[role='row']").all()

            if not grid_rows or row_idx >= len(grid_rows):
                logger.debug(f"그리드 행 {row_idx} 찾기 실패 (총 {len(grid_rows)}행)")
                return self._fill_grid_cell_by_position(row_idx, col_idx, col_name, value)

            row = grid_rows[row_idx]
            # 체크박스 td 건너뛰기: col_idx + 1 (또는 +2 if 확장 아이콘)
            cells = row.locator("td, div[role='gridcell']").all()

            # 체크박스 + 확장아이콘 2개 건너뛰기
            actual_col = col_idx + 2
            if actual_col >= len(cells):
                actual_col = col_idx + 1

            if actual_col >= len(cells):
                logger.debug(f"셀 인덱스 초과: row={row_idx}, col={actual_col}, total={len(cells)}")
                return self._fill_grid_cell_by_position(row_idx, col_idx, col_name, value)

            cell = cells[actual_col]
            return self._activate_and_fill_cell(cell, col_name, value)

        except Exception as e:
            logger.debug(f"그리드 셀 입력 실패 (row={row_idx}, col={col_name}): {e}")
            return self._fill_grid_cell_by_position(row_idx, col_idx, col_name, value)

    def _fill_grid_cell_via_realgrid_api(
        self, row_idx: int, col_idx: int, col_name: str, value: str
    ) -> bool:
        """
        RealGrid JavaScript API를 통해 그리드 셀 값 직접 설정.

        RealGrid API 패턴:
        - window.gridView (또는 첫 번째 GridView 인스턴스)를 찾아서
        - gridView.setValue(itemIndex, fieldName, value) 또는
        - gridView.setValues(itemIndex, {fieldName: value}) 호출

        컬럼 필드명은 RealGrid 설정에 따라 달라질 수 있음:
        '내용', 'content', 'CONT', 'col_1' 등 다양
        """
        page = self.page

        # RealGrid 컬럼 인덱스 → 필드명 매핑 (실제 그리드 설정에 따라 달라짐)
        # 좌표 클릭으로 셀을 활성화한 뒤 편집 input에 type하는 방식이 더 안전
        try:
            result = page.evaluate(f"""
            (function() {{
                // RealGrid 인스턴스 찾기
                const gridNames = ['gridView', 'grid', 'expenseGrid', 'detailGrid'];
                let gv = null;
                for (const name of gridNames) {{
                    if (window[name] && typeof window[name].setCurrent === 'function') {{
                        gv = window[name];
                        break;
                    }}
                }}
                if (!gv) return false;

                // 셀 포커스 이동 (itemIndex, columnIndex)
                try {{
                    gv.setCurrent({{ itemIndex: {row_idx}, column: {col_idx + 1} }});
                    return true;
                }} catch(e) {{
                    return false;
                }}
            }})()
            """)

            if result:
                # 편집 모드 input에 값 입력
                active_input = page.locator("input:focus, textarea:focus").first
                if active_input.is_visible(timeout=1000):
                    active_input.fill(str(value))
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (RealGrid API): {value}")
                    return True
        except Exception as e:
            logger.debug(f"RealGrid API 시도 실패 ({col_name}): {e}")

        return False

    def _activate_and_fill_cell(self, cell, col_name: str, value: str) -> bool:
        """셀 클릭하여 활성화 → input에 값 입력"""
        page = self.page

        try:
            # 1. 셀 클릭 → 편집 모드 활성화
            cell.click(force=True)
            time.sleep(0.5)

            # 2. 활성화된 input 찾기 (셀 내부 또는 페이지 전체에서)
            # RealGrid는 활성 셀에 overlay input을 동적으로 생성
            inp = cell.locator("input:visible, textarea:visible").first
            try:
                if inp.is_visible(timeout=1000):
                    inp.fill("")
                    inp.fill(value)
                    # Tab으로 값 확정
                    inp.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력: {value}")
                    return True
            except Exception:
                pass

            # 3. 셀 내부에 input이 없으면 포커스된 input 찾기
            # OBTGrid가 overlay input을 사용하는 경우
            active_input = page.locator("input:focus, textarea:focus").first
            try:
                if active_input.is_visible(timeout=1000):
                    active_input.fill("")
                    active_input.fill(value)
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (focus): {value}")
                    return True
            except Exception:
                pass

            # 4. 더블클릭 시도 (일부 그리드는 더블클릭으로 편집)
            cell.dblclick(force=True)
            time.sleep(0.5)

            inp = cell.locator("input:visible, textarea:visible").first
            try:
                if inp.is_visible(timeout=1000):
                    inp.fill("")
                    inp.fill(value)
                    inp.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (dblclick): {value}")
                    return True
            except Exception:
                pass

            logger.debug(f"그리드 '{col_name}' 셀 활성화 후 input 미발견")
            return False

        except Exception as e:
            logger.debug(f"그리드 셀 활성화 실패 ({col_name}): {e}")
            return False

    def _fill_grid_cell_by_position(self, row_idx: int, col_idx: int, col_name: str, value: str) -> bool:
        """
        그리드 셀을 좌표 기반으로 입력 (폴백)

        DOM 탐색 데이터 기준 좌표:
        - 그리드 첫 행 y ~ 345
        - 행 높이 ~ 28px
        - 컬럼 x 좌표: 용도~560, 내용~680, 거래처~850, 공급가액~960, 부가세~1070, 합계액~1140
        """
        page = self.page

        # 컬럼별 x 좌표 (중심점, 스크린샷 기준)
        col_x_map = {
            0: 560,   # 용도
            1: 680,   # 내용
            2: 850,   # 거래처
            3: 960,   # 공급가액
            4: 1070,  # 부가세
            5: 1140,  # 합계액
        }

        x = col_x_map.get(col_idx)
        if x is None:
            return False

        # 행별 y 좌표: 첫 행 ~345, 행 높이 ~28
        y = 345 + (row_idx * 28)

        try:
            # 좌표 클릭으로 셀 활성화
            page.mouse.click(x, y)
            time.sleep(0.5)

            # 활성화된 input 찾기
            active_input = page.locator("input:focus, textarea:focus").first
            try:
                if active_input.is_visible(timeout=1000):
                    active_input.fill("")
                    active_input.fill(value)
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (좌표): {value}")
                    return True
            except Exception:
                pass

            # 더블클릭 시도
            page.mouse.dblclick(x, y)
            time.sleep(0.5)

            active_input = page.locator("input:focus, textarea:focus").first
            try:
                if active_input.is_visible(timeout=1000):
                    active_input.fill("")
                    active_input.fill(value)
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (좌표 dblclick): {value}")
                    return True
            except Exception:
                pass

            logger.debug(f"그리드 '{col_name}' 좌표 기반 입력도 실패")
            return False

        except Exception as e:
            logger.debug(f"그리드 좌표 입력 실패 ({col_name}): {e}")
            return False

    def _check_field_has_value(self, label: str, expected: str) -> bool:
        """필드에 값이 입력되었는지 확인"""
        try:
            th_el = self.page.locator(f"th:has-text('{label}')").first
            td_el = th_el.locator("xpath=following-sibling::td").first
            inp = td_el.locator("input:visible").first
            return inp.input_value() == expected
        except Exception:
            return False

    def _save_draft(self) -> dict:
        """보관(임시저장) 클릭 — 상신하지 않고 임시보관문서에 저장"""
        page = self.page

        self._close_popups()

        # 보관 버튼 찾기 (div.topBtn)
        save_btn = None
        for selector in [
            "div.topBtn:has-text('보관')",
            "button:has-text('보관')",
            "text=보관",
        ]:
            try:
                candidates = page.locator(selector).all()
                for candidate in candidates:
                    if candidate.is_visible(timeout=2000):
                        # "임시보관" 등 다른 텍스트와 구분
                        btn_text = candidate.inner_text().strip()
                        if btn_text == "보관":
                            save_btn = candidate
                            logger.info(f"보관 버튼 발견: {selector}")
                            break
                if save_btn:
                    break
            except Exception:
                continue

        # 보관 버튼 못 찾으면 결재상신 버튼도 시도하지 않고 실패
        if not save_btn:
            # 일부 양식(신규 지출결의서)에는 보관 버튼이 없을 수 있음
            # 그 경우 "결재상신" 버튼 옆에 보관이 없으므로 안내
            _save_debug(page, "error_no_save_btn")
            return {"success": False, "message": "보관 버튼을 찾을 수 없습니다. 이 양식에서는 보관이 지원되지 않을 수 있습니다."}

        _save_debug(page, "04_before_save")

        save_btn.click(force=True)

        # 보관 후 결과 대기
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            logger.warning("보관 후 네트워크 대기 타임아웃")
            time.sleep(3)
        except Exception:
            time.sleep(3)

        # 에러 다이얼로그/메시지 확인
        try:
            error_msg = page.locator("div.alert-message, div.error-message, .OBTAlert_message").first
            if error_msg.is_visible(timeout=2000):
                text = error_msg.inner_text()
                logger.error(f"보관 에러 메시지: {text}")
                _save_debug(page, "error_save_response")
                return {"success": False, "message": f"보관 중 오류가 발생했습니다: {text}"}
        except Exception:
            pass  # 에러 메시지 없음 = 정상

        _save_debug(page, "05_after_save")

        logger.info("보관(임시저장) 완료")
        return {"success": True, "message": "임시보관문서에 저장되었습니다. (상신 전 상태)"}

    # ─────────────────────────────────────────
    # 양식별 작성 메서드 (스텁)
    # ─────────────────────────────────────────

    def create_vendor_registration(self, data: dict) -> dict:
        """
        [회계팀] 국내 거래처등록 신청서 작성 + 보관
        ※ 이 양식은 팝업 창으로 열리므로 팝업 기반 흐름 사용

        Args:
            data: {
                "title": "제목",
                "vendor_name": "거래처명(상호)",
                "ceo_name": "대표자명",
                "business_number": "사업자등록번호 (000-00-00000)",
                "business_type": "업태",
                "business_item": "종목",
                "address": "사업장주소",
                "contact_name": "담당자명",
                "contact_phone": "담당자 연락처",
                "contact_email": "담당자 이메일 (선택)",
                "bank_name": "은행명",
                "account_number": "계좌번호",
                "account_holder": "예금주",
                "note": "비고 (선택)",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # 필수 필드 검증
        validation = self._validate_required_fields(data, ["title"], "거래처등록")
        if validation:
            return validation

        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        if not self.context:
            return {"success": False, "message": "BrowserContext가 필요합니다. (팝업 감지용)"}

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            popup_page = None
            try:
                self._close_popups()

                # 1. 전자결재 HOME 이동
                self._navigate_to_approval_home()

                # 2. 양식 선택 → 팝업 창 열기
                popup_page = self._open_form_popup("국내 거래처")

                # 3. 팝업에서 필드 채우기
                self._fill_vendor_fields_in_popup(popup_page, data)

                # 3-1. 결재선 커스텀 설정 (data에 approval_line 키 있을 때)
                if data.get("approval_line"):
                    resolved_line = resolve_approval_line(data["approval_line"], "거래처등록")
                    self.set_approval_line(popup_page, resolved_line)

                # 3-2. 수신참조 설정 (data에 cc 키 있을 때)
                if data.get("cc"):
                    resolved_cc = resolve_cc_recipients(data["cc"], "거래처등록")
                    self.set_cc_recipients(popup_page, resolved_cc)

                # 4. 팝업에서 보관
                result = self._save_draft_in_popup(popup_page)

                return result

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"거래처등록 작성 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                _save_debug(self.page, f"error_vendor_timeout{attempt}")
                if popup_page:
                    _save_debug(popup_page, f"error_vendor_popup_timeout{attempt}")
                if attempt < MAX_RETRIES:
                    if not self._check_session_valid():
                        return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}
                    self._close_popups()
                    time.sleep(RETRY_DELAY)
            except RuntimeError as e:
                return {"success": False, "message": str(e)}
            except Exception as e:
                last_error = e
                logger.error(f"거래처등록 작성 오류 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"error_vendor_{attempt}")
                if popup_page:
                    _save_debug(popup_page, f"error_vendor_popup_{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        _save_debug(self.page, "error_vendor_final")
        return {"success": False, "message": f"거래처등록 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def _click_form_by_keyword(self, *keywords: str):
        """
        양식 찾기: 추천양식 직접 클릭 → 실패 시 결재작성 → 양식 검색
        """
        page = self.page

        # 방법 1: 추천양식에서 직접 텍스트 클릭
        for keyword in keywords:
            try:
                links = page.locator(f"text={keyword}").all()
                for link in links:
                    if link.is_visible():
                        link.click(force=True)
                        logger.info(f"추천양식에서 클릭: '{keyword}'")
                        return
            except Exception:
                continue

        # 방법 2: "결재작성" 메뉴 클릭 → 양식 검색
        logger.info("추천양식에서 못 찾음, 결재작성으로 검색 시도")
        try:
            # 결재작성 버튼/링크 클릭
            for selector in [
                "text=결재작성",
                "a:has-text('결재작성')",
                "span:has-text('결재작성')",
            ]:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=3000):
                        btn.click(force=True)
                        logger.info("결재작성 클릭")
                        time.sleep(3)
                        break
                except Exception:
                    continue

            # 양식 검색 입력란 찾기
            search_input = None
            for selector in [
                "input[placeholder*='검색']",
                "input[placeholder*='양식']",
                "input[type='text']",
            ]:
                try:
                    candidates = page.locator(selector).all()
                    for inp in candidates:
                        if inp.is_visible():
                            search_input = inp
                            break
                    if search_input:
                        break
                except Exception:
                    continue

            if search_input:
                # 첫 번째 키워드로 검색
                search_input.click()
                search_input.fill(keywords[0])
                search_input.press("Enter")
                logger.info(f"양식 검색: '{keywords[0]}'")
                time.sleep(2)

                # 검색 결과에서 클릭
                for keyword in keywords:
                    try:
                        result = page.locator(f"text={keyword}").first
                        if result.is_visible(timeout=3000):
                            result.click(force=True)
                            logger.info(f"검색 결과에서 클릭: '{keyword}'")
                            return
                    except Exception:
                        continue

            _save_debug(page, "error_form_search_failed")
        except Exception as e:
            logger.error(f"양식 검색 실패: {e}")

        raise RuntimeError(f"양식을 찾을 수 없습니다: {keywords}")

    # ─────────────────────────────────────────
    # 팝업 기반 양식 작성 (거래처등록 등)
    # ─────────────────────────────────────────

    def _open_form_popup(self, search_term: str) -> Page:
        """
        결재작성 페이지에서 양식을 검색하고 팝업 창을 열어 반환

        흐름:
        1. 결재작성 페이지(UBA6000)로 이동
        2. 검색 입력란에 search_term 입력 후 Enter
        3. 검색 결과 첫 번째 항목 클릭 → Enter
        4. 새 팝업 페이지 감지 및 반환

        Args:
            search_term: 양식 검색어 (예: "국내 거래처")
        Returns:
            팝업 Page 객체
        """
        page = self.page

        # 현재 열린 페이지 목록 기록 (팝업 감지용)
        pages_before = set(self.context.pages)

        # 1. 결재작성 페이지로 이동 (UBA6000)
        form_select_url = f"{GW_URL}/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA6000"

        # div.sideRegi 클릭 시도 → 실패하면 직접 URL 이동
        try:
            side_regi = page.locator("div.sideRegi").first
            if side_regi.is_visible(timeout=3000):
                side_regi.click(force=True)
                # URL 변경 대기 (최대 5초)
                try:
                    page.wait_for_url("**/UBA6000**", timeout=5000)
                except Exception:
                    pass
                # URL 확인 - UBA6000이 아니면 직접 이동
                if "UBA6000" not in page.url:
                    logger.info("sideRegi 클릭 후 UBA6000이 아님, 직접 이동")
                    page.goto(form_select_url, wait_until="domcontentloaded", timeout=15000)
            else:
                page.goto(form_select_url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            page.goto(form_select_url, wait_until="domcontentloaded", timeout=15000)

        logger.info(f"결재작성 페이지 이동: {page.url[:100]}")
        _save_debug(page, "vendor_01_form_select_page")

        # 2. 양식 검색 입력란 찾기 (placeholder로 식별, 페이지 로드 대기 포함)
        search_input = None
        for selector in [
            "input[placeholder*='카테고리 또는 양식명']",
            "input[placeholder*='양식명']",
            "input[placeholder*='양식']",
            "input[placeholder*='검색']",
        ]:
            try:
                inp = page.locator(selector).first
                if inp.is_visible(timeout=3000):
                    # readonly가 아닌지 확인
                    readonly = inp.get_attribute("readonly")
                    if readonly is None:
                        search_input = inp
                        break
            except Exception:
                continue

        if not search_input:
            _save_debug(page, "error_vendor_no_search_input")
            raise RuntimeError("양식 검색 입력란을 찾을 수 없습니다.")

        # 3. 검색어 입력 + Enter → 결과 로드 대기
        search_input.click()
        search_input.fill(search_term)
        search_input.press("Enter")
        logger.info(f"양식 검색: '{search_term}'")
        # 검색 결과 로드 대기 (networkidle 또는 최대 3초)
        try:
            page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            page.wait_for_timeout(1500)

        _save_debug(page, "vendor_02_search_result")

        # 4. 검색 결과에서 첫 번째 항목 클릭
        result_clicked = False
        for keyword in ["[회계팀] 국내 거래처등록 신청서", "국내 거래처등록", "거래처등록"]:
            try:
                results = page.locator(f"text={keyword}").all()
                for result in results:
                    if result.is_visible():
                        result.click(force=True)
                        logger.info(f"검색 결과 클릭: '{keyword}'")
                        result_clicked = True
                        break
                if result_clicked:
                    break
            except Exception:
                continue

        if not result_clicked:
            _save_debug(page, "error_vendor_no_search_result")
            raise RuntimeError(f"검색 결과에서 양식을 찾을 수 없습니다: '{search_term}'")

        time.sleep(1)

        # 5. Enter 키 → 팝업 열기
        page.keyboard.press("Enter")
        logger.info("Enter 키 눌러 팝업 열기 시도")

        # 6. 새 팝업 페이지 감지 (최대 15초 대기)
        popup_page = None
        for _ in range(30):
            time.sleep(0.5)
            current_pages = set(self.context.pages)
            new_pages = current_pages - pages_before
            for p in new_pages:
                try:
                    p_url = p.url or ""
                    # 팝업 URL 패턴 확인
                    if "popup" in p_url or "formId" in p_url or "eap" in p_url:
                        popup_page = p
                        break
                    # about:blank이 아닌 새 페이지도 후보
                    if p_url and p_url != "about:blank":
                        popup_page = p
                        break
                except Exception:
                    continue
            if popup_page:
                break

        if not popup_page:
            _save_debug(page, "error_vendor_no_popup")
            raise RuntimeError("양식 팝업이 열리지 않았습니다. 검색 결과를 다시 확인해주세요.")

        # 팝업 로드 대기
        try:
            popup_page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            time.sleep(3)

        # 다이얼로그 자동 수락 등록
        popup_page.on("dialog", lambda d: d.accept())

        logger.info(f"팝업 열림: {popup_page.url[:100]}")
        _save_debug(popup_page, "vendor_03_popup_opened")

        return popup_page

    def _fill_vendor_fields_in_popup(self, popup_page: Page, data: dict):
        """
        팝업 페이지에서 거래처등록 필드 채우기

        제목: 기본값 "[국내]신규 거래처등록 요청(거래처명)"에서 (거래처명)만 교체
        본문: dzeditor_0 iframe 내부 테이블 셀에 각 정보를 직접 기입
              (기존 양식 구조를 유지하며 해당 셀만 수정)

        본문 테이블 구조 (Table 2):
        R2: 소속 | 본부/팀 | 성명 | (빈칸)
        R3: 거래처정보 (□매출/□매입) 헤더
        R4: 사업자등록번호 | ex)000-00-00000 | 상호명 | (빈칸)
        R5: 대표자명 | (빈칸) | 수신자이메일 | (빈칸)
        R6: 은행명 | 매출거래처인 경우... (colspan=3)
        R7: 계좌번호 | 매출거래처인 경우... (colspan=3)
        R8: 예금주 | 매출거래처인 경우... (colspan=3)
        R9: 비고 | (빈칸) (colspan=3)
        """
        vendor_name = data.get("vendor_name", "")

        # 1. 제목 — (거래처명) 부분만 업체명으로 교체
        try:
            inputs = popup_page.locator("input[type='text']:visible, input:not([type]):visible").all()
            for inp in inputs:
                val = inp.input_value()
                if "(거래처명)" in val:
                    new_title = val.replace("(거래처명)", vendor_name or "(거래처명)")
                    inp.click()
                    inp.fill(new_title)
                    logger.info(f"팝업 제목 교체: {val} → {new_title}")
                    break
        except Exception as e:
            logger.warning(f"팝업 제목 교체 실패: {e}")

        _save_debug(popup_page, "vendor_04_after_title")

        # 2. 본문 — dzeditor_0 iframe 내부 테이블 셀에 정보 기입
        self._fill_vendor_body_cells(popup_page, data)

        _save_debug(popup_page, "vendor_05_after_body")

    def _fill_vendor_body_cells(self, popup_page: Page, data: dict):
        """
        dzEditor API(setEditorHTMLCodeIframe)를 사용하여 본문 기입

        동작 방식:
        1. getEditorHTMLCodeIframe(0)으로 현재 HTML 가져오기
        2. 양식 HTML에서 placeholder 텍스트를 실제 값으로 교체
        3. setEditorHTMLCodeIframe(html, 0)으로 설정
        → dzEditor 내부 상태에 반영되므로 보관 시 정상 저장됨
        """
        import re

        # 1. 현재 에디터 HTML 가져오기 (로딩 대기 포함)
        current_html = ""
        for wait_try in range(10):
            try:
                current_html = popup_page.evaluate(
                    "(n) => { try { return getEditorHTMLCodeIframe(n); } catch(e) { return ''; } }",
                    0
                )
            except Exception as e:
                logger.warning(f"getEditorHTMLCodeIframe 실패: {e}")
                current_html = ""
            if current_html and len(current_html) >= 100:
                break
            time.sleep(1)

        if not current_html or len(current_html) < 100:
            logger.warning(f"에디터 HTML이 비어있음 (길이: {len(current_html)}), 대기 후에도 로딩 안됨")
            return

        logger.info(f"에디터 HTML 가져옴: {len(current_html)} chars")
        modified = current_html

        # 2. placeholder 텍스트 교체
        # 사업자등록번호: "ex) 000-00-00000"
        biz_num = data.get("business_number", "")
        if biz_num:
            modified = modified.replace("ex) 000-00-00000", biz_num)
            logger.info(f"사업자등록번호: {biz_num}")

        # 소속: "본부 / 팀"
        dept = data.get("department", "")
        if dept:
            modified = modified.replace("본부 / 팀", dept)
            logger.info(f"소속: {dept}")

        # 빈 셀 교체 헬퍼: 라벨 뒤 빈 td의 <p><br></p> → <p>값</p>
        # API HTML에는 태그 사이 줄바꿈/탭이 포함되므로 \s* 필수
        def _replace_empty_cell(html, label, value):
            """라벨 td 다음 빈 td(<p><br></p>)에 값 기입"""
            pattern = rf'(>{re.escape(label)}</p>\s*</td>\s*)(<td[^>]*>\s*)(<p[^>]*>)<br>(</p>\s*</td>)'
            # replacement에서 역참조 사용을 위해 함수형 교체
            def repl(m):
                return m.group(1) + m.group(2) + m.group(3) + value + m.group(4)
            return re.sub(pattern, repl, html, count=1, flags=re.DOTALL)

        def _replace_placeholder_cell(html, label, placeholder, value):
            """라벨 td 다음 td에서 placeholder 텍스트를 값으로 교체"""
            pattern = rf'(>{re.escape(label)}</p>\s*</td>\s*)(<td[^>]*>\s*)(<p[^>]*>){re.escape(placeholder)}(<br>)?(</p>\s*</td>)'
            def repl(m):
                return m.group(1) + m.group(2) + m.group(3) + value + m.group(5)
            return re.sub(pattern, repl, html, count=1, flags=re.DOTALL)

        # 상호명 빈 셀
        vendor_name = data.get("vendor_name", "")
        if vendor_name:
            modified = _replace_empty_cell(modified, "상호명", vendor_name)
            logger.info(f"상호명: {vendor_name}")

        # 대표자명 빈 셀
        ceo = data.get("ceo_name", "")
        if ceo:
            modified = _replace_empty_cell(modified, "대표자명", ceo)
            logger.info(f"대표자명: {ceo}")

        # 성명 빈 셀
        applicant = data.get("applicant_name", "")
        if applicant:
            modified = _replace_empty_cell(modified, "성명", applicant)
            logger.info(f"성명: {applicant}")

        # 수신자이메일 빈 셀
        email = data.get("contact_email", "")
        if email:
            modified = _replace_empty_cell(modified, "이메일", email)
            logger.info(f"수신자이메일: {email}")

        # 은행명 (placeholder 교체)
        bank = data.get("bank_name", "")
        if bank:
            modified = _replace_placeholder_cell(
                modified, "은행명", "매출거래처인 경우 기입하지 않음.", bank
            )
            logger.info(f"은행명: {bank}")

        # 계좌번호
        account = data.get("account_number", "")
        if account:
            modified = _replace_placeholder_cell(
                modified, "계좌번호", "매출거래처인 경우 기입하지 않음.", account
            )
            logger.info(f"계좌번호: {account}")

        # 예금주
        holder = data.get("account_holder", "")
        if holder:
            modified = _replace_placeholder_cell(
                modified, "예금주", "매출거래처인 경우 기입하지 않음.", holder
            )
            logger.info(f"예금주: {holder}")

        # 비고 빈 셀
        note = data.get("note", "")
        if note:
            modified = _replace_empty_cell(modified, "비고", note)
            logger.info(f"비고: {note}")

        # 거래처정보 체크박스 (매출/매입)
        trade_type = data.get("trade_type", "매입")
        if trade_type == "매출":
            modified = re.sub(
                r'(<input type="checkbox">)(</span><span[^>]*>\s*매출)',
                r'<input type="checkbox" checked>\2',
                modified, count=1
            )
        elif trade_type == "매입":
            modified = re.sub(
                r'(<input type="checkbox">)(</span><span[^>]*>\s*매입)',
                r'<input type="checkbox" checked>\2',
                modified, count=1
            )
        elif trade_type in ("매출/매입", "둘다"):
            modified = modified.replace(
                '<input type="checkbox">',
                '<input type="checkbox" checked>',
            )
        logger.info(f"거래처 유형: {trade_type}")

        # 3. setEditorHTMLCodeIframe(html, 0)으로 설정
        try:
            popup_page.evaluate(
                "(args) => { setEditorHTMLCodeIframe(args[0], args[1]); }",
                [modified, 0]
            )
            logger.info("setEditorHTMLCodeIframe 호출 성공")
        except Exception as e:
            logger.error(f"setEditorHTMLCodeIframe 실패: {e}")
            return

        time.sleep(1)

        # 4. 검증: 설정된 HTML에 값이 포함되는지 확인
        try:
            verify = popup_page.evaluate("(n) => getEditorHTMLCodeIframe(n)", 0)
            if vendor_name and vendor_name not in verify:
                logger.warning("검증 실패: 상호명이 설정된 HTML에 없음")
            else:
                logger.info("본문 설정 검증 완료")
        except Exception as e:
            logger.warning(f"본문 검증 중 오류: {e}")

    def _fill_editor_content_in_popup(self, popup_page: Page, text: str):
        """
        팝업 페이지의 dzEditor (contentEditable/iframe) 본문에 텍스트 입력

        Args:
            popup_page: 팝업 Page 객체
            text: 입력할 본문 텍스트
        """
        html_text = text.replace("\n", "<br>")

        # 방법 1: contentEditable div 직접 찾기
        try:
            editor = popup_page.locator("div[contenteditable='true']").first
            if editor.is_visible(timeout=3000):
                editor.click()
                popup_page.evaluate(f"""
                    const el = document.querySelector("[contenteditable='true']");
                    if (el) {{ el.innerHTML = `{html_text}`; }}
                """)
                logger.info("팝업 본문 입력 완료 (contentEditable)")
                return
        except Exception:
            pass

        # 방법 2: iframe 내부 editor
        try:
            iframe = popup_page.locator("iframe").first
            if iframe.is_visible(timeout=3000):
                frame = iframe.content_frame()
                if frame:
                    body = frame.locator("body[contenteditable='true'], div[contenteditable='true']").first
                    if body.is_visible(timeout=2000):
                        body.click()
                        frame.evaluate(f"""
                            const el = document.querySelector('[contenteditable]') || document.body;
                            el.innerHTML = `{html_text}`;
                        """)
                        logger.info("팝업 본문 입력 완료 (iframe)")
                        return
        except Exception:
            pass

        # 방법 3: 키보드 입력 폴백
        try:
            popup_page.keyboard.press("Tab")
            time.sleep(0.5)
            for line in text.split("\n"):
                popup_page.keyboard.type(line)
                popup_page.keyboard.press("Enter")
            logger.info("팝업 본문 입력 완료 (키보드)")
        except Exception as e:
            logger.warning(f"팝업 본문 입력 실패: {e}")

    def _save_draft_in_popup(self, popup_page: Page) -> dict:
        """
        팝업 페이지에서 "보관" 버튼 클릭하여 임시저장

        Args:
            popup_page: 팝업 Page 객체
        Returns:
            {"success": bool, "message": str}
        """
        # "보관" 버튼 찾기 — 팝업 상단 div.topBtn 중 텍스트 "보관"
        save_btn = None
        try:
            top_btns = popup_page.locator("div.topBtn").all()
            for btn in top_btns:
                if btn.is_visible(timeout=2000):
                    btn_text = btn.inner_text().strip()
                    if btn_text == "보관":
                        save_btn = btn
                        logger.info("팝업 보관 버튼 발견: div.topBtn")
                        break
        except Exception:
            pass

        # 폴백: 다른 selector 시도
        if not save_btn:
            for selector in [
                "button:has-text('보관')",
                "a:has-text('보관')",
                "span:has-text('보관')",
            ]:
                try:
                    candidates = popup_page.locator(selector).all()
                    for candidate in candidates:
                        if candidate.is_visible(timeout=1000):
                            btn_text = candidate.inner_text().strip()
                            if btn_text == "보관":
                                save_btn = candidate
                                logger.info(f"팝업 보관 버튼 발견 (폴백): {selector}")
                                break
                    if save_btn:
                        break
                except Exception:
                    continue

        if not save_btn:
            _save_debug(popup_page, "error_vendor_no_save_btn")
            return {"success": False, "message": "팝업에서 보관 버튼을 찾을 수 없습니다."}

        _save_debug(popup_page, "vendor_06_before_save")

        save_btn.click(force=True)

        # 보관 후 결과 대기
        try:
            popup_page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            logger.warning("팝업 보관 후 네트워크 대기 타임아웃")
            time.sleep(3)
        except Exception:
            time.sleep(3)

        # 에러 메시지 확인
        try:
            error_msg = popup_page.locator("div.alert-message, div.error-message, .OBTAlert_message").first
            if error_msg.is_visible(timeout=2000):
                text = error_msg.inner_text()
                logger.error(f"팝업 보관 에러: {text}")
                _save_debug(popup_page, "error_vendor_save_response")
                return {"success": False, "message": f"보관 중 오류: {text}"}
        except Exception:
            pass  # 에러 없음 = 정상

        # 팝업이 자동으로 닫혔는지 확인
        try:
            if popup_page.is_closed():
                logger.info("팝업 자동 닫힘 — 보관 완료")
        except Exception:
            pass

        _save_debug(popup_page, "vendor_07_after_save")
        logger.info("거래처등록 보관(임시저장) 완료")
        return {"success": True, "message": "거래처등록 신청서가 임시보관되었습니다. (상신 전 상태)"}

    def _fill_vendor_fields(self, data: dict):
        """
        거래처등록 필드 채우기
        - 상단: 제목 (th 라벨 기반)
        - 본문: dzEditor contentEditable 영역에 거래처 정보 입력
        """
        page = self.page
        title = data.get("title", "")

        # 1. 제목 입력
        if title:
            self._fill_field_by_label("제목", title)
            # 폴백
            if not self._check_field_has_value("제목", title):
                self._fill_field_by_placeholder("제목", title)

        _save_debug(page, "03_vendor_after_title")

        # 2. 본문 영역 (dzEditor contentEditable)에 거래처 정보 입력
        vendor_info = self._build_vendor_body_text(data)
        if vendor_info:
            self._fill_editor_content(vendor_info)

        _save_debug(page, "03b_vendor_after_body")

    def _build_vendor_body_text(self, data: dict) -> str:
        """거래처 정보를 본문 텍스트로 구성"""
        lines = []

        field_map = [
            ("vendor_name", "거래처명(상호)"),
            ("ceo_name", "대표자명"),
            ("business_number", "사업자등록번호"),
            ("business_type", "업태"),
            ("business_item", "종목"),
            ("address", "사업장주소"),
            ("contact_name", "담당자명"),
            ("contact_phone", "담당자 연락처"),
            ("contact_email", "담당자 이메일"),
            ("bank_name", "은행명"),
            ("account_number", "계좌번호"),
            ("account_holder", "예금주"),
            ("note", "비고"),
        ]

        for key, label in field_map:
            value = data.get(key, "")
            if value:
                lines.append(f"{label}: {value}")

        return "\n".join(lines)

    def _fill_editor_content(self, text: str):
        """dzEditor (contentEditable) 본문 영역에 텍스트 입력"""
        page = self.page

        # dzEditor 본문 영역 찾기 (여러 selector 시도)
        editor = None
        for selector in [
            "div[contenteditable='true']",
            "div.dzEditor",
            "div[class*='editor'] div[contenteditable]",
            "iframe",  # iframe 내부 editor일 수도 있음
        ]:
            try:
                candidate = page.locator(selector).first
                if candidate.is_visible(timeout=3000):
                    if selector == "iframe":
                        # iframe 내부의 contentEditable
                        frame = candidate.content_frame()
                        if frame:
                            body = frame.locator("body[contenteditable='true'], div[contenteditable='true']").first
                            if body.is_visible(timeout=2000):
                                body.click()
                                # 줄바꿈을 위해 HTML로 입력
                                html_text = text.replace("\n", "<br>")
                                frame.evaluate(f"document.querySelector('[contenteditable]').innerHTML = `{html_text}`")
                                logger.info("본문 입력 완료 (iframe)")
                                return
                    else:
                        editor = candidate
                        break
            except Exception:
                continue

        if editor:
            try:
                editor.click()
                # HTML로 줄바꿈 처리
                html_text = text.replace("\n", "<br>")
                page.evaluate(f"""
                    const el = document.querySelector("[contenteditable='true']");
                    if (el) {{ el.innerHTML = `{html_text}`; }}
                """)
                logger.info("본문 입력 완료 (contentEditable)")
                return
            except Exception as e:
                logger.warning(f"contentEditable 입력 실패: {e}")

        # 최종 폴백: 키보드 입력
        try:
            # Tab 등으로 본문 영역으로 이동 시도
            page.keyboard.press("Tab")
            time.sleep(0.5)
            for line in text.split("\n"):
                page.keyboard.type(line)
                page.keyboard.press("Enter")
            logger.info("본문 입력 완료 (키보드)")
        except Exception as e:
            logger.warning(f"본문 키보드 입력도 실패: {e}")

    # ─────────────────────────────────────────
    # 임시보관문서 열기 + 결재상신 E2E
    # ─────────────────────────────────────────

    DRAFT_URL = f"{GW_URL}/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1020"

    def open_draft_and_submit(self, doc_title: str = None, dry_run: bool = False) -> dict:
        """
        임시보관문서함에서 문서 1건을 열고 결재상신까지 E2E 수행.

        Args:
            doc_title: 열려는 문서 제목 (None이면 첫 번째 문서)
            dry_run: True면 상신 버튼을 찾기만 하고 클릭 안 함 (테스트용)
        Returns:
            {"success": bool, "message": str, "doc_title": str}
        """
        if not self.context:
            return {"success": False, "message": "BrowserContext가 필요합니다. (팝업 감지용)"}

        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        page = self.page
        self._close_popups()

        try:
            # ── 1단계: 임시보관문서함 이동 ──
            logger.info("[1/4] 임시보관문서함 이동")
            page.goto(self.DRAFT_URL, wait_until="domcontentloaded", timeout=30000)

            # 리스트 로드 대기 (networkidle 또는 최대 10초)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeout:
                pass

            _save_debug(page, "draft_01_list")

            # ── 2단계: 문서 클릭 ──
            logger.info("[2/4] 문서 클릭")
            popup_page = self._click_draft_document(doc_title)

            if not popup_page:
                _save_debug(page, "draft_error_no_popup")
                return {"success": False, "message": "임시보관문서를 열 수 없습니다. 목록을 확인해주세요."}

            # 팝업에서 문서 제목 읽기
            opened_title = ""
            try:
                opened_title = popup_page.title() or popup_page.url
            except Exception:
                pass

            _save_debug(popup_page, "draft_02_popup_opened")

            # ── 3단계: 상신 버튼 찾기 ──
            logger.info("[3/4] 상신 버튼 탐색")
            submit_btn = self._find_submit_button(popup_page)

            if not submit_btn:
                _save_debug(popup_page, "draft_error_no_submit_btn")
                return {
                    "success": False,
                    "message": "상신 버튼을 찾을 수 없습니다. 문서 상태를 확인해주세요.",
                    "doc_title": opened_title,
                }

            # dry_run 모드: 버튼 확인만 하고 종료
            if dry_run:
                btn_text = submit_btn.inner_text().strip()
                logger.info(f"[dry_run] 상신 버튼 확인: '{btn_text}' — 클릭 안 함")
                return {
                    "success": True,
                    "message": f"[dry_run] 상신 버튼 확인 완료: '{btn_text}'. 실제 상신하려면 dry_run=False로 호출하세요.",
                    "doc_title": opened_title,
                }

            # ── 4단계: 결재상신 클릭 ──
            logger.info("[4/4] 결재상신 클릭")
            result = self._click_submit_button(popup_page, submit_btn)

            result["doc_title"] = opened_title
            return result

        except PlaywrightTimeout as e:
            logger.error(f"임시보관문서 상신 타임아웃: {e}")
            _save_debug(page, "draft_error_timeout")
            return {"success": False, "message": f"타임아웃 발생: {e}"}
        except Exception as e:
            logger.error(f"임시보관문서 상신 오류: {e}", exc_info=True)
            _save_debug(page, "draft_error")
            return {"success": False, "message": f"오류 발생: {e}"}

    def _click_draft_document(self, doc_title: str = None):
        """
        임시보관문서함에서 문서를 클릭하고 팝업 Page를 반환.

        클릭 전략:
        1. doc_title 텍스트로 직접 찾기
        2. 문서 리스트 첫 번째 제목 영역 클릭
        3. 좌표 폴백 클릭
        """
        page = self.page
        pages_before = set(self.context.pages)

        def _wait_for_popup():
            """팝업 Page 감지 (최대 15초)"""
            for _ in range(30):
                current_pages = set(self.context.pages)
                new_pages = current_pages - pages_before
                for p in new_pages:
                    try:
                        p_url = p.url or ""
                        # 결재 문서 팝업 URL 패턴
                        if any(kw in p_url.lower() for kw in ["docid", "formid", "micromodulecode=eap", "popup"]):
                            return p
                        # URL이 빈 문자열이나 about:blank가 아닌 새 페이지
                        if p_url and p_url != "about:blank":
                            return p
                    except Exception:
                        continue
                time.sleep(0.5)
            return None

        # 방법 1: doc_title 텍스트로 클릭
        if doc_title:
            try:
                el = page.locator(f"text={doc_title}").first
                if el.is_visible(timeout=3000):
                    el.click()
                    logger.info(f"문서 클릭 (제목): '{doc_title}'")
                    popup = _wait_for_popup()
                    if popup:
                        popup.wait_for_load_state("domcontentloaded", timeout=15000)
                        popup.on("dialog", lambda d: d.accept())
                        return popup
            except Exception as e:
                logger.debug(f"제목 클릭 실패: {e}")

        # 방법 2: 리스트 아이템 첫 번째 제목 영역 클릭
        for selector in [
            "[class*='subject'] a",
            "[class*='title'] a",
            "[class*='docTitle']",
            "table tbody tr:first-child td:nth-child(3)",  # 제목 컬럼 (일반적으로 3번째 td)
            "table tbody tr:first-child td a",
            "ul.list li:first-child",
            "div[class*='list'] div[class*='item']:first-child",
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    text = el.text_content(timeout=1000) or ""
                    logger.info(f"문서 클릭 (selector '{selector}'): '{text[:60]}'")
                    el.click()
                    popup = _wait_for_popup()
                    if popup:
                        popup.wait_for_load_state("domcontentloaded", timeout=15000)
                        popup.on("dialog", lambda d: d.accept())
                        return popup
            except Exception:
                continue

        # 방법 3: 좌표 폴백 — 이전 스크린샷 기준 문서 첫 번째 행 y~215
        for x, y in [(600, 215), (600, 240), (600, 265)]:
            try:
                page.mouse.click(x, y)
                logger.info(f"문서 클릭 (좌표 {x},{y})")
                popup = _wait_for_popup()
                if popup:
                    popup.wait_for_load_state("domcontentloaded", timeout=15000)
                    popup.on("dialog", lambda d: d.accept())
                    return popup
            except Exception:
                continue

        return None

    def _find_submit_button(self, doc_page: "Page"):
        """
        팝업 문서 페이지에서 결재상신 버튼을 찾아 반환.

        우선순위:
        1. div.topBtn:has-text('상신')  ← 실제 GW 패턴
        2. div.topBtn:has-text('결재상신')
        3. button:has-text('상신')
        """
        # div.topBtn 방식 (실제 GW 패턴)
        try:
            top_btns = doc_page.locator("div.topBtn").all()
            for btn in top_btns:
                try:
                    if not btn.is_visible(timeout=1000):
                        continue
                    txt = btn.inner_text().strip()
                    if txt in ("상신", "결재상신", "수정 후 상신"):
                        logger.info(f"상신 버튼 발견 (div.topBtn): '{txt}'")
                        return btn
                except Exception:
                    continue
        except Exception:
            pass

        # 폴백: button/a 태그
        for selector in [
            "button:has-text('결재상신')",
            "button:has-text('상신')",
            "a:has-text('상신')",
            "span:has-text('상신')",
        ]:
            try:
                candidates = doc_page.locator(selector).all()
                for c in candidates:
                    if c.is_visible(timeout=1000):
                        txt = c.inner_text().strip()
                        if "상신" in txt:
                            logger.info(f"상신 버튼 발견 (폴백 '{selector}'): '{txt}'")
                            return c
            except Exception:
                continue

        return None

    def _click_submit_button(self, doc_page: "Page", submit_btn) -> dict:
        """
        결재상신 버튼 클릭 후 결과 확인.

        Returns:
            {"success": bool, "message": str}
        """
        _save_debug(doc_page, "draft_03_before_submit")

        try:
            submit_btn.click(force=True)
            logger.info("결재상신 버튼 클릭 완료")
        except Exception as e:
            return {"success": False, "message": f"상신 버튼 클릭 실패: {e}"}

        # 상신 후 확인 다이얼로그 처리 (이미 page.on("dialog") 등록됨)
        # 네트워크 안정 대기
        try:
            doc_page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            logger.warning("상신 후 networkidle 타임아웃 — 계속 진행")
            time.sleep(3)
        except Exception:
            time.sleep(3)

        _save_debug(doc_page, "draft_04_after_submit")

        # 에러 메시지 확인
        try:
            error_el = doc_page.locator(
                "div.alert-message, div.error-message, .OBTAlert_message, div[class*='error']"
            ).first
            if error_el.is_visible(timeout=2000):
                err_text = error_el.inner_text().strip()
                logger.error(f"상신 후 에러 메시지: {err_text}")
                return {"success": False, "message": f"상신 중 오류: {err_text}"}
        except Exception:
            pass

        # 성공 시 팝업이 닫히거나 URL이 변경됨
        try:
            if doc_page.is_closed():
                logger.info("상신 완료 — 팝업 자동 닫힘")
                return {"success": True, "message": "결재상신이 완료되었습니다."}
        except Exception:
            pass

        # URL 변화 확인 (상신 완료 시 목록으로 이동하는 경우)
        current_url = ""
        try:
            current_url = doc_page.url
        except Exception:
            pass

        if "popup" not in current_url.lower() or doc_page.is_closed():
            return {"success": True, "message": "결재상신이 완료되었습니다."}

        # 상신 완료 텍스트 확인
        try:
            body_text = doc_page.inner_text("body")
            if any(kw in body_text for kw in ["상신 완료", "결재상신이 완료", "문서가 상신"]):
                return {"success": True, "message": "결재상신이 완료되었습니다."}
        except Exception:
            pass

        return {"success": True, "message": "결재상신 버튼을 클릭했습니다. 결과를 확인해주세요."}

    def create_proof_issuance(self, data: dict) -> dict:
        """
        [회계팀] 증빙발행 신청서 작성

        Args:
            data: {
                "title": "제목",
                "issue_type": "발행구분 (세금계산서/영수증/계산서)",
                "vendor_name": "발행처(거래처명)",
                "business_number": "사업자번호",
                "supply_amount": 공급가액(숫자),
                "tax_amount": 세액(숫자),
                "issue_date": "발행일 (YYYY-MM-DD)",
                "item_description": "품목/내용",
                "note": "비고 (선택)",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "증빙발행 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_advance_payment_request(self, data: dict) -> dict:
        """
        [본사]선급금 요청서 작성

        Args:
            data: {
                "title": "제목",
                "project": "프로젝트 (코드도움)",
                "vendor_name": "거래처명",
                "amount": 요청금액(숫자),
                "payment_date": "지급요청일 (YYYY-MM-DD)",
                "purpose": "요청사유",
                "bank_name": "은행명",
                "account_number": "계좌번호",
                "account_holder": "예금주",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "선급금요청 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_advance_payment_settlement(self, data: dict) -> dict:
        """
        [본사]선급금 정산서 작성

        Args:
            data: {
                "title": "제목",
                "project": "프로젝트 (코드도움)",
                "vendor_name": "거래처명",
                "original_amount": 선급금액(숫자),
                "used_amount": 사용금액(숫자),
                "description": "정산내역",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "선급금정산 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_overtime_request(self, data: dict) -> dict:
        """
        연장근무신청서 작성

        Args:
            data: {
                "title": "제목",
                "work_date": "근무일 (YYYY-MM-DD)",
                "start_time": "시작시간 (HH:MM)",
                "end_time": "종료시간 (HH:MM)",
                "reason": "사유",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "연장근무 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_outside_work_request(self, data: dict) -> dict:
        """
        외근신청서(당일) 작성

        Args:
            data: {
                "title": "제목",
                "work_date": "외근일 (YYYY-MM-DD)",
                "destination": "방문처",
                "purpose": "외근사유",
                "start_time": "출발시간 (HH:MM, 선택)",
                "end_time": "복귀시간 (HH:MM, 선택)",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "외근신청 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_referral_bonus_request(self, data: dict) -> dict:
        """
        사내추천비 자금 요청서 작성

        Args:
            data: {
                "title": "제목",
                "recommended_person": "추천대상자",
                "recommender": "추천인",
                "amount": 요청금액(숫자),
                "purpose": "사용목적",
                "description": "상세내용 (선택)",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "사내추천비 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_form(self, form_key: str, data: dict) -> dict:
        """
        양식 키로 적절한 작성 메서드를 라우팅

        Args:
            form_key: FORM_TEMPLATES 키 (예: "지출결의서", "거래처등록")
            data: 양식별 데이터 딕셔너리
        Returns:
            {"success": bool, "message": str}
        """
        # 양식 키 → 메서드 매핑
        method_map = {
            "지출결의서": self.create_expense_report,
            "거래처등록": self.create_vendor_registration,
            "증빙발행": self.create_proof_issuance,
            "선급금요청": self.create_advance_payment_request,
            "선급금정산": self.create_advance_payment_settlement,
            "연장근무": self.create_overtime_request,
            "외근신청": self.create_outside_work_request,
            "사내추천비": self.create_referral_bonus_request,
        }

        method = method_map.get(form_key)
        if not method:
            return {"success": False, "message": f"지원하지 않는 양식입니다: {form_key}"}

        return method(data)
