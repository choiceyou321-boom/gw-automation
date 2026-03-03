"""
Phase 0: 나머지 6개 양식 formId 탐색 + DOM 구조 문서화
- 증빙발행, 선급금요청, 선급금정산, 연장근무, 외근신청, 사내추천비
- GW 결재작성 양식 목록 API로 formId 조회
- 각 양식 팝업/인라인 열기 → 프레임/입력 구조 캡처
"""
import sys
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "config" / ".env")

OUTPUT_DIR = PROJECT_ROOT / "data" / "approval_dom_remaining"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 탐색 대상 6개 양식
FORMS_TO_EXPLORE = [
    {"key": "증빙발행",   "search": "증빙발행",    "display": "[회계팀] 증빙발행 신청서"},
    {"key": "선급금요청", "search": "선급금 요청서","display": "[본사]선급금 요청서"},
    {"key": "선급금정산", "search": "선급금 정산서","display": "[본사]선급금 정산서"},
    {"key": "연장근무",   "search": "연장근무신청서","display": "연장근무신청서"},
    {"key": "외근신청",   "search": "외근신청서",   "display": "외근신청서(당일)"},
    {"key": "사내추천비", "search": "사내추천비",   "display": "사내추천비 자금 요청서"},
]


def save_screenshot(page, name):
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  [스크린샷] {path.name}")


def dump_inputs(ctx, name):
    """모든 input/select/textarea 정보 추출"""
    info = ctx.evaluate("""() => {
        const result = [];
        document.querySelectorAll('input, select, textarea').forEach(el => {
            const rect = el.getBoundingClientRect();
            result.push({
                tag: el.tagName.toLowerCase(),
                id: el.id,
                name: el.name,
                type: el.type || '',
                placeholder: el.placeholder || '',
                disabled: el.disabled,
                visible: el.offsetParent !== null && rect.width > 0 && rect.height > 0,
                value: el.value.substring(0, 50),
                className: el.className.substring(0, 80),
            });
        });
        return result;
    }""")
    path = OUTPUT_DIR / f"{name}_inputs.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    visible = [i for i in info if i.get("visible")]
    print(f"  [필드] {len(info)}개 (visible {len(visible)}개)")
    for v in visible:
        print(f"    {v['tag']}[{v['type']}] id={v['id']} name={v['name']} ph={v['placeholder'][:40]}")
    return info


def dump_buttons(ctx, name):
    """보이는 버튼/액션 추출"""
    info = ctx.evaluate("""() => {
        const result = [];
        document.querySelectorAll('button, [role="button"], div.topBtn, a[class*="btn"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (el.offsetParent !== null && rect.width > 0) {
                result.push({
                    text: el.textContent.trim().substring(0, 50),
                    tag: el.tagName.toLowerCase(),
                    id: el.id,
                    className: el.className.substring(0, 80),
                });
            }
        });
        return result;
    }""")
    path = OUTPUT_DIR / f"{name}_buttons.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    for b in info:
        if b['text']:
            print(f"    버튼: \"{b['text'][:40]}\"")
    return info


def dump_table_structure(ctx, name):
    """테이블 구조 (라벨↔필드 매핑용)"""
    info = ctx.evaluate("""() => {
        const tables = [];
        document.querySelectorAll('table').forEach((table, ti) => {
            if (table.offsetParent === null) return;
            const rows = [];
            table.querySelectorAll('tr').forEach((tr, ri) => {
                const cells = [];
                tr.querySelectorAll('td, th').forEach(cell => {
                    const inputs = [];
                    cell.querySelectorAll('input, select, textarea').forEach(inp => {
                        inputs.push({
                            tag: inp.tagName.toLowerCase(),
                            name: inp.name, id: inp.id,
                            type: inp.type || '',
                            placeholder: inp.placeholder || '',
                        });
                    });
                    cells.push({
                        tag: cell.tagName.toLowerCase(),
                        text: cell.textContent.trim().substring(0, 80),
                        inputs: inputs,
                    });
                });
                if (cells.length > 0) rows.push(cells);
            });
            if (rows.length > 0):
                tables.push({ti: ti, className: table.className[:80], rows: rows[:30]});
        });
        return tables;
    }""")
    path = OUTPUT_DIR / f"{name}_tables.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"  [테이블] {len(info)}개")
    return info


