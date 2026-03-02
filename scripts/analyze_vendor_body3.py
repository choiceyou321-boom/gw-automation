"""
거래처등록 양식 - dzeditor_0 내부 iframe 본문 HTML 추출
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
        playwright_instance=pw_inst, headless=True,
        user_id=gw_id, user_pw=gw_pw,
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
    except: pass
    for p in context.pages:
        if p != page:
            try: p.close()
            except: pass
    try:
        page.wait_for_selector("text=결재 HOME", timeout=10000)
    except: pass
    time.sleep(2)

    # 팝업 열기
    print("[2] popup...")
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
        if popup: break
    if not popup:
        print("  no popup!")
        close_session(browser); pw_inst.stop(); return
    popup.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(5)
    popup.set_viewport_size({"width": 1920, "height": 1080})

    # 모든 frame 목록
    print("\n[3] frames...")
    for i, frame in enumerate(popup.frames):
        name = frame.name
        url = frame.url[:80]
        print(f"  [{i}] name='{name}' url='{url}'")

    # dzeditor_0 frame 접근
    print("\n[4] dzeditor_0 frame...")
    dz_frame = None
    for frame in popup.frames:
        if frame.name == "dzeditor_0":
            dz_frame = frame
            break

    if not dz_frame:
        print("  dzeditor_0 not found!")
        # editorView frame에서 dzeditor_0 iframe 접근 시도
        ev_frame = None
        for frame in popup.frames:
            if "editorView" in frame.url:
                ev_frame = frame
                break
        if ev_frame:
            print("  editorView frame found, trying child frames...")
            # editorView 내부에서 dzeditor_0 iframe을 찾아 접근
            inner_html = ev_frame.evaluate("""
            () => {
                const iframe = document.getElementById('dzeditor_0');
                if (iframe && iframe.contentDocument) {
                    return iframe.contentDocument.body.innerHTML;
                }
                return 'NOT_FOUND';
            }
            """)
            if inner_html != 'NOT_FOUND':
                print(f"  dzeditor_0 body HTML: {len(inner_html)} chars")
                (OUT_DIR / "dzeditor0_body.html").write_text(inner_html, encoding="utf-8")
                print("  saved: dzeditor0_body.html")
                # 텍스트
                inner_text = ev_frame.evaluate("""
                () => {
                    const iframe = document.getElementById('dzeditor_0');
                    if (iframe && iframe.contentDocument) {
                        return iframe.contentDocument.body.innerText;
                    }
                    return '';
                }
                """)
                (OUT_DIR / "dzeditor0_body.txt").write_text(inner_text, encoding="utf-8")
                print("  saved: dzeditor0_body.txt")
                # 테이블 분석
                tables = ev_frame.evaluate("""
                () => {
                    const iframe = document.getElementById('dzeditor_0');
                    if (!iframe || !iframe.contentDocument) return [];
                    const doc = iframe.contentDocument;
                    const tables = doc.querySelectorAll('table');
                    const result = [];
                    for (let ti = 0; ti < tables.length; ti++) {
                        const t = tables[ti];
                        const rows = [];
                        const trs = t.querySelectorAll('tr');
                        for (let ri = 0; ri < trs.length; ri++) {
                            const cells = [];
                            const allCells = trs[ri].querySelectorAll('th, td');
                            for (let ci = 0; ci < allCells.length; ci++) {
                                const cell = allCells[ci];
                                cells.push({
                                    tag: cell.tagName,
                                    text: cell.textContent.trim().replace(/\\xa0/g, ' ').substring(0, 80),
                                    colspan: cell.getAttribute('colspan') || '1',
                                    rowspan: cell.getAttribute('rowspan') || '1',
                                    bgColor: cell.getAttribute('bgcolor') || cell.style.backgroundColor || '',
                                    width: cell.getAttribute('width') || '',
                                    isEmpty: cell.textContent.trim() === '' || cell.textContent.trim() === '\\xa0',
                                });
                            }
                            rows.push(cells);
                        }
                        result.push({ index: ti, rowCount: rows.length, rows: rows });
                    }
                    return result;
                }
                """)
                print(f"\n  tables: {len(tables)}")
                output_lines = []
                for table in tables:
                    line = f"\n  === Table {table['index']} ({table['rowCount']} rows) ==="
                    print(line)
                    output_lines.append(line)
                    for ri, row in enumerate(table['rows']):
                        for ci, cell in enumerate(row):
                            span = ""
                            if cell['colspan'] != '1': span += f" cs={cell['colspan']}"
                            if cell['rowspan'] != '1': span += f" rs={cell['rowspan']}"
                            extra = ""
                            if cell['isEmpty']: extra += " [EMPTY]"
                            if cell['bgColor']: extra += f" bg={cell['bgColor']}"
                            if cell['width']: extra += f" w={cell['width']}"
                            text = cell['text'].replace('\xa0', ' ')[:50] if cell['text'] else ""
                            line = f"    R{ri}C{ci}: <{cell['tag']}{span}> '{text}'{extra}"
                            print(line)
                            output_lines.append(line)
                # 분석 결과 저장
                (OUT_DIR / "dzeditor0_tables.txt").write_text("\n".join(output_lines), encoding="utf-8")
            else:
                print("  dzeditor_0 not accessible from editorView")
    else:
        print(f"  found! url={dz_frame.url[:60]}")
        body_html = dz_frame.evaluate("() => document.body ? document.body.innerHTML : ''")
        body_text = dz_frame.evaluate("() => document.body ? document.body.innerText : ''")
        print(f"  body HTML: {len(body_html)} chars")
        print(f"  body text: {len(body_text)} chars")
        (OUT_DIR / "dzeditor0_body.html").write_text(body_html, encoding="utf-8")
        (OUT_DIR / "dzeditor0_body.txt").write_text(body_text, encoding="utf-8")

    popup.close()
    close_session(browser)
    pw_inst.stop()
    print("\ndone!")


if __name__ == "__main__":
    run()
