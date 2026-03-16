"""
예실대비현황(상세) Phase 0 DOM 탐색 v6

v5 발견:
- 조회 버튼 클릭 성공 → "프로젝트 을(를) 반드시 입력해 주십시오." validation
- 프로젝트 필수! → 프로젝트 코드 입력 후 조회 필요
- React fiber: __reactInternalInstance (React 15), depth 3 → interface 접근 성공
- row_count=0, columns=[] → 데이터가 없음 (프로젝트 미입력 때문)

v6:
1. 프로젝트 코드 입력 (GS-25-0088 등)
2. 조회 실행
3. API 캡처 + RealGrid 데이터 추출
4. "주식회사 글로우서울" 탭 클릭 후 재확인
"""

import sys
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "config" / ".env")

from playwright.sync_api import sync_playwright

OUTPUT_DIR = PROJECT_ROOT / "data" / "gw_analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_json(data, filename):
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  저장: {path}")


def capture(target, name):
    path = OUTPUT_DIR / name
    try:
        target.screenshot(path=str(path))
        print(f"  스크린샷: {path}")
    except Exception as e:
        print(f"  스크린샷 실패({name}): {e}")


def login(pw_instance):
    from src.auth.login import login_and_get_context
    print("로그인 시도...")
    browser, context, page = login_and_get_context(
        playwright_instance=pw_instance,
        headless=False,
    )
    print(f"로그인 완료: {page.url}")
    time.sleep(2)
    for p in context.pages[1:]:
        try:
            p.close()
        except Exception:
            pass
    return browser, context, page


def extract_grid_data(page, label=""):
    """OBTDataGrid interface에서 데이터 추출"""
    print(f"\n── 그리드 데이터 추출 ({label}) ──")

    try:
        data = page.evaluate("""() => {
            const result = {};

            // OBTDataGrid_grid div → __reactInternalInstance → depth 3 → interface
            const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
            if (!gridEl) return { error: 'OBTDataGrid_grid 없음' };

            result.grid_id = gridEl.id;
            const fiberKey = Object.keys(gridEl).find(k =>
                k.startsWith('__reactInternalInstance') || k.startsWith('__reactFiber'));
            if (!fiberKey) return { error: 'no fiber key' };

            let fiber = gridEl[fiberKey];
            for (let d = 0; d < 25; d++) {
                if (!fiber) break;
                const sn = fiber.stateNode;
                if (sn && sn.state && sn.state.interface) {
                    const iface = sn.state.interface;
                    result.depth = d;

                    try { result.row_count = iface.getRowCount(); } catch(e) { result.row_err = e.message; }

                    try {
                        const cols = iface.getColumns();
                        result.columns = cols.map(c => ({
                            name: c.name || c.fieldName || '',
                            header: c.header?.text || (typeof c.header === 'string' ? c.header : '') || '',
                            fieldName: c.fieldName || '',
                            width: c.width || 0,
                            visible: c.visible !== false,
                        }));
                    } catch(e) { result.col_err = e.message; }

                    // 전체 데이터 (최대 200행)
                    try {
                        const maxR = Math.min(iface.getRowCount(), 200);
                        const cols = iface.getColumns();
                        const rows = [];
                        for (let r = 0; r < maxR; r++) {
                            const row = {};
                            for (const col of cols) {
                                const fn = col.name || col.fieldName;
                                try { row[fn] = iface.getValue(r, fn); } catch(e) {}
                            }
                            rows.push(row);
                        }
                        result.data = rows;
                    } catch(e) { result.data_err = e.message; }

                    break;
                }
                fiber = fiber.return;
            }

            return result;
        }""")

        print(f"  row_count: {data.get('row_count', 'N/A')}")
        if data.get('columns'):
            print(f"  컬럼 ({len(data['columns'])}개): {[(c['name'], c['header']) for c in data['columns'][:20]]}")
        if data.get('data'):
            print(f"  데이터 ({len(data['data'])}행):")
            for row in data['data'][:5]:
                print(f"    {json.dumps(row, ensure_ascii=False)[:200]}")
        if data.get('error'):
            print(f"  오류: {data['error']}")
        return data
    except Exception as e:
        print(f"  추출 실패: {e}")
        return {"error": str(e)}


