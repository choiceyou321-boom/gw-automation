"""
팝업의 보관 버튼 위치 확인
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

    # 전체 버튼 검색
    print("\n[3] 전체 버튼/클릭 요소 검색...")
    all_elements = popup.evaluate("""
    () => {
        const result = [];
        // 모든 요소에서 텍스트 검색
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const text = el.textContent.trim().replace(/\\s+/g, ' ');
            // 보관, 임시저장, save, draft 관련
            if (text.length < 20 && text.length > 0) {
                const tag = el.tagName;
                const cls = el.className || '';
                const vis = el.offsetParent !== null || el.offsetWidth > 0;
                if (vis && (tag === 'BUTTON' || tag === 'A' || tag === 'SPAN' || tag === 'DIV' || tag === 'LI')) {
                    if (['보관', '저장', '임시', '상신', '결재', '닫기', '취소', '확인', '목록'].some(k => text.includes(k))) {
                        result.push({
                            tag: tag,
                            text: text.substring(0, 40),
                            class: (typeof cls === 'string' ? cls : '').substring(0, 80),
                            id: el.id || '',
                            rect: el.getBoundingClientRect()
                        });
                    }
                }
            }
        }
        return result;
    }
    """)
    for el in all_elements:
        r = el.get('rect', {})
        print(f"  {el['tag']} id='{el['id']}' class='{el['class'][:50]}': '{el['text']}' @ ({r.get('x',0):.0f},{r.get('y',0):.0f})")

    # 모든 iframe 내부도 검색
    print("\n[4] iframe 내부 버튼 검색...")
    for frame in popup.frames:
        if frame == popup.main_frame:
            continue
        try:
            frame_btns = frame.evaluate("""
            () => {
                const result = [];
                const els = document.querySelectorAll('button, a, span, div, input[type="button"]');
                for (const el of els) {
                    const text = el.textContent.trim().replace(/\\s+/g, ' ');
                    if (text.length > 0 && text.length < 20 && el.offsetParent !== null) {
                        if (['보관', '저장', '임시', '상신', '결재'].some(k => text.includes(k))) {
                            result.push({
                                tag: el.tagName,
                                text: text.substring(0, 40),
                                class: (el.className || '').substring(0, 50)
                            });
                        }
                    }
                }
                return result;
            }
            """)
            if frame_btns:
                fname = frame.name or frame.url[:50]
                print(f"  frame '{fname}': {frame_btns}")
        except: pass

    # 상단 영역 전체 HTML
    print("\n[5] 상단 영역 HTML...")
    top_html = popup.evaluate("""
    () => {
        // 결재선설정 버튼 근처 영역
        const btn = document.querySelector('button');
        if (btn) {
            let parent = btn.parentElement;
            for (let i = 0; i < 3; i++) {
                if (parent && parent.parentElement) parent = parent.parentElement;
            }
            return parent ? parent.outerHTML.substring(0, 2000) : null;
        }
        return null;
    }
    """)
    if top_html:
        # 버튼 관련 부분만 추출
        safe = top_html.replace('\u200b', '').replace('\xa0', ' ')
        print(f"  (길이: {len(safe)})")
        # 보관/저장/상신 키워드 주변 출력
        import re
        for kw in ['보관', '저장', '임시', '상신']:
            idx = safe.find(kw)
            if idx >= 0:
                start = max(0, idx - 100)
                end = min(len(safe), idx + 100)
                print(f"  '{kw}' 발견 @{idx}: ...{safe[start:end]}...")

    # 전체 페이지 스크린샷
    popup.screenshot(path=str(OUT_DIR / "save_btn_search.png"))
    print("\n  스크린샷: save_btn_search.png")

    popup.close()
    close_session(browser)
    pw_inst.stop()
    print("\ndone!")


if __name__ == "__main__":
    run()
