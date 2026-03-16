"""
계산서내역 팝업 DOM 탐색 스크립트 (Phase 0)

목적:
- 지출결의서 폼에서 "계산서내역" 버튼 클릭
- 열리는 팝업/패널의 DOM 구조 캡처
- 버튼, 입력 필드, 테이블, iframe 구조 저장
- 이 데이터를 바탕으로 _select_invoice_from_popup() 정밀 구현에 활용

결과물:
- data/approval_dom_invoice/*.json
- data/approval_dom_invoice/*.png
- data/approval_dom_invoice/*.html
"""

import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "config" / ".env")

from playwright.sync_api import sync_playwright

OUTPUT_DIR = PROJECT_ROOT / "data" / "approval_dom_invoice"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_json(data, filename):
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  저장: {filename}")
    return path


def capture(page_or_frame, name):
    path = OUTPUT_DIR / name
    try:
        page_or_frame.screenshot(path=str(path))
        print(f"  스크린샷: {name}")
    except Exception as e:
        print(f"  스크린샷 실패({name}): {e}")


def dump_elements(target, selector, label, max_count=50):
    """요소 정보 추출"""
    try:
        elements = target.locator(selector).all()
        result = []
        for el in elements[:max_count]:
            try:
                result.append({
                    "text": (el.inner_text() or "").strip()[:100],
                    "id": el.get_attribute("id") or "",
                    "className": (el.get_attribute("class") or "")[:120],
                    "placeholder": el.get_attribute("placeholder") or "",
                    "name": el.get_attribute("name") or "",
                    "type": el.get_attribute("type") or "",
                    "value": el.get_attribute("value") or "",
                    "maxlength": el.get_attribute("maxlength") or "",
                    "rect": el.bounding_box() or {},
                    "visible": el.is_visible(timeout=500),
                })
            except Exception:
                continue
        print(f"  {label}: {len(result)}개")
        return result
    except Exception as e:
        print(f"  {label} 추출 실패: {e}")
        return []


def find_form_frame(page):
    """지출결의서 폼 iframe 탐색"""
    frames = page.frames
    print(f"\n프레임 수: {len(frames)}")
    for i, f in enumerate(frames):
        try:
            print(f"  [{i}] {f.url[:80]} (name={f.name})")
        except Exception:
            pass

    # APB1020 또는 eap 포함 프레임
    for f in frames:
        try:
            if any(k in f.url for k in ["APB1020", "editorView", "eap"]):
                print(f"  -> 양식 프레임: {f.url[:80]}")
                return f
        except Exception:
            pass

    # 두 번째 프레임 폴백
    if len(frames) > 1:
        return frames[1]
    return page


