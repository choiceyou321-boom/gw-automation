"""
거래처등록 양식 접근 테스트 v3
- 결재작성 → 양식 검색 "거래처" → 양식 선택 → 폼 로드 확인
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

    # 결재 HOME 대기
    try:
        page.wait_for_selector("text=결재 HOME", timeout=10000)
        print("  결재 HOME 도달")
    except:
        print("  결재 HOME 텍스트 미발견, 계속 진행")
    time.sleep(2)

    # ─── "결재작성" 버튼 클릭 ───
    print("\n[3] '결재작성' 버튼 클릭...")
    clicked = False
    for selector in ["text=결재작성", "span:has-text('결재작성')"]:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=5000):
                el.click(force=True)
                clicked = True
                print(f"  {selector} 클릭 성공")
                break
        except Exception as e:
            print(f"  {selector}: {e}")
    if not clicked:
        print("  결재작성 버튼 못 찾음!")
        save(page, "v3_error_no_write_btn")
        close_session(browser)
        pw.stop()
        return
    time.sleep(4)

    for p in context.pages:
        if p != page:
            try: p.close()
            except: pass

    print(f"  URL: {page.url[:100]}")
    save(page, "v3_03_form_select")

    # ─── 양식 검색 입력란 사용 ───
    print("\n[4] 양식 검색 입력란에 '거래처' 입력...")

    # 검색 입력란 찾기 (placeholder: "양식명을 입력하세요.")
    search_input = None

    # 방법 1: placeholder 기반
    try:
        inp = page.locator("input[placeholder*='양식명']").first
        if inp.is_visible(timeout=3000):
            search_input = inp
            print("  검색란 발견 (양식명 placeholder)")
    except:
        pass

    # 방법 2: 모든 visible input 중 첫 번째
    if not search_input:
        try:
            all_inputs = page.locator("input:visible").all()
            for inp in all_inputs:
                ph = inp.get_attribute("placeholder") or ""
                print(f"  input placeholder: '{ph}'")
                if "양식" in ph or "검색" in ph or "입력" in ph:
                    search_input = inp
                    print(f"  검색란 발견 (ph='{ph}')")
                    break
            if not search_input and all_inputs:
                search_input = all_inputs[0]
                print("  검색란: 첫 번째 visible input 사용")
        except:
            pass

    if search_input:
        search_input.click()
        time.sleep(0.5)
        search_input.fill("거래처")
        time.sleep(0.5)
        search_input.press("Enter")
        print("  '거래처' 입력 후 Enter")
        time.sleep(3)
        save(page, "v3_04_after_search")

        # 검색 결과 확인
        print("\n[5] 검색 결과 확인...")
        body_text = page.inner_text("body")
        lines = [l.strip() for l in body_text.split("\n") if l.strip()]
        # "거래처" 포함하는 줄만 출력
        vendor_lines = [(i, l) for i, l in enumerate(lines) if "거래처" in l]
        print(f"  '거래처' 포함 줄 수: {len(vendor_lines)}")
        for i, l in vendor_lines[:15]:
            print(f"    [{i}] {l[:80]}")

        # "국내 거래처" 텍스트 클릭 시도
        print("\n[6] '국내 거래처' 클릭 시도...")
        for keyword in ["국내 거래처등록 신청서", "국내 거래처등록", "거래처등록 신청서", "거래처등록"]:
            try:
                matches = page.locator(f"text={keyword}").all()
                visible_matches = [m for m in matches if m.is_visible()]
                print(f"  '{keyword}' → total={len(matches)}, visible={len(visible_matches)}")

                if visible_matches:
                    m = visible_matches[0]
                    tag = m.evaluate("e => e.tagName")
                    cls = m.evaluate("e => e.className") or ""
                    txt = m.inner_text()[:60]
                    box = m.bounding_box()
                    pos = f"({int(box['x'])},{int(box['y'])})" if box else "?"
                    parent_tag = m.evaluate("e => e.parentElement?.tagName") or ""
                    parent_cls = m.evaluate("e => e.parentElement?.className") or ""
                    print(f"    tag={tag}, text='{txt}', class={cls[:40]}")
                    print(f"    parent: {parent_tag}.{parent_cls[:40]}")
                    print(f"    pos={pos}")

                    # 클릭!
                    print(f"  → 클릭!")
                    m.click(force=True)
                    time.sleep(5)

                    for p2 in context.pages:
                        if p2 != page:
                            try: p2.close()
                            except: pass

                    print(f"  클릭 후 URL: {page.url[:100]}")
                    save(page, "v3_06_after_form_click")

                    # 제목 필드 확인
                    try:
                        th = page.locator("th:has-text('제목')").first
                        if th.is_visible(timeout=8000):
                            print("  ★ 제목 필드 발견! 양식 로드 성공!")
                            save(page, "v3_07_form_loaded")

                            # 폼 구조 분석
                            print("\n[7] 폼 구조 분석...")
                            # th 라벨들 출력
                            ths = page.locator("th:visible").all()
                            print(f"  th 라벨 수: {len(ths)}")
                            for j, th_el in enumerate(ths[:20]):
                                try:
                                    txt = th_el.inner_text().strip()[:30]
                                    if txt:
                                        print(f"    [{j}] {txt}")
                                except:
                                    pass

                            # contentEditable 영역 확인
                            print("\n  contentEditable 영역:")
                            editors = page.locator("[contenteditable='true']:visible").all()
                            print(f"  {len(editors)}개")

                            # iframe 확인
                            iframes = page.locator("iframe:visible").all()
                            print(f"  iframe: {len(iframes)}개")

                            # 보관/상신 버튼 확인
                            print("\n  액션 버튼:")
                            for btn_sel in ["div.topBtn:visible", "button:visible"]:
                                btns = page.locator(btn_sel).all()
                                for b in btns[:10]:
                                    try:
                                        txt = b.inner_text().strip()
                                        if txt and len(txt) < 10:
                                            print(f"    '{txt}'")
                                    except:
                                        pass

                        else:
                            print("  ✗ 제목 필드 안 보임")
                            # 현재 페이지 텍스트 일부 출력
                            text = page.inner_text("body")
                            for line in text.split("\n")[:30]:
                                if line.strip():
                                    print(f"    {line.strip()[:60]}")
                    except Exception as e:
                        print(f"  ✗ 제목 필드 확인 실패: {e}")

                    break
            except Exception as e:
                print(f"  '{keyword}' 검색 실패: {e}")
    else:
        print("  검색 입력란을 찾을 수 없습니다!")

        # 카테고리 트리 탐색
        print("\n[대안] 카테고리 트리에서 찾기...")
        # 좌측 트리 노드 탐색
        tree_items = page.locator("li:visible, div[class*='tree']:visible").all()
        print(f"  트리 항목 수: {len(tree_items)}")
        for j, item in enumerate(tree_items[:20]):
            try:
                txt = item.inner_text()[:40].strip()
                if txt:
                    print(f"    [{j}] {txt}")
            except:
                pass

    save(page, "v3_99_final")

    # 최종 텍스트 저장
    try:
        text = page.inner_text("body")
        (OUT_DIR / "v3_final_text.txt").write_text(text[:8000], encoding="utf-8")
    except:
        pass

    close_session(browser)
    pw.stop()
    print("\n완료!")

if __name__ == "__main__":
    run()
