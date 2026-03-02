"""
거래처등록 양식 접근 테스트 v8
- 결재작성 → 검색 → 양식 선택 → ▶ 버튼 클릭 → 양식 열기
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

def save(page, name):
    path = OUT_DIR / f"{name}.png"
    page.screenshot(path=str(path))
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

    # --- 결재작성 페이지 ---
    print("[3] form selection page...")
    form_url = "https://gw.glowseoul.co.kr/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA6000"
    page.goto(form_url, wait_until="networkidle", timeout=15000)
    time.sleep(3)

    for p in context.pages:
        if p != page:
            try: p.close()
            except: pass

    save(page, "v8_03_form_page")

    # --- "결재작성" 옆 버튼들 분석 ---
    print("\n[4] analyzing header buttons...")
    header_btns = page.evaluate("""
    () => {
        // "결재작성" 텍스트 근처의 아이콘/버튼 분석
        const result = [];
        const all = document.querySelectorAll('button, div[role="button"], [class*="btn"], [class*="Btn"], svg, img');
        for (const el of all) {
            const rect = el.getBoundingClientRect();
            // 상단 영역 (y < 120)에 있는 클릭 가능 요소
            if (rect.y > 60 && rect.y < 120 && rect.x > 200 && rect.x < 400 && rect.width > 5) {
                result.push({
                    tag: el.tagName,
                    className: (el.className?.baseVal || el.className || '').substring(0, 60),
                    title: el.getAttribute('title') || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    text: (el.textContent || '').trim().substring(0, 30),
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    parentClass: (el.parentElement?.className || '').substring(0, 40),
                });
            }
        }
        return result;
    }
    """)

    print(f"  header area elements: {len(header_btns)}")
    for i, btn in enumerate(header_btns):
        r = btn['rect']
        print(f"  [{i}] <{btn['tag']}> title='{btn['title']}' text='{btn['text']}' class={btn['className'][:40]}")
        print(f"       pos=({r['x']},{r['y']}) size={r['w']}x{r['h']}, parent={btn['parentClass'][:30]}")

    # --- 검색 후 양식 선택 ---
    print("\n[5] search and select form...")
    search = None
    for inp in page.locator("input:visible").all():
        ro = inp.get_attribute("readonly") or ""
        if not ro:
            search = inp
            break
    if not search:
        print("  no search input!")
        close_session(browser)
        pw_inst.stop()
        return

    search.click()
    search.fill("국내 거래처")
    search.press("Enter")
    time.sleep(3)

    # 결과 클릭 (선택)
    result = page.locator("text=국내 거래처등록").first
    if result.is_visible(timeout=3000):
        result.click(force=True)
        print("  form selected (single click)")
        time.sleep(1)
        save(page, "v8_05_selected")
    else:
        print("  result not visible!")
        close_session(browser)
        pw_inst.stop()
        return

    # --- ▶ 버튼 클릭 (실행/작성 시작) ---
    print("\n[6] clicking action buttons in header...")

    # "결재작성" 옆 아이콘들 (위치 약 x=270~340, y=80~100)
    # 스크린샷에서 세 아이콘: [문서] [▶] [🔍]
    # 순서대로 시도

    form_opened = False

    # 방법 A: ▶ 재생 버튼 (중간 아이콘) 클릭
    play_btn = page.evaluate("""
    () => {
        // 결재작성 헤더 영역에서 버튼/이미지 찾기
        const els = document.querySelectorAll('[class*="Btn"], [class*="btn"], button, [role="button"]');
        for (const el of els) {
            const rect = el.getBoundingClientRect();
            // 상단 영역의 버튼들
            if (rect.y > 70 && rect.y < 110 && rect.x > 250 && rect.x < 340 && rect.width > 15 && rect.width < 50) {
                return {
                    x: Math.round(rect.x + rect.width / 2),
                    y: Math.round(rect.y + rect.height / 2),
                    className: (el.className || '').substring(0, 50),
                    title: el.getAttribute('title') || '',
                };
            }
        }
        return null;
    }
    """)

    if play_btn:
        print(f"  found btn at ({play_btn['x']},{play_btn['y']}) class={play_btn['className']}")
        pages_before = len(context.pages)
        page.mouse.click(play_btn['x'], play_btn['y'])
        time.sleep(5)

        # 새 페이지 확인
        all_pages = context.pages
        if len(all_pages) > pages_before:
            new_page = all_pages[-1]
            print(f"  NEW PAGE: {new_page.url[:100]}")
            new_page.set_viewport_size({"width": 1920, "height": 1080})
            time.sleep(3)
            save(new_page, "v8_06_new_page")
            try:
                th = new_page.locator("th:has-text('제목')").first
                if th.is_visible(timeout=8000):
                    print("  TITLE in new page!")
                    form_opened = True
                    page = new_page
            except:
                pass
        else:
            # 같은 페이지에서 제목 확인
            print(f"  URL: {page.url[:100]}")
            save(page, "v8_06_after_play")
            try:
                th = page.locator("th:has-text('제목')").first
                if th.is_visible(timeout=5000):
                    print("  TITLE found!")
                    form_opened = True
            except:
                pass

    # 방법 B: 헤더의 세 아이콘을 순서대로 시도
    if not form_opened:
        print("\n[7] trying all three header icons by position...")
        # 아이콘 좌표 (스크린샷 기반)
        icon_positions = [
            (273, 91, "icon1"),
            (298, 91, "icon2-play"),
            (323, 91, "icon3-search"),
        ]
        for x, y, label in icon_positions:
            print(f"  clicking ({x},{y}) [{label}]...")
            pages_before = len(context.pages)
            page.mouse.click(x, y)
            time.sleep(4)

            all_pages = context.pages
            if len(all_pages) > pages_before:
                new_page = all_pages[-1]
                print(f"  NEW PAGE: {new_page.url[:100]}")
                new_page.set_viewport_size({"width": 1920, "height": 1080})
                time.sleep(3)
                save(new_page, f"v8_07_{label}_newpage")
                try:
                    th = new_page.locator("th:has-text('제목')").first
                    if th.is_visible(timeout=5000):
                        print(f"  TITLE in new page from {label}!")
                        form_opened = True
                        page = new_page
                        break
                except:
                    pass
            else:
                save(page, f"v8_07_{label}")
                try:
                    th = page.locator("th:has-text('제목')").first
                    if th.is_visible(timeout=3000):
                        print(f"  TITLE found from {label}!")
                        form_opened = True
                        break
                except:
                    pass
                # URL 변경 확인
                if "UBA6000" not in page.url:
                    print(f"  URL changed: {page.url[:100]}")
                    # 다시 양식 선택 페이지로 복귀
                    page.goto(form_url, wait_until="networkidle", timeout=15000)
                    time.sleep(3)
                    # 다시 검색 + 선택
                    search = page.locator("input:visible:not([readonly])").first
                    if search.is_visible(timeout=3000):
                        search.click()
                        search.fill("국내 거래처")
                        search.press("Enter")
                        time.sleep(2)
                        result = page.locator("text=국내 거래처등록").first
                        if result.is_visible(timeout=2000):
                            result.click(force=True)
                            time.sleep(1)

    if form_opened:
        print("\n--- SUCCESS: Form loaded! ---")
        save(page, "v8_success")
        # 구조 분석
        ths = page.locator("th:visible").all()
        print(f"  th labels ({len(ths)}):")
        for j, th_el in enumerate(ths[:25]):
            try:
                txt = th_el.inner_text().strip()[:40]
                if txt:
                    print(f"    [{j}] {txt}")
            except:
                pass

        editors = page.locator("[contenteditable='true']:visible").all()
        print(f"  contentEditable: {len(editors)}")
        iframes = page.locator("iframe:visible").all()
        print(f"  iframes: {len(iframes)}")

        print("  topBtn:")
        for b in page.locator("div.topBtn:visible").all():
            try:
                t = b.inner_text().strip()
                if t and len(t) < 15:
                    print(f"    '{t}'")
            except:
                pass

        try:
            text = page.inner_text("body")
            (OUT_DIR / "v8_form_text.txt").write_text(text[:8000], encoding="utf-8")
        except:
            pass
    else:
        print("\n[FAILED] Form did not open")
        save(page, "v8_failed")

    close_session(browser)
    pw_inst.stop()
    print("\ndone!")

if __name__ == "__main__":
    run()
