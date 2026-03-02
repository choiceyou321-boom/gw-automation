"""
거래처등록 양식 본문(dzEditor iframe) 내부 HTML 구조 추출 v2
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

OUT_DIR = ROOT / "data" / "vendor_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)


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

    # 팝업 열기
    print("[2] 팝업 열기...")
    form_url = "https://gw.glowseoul.co.kr/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA6000"
    page.goto(form_url, wait_until="networkidle", timeout=15000)
    time.sleep(3)

    search = page.locator("input[placeholder*='카테고리 또는 양식명']").first
    if not search.is_visible(timeout=5000):
        search = page.locator("input:visible:not([readonly])").first
    search.click()
    search.fill("국내 거래처")
    search.press("Enter")
    time.sleep(3)

    result = page.locator("text=국내 거래처등록").first
    result.click(force=True)
    time.sleep(1)

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
        print("  팝업 안 열림!")
        close_session(browser)
        pw_inst.stop()
        return

    popup.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(5)
    popup.set_viewport_size({"width": 1920, "height": 1080})

    # === iframe 접근 (frame_locator 사용) ===
    print("\n[3] iframe 접근 (frame_locator)...")

    # 모든 frame 목록
    frames = popup.frames
    print(f"  frame 수: {len(frames)}")
    for i, frame in enumerate(frames):
        print(f"  frame[{i}]: name='{frame.name}', url='{frame.url[:80]}'")

    # dzEditor iframe 찾기
    editor_frame = None
    for frame in frames:
        if "dzEditor" in frame.url or "editorView" in frame.url:
            editor_frame = frame
            break

    if not editor_frame:
        print("  dzEditor iframe을 찾지 못함!")
        # 모든 frame의 body 확인
        for i, frame in enumerate(frames):
            if frame.url and frame.url != "about:blank":
                try:
                    html = frame.evaluate("() => document.body ? document.body.innerHTML : ''")
                    if len(html) > 100:
                        print(f"  frame[{i}] has content: {len(html)} chars")
                        (OUT_DIR / f"frame{i}_body.html").write_text(html, encoding="utf-8")
                except:
                    pass
        close_session(browser)
        pw_inst.stop()
        return

    print(f"  dzEditor frame: url={editor_frame.url[:80]}")

    # body HTML 추출
    body_html = editor_frame.evaluate("() => document.body ? document.body.innerHTML : ''")
    body_text = editor_frame.evaluate("() => document.body ? document.body.innerText : ''")

    print(f"  body HTML 길이: {len(body_html)}")
    print(f"  body text 길이: {len(body_text)}")

    (OUT_DIR / "editor_body.html").write_text(body_html, encoding="utf-8")
    (OUT_DIR / "editor_body.txt").write_text(body_text, encoding="utf-8")
    print("  저장: editor_body.html, editor_body.txt")

    # 본문 텍스트 출력
    print(f"\n  === 본문 텍스트 ===")
    for line in body_text.split("\n"):
        line = line.strip()
        if line:
            print(f"  {line[:80]}")

    # 테이블 구조 상세 분석
    print("\n[4] 테이블 구조 분석...")
    tables = editor_frame.evaluate("""
    () => {
        const tables = document.querySelectorAll('table');
        const result = [];
        for (let ti = 0; ti < tables.length; ti++) {
            const t = tables[ti];
            const info = { index: ti, rows: [] };
            const trs = t.querySelectorAll(':scope > tbody > tr, :scope > tr');
            for (let ri = 0; ri < trs.length; ri++) {
                const tr = trs[ri];
                const cells = [];
                const allCells = tr.querySelectorAll(':scope > th, :scope > td');
                for (let ci = 0; ci < allCells.length; ci++) {
                    const cell = allCells[ci];
                    const cellInfo = {
                        tag: cell.tagName,
                        text: cell.textContent.trim().substring(0, 80),
                        colspan: cell.getAttribute('colspan') || '1',
                        rowspan: cell.getAttribute('rowspan') || '1',
                        style: (cell.getAttribute('style') || '').substring(0, 150),
                        bgColor: cell.getAttribute('bgcolor') || '',
                        width: cell.getAttribute('width') || '',
                        hasInput: cell.querySelector('input') !== null,
                        hasCheckbox: cell.querySelector('input[type="checkbox"]') !== null,
                        inputCount: cell.querySelectorAll('input').length,
                        isEmpty: cell.textContent.trim() === '' || cell.textContent.trim() === '\\xa0',
                    };
                    cells.push(cellInfo);
                }
                info.rows.push(cells);
            }
            result.push(info);
        }
        return result;
    }
    """)

    print(f"  테이블 수: {len(tables)}")
    for table in tables:
        print(f"\n  === Table {table['index']} ({len(table['rows'])} rows) ===")
        for ri, row in enumerate(table['rows']):
            for ci, cell in enumerate(row):
                span = ""
                if cell['colspan'] != '1':
                    span += f" cs={cell['colspan']}"
                if cell['rowspan'] != '1':
                    span += f" rs={cell['rowspan']}"
                extra = ""
                if cell['hasInput']:
                    extra += f" [INPUT x{cell['inputCount']}]"
                if cell['hasCheckbox']:
                    extra += " [CHECKBOX]"
                if cell['isEmpty']:
                    extra += " [EMPTY]"
                if cell['bgColor']:
                    extra += f" bg={cell['bgColor']}"
                text = cell['text'][:50] if cell['text'] else ""
                print(f"    R{ri}C{ci}: <{cell['tag']}{span}> '{text}'{extra}")

    popup.close()
    close_session(browser)
    pw_inst.stop()
    print("\ndone!")


if __name__ == "__main__":
    run()
