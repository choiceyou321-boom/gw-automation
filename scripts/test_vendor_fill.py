"""
거래처등록 본문 기입 방법 테스트
- dzeditor_0 iframe 내 DOM 수정이 보관 시 반영되는지 확인
- dzEditor API 사용 시도
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


def save(pg, name):
    path = OUT_DIR / f"fill_{name}.png"
    pg.screenshot(path=str(path))
    print(f"  screenshot: {path.name}")


def run():
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password

    gw_id = "tgjeon"
    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw: return

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
    try: page.wait_for_selector("text=결재 HOME", timeout=10000)
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

    # dzeditor_0 frame 찾기
    dz_frame = None
    for frame in popup.frames:
        if frame.name == "dzeditor_0":
            dz_frame = frame
            break

    if not dz_frame:
        print("  dzeditor_0 not found!")
        close_session(browser); pw_inst.stop(); return

    # 현재 본문 확인
    print("\n[3] 현재 본문 확인...")
    body_text = dz_frame.evaluate("() => document.body ? document.body.innerText : ''")
    print(f"  본문 길이: {len(body_text)}")

    # === 방법 1: frame.evaluate로 DOM 직접 수정 ===
    print("\n[4] DOM 직접 수정 테스트...")
    result1 = dz_frame.evaluate("""
    () => {
        const tds = document.querySelectorAll('td');
        let found = false;
        for (let i = 0; i < tds.length; i++) {
            const text = tds[i].textContent.replace(/\\s+/g, '').trim();
            if (text === '상호명') {
                const next = tds[i].nextElementSibling;
                if (next && next.tagName === 'TD') {
                    const p = next.querySelector('p');
                    if (p) {
                        p.innerHTML = '(주)테스트상사';
                    } else {
                        next.innerHTML = '<p>(주)테스트상사</p>';
                    }
                    found = true;
                    break;
                }
            }
        }
        return {found: found, bodyLen: document.body.innerHTML.length};
    }
    """)
    print(f"  DOM 수정 결과: {result1}")

    # 수정 후 확인
    body_after = dz_frame.evaluate("() => document.body ? document.body.innerText : ''")
    has_test = '테스트상사' in body_after
    print(f"  수정 후 '테스트상사' 포함: {has_test}")

    # === 방법 2: dzEditor API 확인 ===
    print("\n[5] dzEditor API 확인...")
    # editorView frame에서 API 확인
    ev_frame = None
    for frame in popup.frames:
        if "editorView" in frame.url:
            ev_frame = frame
            break

    if ev_frame:
        api_info = ev_frame.evaluate("""
        () => {
            const result = {};
            // dzEditor 전역 객체 확인
            if (typeof DZEDITOR !== 'undefined') result.DZEDITOR = Object.keys(DZEDITOR).slice(0, 20);
            if (typeof dzeditor !== 'undefined') result.dzeditor = typeof dzeditor;
            if (typeof duzon_editor !== 'undefined') result.duzon_editor = typeof duzon_editor;
            if (typeof duzon_menubar !== 'undefined') result.duzon_menubar = Object.keys(duzon_menubar).slice(0, 10);

            // window 에서 editor 관련 함수 찾기
            const editorFns = [];
            for (const key of Object.keys(window)) {
                if (key.toLowerCase().includes('editor') || key.toLowerCase().includes('dz')) {
                    editorFns.push(key);
                }
            }
            result.editorFns = editorFns.slice(0, 20);

            // getHTML, setHTML 함수 확인
            if (typeof getEditorHTML === 'function') result.getEditorHTML = true;
            if (typeof setEditorHTML === 'function') result.setEditorHTML = true;

            return result;
        }
        """)
        print(f"  API 정보: {api_info}")

    # === 방법 3: 팝업 페이지의 dzEditor API ===
    print("\n[6] 팝업 페이지의 dzEditor API...")
    popup_api = popup.evaluate("""
    () => {
        const result = {};
        // 전역 함수/객체
        const keys = Object.keys(window).filter(k =>
            k.toLowerCase().includes('editor') || k.toLowerCase().includes('dz') ||
            k.includes('getHTML') || k.includes('setHTML') || k.includes('getContent')
        );
        result.windowKeys = keys.slice(0, 30);

        // dzEditorAPI 확인
        if (window.dzEditorAPI) result.dzEditorAPI = Object.keys(window.dzEditorAPI).slice(0, 20);
        if (window.DZEditor) result.DZEditor = Object.keys(window.DZEditor).slice(0, 20);

        return result;
    }
    """)
    print(f"  팝업 API: {popup_api}")

    # === 방법 4: 클릭+타이핑으로 입력 ===
    print("\n[7] 클릭+타이핑 테스트 (사업자등록번호 셀)...")

    # dzeditor_0 iframe 내부의 사업자등록번호 옆 셀 클릭
    # 좌표 기반 접근 시도
    # 먼저 iframe 위치 확인
    iframe_el = popup.locator("iframe#dzeditor_0, iframe[name='dzeditor_0']")
    if not iframe_el.count():
        # editorView 내부에서 찾기
        iframe_el = popup.frame_locator("[name='editorView_UBAP001']").locator("iframe#dzeditor_0")

    # frame 내부에서 셀 위치 확인
    cell_pos = dz_frame.evaluate("""
    () => {
        const tds = document.querySelectorAll('td');
        const result = [];
        for (let i = 0; i < tds.length; i++) {
            const text = tds[i].textContent.replace(/\\s+/g, '').trim();
            if (['사업자등록번호', '상호명', '대표자명', '은행명', '계좌번호', '예금주', '비고'].includes(text)) {
                const next = tds[i].nextElementSibling;
                if (next) {
                    const rect = next.getBoundingClientRect();
                    result.push({
                        label: text,
                        x: Math.round(rect.x + rect.width / 2),
                        y: Math.round(rect.y + rect.height / 2),
                        w: Math.round(rect.width),
                        h: Math.round(rect.height),
                    });
                }
            }
        }
        return result;
    }
    """)
    print(f"  셀 위치:")
    for cp in cell_pos:
        print(f"    {cp['label']}: ({cp['x']},{cp['y']}) {cp['w']}x{cp['h']}")

    # iframe의 bounding box 확인
    # editorView iframe의 위치
    ev_iframe_box = popup.evaluate("""
    () => {
        // editorView iframe 위치
        const iframes = document.querySelectorAll('iframe');
        for (const iframe of iframes) {
            if (iframe.name && iframe.name.includes('editorView')) {
                const rect = iframe.getBoundingClientRect();
                return {x: rect.x, y: rect.y, w: rect.width, h: rect.height};
            }
        }
        return null;
    }
    """)
    print(f"  editorView iframe box: {ev_iframe_box}")

    # editorView 내부에서 dzeditor_0 iframe 위치
    if ev_frame:
        dz_iframe_box = ev_frame.evaluate("""
        () => {
            const iframe = document.getElementById('dzeditor_0');
            if (iframe) {
                const rect = iframe.getBoundingClientRect();
                return {x: rect.x, y: rect.y, w: rect.width, h: rect.height};
            }
            return null;
        }
        """)
        print(f"  dzeditor_0 iframe box (within editorView): {dz_iframe_box}")

    # 실제 좌표 계산: popup 기준 = editorView.x + dzeditor_0.x + cell.x
    if ev_iframe_box and dz_iframe_box and cell_pos:
        for cp in cell_pos[:3]:
            abs_x = ev_iframe_box['x'] + dz_iframe_box['x'] + cp['x']
            abs_y = ev_iframe_box['y'] + dz_iframe_box['y'] + cp['y']
            print(f"    {cp['label']} 절대좌표: ({abs_x:.0f}, {abs_y:.0f})")

            if cp['label'] == '사업자등록번호':
                print(f"  사업자등록번호 셀 클릭 ({abs_x:.0f}, {abs_y:.0f})...")
                popup.mouse.click(abs_x, abs_y)
                time.sleep(1)
                # 기존 내용 선택 후 타이핑
                popup.keyboard.press("Control+a")
                time.sleep(0.3)
                popup.keyboard.type("999-88-77777")
                time.sleep(1)

    save(popup, "07_after_typing")

    # 타이핑 후 본문 확인
    body_after2 = dz_frame.evaluate("() => document.body ? document.body.innerText : ''")
    has_999 = '999-88-77777' in body_after2
    print(f"\n  타이핑 후 '999-88-77777' 포함: {has_999}")
    (OUT_DIR / "fill_body_after.txt").write_text(body_after2, encoding="utf-8")

    popup.close()
    close_session(browser)
    pw_inst.stop()
    print("\ndone!")


if __name__ == "__main__":
    run()
