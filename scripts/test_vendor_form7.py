"""
거래처등록 양식 접근 테스트 v7
- 직접 URL로 양식 선택 페이지 접근
- 검색 → 더블클릭으로 양식 열기
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
        print("[error] no password")
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

    print(f"\n[1] login ok")

    # --- 전자결재 모듈 먼저 진입 ---
    print("\n[2] EA module...")
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

    # 결재 HOME 대기
    try:
        page.wait_for_selector("text=결재 HOME", timeout=10000)
        print("  approval HOME ok")
    except:
        print("  approval HOME not found, trying direct URL")
    time.sleep(2)

    # --- 결재작성 페이지로 직접 이동 ---
    print("\n[3] navigate to form selection page...")
    # v5에서 확인된 URL (pageCode=UBA6000)
    form_select_url = "https://gw.glowseoul.co.kr/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA6000"

    # 방법 1: sideRegi 클릭 (전자결재 모듈 내에서)
    try:
        side_regi = page.locator("div.sideRegi").first
        if side_regi.is_visible(timeout=3000):
            side_regi.click(force=True)
            print("  sideRegi clicked")
            time.sleep(4)
    except:
        pass

    # URL 확인 - UBA6000이 아니면 직접 이동
    if "UBA6000" not in page.url:
        print(f"  wrong page ({page.url[:80]}), navigating directly...")
        page.goto(form_select_url, wait_until="networkidle", timeout=15000)
        time.sleep(3)

    for p in context.pages:
        if p != page:
            try: p.close()
            except: pass

    print(f"  URL: {page.url[:100]}")
    save(page, "v7_03_form_select")

    # --- 양식 검색 ---
    print("\n[4] search for vendor form...")

    # 검색 입력란 (placeholder: "카테고리 또는 양식명/양식설명을 입력하세요.")
    search = None
    all_inputs = page.locator("input:visible").all()
    for inp in all_inputs:
        ro = inp.get_attribute("readonly") or ""
        ph = inp.get_attribute("placeholder") or ""
        print(f"  input: ph='{ph[:40]}', readonly={bool(ro)}")
        if not ro and ("양식" in ph or "카테고리" in ph or "입력" in ph):
            search = inp
            break
        elif not ro:
            search = inp  # fallback to first non-readonly

    if not search:
        print("  no editable search input found!")
        # 페이지가 올바른지 확인
        body = page.inner_text("body")
        lines = [l.strip() for l in body.split("\n") if l.strip()][:20]
        for line in lines:
            print(f"    {line[:60]}")
        close_session(browser)
        pw_inst.stop()
        return

    search.click()
    time.sleep(0.3)
    search.fill("국내 거래처")
    search.press("Enter")
    print("  searched '국내 거래처'")
    time.sleep(3)
    save(page, "v7_04_search")

    # --- 검색 결과에서 양식 선택 ---
    print("\n[5] selecting form from results...")

    # "국내 거래처등록" 텍스트 요소 찾기
    matches = page.locator("text=국내 거래처등록").all()
    visible = [m for m in matches if m.is_visible()]
    print(f"  matches: total={len(matches)}, visible={len(visible)}")

    if not visible:
        print("  no visible matches! trying '거래처' instead...")
        matches = page.locator("text=거래처등록").all()
        visible = [m for m in matches if m.is_visible()]
        print(f"  '거래처등록': total={len(matches)}, visible={len(visible)}")

    if visible:
        target = visible[0]
        txt = target.inner_text()[:50]
        box = target.bounding_box()
        print(f"  target: '{txt}' at ({int(box['x'])},{int(box['y'])})")

        # 방법 A: 더블클릭 (새 창/팝업 감지 포함)
        print("  >> double-clicking (watching for new pages)...")
        pages_before = len(context.pages)
        target.dblclick(force=True)
        time.sleep(6)

        # 새 창/팝업 확인
        all_pages = context.pages
        print(f"  pages before={pages_before}, after={len(all_pages)}")
        for i, p2 in enumerate(all_pages):
            p_url = p2.url[:80]
            print(f"    page[{i}]: {p_url}")

        # 새 창이 열렸으면 그 창을 사용
        if len(all_pages) > pages_before:
            new_page = all_pages[-1]
            print(f"  NEW PAGE DETECTED! URL: {new_page.url[:100]}")
            new_page.set_viewport_size({"width": 1920, "height": 1080})
            time.sleep(3)
            save(new_page, "v7_05_new_page")
            # 새 창에서 제목 필드 확인
            try:
                th = new_page.locator("th:has-text('제목')").first
                if th.is_visible(timeout=8000):
                    print("  >> TITLE FIELD FOUND in NEW PAGE!")
                    page = new_page  # 이후 분석을 새 페이지에서
            except:
                pass

        new_url = page.url
        print(f"  URL after dblclick: {new_url[:100]}")
        save(page, "v7_05_after_dblclick")

        # 제목 필드 확인
        title_found = False
        try:
            th = page.locator("th:has-text('제목')").first
            if th.is_visible(timeout=8000):
                print("  >> TITLE FIELD FOUND! Form loaded successfully!")
                title_found = True
        except:
            pass

        if not title_found:
            print("  title not found after dblclick, trying click once...")

            # 방법 B: 한 번 클릭 후 확인 버튼 찾기
            target = visible[0]
            target.click(force=True)
            time.sleep(2)

            # "확인" / "선택" / "다음" 버튼 확인
            for btn_text in ["확인", "선택", "다음"]:
                try:
                    btn = page.locator(f"text={btn_text}").first
                    if btn.is_visible(timeout=2000):
                        print(f"  '{btn_text}' button found! clicking...")
                        btn.click(force=True)
                        time.sleep(5)
                        break
                except:
                    pass

            # 다시 제목 확인
            try:
                th = page.locator("th:has-text('제목')").first
                if th.is_visible(timeout=5000):
                    print("  >> TITLE FIELD FOUND after confirm!")
                    title_found = True
            except:
                pass

            if not title_found:
                print(f"  URL: {page.url[:100]}")
                save(page, "v7_05b_still_no_form")

                # 방법 C: 결과 행의 아이콘/체크박스 영역 클릭
                print("  trying row icon click...")
                if box:
                    # 행 맨 왼쪽 (체크박스/아이콘) 클릭
                    icon_x = int(box['x']) - 30
                    icon_y = int(box['y']) + int(box.get('height', 20)) // 2
                    print(f"  clicking icon area at ({icon_x}, {icon_y})")
                    page.mouse.dblclick(icon_x, icon_y)
                    time.sleep(5)
                    save(page, "v7_05c_icon_dblclick")

                    try:
                        th = page.locator("th:has-text('제목')").first
                        if th.is_visible(timeout=5000):
                            print("  >> TITLE FIELD FOUND!")
                            title_found = True
                    except:
                        pass

        if title_found:
            print("\n--- Form loaded! Analyzing structure ---")
            save(page, "v7_06_form_loaded")

            # th labels
            ths = page.locator("th:visible").all()
            print(f"  th labels ({len(ths)}):")
            for j, th_el in enumerate(ths[:25]):
                try:
                    txt = th_el.inner_text().strip()[:40]
                    if txt:
                        print(f"    [{j}] {txt}")
                except:
                    pass

            # contentEditable
            editors = page.locator("[contenteditable='true']:visible").all()
            print(f"  contentEditable: {len(editors)}")

            # iframe
            iframes = page.locator("iframe:visible").all()
            print(f"  iframes: {len(iframes)}")

            # buttons
            print("  topBtn:")
            btns = page.locator("div.topBtn:visible").all()
            for b in btns[:10]:
                try:
                    t = b.inner_text().strip()
                    if t:
                        print(f"    '{t}'")
                except:
                    pass

            # full page text save
            try:
                text = page.inner_text("body")
                (OUT_DIR / "v7_form_text.txt").write_text(text[:8000], encoding="utf-8")
            except:
                pass
        else:
            print("\n  FORM STILL NOT OPENED")
            # 현재 상태 덤프
            body = page.inner_text("body")
            lines = [l.strip() for l in body.split("\n") if l.strip()][:25]
            for line in lines:
                print(f"    {line[:70]}")
    else:
        print("  no results found at all")

    save(page, "v7_99_final")
    close_session(browser)
    pw_inst.stop()
    print("\ndone!")

if __name__ == "__main__":
    run()
