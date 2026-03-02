"""
거래처등록 양식 접근 테스트 v9
- popup/new window 감지
- Enter 키, 더블클릭, 아이콘 클릭 모두 시도
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
    path = OUT_DIR / f"{name}.png"
    pg.screenshot(path=str(path))
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

    # popup 이벤트 감지
    new_pages = []
    context.on("page", lambda p: new_pages.append(p))

    print(f"[1] login ok")

    # --- EA module ---
    print("[2] EA module...")
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

    # --- 양식 선택 페이지 ---
    print("[3] form selection page...")
    form_url = "https://gw.glowseoul.co.kr/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA6000"
    page.goto(form_url, wait_until="networkidle", timeout=15000)
    time.sleep(3)
    save(page, "v9_03_page")

    # --- 헤더 아이콘 정밀 분석 ---
    print("\n[4] precise header icon analysis...")
    icons = page.evaluate("""
    () => {
        const result = [];
        // 결재작성 제목 영역의 모든 요소
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const rect = el.getBoundingClientRect();
            // y: 75~105, x: 255~350 영역
            if (rect.y >= 75 && rect.y <= 105 && rect.x >= 255 && rect.x <= 350
                && rect.width >= 10 && rect.width <= 40 && rect.height >= 10) {
                result.push({
                    tag: el.tagName,
                    className: (el.className?.baseVal || el.className || '').substring(0, 60),
                    title: el.getAttribute('title') || '',
                    id: el.id || '',
                    text: (el.textContent || '').trim().substring(0, 20),
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                           w: Math.round(rect.width), h: Math.round(rect.height)},
                });
            }
        }
        return result;
    }
    """)
    print(f"  found {len(icons)} elements in header icon area:")
    for item in icons:
        r = item['rect']
        print(f"    <{item['tag']}> id='{item['id']}' class='{item['className'][:40]}' title='{item['title']}' pos=({r['x']},{r['y']}) {r['w']}x{r['h']}")

    # 더 넓은 영역도 검색
    wider = page.evaluate("""
    () => {
        const result = [];
        const all = document.querySelectorAll('svg, img, button, [role="button"], [class*="icon"], [class*="Icon"]');
        for (const el of all) {
            const rect = el.getBoundingClientRect();
            if (rect.y >= 70 && rect.y <= 115 && rect.x >= 200 && rect.x <= 400 && rect.width > 5) {
                result.push({
                    tag: el.tagName,
                    className: (el.className?.baseVal || el.className || '').substring(0, 60),
                    title: el.getAttribute('title') || '',
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                           w: Math.round(rect.width), h: Math.round(rect.height)},
                    parentTag: el.parentElement?.tagName || '',
                    parentClass: (el.parentElement?.className || '').substring(0, 40),
                });
            }
        }
        return result;
    }
    """)
    print(f"  wider search: {len(wider)} elements:")
    for item in wider:
        r = item['rect']
        print(f"    <{item['tag']}> class='{item['className'][:30]}' title='{item['title']}' pos=({r['x']},{r['y']}) {r['w']}x{r['h']} parent=<{item['parentTag']}>.{item['parentClass'][:25]}")

    # --- 검색 + 선택 ---
    print("\n[5] search and select...")
    search = page.locator("input:visible:not([readonly])").first
    if not search.is_visible(timeout=3000):
        print("  no search input!")
        close_session(browser)
        pw_inst.stop()
        return

    search.click()
    search.fill("국내 거래처")
    search.press("Enter")
    time.sleep(3)

    # 선택
    result_el = page.locator("text=국내 거래처등록").first
    if not result_el.is_visible(timeout=3000):
        print("  no results!")
        close_session(browser)
        pw_inst.stop()
        return

    result_el.click(force=True)
    time.sleep(1)
    print("  selected")

    # --- 방법 1: Enter 키 ---
    print("\n[6A] pressing Enter...")
    new_pages.clear()
    page.keyboard.press("Enter")
    time.sleep(5)
    if new_pages:
        np = new_pages[-1]
        print(f"  POPUP! URL: {np.url[:100]}")
        np.wait_for_load_state("domcontentloaded", timeout=10000)
        np.set_viewport_size({"width": 1920, "height": 1080})
        time.sleep(3)
        save(np, "v9_06a_popup")
        try:
            th = np.locator("th:has-text('제목')").first
            if th.is_visible(timeout=5000):
                print("  TITLE in popup!")
                analyze_form(np)
                close_session(browser)
                pw_inst.stop()
                print("\ndone!")
                return
        except:
            pass
    print(f"  URL: {page.url[:100]}, new_pages: {len(new_pages)}")
    save(page, "v9_06a_after_enter")

    # 제목 확인
    try:
        th = page.locator("th:has-text('제목')").first
        if th.is_visible(timeout=3000):
            print("  TITLE found in current page!")
            analyze_form(page)
            close_session(browser)
            pw_inst.stop()
            return
    except:
        pass

    # 다시 양식 선택 페이지로
    page.goto(form_url, wait_until="networkidle", timeout=15000)
    time.sleep(3)
    search = page.locator("input:visible:not([readonly])").first
    search.click()
    search.fill("국내 거래처")
    search.press("Enter")
    time.sleep(3)
    result_el = page.locator("text=국내 거래처등록").first
    result_el.click(force=True)
    time.sleep(1)

    # --- 방법 2: 더블클릭 (popup 감지) ---
    print("\n[6B] double-click with popup detection...")
    new_pages.clear()
    result_el.dblclick(force=True)
    time.sleep(5)
    if new_pages:
        np = new_pages[-1]
        print(f"  POPUP! URL: {np.url[:100]}")
        np.wait_for_load_state("domcontentloaded", timeout=10000)
        np.set_viewport_size({"width": 1920, "height": 1080})
        time.sleep(3)
        save(np, "v9_06b_popup")
        try:
            th = np.locator("th:has-text('제목')").first
            if th.is_visible(timeout=5000):
                print("  TITLE in popup!")
                analyze_form(np)
                close_session(browser)
                pw_inst.stop()
                return
        except:
            pass
    print(f"  URL: {page.url[:100]}, new_pages: {len(new_pages)}")

    # 다시 복귀
    page.goto(form_url, wait_until="networkidle", timeout=15000)
    time.sleep(3)
    search = page.locator("input:visible:not([readonly])").first
    search.click()
    search.fill("국내 거래처")
    search.press("Enter")
    time.sleep(3)
    result_el = page.locator("text=국내 거래처등록").first
    result_el.click(force=True)
    time.sleep(1)

    # --- 방법 3: ▶ 아이콘 클릭 (더 넓은 범위) ---
    print("\n[6C] clicking play icon (wider range)...")
    new_pages.clear()

    # 아이콘 위치들 - 스크린샷 기반으로 더 정밀하게
    for pos in [(271, 91), (298, 91), (324, 91),
                (271, 86), (298, 86), (324, 86),
                (275, 90), (300, 90), (325, 90)]:
        x, y = pos
        page.mouse.click(x, y)
        time.sleep(2)
        if new_pages:
            np = new_pages[-1]
            print(f"  POPUP at ({x},{y})! URL: {np.url[:100]}")
            np.wait_for_load_state("domcontentloaded", timeout=10000)
            np.set_viewport_size({"width": 1920, "height": 1080})
            time.sleep(3)
            save(np, "v9_06c_popup")
            try:
                th = np.locator("th:has-text('제목')").first
                if th.is_visible(timeout=5000):
                    print("  TITLE in popup!")
                    analyze_form(np)
                    close_session(browser)
                    pw_inst.stop()
                    return
            except:
                pass
            break

        # URL 변경 확인
        if "UBA6000" not in page.url:
            print(f"  URL changed at ({x},{y}): {page.url[:80]}")
            try:
                th = page.locator("th:has-text('제목')").first
                if th.is_visible(timeout=3000):
                    print("  TITLE found!")
                    analyze_form(page)
                    close_session(browser)
                    pw_inst.stop()
                    return
            except:
                pass
            # 복귀
            page.goto(form_url, wait_until="networkidle", timeout=15000)
            time.sleep(3)
            search = page.locator("input:visible:not([readonly])").first
            search.click()
            search.fill("국내 거래처")
            search.press("Enter")
            time.sleep(3)
            page.locator("text=국내 거래처등록").first.click(force=True)
            time.sleep(1)

    print(f"\n  final URL: {page.url[:100]}")
    print(f"  new_pages detected: {len(new_pages)}")

    # --- 방법 4: 결과 행의 체크박스/아이콘 클릭 ---
    print("\n[6D] clicking checkbox in result row...")
    new_pages.clear()
    checkbox = page.locator("div[class*='check'], input[type='checkbox']").first
    try:
        if checkbox.is_visible(timeout=2000):
            box = checkbox.bounding_box()
            if box:
                print(f"  checkbox at ({int(box['x'])},{int(box['y'])})")
                checkbox.click(force=True)
                time.sleep(2)
    except:
        pass

    # 체크 후 아이콘 다시 클릭
    for pos in [(298, 91), (271, 91)]:
        x, y = pos
        page.mouse.click(x, y)
        time.sleep(3)
        if new_pages:
            np = new_pages[-1]
            print(f"  POPUP! URL: {np.url[:100]}")
            break

    print("\n[RESULT] checking all context pages...")
    for i, pg in enumerate(context.pages):
        pg_url = pg.url[:100]
        print(f"  page[{i}]: {pg_url}")
        if "HP" in pg_url and "APB" in pg_url:
            print(f"    >> This looks like a form page!")
            save(pg, f"v9_form_page_{i}")

    save(page, "v9_99_final")
    close_session(browser)
    pw_inst.stop()
    print("\ndone!")


def analyze_form(pg):
    """폼 구조 분석"""
    print("\n--- Form Analysis ---")
    save(pg, "v9_form_success")

    ths = pg.locator("th:visible").all()
    print(f"  th labels ({len(ths)}):")
    for j, th_el in enumerate(ths[:25]):
        try:
            txt = th_el.inner_text().strip()[:40]
            if txt:
                print(f"    [{j}] {txt}")
        except:
            pass

    editors = pg.locator("[contenteditable='true']:visible").all()
    print(f"  contentEditable: {len(editors)}")

    iframes = pg.locator("iframe:visible").all()
    print(f"  iframes: {len(iframes)}")

    print("  topBtn:")
    for b in pg.locator("div.topBtn:visible").all():
        try:
            t = b.inner_text().strip()
            if t and len(t) < 15:
                print(f"    '{t}'")
        except:
            pass

    try:
        text = pg.inner_text("body")
        (OUT_DIR / "v9_form_text.txt").write_text(text[:8000], encoding="utf-8")
    except:
        pass

    print(f"  URL: {pg.url[:100]}")


if __name__ == "__main__":
    run()
