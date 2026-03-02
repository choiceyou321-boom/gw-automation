"""
dzEditor API를 사용한 본문 기입 테스트
- fnSetEditorHTMLCode / setEditorHTMLCodeIframe 사용
- 보관 후 실제 저장 여부 확인
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

    # === Step 1: API 함수 시그니처 확인 ===
    print("\n[3] API 함수 시그니처 확인...")

    # editorView 프레임 찾기
    ev_frame = None
    for frame in popup.frames:
        if "editorView" in frame.url:
            ev_frame = frame
            break

    if ev_frame:
        # fnGetEditorHTMLCode 시그니처
        api_sig = ev_frame.evaluate("""
        () => {
            const result = {};
            if (typeof fnGetEditorHTMLCode === 'function') {
                result.fnGetEditorHTMLCode = fnGetEditorHTMLCode.toString().substring(0, 200);
            }
            if (typeof fnSetEditorHTMLCode === 'function') {
                result.fnSetEditorHTMLCode = fnSetEditorHTMLCode.toString().substring(0, 200);
            }
            if (typeof fnGetEditorPreviewHTML === 'function') {
                result.fnGetEditorPreviewHTML = fnGetEditorPreviewHTML.toString().substring(0, 200);
            }
            return result;
        }
        """)
        print(f"  editorView API 시그니처:")
        for k, v in api_sig.items():
            print(f"    {k}: {v[:150]}")

    # 팝업 페이지의 API 시그니처
    popup_sig = popup.evaluate("""
    () => {
        const result = {};
        if (typeof setEditorHTMLCodeIframe === 'function') {
            result.setEditorHTMLCodeIframe = setEditorHTMLCodeIframe.toString().substring(0, 300);
        }
        if (typeof getEditorHTMLCodeIframe === 'function') {
            result.getEditorHTMLCodeIframe = getEditorHTMLCodeIframe.toString().substring(0, 300);
        }
        if (typeof getEditorIframeWindow === 'function') {
            result.getEditorIframeWindow = getEditorIframeWindow.toString().substring(0, 300);
        }
        return result;
    }
    """)
    print(f"\n  popup API 시그니처:")
    for k, v in popup_sig.items():
        print(f"    {k}: {v[:200]}")

    # === Step 2: 현재 HTML 가져오기 ===
    print("\n[4] 현재 에디터 HTML 가져오기...")

    # editorView에서 가져오기 시도
    if ev_frame:
        current_html = ev_frame.evaluate("""
        () => {
            try {
                if (typeof fnGetEditorHTMLCode === 'function') {
                    return {method: 'fnGetEditorHTMLCode', html: fnGetEditorHTMLCode()};
                }
            } catch(e) { return {error: e.message}; }
            return {error: 'no function'};
        }
        """)
        print(f"  fnGetEditorHTMLCode 결과: 길이={len(str(current_html.get('html', '')))}, method={current_html.get('method', current_html.get('error', ''))}")

    # 팝업에서 가져오기 시도
    current_html2 = popup.evaluate("""
    () => {
        try {
            if (typeof getEditorHTMLCodeIframe === 'function') {
                return {method: 'getEditorHTMLCodeIframe', html: getEditorHTMLCodeIframe()};
            }
        } catch(e) { return {error: e.message}; }
        return {error: 'no function'};
    }
    """)
    print(f"  getEditorHTMLCodeIframe 결과: 길이={len(str(current_html2.get('html', '')))}, method={current_html2.get('method', current_html2.get('error', ''))}")

    # 실제 HTML 내용 일부 저장
    html_content = current_html.get('html', '') or current_html2.get('html', '')
    if html_content:
        (OUT_DIR / "api_get_html.html").write_text(html_content, encoding="utf-8")
        print(f"  HTML 저장: api_get_html.html ({len(html_content)} chars)")

    # === Step 3: HTML 수정 후 setEditorHTMLCode 테스트 ===
    print("\n[5] setEditorHTMLCode로 본문 수정 테스트...")

    if html_content:
        # 원본 HTML에서 placeholder 텍스트를 실제 값으로 교체
        modified_html = html_content
        # 사업자등록번호: "ex) 000-00-00000" → "123-45-67890"
        modified_html = modified_html.replace("ex) 000-00-00000", "123-45-67890")
        # 소속: "본부 / 팀" → "PM팀"
        modified_html = modified_html.replace("본부 / 팀", "PM팀")

        # 상호명 셀 (빈 <p> 태그 - 사업자등록번호 행의 4번째 td)
        # 대표자명 셀, 수신자이메일 셀도 마찬가지

        # 좀 더 정밀하게: 상호명 레이블 뒤의 빈 td
        # HTML 구조 분석하여 빈 <p> 태그에 값 넣기
        import re

        # 상호명 뒤 빈 셀
        pattern_sangho = r'(>상호명</p></td>)(.*?<p[^>]*>)(<br>)(</p></td>)'
        match = re.search(pattern_sangho, modified_html, re.DOTALL)
        if match:
            modified_html = modified_html[:match.start(3)] + "(주)테스트상사" + modified_html[match.end(3):]
            print("  상호명 셀 수정 완료")
        else:
            print("  상호명 셀 패턴 미매칭")

        # 대표자명 뒤 빈 셀
        pattern_daepyo = r'(>대표자명</p></td>)(.*?<p[^>]*>)(<br>)(</p></td>)'
        match = re.search(pattern_daepyo, modified_html, re.DOTALL)
        if match:
            modified_html = modified_html[:match.start(3)] + "홍길동" + modified_html[match.end(3):]
            print("  대표자명 셀 수정 완료")
        else:
            print("  대표자명 셀 패턴 미매칭")

        # 성명 뒤 빈 셀
        pattern_name = r'(>성명</p></td>)(.*?<p[^>]*>)(<br>)(</p></td>)'
        match = re.search(pattern_name, modified_html, re.DOTALL)
        if match:
            modified_html = modified_html[:match.start(3)] + "전태규" + modified_html[match.end(3):]
            print("  성명 셀 수정 완료")
        else:
            print("  성명 셀 패턴 미매칭")

        # 수신자이메일 뒤 빈 셀
        pattern_email = r'(>이메일</p></td>)(.*?<p[^>]*>)(<br>)(</p></td>)'
        match = re.search(pattern_email, modified_html, re.DOTALL)
        if match:
            modified_html = modified_html[:match.start(3)] + "test@test.com" + modified_html[match.end(3):]
            print("  수신자이메일 셀 수정 완료")
        else:
            print("  수신자이메일 셀 패턴 미매칭")

        (OUT_DIR / "api_modified_html.html").write_text(modified_html, encoding="utf-8")
        print(f"  수정된 HTML 저장 ({len(modified_html)} chars)")

        # setEditorHTMLCode로 설정 - editorView에서
        if ev_frame:
            set_result = ev_frame.evaluate("""
            (html) => {
                try {
                    if (typeof fnSetEditorHTMLCode === 'function') {
                        fnSetEditorHTMLCode(html);
                        return {success: true, method: 'fnSetEditorHTMLCode'};
                    }
                } catch(e) { return {error: e.message}; }
                return {error: 'no function'};
            }
            """, modified_html)
            print(f"  fnSetEditorHTMLCode 결과: {set_result}")

        time.sleep(2)

        # 설정 후 확인
        verify_html = ""
        if ev_frame:
            verify_html = ev_frame.evaluate("""
            () => {
                try { return fnGetEditorHTMLCode(); }
                catch(e) { return ''; }
            }
            """)
        has_test = "(주)테스트상사" in verify_html
        has_bizno = "123-45-67890" in verify_html
        print(f"  검증: 상호명={has_test}, 사업자등록번호={has_bizno}, HTML길이={len(verify_html)}")

        # dzeditor_0 에서도 확인
        dz_frame = None
        for frame in popup.frames:
            if frame.name == "dzeditor_0":
                dz_frame = frame
                break
        if dz_frame:
            dz_text = dz_frame.evaluate("() => document.body ? document.body.innerText : ''")
            print(f"  dzeditor_0 텍스트 내 상호명: {'테스트상사' in dz_text}")
            print(f"  dzeditor_0 텍스트 내 사업자번호: {'123-45-67890' in dz_text}")

    # 스크린샷
    popup.screenshot(path=str(OUT_DIR / "api_test_after_set.png"))
    print("  스크린샷: api_test_after_set.png")

    # === Step 4: 보관 테스트 ===
    print("\n[6] 보관 버튼 클릭 테스트...")
    save_btn = popup.locator("button:has-text('보관'), span:has-text('보관')").first
    if save_btn.is_visible(timeout=3000):
        print(f"  보관 버튼 발견, 클릭...")
        save_btn.click()
        time.sleep(3)
        popup.screenshot(path=str(OUT_DIR / "api_test_after_save.png"))
        print("  스크린샷: api_test_after_save.png")

        # 확인 팝업 처리
        try:
            ok_btn = popup.locator("button:has-text('확인')").first
            if ok_btn.is_visible(timeout=3000):
                ok_btn.click()
                time.sleep(2)
        except: pass
    else:
        print("  보관 버튼 없음!")
        # 버튼 목록 확인
        btns = popup.evaluate("""
        () => {
            const btns = document.querySelectorAll('button, span[class*="btn"], a[class*="btn"]');
            return Array.from(btns).slice(0, 30).map(b => ({
                tag: b.tagName,
                text: b.textContent.trim().substring(0, 30),
                visible: b.offsetParent !== null
            }));
        }
        """)
        for b in btns:
            if b['visible']:
                print(f"    {b['tag']}: '{b['text']}'")

    popup.close()
    close_session(browser)
    pw_inst.stop()
    print("\ndone!")


if __name__ == "__main__":
    run()
