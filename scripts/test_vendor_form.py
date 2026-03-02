"""
거래처등록 양식 접근 테스트 스크립트
- 로그인 → 결재 HOME → 거래처등록 양식 찾기 → 스크린샷
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

    # 팝업 닫기
    for p in context.pages:
        if "popup" in p.url and p != page:
            try: p.close()
            except: pass

    print(f"\n[1] 로그인 완료, URL: {page.url[:80]}")
    save(page, "01_after_login")

    # ─── 전자결재 모듈 클릭 ───
    print("\n[2] 전자결재 모듈 클릭...")
    try:
        ea = page.locator("span.module-link.EA").first
        if ea.is_visible(timeout=5000):
            ea.click(force=True)
            time.sleep(4)
        else:
            page.locator("text=전자결재").first.click(force=True)
            time.sleep(4)
    except Exception as e:
        print(f"  전자결재 모듈 클릭 실패: {e}")

    # 팝업 닫기
    for p in context.pages:
        if "popup" in p.url and p != page:
            try: p.close()
            except: pass

    print(f"  URL: {page.url[:80]}")
    save(page, "02_approval_home")

    # ─── 추천양식 확인 ───
    print("\n[3] 추천양식에서 거래처등록 찾기...")
    found_in_recommend = False
    for keyword in ["거래처등록", "국내 거래처등록", "[회계팀] 국내 거래처등록"]:
        try:
            links = page.locator(f"text={keyword}").all()
            print(f"  '{keyword}' → {len(links)}개 발견")
            for i, link in enumerate(links):
                vis = link.is_visible()
                txt = link.inner_text()[:50] if vis else "(not visible)"
                print(f"    [{i}] visible={vis}, text='{txt}'")
                if vis and not found_in_recommend:
                    print(f"  → 클릭!")
                    link.click(force=True)
                    found_in_recommend = True
                    time.sleep(5)
                    break
            if found_in_recommend:
                break
        except Exception as e:
            print(f"  '{keyword}' 검색 실패: {e}")

    if found_in_recommend:
        # 팝업 닫기
        for p in context.pages:
            if "popup" in p.url and p != page:
                try: p.close()
                except: pass
        print(f"  URL: {page.url[:80]}")
        save(page, "03_after_form_click")
    else:
        print("  추천양식에서 못 찾음!")
        save(page, "03_recommend_not_found")

    # ─── 방법 2: 결재작성 클릭 → 양식 검색 ───
    if not found_in_recommend:
        print("\n[4] 결재작성 메뉴 찾기...")

        # 결재작성 관련 텍스트/링크 탐색
        for selector in ["text=결재작성", "a:has-text('결재작성')", "span:has-text('결재작성')", "text=새 결재", "text=기안"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    print(f"  '{selector}' 발견! 클릭")
                    el.click(force=True)
                    time.sleep(3)
                    save(page, "04_after_write_click")
                    print(f"  URL: {page.url[:80]}")
                    break
            except:
                print(f"  '{selector}' 없음")
                continue

        # 양식 검색 입력란 찾기
        print("\n[5] 양식 검색 입력란 찾기...")
        all_inputs = page.locator("input:visible").all()
        print(f"  보이는 input 수: {len(all_inputs)}")
        for i, inp in enumerate(all_inputs[:10]):
            try:
                ph = inp.get_attribute("placeholder") or ""
                tp = inp.get_attribute("type") or ""
                cls = inp.get_attribute("class") or ""
                val = inp.input_value() or ""
                box = inp.bounding_box()
                pos = f"({int(box['x'])},{int(box['y'])})" if box else "(?)"
                print(f"  [{i}] type={tp}, ph='{ph}', val='{val}', pos={pos}, cls={cls[:40]}")
            except:
                pass

    # ─── 현재 페이지에서 보이는 모든 주요 요소 덤프 ───
    print("\n[6] 현재 페이지 주요 버튼/링크 덤프...")
    for tag in ["button:visible", "a:visible", "div.topBtn:visible"]:
        try:
            els = page.locator(tag).all()[:15]
            if els:
                print(f"  --- {tag} ({len(els)}개) ---")
                for el in els:
                    txt = el.inner_text()[:50].strip()
                    if txt:
                        print(f"    '{txt}'")
        except:
            pass

    # ─── 좌측 메뉴(LNB) 탐색 ───
    print("\n[7] 좌측 네비게이션 메뉴 탐색...")
    for selector in ["div.lnb", "nav", "aside", "div[class*='sidebar']", "div[class*='menu']", "ul.lnb"]:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=1000):
                text = el.inner_text()[:300]
                print(f"  {selector}: {text[:200]}")
                break
        except:
            pass

    # ─── 제목 필드 확인 ───
    print("\n[8] 제목 필드 확인...")
    try:
        th = page.locator("th:has-text('제목')").first
        if th.is_visible(timeout=3000):
            print("  제목 th 발견!")
        else:
            print("  제목 th 안 보임")
    except:
        print("  제목 th 없음")

    save(page, "99_final")

    # 페이지 텍스트 저장
    try:
        text = page.inner_text("body")
        (OUT_DIR / "page_text.txt").write_text(text[:5000], encoding="utf-8")
        print(f"\n  페이지 텍스트 저장 완료")
    except:
        pass

    close_session(browser)
    pw.stop()
    print("\n완료!")

if __name__ == "__main__":
    run()
