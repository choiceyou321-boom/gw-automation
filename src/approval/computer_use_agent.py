"""
Phase B: Computer Use 전용 GW 자동화 에이전트

Playwright DOM 조작이 실패하는 경우 사용:
1. Playwright 자동화 시도 → 실패
2. computer_use_agent.py로 폴백 → 스크린샷 + 클릭/입력

의존성:
- anthropic 라이브러리 (claude-3-5-sonnet, computer_use beta)
- Playwright (브라우저 세션 공유)
"""

from __future__ import annotations

import os
import base64
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

# anthropic import: 없을 경우에도 모듈 로드가 실패하지 않도록 처리
try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None  # type: ignore
    _ANTHROPIC_AVAILABLE = False

logger = logging.getLogger("computer_use_agent")

# ─────────────────────────────────────────
# 상수
# ─────────────────────────────────────────

# Computer Use 최대 반복 횟수 (무한루프 하드 제한)
MAX_STEPS = 20

# 스크린샷 저장 디렉토리 (base.py / attendance.py 와 동일 경로)
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "approval_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# 기본 뷰포트 크기 (GW 화면 기준)
DISPLAY_WIDTH_PX = 1920
DISPLAY_HEIGHT_PX = 1080

# Computer Use API 모델
DEFAULT_MODEL = "claude-3-5-sonnet-20241022"

# Computer Use beta 헤더
BETA_HEADER = "computer-use-2024-10-22"


# ─────────────────────────────────────────
# 디버그 유틸
# ─────────────────────────────────────────

def _save_debug(page: "Page", name: str) -> None:
    """디버그용 스크린샷 저장 (base.py 패턴 동일)"""
    try:
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path))
        logger.info(f"스크린샷 저장: {path}")
    except Exception as e:
        logger.warning(f"스크린샷 저장 실패: {e}")


# ─────────────────────────────────────────
# 메인 클래스
# ─────────────────────────────────────────

