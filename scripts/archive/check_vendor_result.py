"""
보관된 거래처등록 문서의 본문 데이터 확인
- 미리보기 모드로 전체 내용 확인
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
    # 전자결재 모듈 진입
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
    time.sleep(2)

    # 임시보관문서 URL로 직접 이동
    print("[2] 임시보관문서...")
    page.goto("https://gw.glowseoul.co.kr/#/EA/EA/EAB0005", wait_until="networkidle", timeout=15000)
    time.sleep(5)
    page.screenshot(path=str(OUT_DIR / "check_temp_docs.png"))
    print("  스크린샷: check_temp_docs.png")

    # 가장 최근 거래처등록 문서 클릭
    docs = page.locator("text=거래처등록").all()
    visible = [d for d in docs if d.is_visible()]
    if not visible:
        # 하넬무역으로 검색
        docs = page.locator("text=하넬무역").all()
        visible = [d for d in docs if d.is_visible()]
    if not visible:
        print("  거래처등록 문서 없음!")
        page.screenshot(path=str(OUT_DIR / "check_no_doc.png"))
        close_session(browser); pw_inst.stop(); return

    print(f"  문서 {len(visible)}개 발견, 클릭...")
    visible[0].click(force=True)
    time.sleep(5)

    # 팝업 확인
    for p in context.pages:
        if p != page:
            try:
                p_url = p.url or ""
                if "popup" in p_url or "formId" in p_url:
                    p.set_viewport_size({"width": 1920, "height": 2000})
                    time.sleep(3)
                    p.screenshot(path=str(OUT_DIR / "check_result_full.png"), full_page=True)
                    print(f"  스크린샷: check_result_full.png")

                    # dzeditor_0 본문 텍스트 추출
                    for frame in p.frames:
                        if frame.name == "dzeditor_0":
                            text = frame.evaluate("() => document.body ? document.body.innerText : ''")
                            print(f"\n  === 본문 텍스트 ===")
                            for line in text.split("\n"):
                                line = line.strip()
                                if line:
                                    try:
                                        print(f"  {line[:80]}")
                                    except:
                                        pass
                            (OUT_DIR / "check_result_text.txt").write_text(text, encoding="utf-8")
                            break
                    p.close()
                    break
            except Exception as e:
                print(f"  error: {e}")

    # 같은 페이지에서 열릴 수도 있음
    page.screenshot(path=str(OUT_DIR / "check_after_click.png"))

    close_session(browser)
    pw_inst.stop()
    print("\ndone!")

if __name__ == "__main__":
    run()
