"""
거래처등록 양식 본문 구조 정밀 분석
- 빈 양식 팝업을 열고 dzEditor 본문의 HTML 구조를 추출
- 기존 임시보관 거래처등록 문서가 있으면 열어서 비교
"""
import sys
import time
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

OUT_DIR = ROOT / "data" / "vendor_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def save(pg, name):
    path = OUT_DIR / f"analysis_{name}.png"
    pg.screenshot(path=str(path), full_page=True)
    print(f"  screenshot: {path.name}")


def run():
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password

    gw_id = "tgjeon"
    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return

    pw_inst = sync_playwright().start()
    browser, context, page = login_and_get_context(
        playwright_instance=pw_inst,
        headless=True,
        user_id=gw_id,
        user_pw=gw_pw,
    )
    page.set_viewport_size({"width": 1920, "height": 1080})

    for p in context.pages:
        if p != page:
            try: p.close()
            except: pass

    print("[1] login ok")

    # 전자결재 모듈 진입
    try:
        ea = page.locator("span.module-link.EA").first
        if ea.is_visible(timeout=5000):
            ea.click(force=True)
            time.sleep(4)
    except:
        pass

    for p in context.pages:
        if p != page:
            try: p.close()
            except: pass

    try:
        page.wait_for_selector("text=결재 HOME", timeout=10000)
    except:
        pass
    time.sleep(2)

    # ==== Part 1: 빈 양식 팝업 열어서 본문 HTML 구조 분석 ====
    print("\n[2] 빈 양식 팝업 열기...")
    form_url = "https://gw.glowseoul.co.kr/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA6000"
    page.goto(form_url, wait_until="networkidle", timeout=15000)
    time.sleep(3)

    # 검색
    search = page.locator("input[placeholder*='카테고리 또는 양식명']").first
    if not search.is_visible(timeout=5000):
        search = page.locator("input:visible:not([readonly])").first
    search.click()
    search.fill("국내 거래처")
    search.press("Enter")
    time.sleep(3)

    # 선택
    result = page.locator("text=국내 거래처등록").first
    result.click(force=True)
    time.sleep(1)

    # 팝업 감지
    pages_before = set(id(p) for p in context.pages)
    page.keyboard.press("Enter")

    popup = None
    for _ in range(30):
        time.sleep(0.5)
        for p in context.pages:
            if id(p) not in pages_before:
                popup = p
                break
        if popup:
            break

    if not popup:
        print("  팝업 열리지 않음!")
        close_session(browser)
        pw_inst.stop()
        return

    popup.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(3)
    popup.set_viewport_size({"width": 1920, "height": 1080})
    save(popup, "01_blank_form")

    # 본문 에디터 HTML 추출
    print("\n[3] 본문 HTML 구조 분석...")

    # 방법 1: contentEditable div
    editor_html = popup.evaluate("""
    () => {
        const editor = document.querySelector("[contenteditable='true']");
        if (editor) return { type: "contenteditable", html: editor.innerHTML, outerHTML: editor.outerHTML.substring(0, 500) };
        return null;
    }
    """)

    # 방법 2: iframe 내부
    iframe_html = None
    if not editor_html:
        try:
            iframe = popup.locator("iframe").first
            if iframe.is_visible(timeout=3000):
                frame = iframe.content_frame()
                if frame:
                    iframe_html = frame.evaluate("""
                    () => {
                        const body = document.body;
                        return { type: "iframe", html: body.innerHTML, outerHTML: body.outerHTML.substring(0, 500) };
                    }
                    """)
        except:
            pass

    body_data = editor_html or iframe_html
    if body_data:
        print(f"  에디터 타입: {body_data['type']}")
        html = body_data['html']
        print(f"  HTML 길이: {len(html)}")
        # HTML 저장
        (OUT_DIR / "analysis_blank_body.html").write_text(html, encoding="utf-8")
        print(f"  HTML 저장: analysis_blank_body.html")

        # 테이블 구조 분석
        tables_info = popup.evaluate("""
        () => {
            const findTables = (root) => {
                const tables = root.querySelectorAll('table');
                const result = [];
                for (const t of tables) {
                    const rows = [];
                    for (const tr of t.querySelectorAll('tr')) {
                        const cells = [];
                        for (const cell of tr.querySelectorAll('th, td')) {
                            cells.push({
                                tag: cell.tagName,
                                text: cell.textContent.trim().substring(0, 50),
                                colspan: cell.getAttribute('colspan') || '1',
                                rowspan: cell.getAttribute('rowspan') || '1',
                            });
                        }
                        rows.push(cells);
                    }
                    result.push(rows);
                }
                return result;
            };
            // contentEditable 내부
            const ce = document.querySelector("[contenteditable='true']");
            if (ce) return findTables(ce);
            return [];
        }
        """)

        if not tables_info:
            # iframe에서 시도
            try:
                iframe = popup.locator("iframe").first
                frame = iframe.content_frame()
                tables_info = frame.evaluate("""
                () => {
                    const tables = document.querySelectorAll('table');
                    const result = [];
                    for (const t of tables) {
                        const rows = [];
                        for (const tr of t.querySelectorAll('tr')) {
                            const cells = [];
                            for (const cell of tr.querySelectorAll('th, td')) {
                                cells.push({
                                    tag: cell.tagName,
                                    text: cell.textContent.trim().substring(0, 50),
                                    colspan: cell.getAttribute('colspan') || '1',
                                    rowspan: cell.getAttribute('rowspan') || '1',
                                });
                            }
                            rows.push(cells);
                        }
                        result.push(rows);
                    }
                    return result;
                }
                """)
            except:
                pass

        print(f"\n  테이블 수: {len(tables_info)}")
        for ti, table in enumerate(tables_info):
            print(f"\n  --- Table {ti} ({len(table)} rows) ---")
            for ri, row in enumerate(table):
                cells_str = " | ".join([f"<{c['tag']}> {c['text']}" for c in row])
                print(f"    Row {ri}: {cells_str}")
    else:
        print("  에디터를 찾지 못함!")

    # 전체 페이지 본문 (스크롤 포함)
    print("\n[4] 팝업 전체 텍스트...")
    try:
        full_text = popup.inner_text("body")
        (OUT_DIR / "analysis_blank_text.txt").write_text(full_text[:10000], encoding="utf-8")
        print(f"  텍스트 저장: analysis_blank_text.txt ({len(full_text)} chars)")
    except Exception as e:
        print(f"  텍스트 추출 실패: {e}")

    # 스크롤해서 하단도 캡처
    popup.evaluate("window.scrollTo(0, 500)")
    time.sleep(1)
    save(popup, "02_blank_form_scrolled")

    popup.evaluate("window.scrollTo(0, 1000)")
    time.sleep(1)
    save(popup, "03_blank_form_scrolled2")

    popup.evaluate("window.scrollTo(0, 1500)")
    time.sleep(1)
    save(popup, "04_blank_form_scrolled3")

    popup.evaluate("window.scrollTo(0, 2000)")
    time.sleep(1)
    save(popup, "05_blank_form_scrolled4")

    # ==== Part 2: 기존 임시보관 거래처등록 문서 확인 ====
    print("\n[5] 임시보관문서에서 거래처등록 문서 찾기...")
    popup.close()
    time.sleep(1)

    # 임시보관문서 페이지로 이동
    draft_url = "https://gw.glowseoul.co.kr/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBZ0120"
    page.goto(draft_url, wait_until="networkidle", timeout=15000)
    time.sleep(3)
    save(page, "06_draft_list")

    # 거래처등록 문서 찾기
    draft_text = page.inner_text("body")
    lines = [l.strip() for l in draft_text.split("\n") if l.strip()]
    print("  임시보관문서 목록:")
    for line in lines[:40]:
        if "거래처" in line or "E2E" in line or "하넬" in line:
            print(f"    >> {line[:80]}")

    # 거래처등록 문서 클릭해서 열기
    vendor_docs = page.locator("text=거래처등록").all()
    visible_docs = [d for d in vendor_docs if d.is_visible()]
    print(f"  '거래처등록' 텍스트: {len(visible_docs)}개 visible")

    if visible_docs:
        print("  첫 번째 거래처등록 문서 클릭...")
        visible_docs[0].click(force=True)
        time.sleep(5)

        # 새 팝업 확인
        for p in context.pages:
            if p != page:
                try:
                    p_url = p.url or ""
                    if "popup" in p_url or "formId" in p_url:
                        p.set_viewport_size({"width": 1920, "height": 1080})
                        time.sleep(3)
                        save(p, "07_existing_doc_popup")

                        # 본문 HTML 추출
                        existing_html = p.evaluate("""
                        () => {
                            const ce = document.querySelector("[contenteditable='true']");
                            if (ce) return ce.innerHTML;
                            return null;
                        }
                        """)
                        if not existing_html:
                            try:
                                iframe = p.locator("iframe").first
                                frame = iframe.content_frame()
                                existing_html = frame.evaluate("() => document.body.innerHTML")
                            except:
                                pass
                        if existing_html:
                            (OUT_DIR / "analysis_existing_body.html").write_text(existing_html, encoding="utf-8")
                            print(f"  기존 문서 HTML 저장: analysis_existing_body.html ({len(existing_html)} chars)")

                        # 스크롤 캡처
                        p.evaluate("window.scrollTo(0, 500)")
                        time.sleep(1)
                        save(p, "08_existing_doc_scrolled")

                        p.evaluate("window.scrollTo(0, 1000)")
                        time.sleep(1)
                        save(p, "09_existing_doc_scrolled2")

                        p.evaluate("window.scrollTo(0, 1500)")
                        time.sleep(1)
                        save(p, "10_existing_doc_scrolled3")

                        p.close()
                        break
                except Exception as e:
                    print(f"  팝업 처리 오류: {e}")

        # 같은 페이지에서 열릴 수도 있음
        save(page, "07b_after_doc_click")

    close_session(browser)
    pw_inst.stop()
    print("\ndone!")


if __name__ == "__main__":
    run()
