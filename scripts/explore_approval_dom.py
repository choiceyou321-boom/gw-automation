"""
Phase 0: 전자결재 양식 DOM 탐색 스크립트
- 결재작성 페이지 진입 → 지출결의서 양식 열기
- 각 단계 스크린샷 + HTML 덤프 + 필드 정보 저장
"""
import sys
import json
import time
from pathlib import Path

# 프로젝트 루트 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.auth.login import login_and_get_context, close_session, GW_URL

OUTPUT_DIR = PROJECT_ROOT / "data" / "approval_dom"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_screenshot(page, name):
    """스크린샷 저장"""
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  [스크린샷] {path}")


def save_html(page_or_frame, name):
    """HTML 덤프 저장"""
    path = OUTPUT_DIR / f"{name}.html"
    html = page_or_frame.content()
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  [HTML] {path} ({len(html):,} bytes)")


def dump_all_inputs(page_or_frame, name):
    """모든 input/select/textarea 요소 정보 추출"""
    info = page_or_frame.evaluate("""() => {
        const result = [];
        // input
        document.querySelectorAll('input').forEach(el => {
            result.push({
                tag: 'input',
                id: el.id,
                name: el.name,
                type: el.type,
                placeholder: el.placeholder,
                disabled: el.disabled,
                visible: el.offsetParent !== null,
                value: el.value,
                className: el.className.substring(0, 100),
            });
        });
        // select
        document.querySelectorAll('select').forEach(el => {
            const opts = Array.from(el.options).map(o => ({value: o.value, text: o.text}));
            result.push({
                tag: 'select',
                id: el.id,
                name: el.name,
                disabled: el.disabled,
                visible: el.offsetParent !== null,
                options: opts.slice(0, 20),
                className: el.className.substring(0, 100),
            });
        });
        // textarea
        document.querySelectorAll('textarea').forEach(el => {
            result.push({
                tag: 'textarea',
                id: el.id,
                name: el.name,
                placeholder: el.placeholder,
                disabled: el.disabled,
                visible: el.offsetParent !== null,
                className: el.className.substring(0, 100),
            });
        });
        return result;
    }""")
    path = OUTPUT_DIR / f"{name}_inputs.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    visible_count = sum(1 for i in info if i.get("visible"))
    print(f"  [필드] {path} (총 {len(info)}개, visible {visible_count}개)")
    return info


def dump_buttons(page_or_frame, name):
    """버튼 요소 정보 추출"""
    info = page_or_frame.evaluate("""() => {
        const result = [];
        document.querySelectorAll('button, [role="button"], a.btn, input[type="button"], input[type="submit"]').forEach(el => {
            result.push({
                tag: el.tagName.toLowerCase(),
                text: el.textContent.trim().substring(0, 50),
                id: el.id,
                className: el.className.substring(0, 100),
                visible: el.offsetParent !== null,
                disabled: el.disabled,
                type: el.type || '',
            });
        });
        return result;
    }""")
    path = OUTPUT_DIR / f"{name}_buttons.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"  [버튼] {path} ({len(info)}개)")
    return info


def dump_frames_info(page):
    """iframe 정보 추출"""
    frames = []
    for i, frame in enumerate(page.frames):
        try:
            input_count = frame.locator("input").count()
            url = frame.url
        except Exception:
            input_count = -1
            url = "error"
        frames.append({
            "index": i,
            "name": frame.name,
            "url": url[:200],
            "input_count": input_count,
        })
    path = OUTPUT_DIR / f"frames_info.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(frames, f, ensure_ascii=False, indent=2)
    print(f"  [프레임] {path} ({len(frames)}개)")
    return frames


def dump_table_structure(page_or_frame, name):
    """테이블 구조 분석 (양식 내 테이블)"""
    info = page_or_frame.evaluate("""() => {
        const tables = [];
        document.querySelectorAll('table').forEach((table, ti) => {
            const rows = [];
            table.querySelectorAll('tr').forEach((tr, ri) => {
                const cells = [];
                tr.querySelectorAll('td, th').forEach((cell, ci) => {
                    const inputs = [];
                    cell.querySelectorAll('input, select, textarea').forEach(inp => {
                        inputs.push({
                            tag: inp.tagName.toLowerCase(),
                            name: inp.name,
                            id: inp.id,
                            type: inp.type || '',
                            visible: inp.offsetParent !== null,
                        });
                    });
                    cells.push({
                        text: cell.textContent.trim().substring(0, 50),
                        colspan: cell.colSpan,
                        rowspan: cell.rowSpan,
                        inputs: inputs,
                    });
                });
                if (cells.length > 0) {
                    rows.push({rowIndex: ri, cells: cells});
                }
            });
            if (rows.length > 0) {
                tables.push({
                    tableIndex: ti,
                    className: table.className.substring(0, 100),
                    id: table.id,
                    rowCount: rows.length,
                    rows: rows.slice(0, 30),  // 최대 30행
                });
            }
        });
        return tables;
    }""")
    path = OUTPUT_DIR / f"{name}_tables.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"  [테이블] {path} ({len(info)}개 테이블)")
    return info