class ComputerUseGWAgent:
    """
    Claude Computer Use API를 활용한 GW 자동화 에이전트.
    기존 Playwright 세션(page)을 재사용해 스크린샷 기반으로 조작.

    사용 예시:
        agent = ComputerUseGWAgent(page)
        result = agent.fill_form_with_vision(
            task="연차휴가신청서 작성, 2026-04-01 연차 1일",
            data={"start_date": "2026-04-01", "end_date": "2026-04-01", "reason": "개인 사유"},
        )
    """

    def __init__(self, page: "Page", model: str = DEFAULT_MODEL):
        """
        Args:
            page: 기존 Playwright Page 인스턴스 (브라우저 세션 공유)
            model: Claude 모델 ID (기본: claude-3-5-sonnet-20241022)
        """
        if not _ANTHROPIC_AVAILABLE:
            raise RuntimeError(
                "anthropic 라이브러리가 설치되어 있지 않습니다. "
                "`pip install anthropic` 를 실행하세요."
            )

        self.page = page
        self.model = model

        # Anthropic 클라이언트 초기화 (ANTHROPIC_API_KEY 환경변수 사용)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다."
            )
        self.client = anthropic.Anthropic(api_key=api_key)

        logger.info(f"ComputerUseGWAgent 초기화 완료 (model={model})")

    # ─────────────────────────────────────────
    # 내부 유틸
    # ─────────────────────────────────────────

    def _screenshot_base64(self) -> str:
        """현재 페이지 스크린샷을 PNG base64 문자열로 반환"""
        screenshot_bytes = self.page.screenshot()
        return base64.b64encode(screenshot_bytes).decode("utf-8")

    def _get_viewport_size(self) -> tuple[int, int]:
        """
        현재 페이지 뷰포트 크기를 반환.
        설정 값이 없으면 기본값(1920x1080) 사용.
        """
        try:
            viewport = self.page.viewport_size
            if viewport:
                return viewport["width"], viewport["height"]
        except Exception:
            pass
        return DISPLAY_WIDTH_PX, DISPLAY_HEIGHT_PX

    def _execute_action(self, action: dict) -> bool:
        """
        Claude Computer Use API가 반환한 action을 Playwright로 실행.

        지원 action 타입:
            - screenshot: 스크린샷만 캡처 (상태 확인용, 실제 동작 없음)
            - click: 좌표 클릭
            - left_click: 좌표 좌클릭 (click 별칭)
            - double_click: 더블클릭
            - right_click: 우클릭
            - middle_click: 가운데 클릭
            - type: 텍스트 입력
            - key: 키보드 단축키/특수 키 (예: "Return", "Tab", "Escape")
            - scroll: 스크롤 (wheel)
            - mouse_move: 마우스 이동

        Args:
            action: Claude가 반환한 action dict
                예) {"action": "click", "coordinate": [960, 540]}
                    {"action": "type", "text": "안녕하세요"}
                    {"action": "key", "text": "Return"}
                    {"action": "scroll", "coordinate": [960, 540], "direction": "down", "amount": 3}

        Returns:
            True: 실행 성공, False: 실행 실패 또는 미지원 action
        """
        page = self.page
        action_type = action.get("action", "")

        try:
            # ── 스크린샷 (상태 확인용) ──
            if action_type == "screenshot":
                logger.debug("action: screenshot (상태 확인)")
                return True

            # ── 클릭 계열 ──
            elif action_type in ("click", "left_click"):
                coord = action.get("coordinate", [])
                if len(coord) < 2:
                    logger.warning(f"click: coordinate 누락 {action}")
                    return False
                x, y = int(coord[0]), int(coord[1])
                page.mouse.click(x, y)
                logger.info(f"클릭: ({x}, {y})")
                page.wait_for_timeout(500)
                return True

            elif action_type == "double_click":
                coord = action.get("coordinate", [])
                if len(coord) < 2:
                    logger.warning(f"double_click: coordinate 누락 {action}")
                    return False
                x, y = int(coord[0]), int(coord[1])
                page.mouse.dblclick(x, y)
                logger.info(f"더블클릭: ({x}, {y})")
                page.wait_for_timeout(500)
                return True

            elif action_type == "right_click":
                coord = action.get("coordinate", [])
                if len(coord) < 2:
                    logger.warning(f"right_click: coordinate 누락 {action}")
                    return False
                x, y = int(coord[0]), int(coord[1])
                page.mouse.click(x, y, button="right")
                logger.info(f"우클릭: ({x}, {y})")
                page.wait_for_timeout(300)
                return True

            elif action_type == "middle_click":
                coord = action.get("coordinate", [])
                if len(coord) < 2:
                    logger.warning(f"middle_click: coordinate 누락 {action}")
                    return False
                x, y = int(coord[0]), int(coord[1])
                page.mouse.click(x, y, button="middle")
                logger.info(f"가운데 클릭: ({x}, {y})")
                page.wait_for_timeout(300)
                return True

            # ── 텍스트 입력 ──
            elif action_type == "type":
                text = action.get("text", "")
                page.keyboard.type(text)
                logger.info(f"텍스트 입력: {text[:50]}{'...' if len(text) > 50 else ''}")
                page.wait_for_timeout(200)
                return True

            # ── 특수 키 입력 ──
            elif action_type == "key":
                key = action.get("text", "")
                if not key:
                    logger.warning(f"key: text 누락 {action}")
                    return False
                # Playwright 키 이름 변환 (anthropic 표기 → Playwright 표기)
                key_map = {
                    "Return": "Enter",
                    "ctrl+a": "Control+a",
                    "ctrl+c": "Control+c",
                    "ctrl+v": "Control+v",
                    "ctrl+z": "Control+z",
                    "super+l": "Meta+l",
                }
                playwright_key = key_map.get(key, key)
                page.keyboard.press(playwright_key)
                logger.info(f"키 입력: {key} → {playwright_key}")
                page.wait_for_timeout(300)
                return True

            # ── 스크롤 ──
            elif action_type == "scroll":
                coord = action.get("coordinate", [])
                direction = action.get("direction", "down")
                amount = int(action.get("amount", 3))

                # 스크롤 좌표가 있으면 먼저 마우스 이동
                if len(coord) >= 2:
                    page.mouse.move(int(coord[0]), int(coord[1]))

                # 방향에 따른 delta 계산 (한 단위 = 100px)
                delta_x = 0
                delta_y = 0
                scroll_unit = 100
                if direction == "down":
                    delta_y = scroll_unit * amount
                elif direction == "up":
                    delta_y = -scroll_unit * amount
                elif direction == "right":
                    delta_x = scroll_unit * amount
                elif direction == "left":
                    delta_x = -scroll_unit * amount

                page.mouse.wheel(delta_x, delta_y)
                logger.info(f"스크롤: direction={direction}, amount={amount}, delta=({delta_x}, {delta_y})")
                page.wait_for_timeout(300)
                return True

            # ── 마우스 이동 ──
            elif action_type == "mouse_move":
                coord = action.get("coordinate", [])
                if len(coord) < 2:
                    logger.warning(f"mouse_move: coordinate 누락 {action}")
                    return False
                x, y = int(coord[0]), int(coord[1])
                page.mouse.move(x, y)
                logger.debug(f"마우스 이동: ({x}, {y})")
                return True

            else:
                logger.warning(f"지원하지 않는 action 타입: {action_type} (전체: {action})")
                return False

        except Exception as e:
            logger.error(f"action 실행 오류 [{action_type}]: {e}")
            _save_debug(page, f"error_action_{action_type}")
            return False

    def _build_computer_tool(self) -> dict:
        """Computer Use tool 정의 딕셔너리 생성"""
        width, height = self._get_viewport_size()
        return {
            "type": "computer_20241022",
            "name": "computer",
            "display_width_px": width,
            "display_height_px": height,
        }

    # ─────────────────────────────────────────
    # 메인 API: 비전 기반 양식 작성
    # ─────────────────────────────────────────

    def fill_form_with_vision(
        self,
        task: str,
        data: dict,
        max_steps: int = MAX_STEPS,
    ) -> dict:
        """
        Claude Computer Use API로 GW 양식을 시각적으로 자동 작성.

        동작 흐름:
            1. 현재 페이지 스크린샷 캡처
            2. Claude에게 task + data + 스크린샷 전달
            3. Claude가 반환한 action 순서대로 실행
            4. 각 step마다 최신 스크린샷을 Claude에게 피드백
            5. Claude가 "stop_reason=end_turn" 이거나 tool_use 없으면 완료

        Args:
            task: 자연어 작업 설명
                예) "연차휴가신청서를 작성해주세요. 날짜: 2026-04-01, 사유: 개인 사유"
            data: 입력 데이터 dict (task 설명에도 포함되어 있어야 함)
                예) {"start_date": "2026-04-01", "end_date": "2026-04-01", "reason": "개인 사유"}
            max_steps: 최대 실행 단계 수 (기본값: MAX_STEPS=20, 하드 제한)

        Returns:
            {
                "success": bool,
                "message": str,      # 결과 메시지 (한국어)
                "steps": int,        # 실제 실행 단계 수
            }
        """
        # max_steps 하드 제한 (요청값이 MAX_STEPS를 초과할 수 없음)
        max_steps = min(max_steps, MAX_STEPS)

        if not _ANTHROPIC_AVAILABLE:
            return {
                "success": False,
                "message": "anthropic 라이브러리가 설치되어 있지 않습니다.",
                "steps": 0,
            }

        # 시스템 프롬프트: GW 자동화 컨텍스트 설명
        system_prompt = (
            "당신은 한국의 그룹웨어(GW) 시스템을 자동으로 조작하는 에이전트입니다. "
            "주어진 task와 data를 바탕으로 현재 화면에서 필요한 작업을 수행하세요. "
            "각 단계마다 스크린샷을 확인하고 정확한 좌표를 클릭해 양식을 작성하세요. "
            "작업이 완료되면 더 이상 tool을 호출하지 마세요."
        )

        # 초기 사용자 메시지 구성
        initial_text = (
            f"다음 작업을 수행해주세요:\n\n"
            f"작업: {task}\n\n"
            f"입력 데이터:\n"
            + "\n".join(f"  - {k}: {v}" for k, v in data.items())
            + "\n\n현재 화면 스크린샷을 확인하고 작업을 시작하세요."
        )

        # 초기 스크린샷 캡처
        _save_debug(self.page, "cu_00_initial")
        screenshot_b64 = self._screenshot_base64()

        # 대화 히스토리 초기화
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    },
                    {"type": "text", "text": initial_text},
                ],
            }
        ]

        computer_tool = self._build_computer_tool()
        step = 0

        logger.info(f"Computer Use 시작: task='{task[:60]}...', max_steps={max_steps}")

        try:
            while step < max_steps:
                step += 1
                logger.info(f"[step {step}/{max_steps}] Claude API 호출 중...")

                # Claude Computer Use API 호출
                response = self.client.beta.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system_prompt,
                    tools=[computer_tool],
                    messages=messages,
                    betas=[BETA_HEADER],
                )

                logger.debug(f"[step {step}] stop_reason={response.stop_reason}")

                # tool_use 블록 수집
                tool_use_blocks = [
                    block for block in response.content
                    if block.type == "tool_use" and block.name == "computer"
                ]

                # assistant 응답을 대화 히스토리에 추가
                messages.append({
                    "role": "assistant",
                    "content": response.content,
                })

                # tool_use 없거나 end_turn → 작업 완료
                if not tool_use_blocks or response.stop_reason == "end_turn":
                    # Claude의 텍스트 응답 추출
                    text_blocks = [
                        block.text for block in response.content
                        if hasattr(block, "text")
                    ]
                    completion_msg = " ".join(text_blocks) if text_blocks else "작업이 완료되었습니다."
                    _save_debug(self.page, f"cu_{step:02d}_completed")
                    logger.info(f"Computer Use 완료 (step={step}): {completion_msg[:80]}")
                    return {
                        "success": True,
                        "message": completion_msg,
                        "steps": step,
                    }

                # tool_use action 순서대로 실행
                tool_results = []
                for block in tool_use_blocks:
                    action = block.input  # {"action": "click", "coordinate": [...]} 등
                    logger.info(f"[step {step}] action 실행: {action}")

                    action_ok = self._execute_action(action)

                    # 각 action 실행 후 스크린샷 저장 (디버그)
                    _save_debug(self.page, f"cu_{step:02d}_after_{action.get('action', 'unknown')}")

                    # action이 screenshot이거나 실행 후에는 최신 스크린샷 캡처
                    new_screenshot_b64 = self._screenshot_base64()

                    # tool_result 구성 (Computer Use 프로토콜)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": new_screenshot_b64,
                                },
                            }
                        ],
                    })

                # tool_result를 user 메시지로 대화 히스토리에 추가
                messages.append({
                    "role": "user",
                    "content": tool_results,
                })

                # 짧은 대기 (GW UI 반응 시간)
                self.page.wait_for_timeout(300)

            # max_steps 초과
            logger.warning(f"Computer Use: max_steps({max_steps}) 도달, 작업 미완료")
            _save_debug(self.page, f"cu_{step:02d}_max_steps_reached")
            return {
                "success": False,
                "message": f"최대 단계 수({max_steps})에 도달했지만 작업이 완료되지 않았습니다.",
                "steps": step,
            }

        except Exception as e:
            logger.error(f"Computer Use 오류 (step={step}): {e}")
            _save_debug(self.page, f"cu_error_step_{step}")
            return {
                "success": False,
                "message": f"Computer Use 에이전트 오류: {e}",
                "steps": step,
            }

    # ─────────────────────────────────────────
    # 메뉴 탐색
    # ─────────────────────────────────────────

    def navigate_to_form(self, form_name: str) -> bool:
        """
        시각적으로 GW 메뉴를 탐색해 지정한 양식을 열기.

        Args:
            form_name: 양식 이름 (예: "연차휴가신청서", "지출결의서", "외근신청서")

        Returns:
            True: 양식 열기 성공, False: 실패
        """
        task = (
            f"GW 그룹웨어에서 '{form_name}' 양식을 찾아서 열어주세요. "
            f"메뉴를 탐색하거나 검색 기능을 활용하세요. "
            f"양식이 열리면 작업을 멈추세요."
        )
        result = self.fill_form_with_vision(
            task=task,
            data={"form_name": form_name},
            max_steps=10,  # 탐색은 10 step으로 제한
        )
        if result["success"]:
            logger.info(f"양식 탐색 성공: {form_name}")
            return True
        else:
            logger.warning(f"양식 탐색 실패: {form_name} — {result['message']}")
            return False


