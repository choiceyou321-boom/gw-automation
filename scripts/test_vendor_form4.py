"""
거래처등록 양식 접근 테스트 v4
- 결재 HOME의 추천양식 아이콘 HTML 구조 분석
- 올바른 클릭 대상 식별
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
    print(f"  스크린샷: {path.name}")

def run():
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password

    gw_id = "tgjeon"
    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        print("[오류] 비밀번호를 찾을 수 없습니다.")
        return

    pw = sync_playwright().start()
    browser, context, page = login_and_get_context(
        playwright_instance=pw,
        headless=True,
        user_id=gw_id,
        user_pw=gw_pw,
    )
    page.set_viewport_size({"width": 1920, "height": 1080})

    for p in context.pages:
        if p != page:
            try: p.close()
            except: pass

    print(f"\n[1] 로그인 완료, URL: {page.url[:80]}")

    # ─── 전자결재 모듈 클릭 ───
    print("\n[2] 전자결재 모듈 클릭...")
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
        print("  결재 HOME 도달")
    except:
        print("  결재 HOME 텍스트 미발견")

    time.sleep(2)
    print(f"  URL: {page.url[:100]}")
    save(page, "v4_02_approval_home")

    # ─── 추천양식 섹션 HTML 구조 분석 ───
    print("\n[3] 추천양식 섹션 HTML 구조 분석...")

    # 추천양식 관련 컨테이너 찾기
    recommend_html = page.evaluate("""
    () => {
        // "추천양식" 텍스트를 포함하는 요소 찾기
        const allElements = document.querySelectorAll('*');
        let targetSection = null;

        for (const el of allElements) {
            const text = el.textContent?.trim() || '';
            if (text === '추천양식' || (el.className && el.className.includes && el.className.includes('recommend'))) {
                // 추천양식 텍스트 요소의 부모 섹션 찾기
                let parent = el.parentElement;
                for (let i = 0; i < 5; i++) {
                    if (parent && parent.innerHTML && parent.innerHTML.length > 200) {
                        targetSection = parent;
                        break;
                    }
                    parent = parent?.parentElement;
                }
                if (targetSection) break;
            }
        }

        if (!targetSection) return '추천양식 섹션 미발견';

        // 섹션 내 클릭 가능 요소 분석
        const result = [];
        const clickables = targetSection.querySelectorAll('a, button, [role="button"], div[class*="item"], span[class*="item"]');
        for (const el of clickables) {
            const text = el.textContent?.trim()?.substring(0, 60) || '';
            if (text && text.length > 2 && text.length < 80) {
                result.push({
                    tag: el.tagName,
                    className: (el.className || '').substring(0, 80),
                    text: text.substring(0, 60),
                    href: el.getAttribute('href') || '',
                    onclick: el.getAttribute('onclick') || '',
                    role: el.getAttribute('role') || '',
                    rect: el.getBoundingClientRect ? {
                        x: Math.round(el.getBoundingClientRect().x),
                        y: Math.round(el.getBoundingClientRect().y),
                        w: Math.round(el.getBoundingClientRect().width),
                        h: Math.round(el.getBoundingClientRect().height),
                    } : null,
                });
            }
        }

        // 섹션 HTML 일부
        return {
            sectionTag: targetSection.tagName,
            sectionClass: (targetSection.className || '').substring(0, 100),
            sectionHTML: targetSection.outerHTML.substring(0, 3000),
            clickables: result,
        };
    }
    """)

    if isinstance(recommend_html, str):
        print(f"  {recommend_html}")
    else:
        print(f"  섹션: {recommend_html.get('sectionTag')}.{recommend_html.get('sectionClass', '')[:60]}")
        clickables = recommend_html.get('clickables', [])
        print(f"  클릭 가능 요소: {len(clickables)}개")
        for i, item in enumerate(clickables):
            print(f"    [{i}] <{item['tag']}> text='{item['text']}' class={item['className'][:40]}")
            if item.get('href'):
                print(f"         href={item['href']}")
            if item.get('rect'):
                r = item['rect']
                print(f"         pos=({r['x']},{r['y']}) size={r['w']}x{r['h']}")

        # HTML 저장
        html = recommend_html.get('sectionHTML', '')
        (OUT_DIR / "v4_recommend_section.html").write_text(html, encoding="utf-8")
        print(f"\n  HTML 저장: v4_recommend_section.html ({len(html)}bytes)")

    # ─── "결재작성" 버튼 정확한 분석 ───
    print("\n[4] '결재작성' 버튼 분석...")
    write_btn_info = page.evaluate("""
    () => {
        const results = [];
        const allElements = document.querySelectorAll('*');
        for (const el of allElements) {
            const text = el.textContent?.trim();
            if (text === '결재작성') {
                let parent = el;
                for (let i = 0; i < 3; i++) {
                    results.push({
                        tag: parent.tagName,
                        className: (parent.className || '').substring(0, 80),
                        text: parent.textContent?.trim()?.substring(0, 40),
                        href: parent.getAttribute('href') || '',
                        role: parent.getAttribute('role') || '',
                        rect: parent.getBoundingClientRect ? {
                            x: Math.round(parent.getBoundingClientRect().x),
                            y: Math.round(parent.getBoundingClientRect().y),
                            w: Math.round(parent.getBoundingClientRect().width),
                            h: Math.round(parent.getBoundingClientRect().height),
                        } : null,
                    });
                    parent = parent.parentElement;
                    if (!parent) break;
                }
                break;
            }
        }
        return results;
    }
    """)

    for i, item in enumerate(write_btn_info):
        r = item.get('rect', {})
        print(f"  [{i}] <{item['tag']}> text='{item['text']}' class={item['className'][:50]}")
        print(f"       pos=({r.get('x','?')},{r.get('y','?')}) size={r.get('w','?')}x{r.get('h','?')}")
        if item.get('href'):
            print(f"       href={item['href']}")

    # ─── 거래처등록 텍스트의 정확한 위치 ───
    print("\n[5] '거래처등록' 텍스트 위치 분석...")
    vendor_info = page.evaluate("""
    () => {
        const results = [];
        const allElements = document.querySelectorAll('*');
        for (const el of allElements) {
            const directText = el.childNodes.length === 1 && el.childNodes[0].nodeType === 3
                ? el.textContent.trim() : '';
            const fullText = el.textContent?.trim() || '';

            if (fullText.includes('거래처등록') && fullText.length < 100) {
                const rect = el.getBoundingClientRect();
                results.push({
                    tag: el.tagName,
                    className: (el.className || '').substring(0, 80),
                    text: fullText.substring(0, 60),
                    directText: directText.substring(0, 60),
                    visible: rect.width > 0 && rect.height > 0,
                    rect: {
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        w: Math.round(rect.width),
                        h: Math.round(rect.height),
                    },
                    parentTag: el.parentElement?.tagName || '',
                    parentClass: (el.parentElement?.className || '').substring(0, 60),
                    parentParentTag: el.parentElement?.parentElement?.tagName || '',
                    parentParentClass: (el.parentElement?.parentElement?.className || '').substring(0, 60),
                });
            }
        }
        return results;
    }
    """)

    print(f"  '거래처등록' 포함 요소: {len(vendor_info)}개")
    for i, item in enumerate(vendor_info):
        r = item['rect']
        vis = "V" if item['visible'] else "H"
        print(f"  [{i}] [{vis}] <{item['tag']}> text='{item['text'][:40]}'")
        print(f"       class={item['className'][:50]}")
        print(f"       pos=({r['x']},{r['y']}) size={r['w']}x{r['h']}")
        print(f"       parent: <{item['parentTag']}>.{item['parentClass'][:40]}")

    # ─── 추천양식 아이콘 직접 클릭 시도 (visible 요소 중 추천양식 영역에 있는 것) ───
    print("\n[6] 추천양식에서 거래처등록 아이콘 클릭 시도...")

    # 추천양식 영역은 보통 결재 HOME 상단 (y < 400)
    for item in vendor_info:
        if item['visible'] and item['rect']['y'] < 500:
            r = item['rect']
            center_x = r['x'] + r['w'] // 2
            center_y = r['y'] + r['h'] // 2
            print(f"  클릭 대상: ({center_x},{center_y}) - {item['text'][:40]}")

            # 이 요소의 부모(아이콘 컨테이너)를 클릭
            # 아이콘 위쪽 (텍스트가 아이콘 아래에 있으므로) 20px 위를 클릭
            click_y = r['y'] - 20 if r['y'] > 30 else center_y
            print(f"  아이콘 영역 클릭: ({center_x},{click_y})")

            page.mouse.click(center_x, click_y)
            time.sleep(5)

            for p2 in context.pages:
                if p2 != page:
                    try: p2.close()
                    except: pass

            print(f"  클릭 후 URL: {page.url[:100]}")
            save(page, "v4_06_after_icon_click")

            # 제목 필드 확인
            try:
                th = page.locator("th:has-text('제목')").first
                if th.is_visible(timeout=8000):
                    print("  ★ 제목 필드 발견! 양식 로드 성공!")
                else:
                    print("  ✗ 제목 필드 안 보임")
            except:
                print("  ✗ 제목 필드 없음")

            # 현재 페이지 텍스트 저장
            try:
                text = page.inner_text("body")
                lines = [l.strip() for l in text.split("\n") if l.strip()][:30]
                for line in lines:
                    print(f"    {line[:60]}")
            except:
                pass
            break

    save(page, "v4_99_final")

    close_session(browser)
    pw.stop()
    print("\n완료!")

if __name__ == "__main__":
    run()
