"""
거래처등록 양식 접근 테스트 v2
- "결재작성" 버튼 경로로 양식 선택
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
        if p != page:
            try: p.close()
            except: pass

    print(f"\n[1] 로그인 완료, URL: {page.url[:80]}")
    save(page, "v2_01_login")

    # ─── 전자결재 모듈 클릭 ───
    print("\n[2] 전자결재 모듈 클릭...")
    try:
        ea = page.locator("span.module-link.EA").first
        if ea.is_visible(timeout=5000):
            ea.click(force=True)
            time.sleep(4)
    except Exception as e:
        print(f"  전자결재 모듈 클릭 실패: {e}")
        page.locator("text=전자결재").first.click(force=True)
        time.sleep(4)

    for p in context.pages:
        if p != page:
            try: p.close()
            except: pass

    print(f"  URL: {page.url[:80]}")
    save(page, "v2_02_approval_home")

    # ─── "결재작성" 버튼 클릭 ───
    print("\n[3] '결재작성' 버튼 클릭...")
    clicked_write = False
    for selector in [
        "text=결재작성",
        "a:has-text('결재작성')",
        "span:has-text('결재작성')",
        "button:has-text('결재작성')",
    ]:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=3000):
                # 요소 정보 출력
                tag = el.evaluate("e => e.tagName")
                cls = el.evaluate("e => e.className") or ""
                href = el.evaluate("e => e.getAttribute('href')") or ""
                box = el.bounding_box()
                pos = f"({int(box['x'])},{int(box['y'])})" if box else "?"
                print(f"  발견: {selector} → tag={tag}, class={cls[:50]}, href={href}, pos={pos}")
                el.click(force=True)
                clicked_write = True
                time.sleep(4)
                break
        except Exception as e:
            print(f"  {selector}: {e}")

    if clicked_write:
        for p in context.pages:
            if p != page:
                try: p.close()
                except: pass
        print(f"  클릭 후 URL: {page.url[:100]}")
        save(page, "v2_03_after_write_click")

        # ─── 양식 선택 화면 분석 ───
        print("\n[4] 양식 선택 화면 분석...")

        # 페이지 내 모든 텍스트 (양식 목록 확인용)
        try:
            body_text = page.inner_text("body")
            lines = [l.strip() for l in body_text.split("\n") if l.strip()]
            print(f"  페이지 텍스트 ({len(lines)}줄):")
            for i, line in enumerate(lines[:60]):
                print(f"    [{i}] {line[:80]}")
            # 저장
            (OUT_DIR / "v2_form_select_text.txt").write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            print(f"  텍스트 추출 실패: {e}")

        # input 확인
        print("\n[5] 검색 입력란...")
        all_inputs = page.locator("input:visible").all()
        print(f"  보이는 input 수: {len(all_inputs)}")
        for i, inp in enumerate(all_inputs[:10]):
            try:
                ph = inp.get_attribute("placeholder") or ""
                tp = inp.get_attribute("type") or ""
                box = inp.bounding_box()
                pos = f"({int(box['x'])},{int(box['y'])})" if box else "(?)"
                print(f"  [{i}] type={tp}, ph='{ph}', pos={pos}")
            except:
                pass

        # "거래처" 키워드 검색 시도
        print("\n[6] 거래처 양식 검색 시도...")
        for selector in [
            "input[placeholder*='검색']",
            "input[placeholder*='양식']",
            "input[placeholder*='form']",
        ]:
            try:
                search = page.locator(selector).first
                if search.is_visible(timeout=2000):
                    print(f"  검색란 발견: {selector}")
                    search.click()
                    search.fill("거래처")
                    search.press("Enter")
                    time.sleep(3)
                    save(page, "v2_06_after_search")

                    # 검색 결과
                    results = page.locator("text=거래처").all()
                    print(f"  '거래처' 검색 결과: {len(results)}개")
                    for j, r in enumerate(results[:10]):
                        vis = r.is_visible()
                        txt = r.inner_text()[:60] if vis else "(hidden)"
                        print(f"    [{j}] vis={vis}, text='{txt}'")
                    break
            except:
                continue

        # 양식 목록에서 거래처등록 찾기
        print("\n[7] 양식 목록에서 거래처등록 찾기...")
        for keyword in ["국내 거래처등록", "거래처등록 신청", "거래처등록"]:
            try:
                matches = page.locator(f"text={keyword}").all()
                print(f"  '{keyword}' → {len(matches)}개")
                for j, m in enumerate(matches[:5]):
                    vis = m.is_visible()
                    if vis:
                        txt = m.inner_text()[:60]
                        tag = m.evaluate("e => e.tagName")
                        cls = m.evaluate("e => e.className") or ""
                        box = m.bounding_box()
                        pos = f"({int(box['x'])},{int(box['y'])})" if box else "?"
                        print(f"    [{j}] tag={tag}, text='{txt}', class={cls[:40]}, pos={pos}")

                        # 첫 번째 visible 클릭 시도
                        if j == 0:
                            print(f"  → 클릭 시도!")
                            m.click(force=True)
                            time.sleep(5)

                            for p2 in context.pages:
                                if p2 != page:
                                    try: p2.close()
                                    except: pass

                            print(f"  클릭 후 URL: {page.url[:100]}")
                            save(page, "v2_07_after_form_select")

                            # 제목 필드 확인
                            try:
                                th = page.locator("th:has-text('제목')").first
                                if th.is_visible(timeout=5000):
                                    print("  ★ 제목 필드 발견! 양식 로드 성공!")
                                else:
                                    print("  ✗ 제목 필드 안 보임")
                            except:
                                print("  ✗ 제목 필드 없음")

                            # 보관 버튼 확인
                            try:
                                for btn_sel in ["div.topBtn:has-text('보관')", "button:has-text('보관')", "text=보관"]:
                                    btns = page.locator(btn_sel).all()
                                    for b in btns:
                                        if b.is_visible():
                                            print(f"  ★ 보관 버튼 발견: {btn_sel}")
                                            break
                            except:
                                pass

                            break
                    else:
                        print(f"    [{j}] (hidden)")
                break
            except Exception as e:
                print(f"  '{keyword}' 검색 실패: {e}")
    else:
        print("  결재작성 버튼을 찾을 수 없습니다!")

    save(page, "v2_99_final")

    # 최종 페이지 텍스트 저장
    try:
        text = page.inner_text("body")
        (OUT_DIR / "v2_final_text.txt").write_text(text[:5000], encoding="utf-8")
    except:
        pass

    close_session(browser)
    pw.stop()
    print("\n완료!")

if __name__ == "__main__":
    run()