def get_frames_info(page):
    """프레임 목록 + input 수 반환"""
    frames = []
    for i, frame in enumerate(page.frames):
        try:
            cnt = frame.locator("input").count()
            frames.append({"index": i, "name": frame.name, "url": frame.url[:150], "input_count": cnt})
        except Exception:
            frames.append({"index": i, "name": "?", "url": "error", "input_count": -1})
    return frames


def explore_form(page, context, form_info: dict):
    """단일 양식 탐색"""
    key = form_info["key"]
    search_kw = form_info["search"]
    display = form_info["display"]
    result = {
        "key": key,
        "display": display,
        "form_id": None,
        "open_type": None,  # "inline" or "popup"
        "frames": [],
        "input_count": 0,
        "status": "not_found",
    }

    print(f"\n{'='*50}")
    print(f"탐색: {display} ({search_kw})")
    print(f"{'='*50}")

    # 결재작성 페이지로 이동
    write_url = "https://gw.glowseoul.co.kr/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA6000"
    page.goto(write_url, wait_until="domcontentloaded", timeout=20000)
    try:
        page.wait_for_selector("input[placeholder*='카테고리'], input[placeholder*='양식명'], input[type='text']:visible", timeout=8000)
    except Exception:
        page.wait_for_timeout(3000)

    save_screenshot(page, f"{key}_01_write_page")

    # 양식 검색
    search_input = None
    for sel in [
        "input[placeholder*='카테고리 또는 양식명']",
        "input[placeholder*='양식']",
        "input[placeholder*='검색']",
        "input[type='text']:visible",
    ]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                search_input = el
                break
        except Exception:
            continue

    if not search_input:
        print(f"  [실패] 검색 입력란 미발견")
        result["status"] = "search_input_not_found"
        return result

    search_input.click()
    search_input.fill(search_kw)
    search_input.press("Enter")
    page.wait_for_timeout(2000)

    save_screenshot(page, f"{key}_02_search_result")

    # 검색 결과에서 양식 선택
    form_found = False
    for keyword in [display, search_kw, key]:
        try:
            links = page.locator(f"text={keyword}").all()
            for link in links:
                if link.is_visible(timeout=1000):
                    link.click(force=True)
                    form_found = True
                    print(f"  양식 선택: '{keyword}'")
                    break
            if form_found:
                break
        except Exception:
            continue

    if not form_found:
        print(f"  [실패] 검색 결과에서 양식 미발견")
        result["status"] = "form_not_found_in_search"
        return result

    # URL에서 formId 추출 시도
    page.wait_for_timeout(1000)
    current_url = page.url
    import re
    m = re.search(r"formId=(\d+)", current_url)
    if m:
        result["form_id"] = m.group(1)
        print(f"  formId (URL): {result['form_id']}")

    # Enter 눌러 팝업 또는 인라인 열기
    pages_before = set(id(p) for p in context.pages)
    page.keyboard.press("Enter")

    # 팝업 감지 (3초 대기)
    popup_page = None
    for _ in range(10):
        page.wait_for_timeout(300)
        for p in context.pages:
            if id(p) not in pages_before and "popup" in p.url:
                popup_page = p
                break
        if popup_page:
            break

    if popup_page:
        result["open_type"] = "popup"
        print(f"  열기 방식: 팝업")
        popup_page.wait_for_load_state("domcontentloaded", timeout=15000)
        popup_page.wait_for_timeout(3000)
        popup_page.set_viewport_size({"width": 1920, "height": 1080})

        # URL에서 formId 추출
        popup_url = popup_page.url
        m = re.search(r"formId=(\d+)", popup_url)
        if m:
            result["form_id"] = m.group(1)
            print(f"  formId (팝업 URL): {result['form_id']}")

        save_screenshot(popup_page, f"{key}_03_form")

        # 프레임 분석
        frames = get_frames_info(popup_page)
        result["frames"] = frames
        print(f"  프레임 {len(frames)}개:")
        for fi in frames:
            print(f"    frame[{fi['index']}] name={fi['name']} inputs={fi['input_count']}")

        # 입력 필드 분석 (가장 많은 input을 가진 프레임 우선)
        target = popup_page
        max_inputs = popup_page.locator("input").count()
        for frame in popup_page.frames:
            try:
                cnt = frame.locator("input").count()
                if cnt > max_inputs:
                    max_inputs = cnt
                    target = frame
            except Exception:
                pass

        result["input_count"] = max_inputs
        dump_inputs(target, key)
        dump_buttons(popup_page, key)

        popup_page.close()

    else:
        # 인라인 양식 (팝업 없음)
        result["open_type"] = "inline"
        print(f"  열기 방식: 인라인")
        page.wait_for_timeout(3000)

        # URL에서 formId 추출
        current_url = page.url
        m = re.search(r"formId=(\d+)", current_url)
        if m:
            result["form_id"] = m.group(1)
            print(f"  formId (인라인 URL): {result['form_id']}")

        save_screenshot(page, f"{key}_03_form")

        frames = get_frames_info(page)
        result["frames"] = frames

        # 입력 분석
        input_count = page.locator("input:visible").count()
        result["input_count"] = input_count
        dump_inputs(page, key)
        dump_buttons(page, key)

    result["status"] = "explored"
    print(f"  완료: formId={result['form_id']}, open={result['open_type']}, inputs={result['input_count']}")
    return result


