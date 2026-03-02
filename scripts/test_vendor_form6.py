"""
거래처등록 양식 접근 테스트 v6
- 결재작성 → 거래처 검색 → 더블클릭으로 양식 열기
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

    # --- EA module ---
    print("\n[2] EA module...")
    try:
        ea = page.locator("span.module-link.EA").first
        if ea.is_visible(timeout=5000):
            ea.click(force=True)
            time.sleep(4)
    except:
        page.locator("text=전자결재").first.click(force=True)
        time.sleep(4)

    for p in context.pages:
        if p != page:
            try: p.close()
            except: pass

    try:
        page.wait_for_selector("text=결재 HOME", timeout=10000)
    except:
        pass
    time.sleep(2)

    # --- "결재작성" 사이드바 버튼 ---
    print("\n[3] sideRegi click...")
    page.locator("div.sideRegi").first.click(force=True)
    time.sleep(4)

    for p in context.pages:
        if p != page:
            try: p.close()
            except: pass

    print(f"  URL: {page.url[:100]}")
    save(page, "v6_03_form_select")

    # --- 검색 ---
    print("\n[4] search '국내 거래처'...")
    search = page.locator("input:visible").first
    search.click()
    search.fill("국내 거래처")
    search.press("Enter")
    time.sleep(3)
    save(page, "v6_04_search_result")

    # --- 첫 번째 결과 분석 ---
    print("\n[5] analyzing search results...")
    results = page.locator("text=국내 거래처등록").all()
    visible_results = [r for r in results if r.is_visible()]
    print(f"  total={len(results)}, visible={len(visible_results)}")

    if not visible_results:
        print("  no visible results!")
        close_session(browser)
        pw_inst.stop()
        return

    # 결과 행의 구조 분석
    for i, r in enumerate(visible_results[:3]):
        txt = r.inner_text()[:50]
        tag = r.evaluate("e => e.tagName")
        cls = r.evaluate("e => e.className") or ""
        box = r.bounding_box()
        pos = f"({int(box['x'])},{int(box['y'])})" if box else "?"
        # 부모 체인
        parent_info = r.evaluate("""
        e => {
            let info = [];
            let p = e;
            for (let i = 0; i < 5; i++) {
                info.push({
                    tag: p.tagName,
                    cls: (p.className || '').substring(0, 40),
                    onclick: p.getAttribute('onclick') ? 'yes' : 'no',
                });
                p = p.parentElement;
                if (!p) break;
            }
            return info;
        }
        """)
        print(f"  [{i}] tag={tag}, text='{txt}', pos={pos}")
        for j, pi in enumerate(parent_info):
            print(f"    {'  '*j}<{pi['tag']}> cls={pi['cls']}")

    # --- 더블클릭 시도 ---
    target = visible_results[0]
    print(f"\n[6] double-clicking first result...")
    target.dblclick(force=True)
    time.sleep(6)

    for p2 in context.pages:
        if p2 != page:
            try: p2.close()
            except: pass

    print(f"  URL: {page.url[:100]}")
    save(page, "v6_06_after_dblclick")

    # 제목 필드?
    title_found = False
    try:
        th = page.locator("th:has-text('제목')").first
        if th.is_visible(timeout=8000):
            print("  TITLE FIELD FOUND!")
            title_found = True
        else:
            print("  title field not visible")
    except:
        print("  title field not found")

    if not title_found:
        # 다른 접근: 결과 행 자체를 클릭 (부모 div/tr)
        print("\n[7] try clicking parent row...")

        # 결과 행을 JS로 찾아서 클릭
        page.evaluate("""
        () => {
            const els = document.querySelectorAll('*');
            for (const el of els) {
                const t = el.textContent?.trim() || '';
                if (t.includes('국내 거래처등록') && t.includes('회계팀') && !t.includes('국외')) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 10 && rect.height < 80 && rect.y > 150) {
                        // 부모 행을 클릭 시도
                        let row = el;
                        while (row && row.tagName !== 'TR' && row.tagName !== 'DIV') {
                            row = row.parentElement;
                        }
                        if (row) {
                            row.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
                            return `clicked: ${row.tagName}.${row.className?.substring(0,40)}`;
                        }
                    }
                }
            }
            return 'not found';
        }
        """)
        time.sleep(5)
        print(f"  URL: {page.url[:100]}")
        save(page, "v6_07_after_js_dblclick")

        try:
            th = page.locator("th:has-text('제목')").first
            if th.is_visible(timeout=8000):
                print("  TITLE FIELD FOUND after JS dblclick!")
                title_found = True
        except:
            pass

    if not title_found:
        # 아이콘 (checkbox?) 옆 텍스트가 아닌 행 전체 클릭
        print("\n[8] clicking result row at specific position...")
        # 첫 번째 결과 행 위치 (v5_07에서 약 (700, 187))
        # 결과 행 내부 설명 텍스트를 더블클릭
        desc_text = page.locator("text=국내거래처 신규등록").first
        if desc_text.is_visible(timeout=3000):
            print("  desc text found, double-clicking...")
            desc_text.dblclick(force=True)
            time.sleep(5)
            print(f"  URL: {page.url[:100]}")
            save(page, "v6_08_after_desc_dblclick")

            try:
                th = page.locator("th:has-text('제목')").first
                if th.is_visible(timeout=8000):
                    print("  TITLE FIELD FOUND!")
                    title_found = True
            except:
                pass

    if title_found:
        print("\n--- Form Analysis ---")
        # th labels
        ths = page.locator("th:visible").all()
        print(f"  th labels ({len(ths)}):")
        for j, th_el in enumerate(ths[:20]):
            try:
                txt = th_el.inner_text().strip()[:30]
                if txt:
                    print(f"    [{j}] {txt}")
            except:
                pass

        # action buttons
        print("  action buttons:")
        for sel in ["div.topBtn:visible", "button:visible"]:
            btns = page.locator(sel).all()
            for b in btns[:10]:
                try:
                    t = b.inner_text().strip()
                    if t and len(t) < 15:
                        print(f"    '{t}'")
                except:
                    pass
    else:
        print("\n  FORM DID NOT OPEN - checking page state...")
        body = page.inner_text("body")
        lines = [l.strip() for l in body.split("\n") if l.strip()][:30]
        for line in lines:
            print(f"    {line[:60]}")

    save(page, "v6_99_final")
    close_session(browser)
    pw_inst.stop()
    print("\ndone!")

if __name__ == "__main__":
    run()