def explore_popup_structure(page, context, form_frame):
    """팝업 열린 후 전체 구조 탐색"""
    print("\n" + "=" * 50)
    print("팝업 구조 탐색")
    print("=" * 50)

    result = {
        "pages": [],
        "form_frame_changes": {},
        "popup_page": {},
        "iframe_structures": [],
    }

    # 1. 페이지 목록 확인
    pages = context.pages
    print(f"\n페이지 수: {len(pages)}")
    for i, p in enumerate(pages):
        try:
            url = p.url or ""
            print(f"  Page[{i}]: {url[:80]}")
            result["pages"].append({"index": i, "url": url})
        except Exception:
            pass

    # 2. 새 팝업 페이지 (2번째 이후)
    popup_target = None
    if len(pages) > 1:
        popup_target = pages[-1]
        print(f"\n새 팝업 페이지: {popup_target.url[:80]}")
        try:
            popup_target.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass

        capture(popup_target, "03_popup_page.png")

        # 팝업 내 전체 DOM
        try:
            html = popup_target.content()
            html_path = OUTPUT_DIR / "popup_full.html"
            html_path.write_text(html, encoding="utf-8")
            print(f"  팝업 HTML 저장: popup_full.html ({len(html)}bytes)")
        except Exception as e:
            print(f"  HTML 저장 실패: {e}")

        # 팝업 버튼/입력 탐색
        p_buttons = dump_elements(popup_target, "button, div.OBTButton_root__1g4ov", "팝업 버튼")
        p_inputs = dump_elements(popup_target, "input, select, textarea", "팝업 입력")
        save_json(p_buttons, "popup_buttons.json")
        save_json(p_inputs, "popup_inputs.json")

        # 팝업 테이블 행
        try:
            rows = popup_target.locator("table tbody tr, tr[class*='row'], tr[class*='grid']").all()
            row_data = []
            for i, row in enumerate(rows[:30]):
                try:
                    txt = (row.inner_text() or "").strip().replace("\n", " | ")[:150]
                    cls = (row.get_attribute("class") or "")[:60]
                    row_data.append({"index": i, "text": txt, "class": cls, "rect": row.bounding_box()})
                    if txt:
                        print(f"  row[{i}]: {txt}")
                except Exception:
                    pass
            save_json(row_data, "popup_rows.json")
        except Exception as e:
            print(f"  테이블 행 탐색 실패: {e}")

        # 팝업 내 모든 iframe
        for fi, frame in enumerate(popup_target.frames):
            try:
                url = frame.url[:80]
                print(f"\n  팝업 Frame[{fi}]: {url}")
                f_buttons = dump_elements(frame, "button, div.OBTButton_root__1g4ov", f"  Frame{fi} 버튼")
                f_inputs = dump_elements(frame, "input, select", f"  Frame{fi} 입력")
                save_json(f_buttons, f"popup_frame{fi}_buttons.json")
                save_json(f_inputs, f"popup_frame{fi}_inputs.json")

                # 날짜 입력 필드 상세
                date_fields = frame.locator(
                    "input[class*='DatePickerRebuild'], input[class*='datepicker'], "
                    "input[maxlength='8'], input[placeholder*='날짜'], input[placeholder*='date']"
                ).all()
                print(f"    날짜 필드: {len(date_fields)}개")
                for di, dinp in enumerate(date_fields):
                    try:
                        info = {
                            "value": dinp.get_attribute("value") or "",
                            "placeholder": dinp.get_attribute("placeholder") or "",
                            "class": (dinp.get_attribute("class") or "")[:80],
                            "rect": dinp.bounding_box(),
                        }
                        print(f"      date[{di}]: {info}")
                    except Exception:
                        pass

                # 그리드 행
                grid_rows = frame.locator("table tbody tr").all()
                print(f"    테이블 행: {len(grid_rows)}개")
                for ri, row in enumerate(grid_rows[:10]):
                    try:
                        txt = (row.inner_text() or "").replace("\n", " | ").strip()[:120]
                        if txt:
                            print(f"      row[{ri}]: {txt}")
                    except Exception:
                        pass

                # iframe HTML
                try:
                    frame_html = frame.content()
                    frame_path = OUTPUT_DIR / f"popup_frame{fi}.html"
                    frame_path.write_text(frame_html, encoding="utf-8")
                    print(f"    HTML 저장: popup_frame{fi}.html")
                except Exception:
                    pass

            except Exception as e:
                print(f"  Frame[{fi}] 탐색 실패: {e}")

        result["popup_page"] = {"url": popup_target.url, "page_count": len(pages)}

    else:
        # 별도 팝업 없음 → 현재 페이지 모달 탐색
        print("\n별도 팝업 없음 → 현재 페이지 레이어/모달 탐색")
        capture(page, "03_page_after_click.png")

        # 현재 페이지 전체 HTML 저장
        try:
            html = page.content()
            (OUTPUT_DIR / "page_after_click.html").write_text(html, encoding="utf-8")
            print(f"  페이지 HTML 저장 ({len(html)}bytes)")
        except Exception as e:
            print(f"  HTML 저장 실패: {e}")

        # form_frame 변화 탐색
        print("\nform_frame 클릭 후 상태:")
        ff_buttons = dump_elements(form_frame, "button, div.OBTButton_root__1g4ov", "form_frame 버튼")
        ff_inputs = dump_elements(form_frame, "input, select", "form_frame 입력")
        save_json(ff_buttons, "after_form_buttons.json")
        save_json(ff_inputs, "after_form_inputs.json")

        # form_frame HTML
        try:
            ff_html = form_frame.content()
            (OUTPUT_DIR / "form_frame_after.html").write_text(ff_html, encoding="utf-8")
            print(f"  form_frame HTML 저장 ({len(ff_html)}bytes)")
        except Exception as e:
            print(f"  form_frame HTML 저장 실패: {e}")

        # form_frame 자식 프레임
        for fi, child in enumerate(form_frame.child_frames):
            try:
                print(f"\n  자식 Frame[{fi}]: {child.url[:80]}")
                c_buttons = dump_elements(child, "button, div.OBTButton_root__1g4ov", f"  child{fi} 버튼")
                c_inputs = dump_elements(child, "input, select", f"  child{fi} 입력")
                save_json(c_buttons, f"child_frame{fi}_buttons.json")
                save_json(c_inputs, f"child_frame{fi}_inputs.json")

                # 날짜 필드
                date_fields = child.locator(
                    "input[class*='DatePickerRebuild'], input[maxlength='8']"
                ).all()
                print(f"    날짜 필드: {len(date_fields)}개")

                # 그리드 행
                rows = child.locator("table tbody tr").all()
                print(f"    테이블 행: {len(rows)}개")
                for ri, row in enumerate(rows[:5]):
                    try:
                        txt = (row.inner_text() or "").replace("\n", " | ").strip()[:100]
                        if txt:
                            print(f"      row[{ri}]: {txt}")
                    except Exception:
                        pass
            except Exception as e:
                print(f"  자식 Frame[{fi}] 실패: {e}")

        # RealGrid 캔버스 탐색 (canvas 기반 그리드)
        try:
            canvases = page.locator("canvas").all()
            print(f"\n  canvas 요소: {len(canvases)}개")
            for ci, canvas in enumerate(canvases):
                try:
                    box = canvas.bounding_box()
                    print(f"    canvas[{ci}]: {box}")
                except Exception:
                    pass
        except Exception:
            pass

    save_json(result, "explore_summary.json")


