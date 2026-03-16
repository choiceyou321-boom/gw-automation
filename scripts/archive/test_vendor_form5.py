"""
거래처등록 양식 접근 테스트 v5
- 추천양식 LI.ico7 직접 클릭 (정확한 좌표)
- 실패 시 "결재작성" 버튼 → 양식 선택
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

    print(f"\n[1] login ok, URL: {page.url[:80]}")

    # --- 전자결재 모듈 ---
    print("\n[2] EA module click...")
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
        print("  approval HOME reached")
    except:
        print("  approval HOME text not found")
    time.sleep(2)

    save(page, "v5_02_home")

    # --- 방법1: 추천양식 LI 직접 클릭 ---
    print("\n[3] Method 1: click reco_box li...")

    # div.reco_box 내부의 li 중 "거래처등록" 포함하는 것
    form_opened = False
    try:
        reco_lis = page.locator("div.reco_box li").all()
        print(f"  reco_box li count: {len(reco_lis)}")
        for i, li in enumerate(reco_lis):
            txt = li.inner_text().strip()[:50]
            cls = li.get_attribute("class") or ""
            box = li.bounding_box()
            pos = f"({int(box['x'])},{int(box['y'])})" if box else "?"
            print(f"  [{i}] class={cls}, text='{txt}', pos={pos}")

            if "거래처등록" in txt:
                print(f"  >> clicking li[{i}] at center...")
                li.click(force=True)
                time.sleep(5)

                for p2 in context.pages:
                    if p2 != page:
                        try: p2.close()
                        except: pass

                print(f"  after click URL: {page.url[:100]}")
                save(page, "v5_03_after_li_click")

                # 제목 필드 확인
                try:
                    th = page.locator("th:has-text('제목')").first
                    if th.is_visible(timeout=8000):
                        print("  TITLE FIELD FOUND - form loaded!")
                        form_opened = True
                    else:
                        print("  title field not visible")
                except:
                    print("  title field not found")

                # 내부 탭 확인 (GW 앱 내부 탭)
                print("\n  checking internal tabs...")
                tabs = page.locator("div[class*='tab'] span, li[class*='tab'] span").all()
                for j, tab in enumerate(tabs[:10]):
                    try:
                        t = tab.inner_text().strip()[:30]
                        if t:
                            print(f"    tab[{j}]: '{t}'")
                    except:
                        pass

                break
    except Exception as e:
        print(f"  reco_box approach failed: {e}")

    if form_opened:
        print("\n[SUCCESS] Form loaded via reco_box li click!")
        _analyze_form(page)
        save(page, "v5_99_success")
        close_session(browser)
        pw_inst.stop()
        print("\ndone!")
        return

    # --- 방법2: "결재작성" 사이드바 버튼 → 양식 선택 ---
    print("\n[4] Method 2: sidebar '결재작성' button...")

    # 좌측 사이드바의 "결재작성" (div.sideRegi)
    try:
        write_btn = page.locator("div.sideRegi").first
        if write_btn.is_visible(timeout=5000):
            print(f"  sideRegi found")
            write_btn.click(force=True)
            time.sleep(5)

            for p2 in context.pages:
                if p2 != page:
                    try: p2.close()
                    except: pass

            print(f"  after click URL: {page.url[:100]}")
            save(page, "v5_04_after_sideregi")

            # 양식 선택 페이지 분석
            print("\n[5] Form selection page analysis...")
            body = page.inner_text("body")
            lines = [l.strip() for l in body.split("\n") if l.strip()]
            print(f"  total lines: {len(lines)}")

            # "거래처" 관련 줄
            for i, line in enumerate(lines):
                if "거래처" in line or "양식" in line or "검색" in line:
                    print(f"  [{i}] {line[:80]}")

            # input 찾기
            all_inputs = page.locator("input:visible").all()
            print(f"\n  visible inputs: {len(all_inputs)}")
            for i, inp in enumerate(all_inputs[:10]):
                try:
                    ph = inp.get_attribute("placeholder") or ""
                    tp = inp.get_attribute("type") or ""
                    ro = inp.get_attribute("readonly") or ""
                    box = inp.bounding_box()
                    pos = f"({int(box['x'])},{int(box['y'])})" if box else "?"
                    print(f"  [{i}] type={tp}, ph='{ph}', readonly={ro}, pos={pos}")
                except:
                    pass

            # 양식 검색란이 readonly면 클릭 후 팝업에서 입력
            search_input = None
            for inp in all_inputs:
                ph = inp.get_attribute("placeholder") or ""
                if "양식" in ph:
                    search_input = inp
                    break

            if search_input:
                print("\n[6] Clicking readonly search input...")
                search_input.click()
                time.sleep(2)
                save(page, "v5_06_after_search_click")

                # 팝업/모달 확인
                modal_inputs = page.locator("input:visible:not([readonly])").all()
                print(f"  editable inputs after click: {len(modal_inputs)}")
                for i, inp in enumerate(modal_inputs[:5]):
                    ph = inp.get_attribute("placeholder") or ""
                    box = inp.bounding_box()
                    pos = f"({int(box['x'])},{int(box['y'])})" if box else "?"
                    print(f"  [{i}] ph='{ph}', pos={pos}")

                    if i == 0:
                        # 첫 번째 editable input에 거래처 입력
                        print("  typing '거래처' in first editable input...")
                        inp.click()
                        inp.fill("거래처")
                        inp.press("Enter")
                        time.sleep(3)
                        save(page, "v5_06b_after_type")

                        # 결과 확인
                        results = page.locator("text=거래처등록").all()
                        visible_results = [r for r in results if r.is_visible()]
                        print(f"  '거래처등록' results: total={len(results)}, visible={len(visible_results)}")
                        for j, r in enumerate(visible_results[:5]):
                            t = r.inner_text()[:60]
                            print(f"    [{j}] '{t}'")

                        if visible_results:
                            print("  clicking first result...")
                            visible_results[0].click(force=True)
                            time.sleep(5)
                            print(f"  URL: {page.url[:100]}")
                            save(page, "v5_07_after_form_select")

                            # 제목 필드?
                            try:
                                th = page.locator("th:has-text('제목')").first
                                if th.is_visible(timeout=8000):
                                    print("  TITLE FIELD FOUND!")
                                    form_opened = True
                                    _analyze_form(page)
                                else:
                                    print("  title not visible")
                            except:
                                print("  title not found")
                        break

            # 양식 트리에서 직접 찾기
            if not form_opened:
                print("\n[7] Looking in form tree...")
                # 트리 노드 찾기
                tree_items = page.evaluate("""
                () => {
                    const items = [];
                    const allText = document.querySelectorAll('span, div, a, li');
                    for (const el of allText) {
                        const t = el.textContent?.trim() || '';
                        if (t.includes('거래처') && t.length < 60) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                items.push({
                                    tag: el.tagName,
                                    text: t.substring(0, 50),
                                    className: (el.className || '').substring(0, 50),
                                    x: Math.round(rect.x),
                                    y: Math.round(rect.y),
                                    w: Math.round(rect.width),
                                    h: Math.round(rect.height),
                                });
                            }
                        }
                    }
                    return items;
                }
                """)
                print(f"  visible '거래처' elements: {len(tree_items)}")
                for item in tree_items[:10]:
                    print(f"    <{item['tag']}> '{item['text']}' at ({item['x']},{item['y']}) {item['w']}x{item['h']}")
        else:
            print("  sideRegi not visible")
    except Exception as e:
        print(f"  Method 2 failed: {e}")

    save(page, "v5_99_final")

    close_session(browser)
    pw_inst.stop()
    print("\ndone!")


def _analyze_form(page):
    """폼 구조 분석"""
    print("\n--- Form Structure Analysis ---")

    # th 라벨들
    ths = page.locator("th:visible").all()
    print(f"  th labels: {len(ths)}")
    for j, th in enumerate(ths[:20]):
        try:
            txt = th.inner_text().strip()[:30]
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
    print("  action buttons:")
    for sel in ["div.topBtn:visible"]:
        btns = page.locator(sel).all()
        for b in btns:
            try:
                t = b.inner_text().strip()
                if t and len(t) < 15:
                    print(f"    '{t}'")
            except:
                pass


if __name__ == "__main__":
    run()