def dump_text_elements(page_or_frame, name):
    """주요 텍스트 요소 추출 (메뉴, 탭, 라벨 등)"""
    info = page_or_frame.evaluate("""() => {
        const result = [];
        // 주요 텍스트 요소 수집
        document.querySelectorAll('a, button, span, label, th, td, h1, h2, h3, h4, li').forEach(el => {
            const text = el.textContent.trim();
            if (text && text.length > 0 && text.length < 50 && el.offsetParent !== null) {
                result.push({
                    tag: el.tagName.toLowerCase(),
                    text: text,
                    id: el.id,
                    className: (el.className || '').substring(0, 80),
                    href: el.href || '',
                });
            }
        });
        // 중복 제거
        const seen = new Set();
        return result.filter(item => {
            const key = item.tag + ':' + item.text;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        }).slice(0, 200);
    }""")
    path = OUTPUT_DIR / f"{name}_texts.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"  [텍스트] {path} ({len(info)}개)")
    return info


def main():
    print("=" * 60)
    print("Phase 0: 전자결재 DOM 탐색 시작")
    print("=" * 60)

    # 1. 로그인
    print("\n[1/6] 로그인...")
    browser, context, page = login_and_get_context(headless=False)
    page.set_viewport_size({"width": 1920, "height": 1080})
    save_screenshot(page, "01_after_login")

    try:
        # 2. 전자결재 메뉴 진입
        print("\n[2/6] 전자결재 메뉴 진입...")

        # 전자결재 메뉴 찾기 (여러 방법 시도)
        approval_found = False

        # 방법 1: 텍스트로 찾기
        for selector in ["text=전자결재", "a:has-text('전자결재')", "span:has-text('전자결재')"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=3000):
                    el.click(force=True)
                    approval_found = True
                    print(f"  전자결재 메뉴 클릭: {selector}")
                    break
            except Exception:
                continue

        # 방법 2: URL 직접 이동
        if not approval_found:
            for url in [f"{GW_URL}/#/approval", f"{GW_URL}/#/eap", f"{GW_URL}/#/app/approval"]:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(3000)
                    # 결재 관련 텍스트가 있으면 성공
                    if page.locator("text=결재").first.is_visible(timeout=3000):
                        approval_found = True
                        print(f"  URL 직접 이동: {url}")
                        break
                except Exception:
                    continue

        time.sleep(3)
        save_screenshot(page, "02_approval_home")
        dump_text_elements(page, "02_approval_home")
        dump_buttons(page, "02_approval_home")

        if not approval_found:
            print("  [경고] 전자결재 메뉴를 찾지 못했습니다. 현재 페이지에서 계속합니다.")

        # 3. 결재작성 페이지 이동
        print("\n[3/6] 결재작성 페이지...")
        write_found = False
        for selector in ["text=결재작성", "a:has-text('결재작성')", "span:has-text('결재작성')", "button:has-text('결재작성')"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=3000):
                    el.click(force=True)
                    write_found = True
                    print(f"  결재작성 클릭: {selector}")
                    break
            except Exception:
                continue

        time.sleep(3)
        save_screenshot(page, "03_approval_write")
        dump_text_elements(page, "03_approval_write")
        dump_buttons(page, "03_approval_write")
        dump_all_inputs(page, "03_approval_write")

        # 4. 양식 검색 (지출결의서)
        print("\n[4/6] 양식 검색: 지출결의서...")

        # 검색 입력창 찾기
        search_box = None
        for selector in [
            "input[placeholder*='양식']",
            "input[placeholder*='검색']",
            "input[type='search']",
            "input[type='text']:visible",
        ]:
            try:
                candidates = page.locator(selector).all()
                for inp in candidates:
                    if inp.is_visible():
                        ph = inp.get_attribute("placeholder") or ""
                        # 사이드바 관련 제외
                        if any(skip in ph for skip in ["담당", "사원"]):
                            continue
                        search_box = inp
                        print(f"  검색 박스 발견: {selector} (placeholder: '{ph}')")
                        break
                if search_box:
                    break
            except Exception:
                continue

        if search_box:
            search_box.click(force=True)
            search_box.fill("지출결의서")
            page.keyboard.press("Enter")
            time.sleep(4)
            save_screenshot(page, "04_search_result")
            dump_text_elements(page, "04_search_result")

            # 검색 결과에서 지출결의서 클릭
            form_found = False
            for keyword in ["지출결의서", "[프로젝트]지출결의서"]:
                try:
                    links = page.locator(f"text={keyword}").all()
                    for link in links:
                        if link.is_visible():
                            link.click(force=True)
                            form_found = True
                            print(f"  양식 선택: '{keyword}'")
                            break
                    if form_found:
                        break
                except Exception:
                    continue

            if form_found:
                # 다이얼로그 자동 처리
                page.on("dialog", lambda d: d.accept())
                print("  양식 로드 대기 (10초)...")
                time.sleep(10)
            else:
                print("  [경고] 지출결의서 양식을 찾지 못했습니다.")
        else:
            print("  [경고] 검색 박스를 찾지 못했습니다.")

        # 5. 양식 페이지 분석
        print("\n[5/6] 양식 페이지 분석...")
        save_screenshot(page, "05_form_loaded")

        # 메인 페이지 분석
        dump_all_inputs(page, "05_main_page")
        dump_buttons(page, "05_main_page")
        dump_table_structure(page, "05_main_page")

        # iframe 분석
        frames = dump_frames_info(page)

        # 각 프레임 분석
        for fi, frame in enumerate(page.frames):
            try:
                input_count = frame.locator("input").count()
                if input_count > 3:
                    fname = f"05_frame_{fi}"
                    print(f"\n  [프레임 {fi}] input {input_count}개 - 상세 분석")
                    dump_all_inputs(frame, fname)
                    dump_table_structure(frame, fname)
                    dump_buttons(frame, fname)

                    # 프레임 HTML 저장 (크기 제한)
                    try:
                        html = frame.content()
                        if len(html) < 5_000_000:  # 5MB 이하만
                            save_html(frame, fname)
                    except Exception:
                        pass
            except Exception as e:
                print(f"  [프레임 {fi}] 분석 실패: {e}")

        # 6. 결재선 영역 분석
        print("\n[6/6] 결재선 + 상단 버튼 영역 분석...")
        save_screenshot(page, "06_final")

        # 상단 결재 액션 버튼들 (보관, 상신 등) 분석
        action_buttons = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('button, [role="button"]').forEach(el => {
                const text = el.textContent.trim();
                if (['보관', '상신', '임시저장', '미리보기', '결재선'].some(k => text.includes(k))) {
                    result.push({
                        text: text.substring(0, 50),
                        id: el.id,
                        className: el.className.substring(0, 100),
                        tagName: el.tagName,
                        visible: el.offsetParent !== null,
                    });
                }
            });
            return result;
        }""")
        path = OUTPUT_DIR / "06_action_buttons.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(action_buttons, f, ensure_ascii=False, indent=2)
        print(f"  [액션 버튼] {path} ({len(action_buttons)}개)")

        # 결재선 영역 분석
        approval_line = page.evaluate("""() => {
            const result = [];
            // 결재선 관련 요소 탐색
            document.querySelectorAll('[class*="approval"], [class*="sign"], [class*="agree"]').forEach(el => {
                result.push({
                    tag: el.tagName.toLowerCase(),
                    text: el.textContent.trim().substring(0, 100),
                    className: el.className.substring(0, 100),
                    id: el.id,
                });
            });
            return result.slice(0, 30);
        }""")
        path = OUTPUT_DIR / "06_approval_line.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(approval_line, f, ensure_ascii=False, indent=2)
        print(f"  [결재선] {path} ({len(approval_line)}개)")

        print("\n" + "=" * 60)
        print(f"탐색 완료! 결과: {OUTPUT_DIR}")
        print("=" * 60)

        # 사용자가 직접 확인할 수 있도록 브라우저 열어둠
        print("\n브라우저를 열어두었습니다. 확인 후 Enter를 누르면 종료합니다.")
        input()

    finally:
        close_session(browser)


if __name__ == "__main__":
    main()