def navigate_to_form(page, context):
    """지출결의서 폼으로 이동"""
    from src.auth.login import _do_login, _check_logged_in
    import os

    gw_url = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")
    uid = os.environ.get("GW_USER_ID", "tgjeon")
    upw = os.environ.get("GW_USER_PW", "")

    # 로그인
    print("로그인 중...")
    _do_login(page, login_id=uid, login_pw=upw)
    print("  로그인 완료")

    # 전자결재 메뉴 이동
    print("전자결재 메뉴 이동...")
    try:
        page.goto(f"{gw_url}/#/HP/APB1020", wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(3000)

    # 추천양식 "[프로젝트]지출결의서" 클릭
    opened = False
    for sel in [
        "text=[프로젝트]지출결의서",
        "text=지출결의서",
        "a[href*='formId=255']",
        "[title*='지출결의서']",
    ]:
        try:
            link = page.locator(sel).first
            if link.is_visible(timeout=3000):
                link.click()
                page.wait_for_timeout(3000)
                opened = True
                print(f"  양식 클릭: {sel}")
                break
        except Exception:
            continue

    if not opened:
        # 직접 URL 이동
        url = (
            f"{gw_url}/#/HP/APB1020/APB1020"
            "?pageCode=UBA1020&formDTp=APB1020_00001&formId=255"
        )
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        print("  직접 URL 이동")

    # iframe 로드 대기
    try:
        page.wait_for_selector("iframe", timeout=15000)
        page.wait_for_timeout(2000)
    except Exception:
        pass

    capture(page, "01_form_loaded.png")
    print("  폼 로드 완료")


def click_invoice_button(page, form_frame):
    """계산서내역 버튼 클릭"""
    print("\n계산서내역 버튼 클릭 중...")
    clicked = False

    # form_frame 내 selector 시도
    for sel in [
        "button:has-text('계산서내역')",
        "div.OBTButton_root__1g4ov:has-text('계산서내역')",
        "*:has-text('계산서내역')",
    ]:
        for target in [form_frame, page]:
            try:
                btn = target.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click(force=True)
                    clicked = True
                    print(f"  클릭 성공: {sel} (target={'form_frame' if target is form_frame else 'page'})")
                    break
            except Exception:
                continue
        if clicked:
            break

    if not clicked:
        # 좌표 클릭 폴백 (form_frame_buttons.json 기준 x=1476, y=373)
        print("  좌표 클릭 (1476, 373)")
        page.mouse.click(1476, 373)
        clicked = True

    # 팝업 열림 대기
    print("  팝업 열림 대기 (3초)...")
    page.wait_for_timeout(3000)
    capture(page, "02_after_click.png")
    return clicked


def main():
    print("=" * 60)
    print("계산서내역 팝업 DOM 탐색 (Phase 0)")
    print("=" * 60)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            slow_mo=50,
            args=["--window-size=1920,1080"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        page.on("dialog", lambda d: d.accept())

        try:
            # 1. 로그인 + 폼 이동
            navigate_to_form(page, context)

            # 2. 양식 iframe 찾기
            form_frame = find_form_frame(page)

            # 3. 클릭 전 버튼 목록 저장
            print("\n클릭 전 버튼 목록:")
            before_buttons = dump_elements(
                form_frame, "button, div.OBTButton_root__1g4ov", "버튼"
            )
            save_json(before_buttons, "before_buttons.json")

            # 4. 계산서내역 버튼 클릭
            click_invoice_button(page, form_frame)

            # 5. 팝업 DOM 탐색
            explore_popup_structure(page, context, form_frame)

            print("\n\n탐색 완료!")
            print(f"결과 저장 위치: {OUTPUT_DIR}")
            print("브라우저를 확인하고 Enter를 누르면 종료...")
            input()

        except Exception as e:
            print(f"\n오류: {e}")
            import traceback
            traceback.print_exc()
            capture(page, "error.png")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
