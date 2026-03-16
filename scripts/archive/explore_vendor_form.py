"""
Phase 0: 국내 거래처등록 신청서 양식 DOM 탐색
- 결재 HOME → 추천양식 "[회계팀] 국내 거래처등록 신청서" 클릭
- 양식 폼 구조 캡쳐 (스크린샷 + HTML + 필드 정보)
- explore_approval_dom_v2.py 패턴 참고
"""

import sys
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.auth.login import login_and_get_context, close_session, GW_URL

OUTPUT_DIR = PROJECT_ROOT / "data" / "approval_dom_vendor"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_screenshot(page, name):
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  [스크린샷] {path.name}")


def dump_all_inputs(ctx, name):
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
                className: el.className.substring(0, 120),
                rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
            });
        });
        return result;
    }""")
    path = OUTPUT_DIR / f"{name}_inputs.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    visible = [i for i in info if i.get("visible")]
    print(f"  [필드] {path.name} (총 {len(info)}개, visible {len(visible)}개)")
    for v in visible:
        print(f"    - {v['tag']}[{v['type']}] id={v['id']} name={v['name']} ph={v['placeholder']} val={v['value']}")
    return info


def dump_buttons(ctx, name):
    """보이는 버튼들만 추출"""
    info = ctx.evaluate("""() => {
        const result = [];
        document.querySelectorAll('button, [role="button"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                result.push({
                    text: el.textContent.trim().substring(0, 50),
                    id: el.id,
                    className: el.className.substring(0, 120),
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                });
            }
        });
        return result;
    }""")
    path = OUTPUT_DIR / f"{name}_buttons.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"  [버튼] {path.name} ({len(info)}개 visible)")
    for b in info:
        if b['text']:
            print(f"    - \"{b['text']}\" class={b['className'][:60]}")
    return info


def dump_table_structure(ctx, name):
    """테이블 구조 분석"""
    info = ctx.evaluate("""() => {
        const tables = [];
        document.querySelectorAll('table').forEach((table, ti) => {
            if (table.offsetParent === null) return;
            const rows = [];
            table.querySelectorAll('tr').forEach((tr, ri) => {
                const cells = [];
                tr.querySelectorAll('td, th').forEach((cell, ci) => {
                    const inputs = [];
                    cell.querySelectorAll('input, select, textarea').forEach(inp => {
                        inputs.push({
                            tag: inp.tagName.toLowerCase(),
                            name: inp.name, id: inp.id,
                            type: inp.type || '', visible: inp.offsetParent !== null,
                            placeholder: inp.placeholder || '',
                        });
                    });
                    cells.push({
                        tag: cell.tagName.toLowerCase(),
                        text: cell.textContent.trim().substring(0, 80),
                        colspan: cell.colSpan, rowspan: cell.rowSpan,
                        inputs: inputs,
                    });
                });
                if (cells.length > 0) rows.push({ri: ri, cells: cells});
            });
            if (rows.length > 0) {
                tables.push({ti: ti, id: table.id, className: table.className.substring(0, 100), rows: rows.slice(0, 50)});
            }
        });
        return tables;
    }""")
    path = OUTPUT_DIR / f"{name}_tables.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"  [테이블] {path.name} ({len(info)}개 visible 테이블)")
    return info


def dump_frames_info(page):
    """iframe 정보"""
    frames = []
    for i, frame in enumerate(page.frames):
        try:
            input_count = frame.locator("input").count()
            url = frame.url
        except Exception:
            input_count = -1
            url = "error"
        frames.append({"index": i, "name": frame.name, "url": url[:200], "input_count": input_count})
    path = OUTPUT_DIR / f"frames_info.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(frames, f, ensure_ascii=False, indent=2)
    print(f"  [프레임] {len(frames)}개")
    for fi in frames:
        print(f"    - frame[{fi['index']}] name={fi['name']} inputs={fi['input_count']} url={fi['url'][:80]}")
    return frames


def save_html(ctx, name, max_size=3_000_000):
    """HTML 저장"""
    try:
        html = ctx.content()
        if len(html) > max_size:
            print(f"  [HTML] {name} 너무 큼 ({len(html):,} bytes), 스킵")
            return
        path = OUTPUT_DIR / f"{name}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  [HTML] {path.name} ({len(html):,} bytes)")
    except Exception as e:
        print(f"  [HTML] 저장 실패: {e}")


def main():
    print("=" * 60)
    print("Phase 0: 국내 거래처등록 신청서 DOM 탐색")
    print("=" * 60)

    # 1. 로그인
    print("\n[1/7] 로그인...")
    browser, context, page = login_and_get_context(headless=False)
    page.set_viewport_size({"width": 1920, "height": 1080})

    try:
        # 팝업 닫기
        time.sleep(3)
        for p in context.pages:
            if "popup" in p.url and p != page:
                try:
                    p.close()
                except Exception:
                    pass

        # 2. 전자결재 모듈로 이동
        print("\n[2/7] 전자결재 모듈 이동...")

        ea_link = page.locator("span.module-link.EA").first
        if ea_link.is_visible(timeout=5000):
            ea_link.click(force=True)
            print("  span.module-link.EA 클릭")
        else:
            page.locator("text=전자결재").first.click(force=True)
            print("  text=전자결재 클릭")

        time.sleep(4)
        save_screenshot(page, "01_approval_home")

        try:
            page.wait_for_selector("text=결재 HOME", timeout=10000)
            print("  결재 HOME 확인!")
        except Exception:
            print("  [경고] 결재 HOME 텍스트 미발견, 계속 진행")

        # 3. 추천양식에서 "[회계팀] 국내 거래처등록 신청서" 클릭
        print("\n[3/7] 추천양식에서 거래처등록 클릭...")

        form_clicked = False
        # 키워드 목록 — 양식 정확한 이름 → 부분 매칭 순
        for keyword in [
            "[회계팀] 국내 거래처등록 신청서",
            "국내 거래처등록",
            "거래처등록 신청서",
            "거래처등록",
        ]:
            try:
                links = page.locator(f"text={keyword}").all()
                for link in links:
                    if link.is_visible():
                        link.click(force=True)
                        form_clicked = True
                        print(f"  '{keyword}' 클릭 성공")
                        break
                if form_clicked:
                    break
            except Exception:
                continue

        if not form_clicked:
            # 대안: 추천양식 영역 탐색
            print("  직접 텍스트 검색 실패, 추천양식 영역 탐색...")
            icons = page.locator(".recommend-form-item, [class*='recommend']").all()
            for icon in icons:
                try:
                    txt = icon.text_content()
                    if "거래처" in txt:
                        icon.click(force=True)
                        form_clicked = True
                        print(f"  추천양식 아이콘 클릭: {txt[:30]}")
                        break
                except Exception:
                    continue

        if not form_clicked:
            # 최종 대안: 결재작성 → 양식 검색
            print("  추천양식에서 미발견. 결재작성 페이지에서 검색 시도...")
            try:
                # 결재작성 메뉴 클릭
                write_link = page.locator("text=결재작성").first
                if write_link.is_visible(timeout=3000):
                    write_link.click(force=True)
                    time.sleep(3)
                    # 양식 검색
                    search_input = page.locator("input[placeholder*='양식']").first
                    if not search_input.is_visible(timeout=3000):
                        search_input = page.locator("input[type='text']:visible").first
                    search_input.fill("거래처등록")
                    search_input.press("Enter")
                    time.sleep(3)
                    # 검색 결과에서 클릭
                    result = page.locator("text=거래처등록").first
                    if result.is_visible(timeout=3000):
                        result.click(force=True)
                        form_clicked = True
                        print("  검색으로 거래처등록 양식 선택")
            except Exception as e:
                print(f"  검색 실패: {e}")

        if not form_clicked:
            print("  [실패] 거래처등록 양식을 찾지 못했습니다!")
            save_screenshot(page, "03_failed")
            return

        # 다이얼로그 자동 처리
        page.on("dialog", lambda d: d.accept())

        # 양식 로드 대기
        print("  양식 로드 대기 (12초)...")
        time.sleep(12)
        save_screenshot(page, "02_form_loading")

        # 4. 현재 URL 확인 + 탭/팝업 처리
        print(f"\n[4/7] 현재 URL: {page.url}")

        all_pages = context.pages
        print(f"  열린 페이지 수: {len(all_pages)}")
        for i, p in enumerate(all_pages):
            print(f"    page[{i}]: {p.url[:100]}")

        # 결재 양식 페이지 찾기
        form_page = None
        for p in all_pages:
            if "APB1020" in p.url or "eap" in p.url:
                form_page = p
                break
        if form_page and form_page != page:
            page = form_page
            print(f"  결재 양식 페이지로 전환: {page.url[:100]}")
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.bring_to_front()
            time.sleep(3)
        else:
            # 팝업 닫기 후 원래 페이지 사용
            for p in all_pages[1:]:
                if "popup" in p.url:
                    try:
                        p.close()
                    except Exception:
                        pass
            page = all_pages[0]
            print(f"  원래 페이지 사용: {page.url[:100]}")

        save_screenshot(page, "03_form_page")

        # 5. 프레임 분석
        print("\n[5/7] 프레임 분석...")
        frames = dump_frames_info(page)

        form_frame = None
        for fi, frame in enumerate(page.frames):
            try:
                input_count = frame.locator("input").count()
                if input_count > 5:
                    form_frame = frame
                    print(f"  → 양식 프레임 후보: frame[{fi}] (input {input_count}개)")
            except Exception:
                continue

        # 6. 메인 페이지 + 양식 프레임 상세 분석
        print("\n[6/7] DOM 상세 분석...")

        print("\n  --- 메인 페이지 ---")
        dump_all_inputs(page, "main_page")
        dump_buttons(page, "main_page")
        dump_table_structure(page, "main_page")

        if form_frame:
            print(f"\n  --- 양식 프레임 ---")
            dump_all_inputs(form_frame, "form_frame")
            dump_buttons(form_frame, "form_frame")
            dump_table_structure(form_frame, "form_frame")
            save_html(form_frame, "form_frame")
        else:
            print("  양식 프레임 미발견, 메인 페이지 HTML 저장")
            save_html(page, "main_page")

        # 7. 액션 버튼 + 결재선
        print("\n[7/7] 액션 버튼 + 결재선...")

        action_info = page.evaluate("""() => {
            const result = [];
            const keywords = ['보관', '상신', '임시저장', '미리보기', '결재선', '취소', '닫기', '결재상신'];
            document.querySelectorAll('button, [role="button"], a').forEach(el => {
                const text = el.textContent.trim();
                if (keywords.some(k => text.includes(k)) && el.offsetParent !== null) {
                    const rect = el.getBoundingClientRect();
                    result.push({
                        text: text.substring(0, 50),
                        tag: el.tagName.toLowerCase(),
                        id: el.id,
                        className: el.className.substring(0, 100),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return result;
        }""")
        path = OUTPUT_DIR / "action_buttons.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(action_info, f, ensure_ascii=False, indent=2)
        print(f"  [액션 버튼] {len(action_info)}개")
        for a in action_info:
            print(f"    - \"{a['text']}\" ({a['tag']}) at ({a['rect']['x']},{a['rect']['y']})")

        # 결재선 영역
        approval_line = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('[class*="sign"], [class*="approval"], [class*="agree"], [class*="eapLine"]').forEach(el => {
                if (el.offsetParent !== null) {
                    const rect = el.getBoundingClientRect();
                    result.push({
                        tag: el.tagName.toLowerCase(),
                        text: el.textContent.trim().substring(0, 80),
                        className: el.className.substring(0, 100),
                        id: el.id,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return result;
        }""")
        path = OUTPUT_DIR / "approval_line.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(approval_line, f, ensure_ascii=False, indent=2)
        print(f"  [결재선] {len(approval_line)}개")
        for a in approval_line:
            if a['text']:
                print(f"    - \"{a['text'][:40]}\" class={a['className'][:50]}")

        # 최종 스크린샷
        save_screenshot(page, "04_final")

        print("\n" + "=" * 60)
        print(f"탐색 완료! 결과: {OUTPUT_DIR}")
        print("=" * 60)

    finally:
        close_session(browser)


if __name__ == "__main__":
    main()
