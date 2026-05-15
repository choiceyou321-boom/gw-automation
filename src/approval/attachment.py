"""
첨부파일 업로드 헬퍼.

지출결의서 등 양식의 파일 첨부 영역을 처리한다.
GW 첨부 영역 구조:
  - input[type=file][id=uploadFile] (hidden) → setInputFiles로 직접 처리 (방법 1)
  - placeholder="파일을 첨부해주세요" input 옆 "선택" 버튼 → file_chooser (방법 2)

이전에 `ExpenseReportMixin._upload_attachment`로 존재했으나 4938→4154줄 분할 작업의
일환으로 독립 모듈로 추출됨.
"""
from __future__ import annotations

import logging
import pathlib
from playwright.sync_api import Page

from src.approval.base import _save_debug

logger = logging.getLogger("approval_automation")


def upload_attachment(page: Page, file_path: str) -> bool:
    """첨부파일 업로드.

    Args:
        page: Playwright Page 인스턴스
        file_path: 업로드할 파일의 로컬 절대 경로
    Returns:
        True if 업로드 성공, False if 파일 없음 또는 셀렉터 모두 실패.
    """
    p = pathlib.Path(file_path)
    if not p.exists():
        logger.warning(f"첨부파일 없음: {file_path}")
        return False

    # 방법 1: hidden file input에 직접 파일 설정 (가장 빠른 정상 경로)
    try:
        file_input = page.locator(
            "input[type='file']#uploadFile, input[type='file'][name='uploadFile']"
        ).first
        file_input.set_input_files(str(p))
        logger.info(f"첨부파일 업로드 (hidden input): {p.name}")
        return True
    except Exception:
        pass

    # 방법 2: "선택" 버튼 클릭 → file chooser 처리
    try:
        with page.expect_file_chooser() as fc_info:
            clicked = _click_attachment_button(page)
            if not clicked:
                # 클릭 이벤트가 발생하지 않으면 fc_info.value는 30초 timeout 대기.
                # 즉시 return해 with 컨텍스트를 종료하고 무익한 대기를 회피.
                _save_debug(page, "error_attachment_button_selector_exhausted")
                logger.error(
                    "첨부 선택 버튼을 찾지 못했습니다. 기본/확장 14종 셀렉터 + JS 동적 탐색 모두 실패. "
                    "DOM 구조 변경 가능성 — 스크린샷 확인."
                )
                return False

        file_chooser = fc_info.value
        file_chooser.set_files(str(p))
        logger.info(f"첨부파일 업로드 (file chooser): {p.name}")
        return True
    except Exception as e:
        logger.warning(f"첨부파일 업로드 실패: {e}")

    return False


def _click_attachment_button(page: Page) -> bool:
    """첨부 영역의 "선택" 버튼을 다층 폴백으로 찾아 클릭. 클릭 성공 시 True."""
    # 1차: y 범위 기반 "선택" 버튼 (DOM 데이터 기준 230~270)
    sel_btns = page.locator("button:has-text('선택')").all()
    for btn in sel_btns:
        if btn.is_visible():
            box = btn.bounding_box()
            if box and 230 < box["y"] < 270:
                btn.click(force=True)
                logger.info(f"첨부 '선택' 버튼 클릭 (y={box['y']:.0f})")
                return True

    # 2차: 확장 셀렉터 14종 (다양한 라벨/속성)
    for extra_sel in [
        "button:has-text('선택')",
        "button:has-text('파일선택')",
        "button:has-text('첨부')",
        "[title='파일선택']",
        "[title='선택']",
        "input[type='file'] + button",
        "label[for='uploadFile']",
        "label:has(input[type='file'])",
        "button[title*='파일']",
        "button:has(svg)",
        "[aria-label*='파일']",
        "[aria-label*='선택']",
        "button[class*='upload']",
        "button[class*='file']",
    ]:
        try:
            extra_btn = page.locator(extra_sel).first
            if extra_btn.is_visible(timeout=1500):
                extra_btn.click(force=True)
                logger.info(f"첨부 버튼 클릭 (확장 셀렉터 '{extra_sel}')")
                return True
        except Exception:
            continue

    # 3차: JS 동적 탐색 — 텍스트/title/aria-label에 파일 관련 키워드 포함된 클릭 요소
    try:
        js_clicked = page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button, [role="button"], label, a'));
            for (const btn of btns) {
                const text = btn.textContent.trim();
                const title = btn.getAttribute('title') || '';
                const ariaLabel = btn.getAttribute('aria-label') || '';
                const isMatch = ['선택', '파일선택', '첨부', '파일'].some(
                    kw => text === kw || title.includes(kw) || ariaLabel.includes(kw)
                );
                if (!isMatch) continue;
                const r = btn.getBoundingClientRect();
                if (r.width > 0 && r.height > 0 && r.y > 100 && r.y < 400) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")
        if js_clicked:
            logger.info("첨부 버튼 클릭 (JS직접클릭)")
            return True
    except Exception as e:
        logger.debug(f"첨부 버튼 JS동적탐색 실패: {e}")

    return False
