"""
거래처등록 양식 본문(dzEditor) 내부 HTML 구조 정밀 추출
- iframe 내부 접근
- 테이블 셀 구조 매핑
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

    # 전자결재 모듈
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

    # 양식 팝업 열기
    print("[2] 양식 팝업 열기...")
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
        print("  팝업 열리지 않음!")
        close_session(browser)
        pw_inst.stop()
        return

    popup.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(5)
    popup.set_viewport_size({"width": 1920, "height": 1080})
    print(f"  팝업 URL: {popup.url[:100]}")

    # === 본문 에디터 접근 ===
    print("\n[3] 에디터 접근 시도...")

    # 방법 1: 모든 iframe 분석
    iframes = popup.locator("iframe").all()
    print(f"  iframe 수: {len(iframes)}")
    for i, iframe in enumerate(iframes):
        try:
            vis = iframe.is_visible()
            src = iframe.get_attribute("src") or ""
            name = iframe.get_attribute("name") or ""
            box = iframe.bounding_box()
            print(f"  iframe[{i}]: visible={vis}, name='{name}', src='{src[:60]}', box={box}")
            if vis and box and box['height'] > 50:
                frame = iframe.content_frame()
                if frame:
                    body_html = frame.evaluate("() => document.body.innerHTML")
                    body_text = frame.evaluate("() => document.body.innerText")
                    print(f"    body HTML 길이: {len(body_html)}")
                    print(f"    body text 길이: {len(body_text)}")
                    # HTML 저장
                    (OUT_DIR / f"body_iframe{i}.html").write_text(body_html, encoding="utf-8")
                    (OUT_DIR / f"body_iframe{i}.txt").write_text(body_text[:5000], encoding="utf-8")
                    print(f"    저장: body_iframe{i}.html, body_iframe{i}.txt")

                    # 테이블 구조 분석
                    tables = frame.evaluate("""
                    () => {
                        const tables = document.querySelectorAll('table');
                        const result = [];
                        for (const t of tables) {
                            const info = { rows: [], attrs: {} };
                            // 테이블 속성
                            for (const attr of t.attributes) {
                                info.attrs[attr.name] = attr.value.substring(0, 100);
                            }
                            for (const tr of t.querySelectorAll('tr')) {
                                const cells = [];
                                for (const cell of tr.querySelectorAll('th, td')) {
                                    const cellInfo = {
                                        tag: cell.tagName,
                                        text: cell.textContent.trim().substring(0, 80),
                                        colspan: cell.getAttribute('colspan') || '1',
                                        rowspan: cell.getAttribute('rowspan') || '1',
                                        style: (cell.getAttribute('style') || '').substring(0, 100),
                                        className: (cell.className || '').substring(0, 50),
                                        childTags: [],
                                    };
                                    // 직접 자식 태그 확인
                                    for (const child of cell.children) {
                                        cellInfo.childTags.push(child.tagName);
                                    }
                                    cells.push(cellInfo);
                                }
                                info.rows.push(cells);
                            }
                            result.push(info);
                        }
                        return result;
                    }
                    """)
                    print(f"    테이블 수: {len(tables)}")
                    for ti, table in enumerate(tables):
                        print(f"\n    --- Table {ti} ({len(table['rows'])} rows) ---")
                        print(f"    attrs: {table['attrs']}")
                        for ri, row in enumerate(table['rows']):
                            for ci, cell in enumerate(row):
                                span = ""
                                if cell['colspan'] != '1':
                                    span += f" colspan={cell['colspan']}"
                                if cell['rowspan'] != '1':
                                    span += f" rowspan={cell['rowspan']}"
                                children = ",".join(cell['childTags']) if cell['childTags'] else ""
                                print(f"      R{ri}C{ci}: <{cell['tag']}{span}> '{cell['text'][:50]}' children=[{children}]")
        except Exception as e:
            print(f"    error: {e}")

    # 방법 2: contentEditable 직접 탐색
    print("\n[4] contentEditable 직접 탐색...")
    ce_info = popup.evaluate("""
    () => {
        const all = document.querySelectorAll("[contenteditable='true']");
        const result = [];
        for (const el of all) {
            const rect = el.getBoundingClientRect();
            result.push({
                tag: el.tagName,
                className: (el.className || '').substring(0, 60),
                id: el.id || '',
                htmlLen: el.innerHTML.length,
                textLen: el.innerText.length,
                rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                       w: Math.round(rect.width), h: Math.round(rect.height)},
            });
        }
        return result;
    }
    """)
    print(f"  contentEditable 요소: {len(ce_info)}")
    for ci, info in enumerate(ce_info):
        r = info['rect']
        print(f"  [{ci}] <{info['tag']}> id='{info['id']}' class='{info['className'][:40]}' html={info['htmlLen']} text={info['textLen']} pos=({r['x']},{r['y']}) {r['w']}x{r['h']}")
        if info['htmlLen'] > 0:
            # HTML 추출
            html = popup.evaluate(f"""
            () => {{
                const els = document.querySelectorAll("[contenteditable='true']");
                return els[{ci}] ? els[{ci}].innerHTML : '';
            }}
            """)
            (OUT_DIR / f"body_ce{ci}.html").write_text(html, encoding="utf-8")
            print(f"    저장: body_ce{ci}.html")

    # 제목 필드 값 확인
    print("\n[5] 제목 필드 확인...")
    title_val = popup.evaluate("""
    () => {
        const inputs = document.querySelectorAll('input[type="text"], input:not([type])');
        const result = [];
        for (const inp of inputs) {
            if (inp.value && inp.value.length > 5) {
                const rect = inp.getBoundingClientRect();
                result.push({
                    value: inp.value,
                    name: inp.name || '',
                    id: inp.id || '',
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                });
            }
        }
        return result;
    }
    """)
    for tv in title_val:
        print(f"  input: value='{tv['value'][:60]}' name='{tv['name']}' id='{tv['id']}' pos=({tv['rect']['x']},{tv['rect']['y']})")

    popup.close()
    close_session(browser)
    pw_inst.stop()
    print("\ndone!")


if __name__ == "__main__":
    run()
