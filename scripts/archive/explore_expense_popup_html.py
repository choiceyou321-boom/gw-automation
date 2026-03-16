"""
지출결의서 팝업 폼의 dzEditor HTML 템플릿 추출

목적: 팝업 폼에서 보관 기능을 구현하기 위해 HTML 구조 파악

사용법:
  python scripts/explore_expense_popup_html.py
"""

import sys
import os
import io
import time
import json
import logging
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / "config" / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("explore_html")

OUTPUT_DIR = ROOT_DIR / "data" / "dom_explore"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GW_URL = "https://gw.glowseoul.co.kr"


def main():
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context

    pw = sync_playwright().start()
    browser, context, page = login_and_get_context(
        playwright_instance=pw, headless=False
    )
    page.set_viewport_size({"width": 1920, "height": 1080})
    logger.info("로그인 완료")

    # 팝업으로 지출결의서 열기
    popup_url = f"{GW_URL}/#popup?MicroModuleCode=eap&formId=255&callComp=UBAP001"
    popup_page = context.new_page()
    popup_page.set_viewport_size({"width": 1920, "height": 1080})
    popup_page.goto(popup_url)
    try:
        popup_page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    time.sleep(5)
    logger.info("팝업 폼 로드 완료")

    # ── 제목 필드 구조 확인 ──
    try:
        title_val = popup_page.locator("input").all()
        title_info = []
        for inp in title_val[:10]:
            try:
                val = inp.input_value()
                placeholder = inp.get_attribute("placeholder") or ""
                name = inp.get_attribute("name") or ""
                cls = inp.get_attribute("class") or ""
                title_info.append({
                    "value": val[:60],
                    "placeholder": placeholder[:40],
                    "name": name,
                    "class": cls[:60],
                })
            except Exception:
                pass
        logger.info(f"Input 필드들: {json.dumps(title_info, ensure_ascii=False, indent=2)}")
    except Exception as e:
        logger.warning(f"Input 탐색 실패: {e}")

    # ── dzEditor 프레임 구조 확인 ──
    frames = popup_page.frames
    logger.info(f"\n프레임 수: {len(frames)}")
    for i, frame in enumerate(frames):
        logger.info(f"  frame[{i}]: name={frame.name}, url={frame.url[:80]}")

    # ── editorView 프레임에서 getEditorHTMLCodeIframe(0) 호출 ──
    editor_html = None
    # 방법 1: editorView 프레임 찾기
    editor_frame = None
    for frame in frames:
        if "editorView" in frame.name or "editorView" in frame.url:
            editor_frame = frame
            logger.info(f"editorView 프레임 발견: {frame.name}")
            break

    if editor_frame:
        try:
            editor_html = editor_frame.evaluate("getEditorHTMLCodeIframe(0)")
            logger.info(f"getEditorHTMLCodeIframe(0) 성공: {len(editor_html)} chars")
        except Exception as e:
            logger.warning(f"getEditorHTMLCodeIframe 실패: {e}")

    # 방법 2: 팝업 페이지에서 직접 시도
    if not editor_html:
        try:
            editor_html = popup_page.evaluate("getEditorHTMLCodeIframe(0)")
            logger.info(f"popup_page에서 직접 호출 성공: {len(editor_html)} chars")
        except Exception as e:
            logger.warning(f"직접 호출도 실패: {e}")

    # 방법 3: dzeditor_0 프레임에서 contentDocument 접근
    if not editor_html:
        for frame in frames:
            if "dzeditor" in frame.name:
                try:
                    editor_html = frame.evaluate("document.body.innerHTML")
                    logger.info(f"dzeditor body.innerHTML: {len(editor_html)} chars")
                except Exception:
                    pass
                break

    # ── HTML 저장 ──
    if editor_html:
        html_path = OUTPUT_DIR / "expense_popup_editor_html.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(editor_html)
        logger.info(f"에디터 HTML 저장: {html_path}")
        # 첫 3000자 출력
        print(f"\n=== dzEditor HTML (처음 3000자) ===")
        print(editor_html[:3000])
        print(f"... (총 {len(editor_html)}자)")
    else:
        logger.error("에디터 HTML 추출 실패!")

    # ── 상단 필드 (제목, 기안부서 등) 탐색 ──
    try:
        top_fields = popup_page.evaluate("""() => {
            const results = [];
            // th-td 쌍 찾기
            document.querySelectorAll('th').forEach(th => {
                const text = th.textContent?.trim();
                const td = th.nextElementSibling;
                if (td) {
                    const input = td.querySelector('input, select, textarea');
                    results.push({
                        label: text?.substring(0, 20),
                        hasInput: !!input,
                        inputType: input?.tagName,
                        inputValue: input?.value?.substring(0, 60) || '',
                    });
                }
            });
            return results;
        }""")
        logger.info(f"\n상단 필드 (th-td):")
        for f in top_fields:
            logger.info(f"  {f['label']}: hasInput={f['hasInput']}, type={f.get('inputType')}, value='{f.get('inputValue')}'")
    except Exception as e:
        logger.warning(f"상단 필드 탐색 실패: {e}")

    popup_page.close()
    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
