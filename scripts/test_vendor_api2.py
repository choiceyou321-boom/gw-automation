"""
dzEditor API 테스트 v2
- 에디터 번호(0) 명시하여 get/set 호출
- 보관 버튼 정확히 찾기
"""
import sys
import time
import re
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

    # editorView 프레임 찾기
    ev_frame = None
    for frame in popup.frames:
        if "editorView" in frame.url:
            ev_frame = frame
            break
    print(f"  editorView frame: {ev_frame is not None}")

    # === Step 1: getEditorHTMLCodeIframe(0) ===
    print("\n[3] getEditorHTMLCodeIframe(0)...")
    html_from_popup = popup.evaluate("""
    (editorNo) => {
        try {
            return getEditorHTMLCodeIframe(editorNo);
        } catch(e) { return 'ERROR: ' + e.message; }
    }
    """, 0)
    print(f"  결과 길이: {len(html_from_popup)}")
    if html_from_popup and not html_from_popup.startswith("ERROR"):
        (OUT_DIR / "api2_get_html.html").write_text(html_from_popup, encoding="utf-8")
        safe = html_from_popup[:200].replace('\u200b', '')
        print(f"  HTML 저장됨 (처음 200자): {safe}")
    else:
        safe = html_from_popup[:200].replace('\u200b', '')
        print(f"  결과: {safe}")

    # editorView 프레임에서도 시도
    if ev_frame:
        html_from_ev = ev_frame.evaluate("""
        () => {
            try {
                // g_nActiveEditNumber 확인
                const editNo = typeof g_nActiveEditNumber !== 'undefined' ? g_nActiveEditNumber : 0;
                return {editNo: editNo, html: fnGetEditorHTMLCode(false, editNo)};
            } catch(e) { return {error: e.message}; }
        }
        """)
        print(f"  editorView fnGetEditorHTMLCode: {str(html_from_ev)[:200]}")

    # === Step 2: HTML 수정 ===
    print("\n[4] HTML 수정...")
    # 원본 HTML 사용 (파일에서 읽기)
    original_html_path = OUT_DIR / "dzeditor0_body.html"
    if original_html_path.exists():
        original_html = original_html_path.read_text(encoding="utf-8")
        print(f"  원본 HTML 파일 길이: {len(original_html)}")
    elif html_from_popup and not html_from_popup.startswith("ERROR") and len(html_from_popup) > 100:
        original_html = html_from_popup
        print(f"  API에서 가져온 HTML 사용: {len(original_html)}")
    else:
        print("  HTML을 가져올 수 없음!")
        popup.close(); close_session(browser); pw_inst.stop(); return

    modified = original_html

    # 사업자등록번호: "ex) 000-00-00000" → "123-45-67890"
    modified = modified.replace("ex) 000-00-00000", "123-45-67890")
    print(f"  사업자등록번호 교체: {'123-45-67890' in modified}")

    # 소속: "본부 / 팀" → "PM팀"
    modified = modified.replace("본부 / 팀", "PM팀")
    print(f"  소속 교체: {'PM팀' in modified}")

    # 상호명 빈 셀 채우기 (상호명 레이블 td 다음의 빈 td)
    # 패턴: 상호명</p></td> ... <td ...><p ...><br></p></td>
    modified = re.sub(
        r'(>상호명</p></td>)(<td[^>]*>)(<p[^>]*>)<br>(</p></td>)',
        r'\1\2\3(주)테스트상사\4',
        modified
    )
    print(f"  상호명: {'테스트상사' in modified}")

    # 대표자명 빈 셀
    modified = re.sub(
        r'(>대표자명</p></td>)(<td[^>]*>)(<p[^>]*>)<br>(</p></td>)',
        r'\1\2\3홍길동\4',
        modified
    )
    print(f"  대표자명: {'홍길동' in modified}")

    # 성명 빈 셀
    modified = re.sub(
        r'(>성명</p></td>)(<td[^>]*>)(<p[^>]*>)<br>(</p></td>)',
        r'\1\2\3전태규\4',
        modified
    )
    print(f"  성명: {'전태규' in modified}")

    # 수신자이메일 빈 셀 (이메일</p></td> 뒤)
    modified = re.sub(
        r'(>이메일</p></td>)(<td[^>]*>)(<p[^>]*>)<br>(</p></td>)',
        r'\1\2\3test@example.com\4',
        modified
    )
    print(f"  이메일: {'test@example.com' in modified}")

    # 비고 빈 셀
    modified = re.sub(
        r'(>비고</p></td>)(<td[^>]*>)(<p[^>]*>)<br>(</p></td>)',
        r'\1\2\3테스트 비고입니다\4',
        modified
    )
    print(f"  비고: {'테스트 비고' in modified}")

    (OUT_DIR / "api2_modified.html").write_text(modified, encoding="utf-8")

    # === Step 3: setEditorHTMLCodeIframe(html, 0) ===
    print("\n[5] setEditorHTMLCodeIframe(html, 0)...")
    set_result = popup.evaluate("""
    (args) => {
        const [html, editorNo] = args;
        try {
            setEditorHTMLCodeIframe(html, editorNo);
            return {success: true};
        } catch(e) { return {error: e.message}; }
    }
    """, [modified, 0])
    print(f"  결과: {set_result}")
    time.sleep(2)

    # 설정 후 확인
    verify = popup.evaluate("(n) => getEditorHTMLCodeIframe(n)", 0)
    if verify:
        has_test = "테스트상사" in verify
        has_bizno = "123-45-67890" in verify
        print(f"  검증: 상호명={has_test}, 사업자등록번호={has_bizno}, 길이={len(verify)}")
    else:
        print(f"  검증 실패: 빈 HTML")

    # dzeditor_0 텍스트로도 확인
    dz_frame = None
    for frame in popup.frames:
        if frame.name == "dzeditor_0":
            dz_frame = frame
            break
    if dz_frame:
        dz_text = dz_frame.evaluate("() => document.body ? document.body.innerText : ''")
        print(f"  dzeditor_0: 상호명={'테스트상사' in dz_text}, 사업자번호={'123-45-67890' in dz_text}")

    popup.screenshot(path=str(OUT_DIR / "api2_after_set.png"))
    print("  스크린샷: api2_after_set.png")

    # === Step 4: 보관 버튼 찾기 ===
    print("\n[6] 보관 버튼 찾기...")
    # 모든 버튼/링크 텍스트 출력
    all_btns = popup.evaluate("""
    () => {
        const result = [];
        // 모든 clickable 요소
        const els = document.querySelectorAll('button, a, span[onclick], div[onclick], input[type="button"]');
        for (const el of els) {
            const text = el.textContent.trim().replace(/\\s+/g, ' ');
            if (text && el.offsetParent !== null) {
                result.push({
                    tag: el.tagName,
                    text: text.substring(0, 50),
                    class: (el.className || '').substring(0, 50),
                    id: el.id || ''
                });
            }
        }
        return result;
    }
    """)
    print(f"  보이는 버튼/링크 {len(all_btns)}개:")
    for b in all_btns:
        txt = b['text']
        # 보관, 저장, 임시, draft 관련 키워드
        if any(k in txt for k in ['보관', '저장', '임시', '상신', '닫기', '설정', '취소']):
            print(f"    ★ {b['tag']} id={b['id']} class={b['class']}: '{txt}'")

    # 팝업 상단 버튼바 확인 (iframe 바깥)
    top_btns = popup.evaluate("""
    () => {
        const header = document.querySelector('.btn-area, .button-area, .top-btn, .header-btn, [class*="btnArea"], [class*="btn_area"]');
        if (header) return header.innerHTML.substring(0, 500);
        // 첫 번째 button 주변
        const first = document.querySelector('button');
        if (first && first.parentElement) return first.parentElement.innerHTML.substring(0, 500);
        return null;
    }
    """)
    print(f"\n  상단 영역 HTML: {str(top_btns)[:300] if top_btns else 'null'}")

    popup.close()
    close_session(browser)
    pw_inst.stop()
    print("\ndone!")


if __name__ == "__main__":
    run()
