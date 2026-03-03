"""
거래처등록 양식 내부 iframe(dzEditor) DOM 캡처
- 메인 페이지 → editorView iframe → dzeditor_0 iframe 순서로 접근
- 실제 폼 필드(거래처명, 사업자번호 등)는 dzeditor_0 내부에 있음
"""

import sys
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright
from src.auth.login import login_and_get_context, close_session

OUTPUT_DIR = PROJECT_ROOT / "data" / "approval_dom_vendor"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_screenshot(page, name):
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  [스크린샷] {path.name}")


def run():
    print("=" * 60)
    print("거래처등록 양식 inner iframe DOM 캡처")
    print("=" * 60)

    pw = sync_playwright().start()
    browser, context, page = login_and_get_context(
        playwright_instance=pw, headless=False
    )
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

        # 전자결재 모듈 이동
        print("\n[1] 전자결재 모듈 이동...")
        ea_link = page.locator("span.module-link.EA").first
        if ea_link.is_visible(timeout=5000):
            ea_link.click(force=True)
        else:
            page.locator("text=전자결재").first.click(force=True)
        time.sleep(4)

        try:
            page.wait_for_selector("text=결재 HOME", timeout=10000)
            print("  결재 HOME 확인")
        except Exception:
            print("  결재 HOME 미확인, 계속")

        # 거래처등록 양식 클릭
        print("\n[2] 거래처등록 양식 클릭...")
        for keyword in ["[회계팀] 국내 거래처등록 신청서", "국내 거래처등록", "거래처등록"]:
            try:
                links = page.locator(f"text={keyword}").all()
                for link in links:
                    if link.is_visible():
                        link.click(force=True)
                        print(f"  '{keyword}' 클릭")
                        break
                else:
                    continue
                break
            except Exception:
                continue

        page.on("dialog", lambda d: d.accept())
        print("  양식 로드 대기 (15초)...")
        time.sleep(15)

        # 팝업 페이지 찾기 (formId 포함)
        form_page = None
        for p in context.pages:
            if "formId" in p.url and p != page:
                form_page = p
                break
        if form_page:
            print(f"  팝업 발견: {form_page.url[:100]}")
            form_page.set_viewport_size({"width": 1920, "height": 1080})
            form_page.bring_to_front()
            time.sleep(3)
        else:
            form_page = page
            print("  팝업 없음, 원래 페이지 사용")

        # 프레임 분석
        print("\n[3] 프레임 분석...")
        for i, frame in enumerate(form_page.frames):
            try:
                input_count = frame.locator("input").count()
                print(f"  frame[{i}] name={frame.name} inputs={input_count} url={frame.url[:80]}")
            except Exception:
                print(f"  frame[{i}] name={frame.name} url=error")

        # dzeditor_0 iframe 찾기 — 여기에 실제 거래처 양식이 있음
        editor_frame = None
        for frame in form_page.frames:
            if "dzeditor_0" in frame.name:
                editor_frame = frame
                break
            if "editorView" in frame.name:
                # editorView 안의 dzeditor_0 찾기
                for sub_frame in form_page.frames:
                    if "dzeditor_0" in sub_frame.name:
                        editor_frame = sub_frame
                        break

        if not editor_frame:
            print("  dzeditor_0 프레임 미발견!")
            # 모든 프레임에서 table이 많은 것 찾기
            for frame in form_page.frames:
                try:
                    table_count = frame.locator("table").count()
                    if table_count > 3:
                        editor_frame = frame
                        print(f"  대안: {frame.name} (tables={table_count})")
                        break
                except Exception:
                    continue

        if editor_frame:
            print(f"\n[4] dzEditor 내부 DOM 캡처 (frame: {editor_frame.name})...")

            # HTML 저장
            try:
                html = editor_frame.content()
                (OUTPUT_DIR / "editor_content.html").write_text(html, encoding="utf-8")
                print(f"  HTML 저장 ({len(html):,} bytes)")
            except Exception as e:
                print(f"  HTML 저장 실패: {e}")

            # 텍스트 저장
            try:
                text = editor_frame.locator("body").inner_text(timeout=5000)
                (OUTPUT_DIR / "editor_text.txt").write_text(text, encoding="utf-8")
                print(f"  텍스트 저장 ({len(text)} chars)")
            except Exception as e:
                print(f"  텍스트 저장 실패: {e}")

            # 테이블 구조 캡처
            try:
                tables = editor_frame.evaluate("""() => {
                    const tables = [];
                    document.querySelectorAll('table').forEach((table, ti) => {
                        const rows = [];
                        table.querySelectorAll('tr').forEach((tr, ri) => {
                            const cells = [];
                            tr.querySelectorAll('td, th').forEach((cell, ci) => {
                                cells.push({
                                    tag: cell.tagName.toLowerCase(),
                                    text: cell.textContent.trim().substring(0, 100),
                                    colspan: cell.colSpan,
                                    rowspan: cell.rowSpan,
                                    className: cell.className.substring(0, 80),
                                    bgColor: cell.style.backgroundColor || '',
                                });
                            });
                            if (cells.length > 0) rows.push({ri, cells});
                        });
                        if (rows.length > 0) {
                            tables.push({
                                ti, id: table.id,
                                className: table.className.substring(0, 100),
                                width: table.getAttribute('width') || '',
                                rows: rows.slice(0, 60),
                            });
                        }
                    });
                    return tables;
                }""")
                (OUTPUT_DIR / "editor_tables.json").write_text(
                    json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"  테이블 {len(tables)}개 저장")
                for t in tables:
                    print(f"    table[{t['ti']}] rows={len(t['rows'])} class={t['className'][:50]}")
                    for row in t['rows'][:5]:
                        labels = [c['text'][:30] for c in row['cells'] if c['text']]
                        if labels:
                            print(f"      row[{row['ri']}]: {' | '.join(labels)}")
            except Exception as e:
                print(f"  테이블 캡처 실패: {e}")

            # input/select/textarea 캡처
            try:
                inputs = editor_frame.evaluate("""() => {
                    const result = [];
                    document.querySelectorAll('input, select, textarea').forEach(el => {
                        const rect = el.getBoundingClientRect();
                        result.push({
                            tag: el.tagName.toLowerCase(),
                            id: el.id, name: el.name,
                            type: el.type || '',
                            value: el.value.substring(0, 50),
                            placeholder: el.placeholder || '',
                            className: el.className.substring(0, 80),
                            visible: el.offsetParent !== null && rect.width > 0,
                        });
                    });
                    return result;
                }""")
                (OUTPUT_DIR / "editor_inputs.json").write_text(
                    json.dumps(inputs, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                visible = [i for i in inputs if i.get("visible")]
                print(f"  입력 필드 {len(inputs)}개 (visible {len(visible)}개)")
                for v in visible:
                    print(f"    {v['tag']}[{v['type']}] id={v['id']} name={v['name']} val={v['value'][:30]}")
            except Exception as e:
                print(f"  입력 필드 캡처 실패: {e}")

            # checkbox 캡처
            try:
                checkboxes = editor_frame.evaluate("""() => {
                    const result = [];
                    document.querySelectorAll('input[type="checkbox"]').forEach(el => {
                        const label = el.parentElement?.textContent?.trim() || '';
                        result.push({
                            id: el.id, name: el.name,
                            checked: el.checked,
                            label: label.substring(0, 50),
                        });
                    });
                    return result;
                }""")
                if checkboxes:
                    (OUTPUT_DIR / "editor_checkboxes.json").write_text(
                        json.dumps(checkboxes, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    print(f"  체크박스 {len(checkboxes)}개")
                    for cb in checkboxes:
                        print(f"    [{('x' if cb['checked'] else ' ')}] {cb['label']}")
            except Exception as e:
                print(f"  체크박스 캡처 실패: {e}")
        else:
            print("  에디터 프레임을 찾을 수 없습니다!")

        # 팝업에서 스크롤 다운 스크린샷
        print("\n[5] 추가 스크린샷...")
        try:
            form_page.evaluate("window.scrollTo(0, 500)")
            time.sleep(1)
            save_screenshot(form_page, "05_scrolled_down")
        except Exception:
            pass

        # editorView iframe의 스크롤 다운
        for frame in form_page.frames:
            if "editorView" in frame.name:
                try:
                    frame.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(1)
                    save_screenshot(form_page, "06_editor_scrolled")
                except Exception:
                    pass
                break

        print("\n" + "=" * 60)
        print(f"완료! 결과: {OUTPUT_DIR}")
        print("=" * 60)

    finally:
        close_session(browser)
        pw.stop()


if __name__ == "__main__":
    run()