def navigate_to_approval_home(page, context):
    """전자결재 HOME 이동"""
    page.goto("https://gw.glowseoul.co.kr/#/", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(2000)

    # 잡다한 팝업 닫기
    for p in context.pages:
        if p != page and "popup" in p.url:
            try:
                p.close()
            except Exception:
                pass

    # 전자결재 모듈 클릭
    try:
        ea = page.locator("span.module-link.EA").first
        if ea.is_visible(timeout=5000):
            ea.click(force=True)
            print("  전자결재 모듈 클릭")
    except Exception:
        try:
            page.locator("text=전자결재").first.click(force=True)
        except Exception:
            pass

    try:
        page.wait_for_selector("text=결재 HOME", timeout=10000)
        print("  결재 HOME 도달")
    except Exception:
        print("  [경고] 결재 HOME 미확인, 계속")


def main():
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password

    print("=" * 60)
    print("Phase 0: 나머지 6개 양식 DOM 탐색")
    print("=" * 60)

    gw_id = "tgjeon"
    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        print("[오류] 비밀번호를 찾을 수 없습니다.")
        return

    pw_inst = sync_playwright().start()
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw_inst,
            headless=False,  # DOM 탐색은 headful 모드
            user_id=gw_id,
            user_pw=gw_pw,
        )
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.on("dialog", lambda d: d.accept())

        print("\n[로그인 완료]")

        # 전자결재 HOME으로 이동
        navigate_to_approval_home(page, context)

        # 6개 양식 순차 탐색
        all_results = []
        for form_info in FORMS_TO_EXPLORE:
            try:
                result = explore_form(page, context, form_info)
                all_results.append(result)
                # 각 양식 후 HOME으로 복귀
                navigate_to_approval_home(page, context)
            except Exception as e:
                print(f"  [오류] {form_info['key']}: {e}")
                all_results.append({
                    "key": form_info["key"],
                    "display": form_info["display"],
                    "form_id": None,
                    "status": f"error: {str(e)[:100]}",
                })
                # 오류 시 HOME 복귀 재시도
                try:
                    navigate_to_approval_home(page, context)
                except Exception:
                    pass

        # 결과 저장
        results_path = OUTPUT_DIR / "form_ids_discovered.json"
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)

        print("\n" + "=" * 60)
        print("탐색 결과 요약")
        print("=" * 60)
        for r in all_results:
            fid = r.get("form_id", "미발견")
            status = r.get("status", "?")
            open_type = r.get("open_type", "?")
            print(f"  {r['key']:10s} | formId={fid:6s} | 열기={open_type:8s} | {status}")

        print(f"\n결과 파일: {OUTPUT_DIR}")

        close_session(browser)
    finally:
        pw_inst.stop()


if __name__ == "__main__":
    main()