# ─────────────────────────────────────────
# 폴백 진입점 (공개 API)
# ─────────────────────────────────────────

def create_computer_use_fallback(page: "Page", form_type: str, data: dict) -> dict:
    """
    Playwright DOM 자동화 실패 시 Computer Use 폴백 진입점.

    기존 자동화 코드에서 다음 패턴으로 사용:

        result = create_form(data)
        if not result["success"]:
            result = create_computer_use_fallback(page, "연차휴가신청서", data)

    Args:
        page: 기존 Playwright Page 인스턴스
        form_type: 양식 종류 (예: "연차휴가신청서", "지출결의서", "외근신청서")
        data: 입력 데이터 dict

    Returns:
        {"success": bool, "message": str, "steps": int}
    """
    if not _ANTHROPIC_AVAILABLE:
        logger.error("anthropic 라이브러리 미설치 — Computer Use 폴백 불가")
        return {
            "success": False,
            "message": (
                "Computer Use 폴백을 사용하려면 anthropic 라이브러리가 필요합니다. "
                "`pip install anthropic` 를 실행하세요."
            ),
            "steps": 0,
        }

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY 미설정 — Computer Use 폴백 불가")
        return {
            "success": False,
            "message": "ANTHROPIC_API_KEY 환경변수가 설정되지 않아 Computer Use 폴백을 사용할 수 없습니다.",
            "steps": 0,
        }

    logger.info(f"Computer Use 폴백 진입: form_type={form_type}")

    # 자연어 task 구성 (form_type + data 기반)
    data_summary = ", ".join(f"{k}={v}" for k, v in data.items())
    task = (
        f"GW 그룹웨어에서 '{form_type}'을 작성해주세요. "
        f"필요한 데이터: {data_summary}. "
        f"양식을 찾아서 열고, 모든 필드를 입력한 뒤 임시보관(보관) 버튼을 클릭하세요."
    )

    try:
        agent = ComputerUseGWAgent(page=page)
        result = agent.fill_form_with_vision(task=task, data=data)
        logger.info(f"Computer Use 폴백 완료: success={result['success']}, steps={result['steps']}")
        return result
    except Exception as e:
        logger.error(f"Computer Use 폴백 오류: {e}")
        _save_debug(page, "cu_fallback_error")
        return {
            "success": False,
            "message": f"Computer Use 폴백 실패: {e}",
            "steps": 0,
        }