def main():
    print("=" * 60)
    print("예실대비현황(상세) Phase 0 DOM 탐색 v6")
    print("=" * 60)

    all_results = {}

    with sync_playwright() as pw:
        browser, context, page = login(pw)

        # API 캡처
        captured_apis = []
        def on_response(response):
            url = response.url
            if ('gw.glowseoul.co.kr' in url and
                any(kw in url for kw in ['/bp/', '/bn/', '/BN/']) and
                '/static/' not in url and '/mxGraph/' not in url and
                not any(ext in url for ext in ['.css', '.js', '.png', '.jpg', '.woff', '.svg', '.txt', '.ttc', '.ico'])):
                try:
                    ct = response.headers.get('content-type', '') or ''
                    body = response.json() if 'json' in ct else None
                except Exception:
                    body = None
                captured_apis.append({
                    "url": url,
                    "status": response.status,
                    "method": response.request.method,
                    "post_data": response.request.post_data,
                    "response_preview": str(body)[:5000] if body else None,
                })
                print(f"  [API] {response.request.method} ...{url.split('/')[-1]} → {response.status}")
        page.on("response", on_response)

        # Step 1: 예산관리 → 예실대비현황(상세) 이동
        print("\n" + "=" * 60)
        print("Step 1: 예실대비현황(상세) 이동")
        print("=" * 60)

        page.goto("https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0020", wait_until="domcontentloaded")
        time.sleep(5)

        page.locator("text=예산장부").first.click()
        time.sleep(3)

        page.locator("text=예실대비현황(상세)").first.click()
        time.sleep(3)

        # canvas 나타날 때까지 대기
        for i in range(15):
            time.sleep(1)
            has_canvas = page.evaluate("() => !!document.querySelector('canvas')")
            if has_canvas:
                print(f"  콘텐츠 로드 완료 ({i+1}초)")
                break

        capture(page, "budget_actual_v6_01_loaded.png")

        # Step 2: 프로젝트 코드 입력
        print("\n" + "=" * 60)
        print("Step 2: 프로젝트 코드 입력")
        print("=" * 60)

        # "사업코드도움" placeholder 가진 input에 프로젝트 코드 입력
        try:
            proj_input = page.locator("input[placeholder='사업코드도움']").first
            if proj_input.is_visible(timeout=3000):
                proj_input.click()
                time.sleep(0.5)
                proj_input.fill("GS-25-0088")
                time.sleep(0.5)
                proj_input.press("Enter")
                time.sleep(2)
                print("  프로젝트 'GS-25-0088' 입력 + Enter")
            else:
                print("  사업코드도움 input 안보임")
        except Exception as e:
            print(f"  프로젝트 입력 실패: {e}")

        capture(page, "budget_actual_v6_02_project_entered.png")

        # Step 3: 조회 (2026년 기본)
        print("\n" + "=" * 60)
        print("Step 3: 조회 실행 (2026)")
        print("=" * 60)

        captured_apis.clear()

        try:
            page.evaluate("""() => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.textContent.trim() === '조회') { btn.click(); return 'clicked'; }
                }
                return 'not found';
            }""")
            print("  조회 클릭")
        except Exception as e:
            print(f"  조회 클릭 실패: {e}")

        # 데이터 로드 대기 (최대 15초, 데이터 나타날 때까지)
        print("  데이터 로드 대기...")
        for i in range(15):
            time.sleep(1)
            row_count = page.evaluate("""() => {
                const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
                if (!gridEl) return -1;
                const fk = Object.keys(gridEl).find(k => k.startsWith('__reactInternalInstance') || k.startsWith('__reactFiber'));
                if (!fk) return -2;
                let fiber = gridEl[fk];
                for (let d = 0; d < 25; d++) {
                    if (!fiber) break;
                    if (fiber.stateNode?.state?.interface) {
                        try { return fiber.stateNode.state.interface.getRowCount(); } catch(e) { return -3; }
                    }
                    fiber = fiber.return;
                }
                return -4;
            }""")
            print(f"    {i+1}초: row_count={row_count}")
            if row_count > 0:
                print("  데이터 로드 감지!")
                break

        capture(page, "budget_actual_v6_03_after_search_2026.png")

        # API 결과
        all_results["search_2026_apis"] = list(captured_apis)
        print(f"\n  2026 조회 API: {len(captured_apis)}개")
        for api in captured_apis:
            print(f"    {api['method']} {api['url']} → {api['status']}")
            if api['post_data']:
                print(f"      POST: {api['post_data'][:300]}")
            if api['response_preview']:
                print(f"      RESP: {api['response_preview'][:500]}")

        # 그리드 데이터 추출
        grid_2026 = extract_grid_data(page, "2026")
        all_results["grid_data_2026"] = grid_2026

        # Step 4: "주식회사 글로우서울" 탭 클릭
        print("\n" + "=" * 60)
        print("Step 4: '주식회사 글로우서울' 탭")
        print("=" * 60)

        try:
            tab = page.locator("text=주식회사 글로우서울").first
            if tab.is_visible(timeout=3000):
                # 탭인지 확인 (button role)
                tab.click()
                time.sleep(3)
                print("  '주식회사 글로우서울' 탭 클릭")
                capture(page, "budget_actual_v6_04_glowseoul_tab.png")

                # 이 탭에서 데이터 추출
                grid_glow = extract_grid_data(page, "글로우서울 탭")
                all_results["grid_glowseoul_tab"] = grid_glow
        except Exception as e:
            print(f"  탭 클릭 실패: {e}")

        # Step 5: 2025년 조회
        print("\n" + "=" * 60)
        print("Step 5: 2025년 조회 (기수 8)")
        print("=" * 60)

        # "전체회계단위" 탭으로 돌아가기
        try:
            page.locator("text=전체회계단위").first.click()
            time.sleep(2)
        except Exception:
            pass

        # 기수 select 변경 (기수 드롭다운)
        try:
            # 기수 필드: 9가 선택된 select 또는 OBTDropDown
            # 스크린샷에서 기수 옆에 "9" select 보임 → OBTNumberTextBox일 수 있음
            # 기수 input(value=9 아닌 숫자) 대신 OBT DropDown을 사용
            # 먼저 기수 select 요소 확인
            kisu_info = page.evaluate("""() => {
                // "기수" 라벨 근처의 select 또는 input 찾기
                const allEls = document.querySelectorAll('[class*="DropDown"], [class*="dropdown"], select');
                const result = [];
                for (const el of allEls) {
                    if (el.offsetParent !== null) {
                        result.push({
                            tag: el.tagName,
                            cls: (el.className || '').substring(0, 200),
                            text: (el.textContent || '').trim().substring(0, 50),
                            value: el.value || '',
                            x: Math.round(el.getBoundingClientRect().x),
                            y: Math.round(el.getBoundingClientRect().y),
                        });
                    }
                }
                return result;
            }""")
            print(f"  드롭다운 요소: {len(kisu_info)}개")
            for dd in kisu_info:
                print(f"    [{dd['tag']}] '{dd['text']}' val='{dd['value']}' ({dd['x']},{dd['y']})")
        except Exception as e:
            print(f"  기수 정보 실패: {e}")

        # 기수 변경 시도 — 기수 select 클릭 후 8 선택
        try:
            # 기수 select는 value="9"인 select 요소
            kisu_select = page.locator("select").first
            if kisu_select.is_visible(timeout=2000):
                kisu_select.select_option("8")
                print("  기수 select → 8 변경")
            else:
                # OBTDropDownList 패턴 (커스텀 드롭다운)
                # 기수 "9" 가 보이는 영역 클릭
                # 스크린샷에서 기수=9는 (700, 188) 근처
                page.click("text=9", position={"x": 0, "y": 0})  # 잘못된 접근일 수 있음
        except Exception:
            pass

        # 기간도 변경: 직접 input fill 시도
        try:
            # 2026-01 입력란 찾아서 클릭 후 변경
            date_inputs = page.locator("input[class*='DatePicker']").all()
            for di in date_inputs:
                val = di.get_attribute("value") or ""
                if "2026-01" in val:
                    di.triple_click()
                    di.fill("2025-01")
                    di.press("Tab")
                    print("  시작일 → 2025-01")
                elif "2026-12" in val:
                    di.triple_click()
                    di.fill("2025-12")
                    di.press("Tab")
                    print("  종료일 → 2025-12")
        except Exception:
            # DatePicker 클래스 안맞으면 value로 찾기
            try:
                page.evaluate("""() => {
                    const inputs = document.querySelectorAll('input');
                    for (const inp of inputs) {
                        if (inp.value === '2026-01' && inp.offsetParent) {
                            inp.focus();
                            inp.select();
                        }
                    }
                }""")
                page.keyboard.type("2025-01")
                page.keyboard.press("Tab")
                time.sleep(0.5)

                page.evaluate("""() => {
                    const inputs = document.querySelectorAll('input');
                    for (const inp of inputs) {
                        if (inp.value === '2026-12' && inp.offsetParent) {
                            inp.focus();
                            inp.select();
                        }
                    }
                }""")
                page.keyboard.type("2025-12")
                page.keyboard.press("Tab")
                print("  기간 2025-01~2025-12 설정 (keyboard)")
            except Exception as e:
                print(f"  기간 변경 실패: {e}")

        time.sleep(1)
        capture(page, "budget_actual_v6_05_before_2025_search.png")

        # 2025 조회
        captured_apis.clear()
        try:
            page.evaluate("""() => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.textContent.trim() === '조회') { btn.click(); return; }
                }
            }""")
            print("  2025 조회 클릭")

            for i in range(15):
                time.sleep(1)
                rc = page.evaluate("""() => {
                    const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
                    if (!gridEl) return -1;
                    const fk = Object.keys(gridEl).find(k => k.startsWith('__reactInternalInstance') || k.startsWith('__reactFiber'));
                    if (!fk) return -2;
                    let fiber = gridEl[fk];
                    for (let d = 0; d < 25; d++) {
                        if (!fiber) break;
                        if (fiber.stateNode?.state?.interface) {
                            try { return fiber.stateNode.state.interface.getRowCount(); } catch(e) { return -3; }
                        }
                        fiber = fiber.return;
                    }
                    return -4;
                }""")
                print(f"    {i+1}초: row_count={rc}")
                if rc > 0:
                    break
        except Exception as e:
            print(f"  2025 조회 실패: {e}")

        capture(page, "budget_actual_v6_06_after_search_2025.png")

        all_results["search_2025_apis"] = list(captured_apis)
        print(f"\n  2025 조회 API: {len(captured_apis)}개")
        for api in captured_apis:
            print(f"    {api['method']} {api['url']} → {api['status']}")
            if api['post_data']:
                print(f"      POST: {api['post_data'][:300]}")
            if api['response_preview']:
                print(f"      RESP: {api['response_preview'][:500]}")

        grid_2025 = extract_grid_data(page, "2025")
        all_results["grid_data_2025"] = grid_2025

        # 최종 저장
        save_json(all_results, "budget_actual_v6_exploration.json")

        print("\n" + "=" * 60)
        print("탐색 완료!")
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    main()
