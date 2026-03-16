"""
예실대비현황(상세) Phase 0 DOM 탐색 v5

v4에서 확인:
- 페이지가 완전히 렌더링됨 (스크린샷 정상)
- micro-frontend이지만 same-origin이므로 page에서 직접 접근 가능
- page.frames[0] = main frame = 실제 콘텐츠 포함
- 별도 iframe이 아님

v5: main page에서 직접 조회 + 데이터 추출
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


def main():
    print("=" * 60)
    print("예실대비현황(상세) Phase 0 DOM 탐색 v5")
    print("=" * 60)

    all_results = {}

    with sync_playwright() as pw:
        browser, context, page = login(pw)

        # API 캡처
        captured_apis = []
        def on_response(response):
            url = response.url
            if ('gw.glowseoul.co.kr' in url and
                not any(ext in url for ext in ['.css', '.js', '.png', '.jpg', '.woff', '.svg', '.txt', '.ttc', '.ico']) and
                'static/' not in url and 'mxGraph/' not in url and
                'timestamp' not in url and 'support.amaranth' not in url and
                'contentsImg' not in url):
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
                print(f"  [API] {response.request.method} {url.split('/')[-1]} → {response.status}")
        page.on("response", on_response)

        # Step 1: 예산관리 → 예실대비현황(상세)
        print("\n" + "=" * 60)
        print("Step 1: 예실대비현황(상세) 이동")
        print("=" * 60)

        page.goto("https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0020", wait_until="domcontentloaded")
        time.sleep(5)

        page.locator("text=예산장부").first.click()
        time.sleep(3)

        page.locator("text=예실대비현황(상세)").first.click()
        time.sleep(3)

        # 콘텐츠 로드 대기 - canvas가 나타날 때까지
        print("  콘텐츠 로드 대기...")
        for i in range(20):
            time.sleep(1)
            has_canvas = page.evaluate("() => !!document.querySelector('canvas')")
            input_count = page.evaluate("() => Array.from(document.querySelectorAll('input')).filter(el => el.offsetParent !== null).length")
            print(f"    {i+1}초: canvas={has_canvas} inputs={input_count}")
            if has_canvas and input_count > 5:
                print("  페이지 로드 완료!")
                break

        capture(page, "budget_actual_v5_01_loaded.png")

        # Step 2: 조회 조건 분석
        print("\n" + "=" * 60)
        print("Step 2: 조회 조건 분석")
        print("=" * 60)

        conditions = page.evaluate("""() => {
            const result = {};
            const inputs = document.querySelectorAll('input');
            result.inputs = Array.from(inputs).filter(el => el.offsetParent !== null).map(el => {
                const rect = el.getBoundingClientRect();
                // 라벨 찾기 — 이전 형제 텍스트 노드 또는 FormPanel
                let label = '';
                const parent = el.closest('[class*="FormPanel_contentsWrapper"], [class*="formItem"], tr, div');
                if (parent) {
                    const lbl = parent.querySelector('[class*="title"], [class*="Title"], label, th, [class*="FormPanel_label"]');
                    if (lbl) label = lbl.textContent.trim();
                }
                // 앞쪽 텍스트도 확인
                const prev = el.previousElementSibling;
                if (!label && prev && prev.textContent) {
                    label = prev.textContent.trim().substring(0, 30);
                }
                return {
                    placeholder: el.placeholder || '',
                    value: el.value || '',
                    type: el.type || '',
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    w: Math.round(rect.width), h: Math.round(rect.height),
                    label: label,
                };
            });
            return result;
        }""")
        all_results["conditions"] = conditions
        print(f"  조회 조건 필드:")
        for inp in conditions.get('inputs', []):
            print(f"    [{inp['type']}] ph='{inp['placeholder']}' val='{inp['value']}' label='{inp['label']}' ({inp['x']},{inp['y']})")

        # Step 3: 조회 버튼 클릭 (2026 기본값 그대로)
        print("\n" + "=" * 60)
        print("Step 3: 조회 실행 (2026)")
        print("=" * 60)

        captured_apis.clear()

        # 조회 버튼: OBTButton 타입
        try:
            # JS로 직접 버튼 찾아 클릭
            click_result = page.evaluate("""() => {
                // button 요소 중 "조회" 텍스트
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    const text = btn.textContent.trim();
                    if (text === '조회' || text.includes('조회')) {
                        btn.click();
                        return { clicked: true, cls: btn.className, text: text };
                    }
                }
                return { clicked: false };
            }""")
            print(f"  조회 클릭 결과: {click_result}")
        except Exception as e:
            print(f"  조회 버튼 JS 클릭 실패: {e}")

        # 데이터 로드 대기
        print("  데이터 로드 대기 10초...")
        time.sleep(10)

        capture(page, "budget_actual_v5_02_after_search_2026.png")

        # API 캡처 결과
        all_results["search_2026_apis"] = list(captured_apis)
        print(f"\n  조회 API: {len(captured_apis)}개")
        for api in captured_apis:
            print(f"    {api['method']} {api['url']} → {api['status']}")
            if api['post_data']:
                print(f"      POST: {api['post_data'][:300]}")
            if api['response_preview']:
                print(f"      RESP: {api['response_preview'][:500]}")

        # Step 4: RealGrid 데이터 추출
        print("\n" + "=" * 60)
        print("Step 4: RealGrid/OBTDataGrid 데이터 추출")
        print("=" * 60)

        grid_data = page.evaluate("""() => {
            const result = {};

            // 1. OBTDataGrid_grid div 찾기
            const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
            if (!gridEl) {
                result.error = 'OBTDataGrid_grid 없음';
                return result;
            }
            result.grid_id = gridEl.id;
            result.grid_class = gridEl.className;

            // 2. gridWrapper 찾기
            const wrapper = document.querySelector('[class*="OBTDataGrid_root"]');
            result.wrapper_id = wrapper ? wrapper.id : '';

            // 3. React fiber 접근 (grid div)
            const allKeys = Object.keys(gridEl);
            result.grid_div_special_keys = allKeys.filter(k => k.startsWith('__'));

            const fiberKey = allKeys.find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
            if (!fiberKey) {
                result.fiber_error = 'no fiber key';
                // 4. wrapper에서 시도
                if (wrapper) {
                    const wKeys = Object.keys(wrapper).filter(k => k.startsWith('__'));
                    result.wrapper_special_keys = wKeys;
                    const wFiberKey = wKeys.find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                    if (wFiberKey) {
                        result.wrapper_fiber = true;
                        let fiber = wrapper[wFiberKey];
                        for (let d = 0; d < 25; d++) {
                            if (!fiber) break;
                            const sn = fiber.stateNode;
                            if (sn && sn.state) {
                                const sk = Object.keys(sn.state);
                                if (sk.includes('interface') || sk.includes('grid') || sk.includes('gridView') || sk.includes('dataProvider')) {
                                    result.wrapper_state_depth = d;
                                    result.wrapper_state_keys = sk;

                                    // interface
                                    if (sn.state.interface) {
                                        const iface = sn.state.interface;
                                        try { result.row_count = iface.getRowCount(); } catch(e) { result.row_err = e.message; }
                                        try {
                                            result.columns = iface.getColumns().map(c => ({
                                                name: c.name || c.fieldName || '',
                                                header: c.header?.text || c.header || '',
                                                fieldName: c.fieldName || '',
                                                width: c.width || 0,
                                            }));
                                        } catch(e) { result.col_err = e.message; }
                                        // 데이터
                                        try {
                                            const maxR = Math.min(iface.getRowCount(), 20);
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
                                    }

                                    // gridView + dataProvider
                                    if (sn.state.gridView) {
                                        const gv = sn.state.gridView;
                                        try { result.gv_item_count = gv.getItemCount(); } catch(e) {}
                                        try {
                                            const dp = gv.getDataSource();
                                            if (dp) {
                                                result.dp_row_count = dp.getRowCount();
                                                result.dp_fields = dp.getFields().map(f => f.fieldName || f.name);
                                                // 데이터 추출
                                                const maxR = Math.min(dp.getRowCount(), 20);
                                                const rows = [];
                                                for (let r = 0; r < maxR; r++) {
                                                    try { rows.push(dp.getJsonRow(r)); } catch(e) {
                                                        const row = {};
                                                        for (const f of dp.getFields()) {
                                                            try { row[f.fieldName] = dp.getValue(r, f.fieldName); } catch(e2) {}
                                                        }
                                                        rows.push(row);
                                                    }
                                                }
                                                result.dp_data = rows;
                                            }
                                        } catch(e) { result.gv_dp_err = e.message; }
                                    }
                                    if (sn.state.dataProvider) {
                                        const dp = sn.state.dataProvider;
                                        try {
                                            result.direct_dp_rows = dp.getRowCount();
                                            result.direct_dp_fields = dp.getFields().map(f => f.fieldName || f.name);
                                        } catch(e) {}
                                    }
                                    break;
                                }
                            }
                            fiber = fiber.return;
                        }
                    }
                }
                return result;
            }

            result.fiber_key = fiberKey;
            let fiber = gridEl[fiberKey];

            // depth 순회 (최대 25)
            for (let d = 0; d < 25; d++) {
                if (!fiber) break;
                const sn = fiber.stateNode;
                if (sn && sn.state) {
                    const sk = Object.keys(sn.state);
                    result[`depth_${d}_keys`] = sk;

                    if (sk.includes('interface')) {
                        result.interface_depth = d;
                        const iface = sn.state.interface;
                        try { result.row_count = iface.getRowCount(); } catch(e) {}
                        try {
                            result.columns = iface.getColumns().map(c => ({
                                name: c.name || c.fieldName || '',
                                header: c.header?.text || c.header || '',
                                fieldName: c.fieldName || '',
                            }));
                        } catch(e) {}
                        try {
                            const maxR = Math.min(iface.getRowCount(), 20);
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
                        } catch(e) {}
                        break;
                    }
                    if (sk.includes('grid') || sk.includes('gridView') || sk.includes('dataProvider')) {
                        result.grid_state_depth = d;
                        result.grid_state_keys = sk;
                        // grid
                        if (sn.state.grid) {
                            const g = sn.state.grid;
                            try {
                                const dp = g.getDataSource();
                                result.grid_dp_rows = dp.getRowCount();
                                result.grid_dp_fields = dp.getFields().map(f => f.fieldName || f.name);
                            } catch(e) {}
                        }
                        break;
                    }
                }
                fiber = fiber.return;
            }

            return result;
        }""")

        all_results["grid_data_2026"] = grid_data
        print(f"  Grid 결과:")
        for k, v in grid_data.items():
            if isinstance(v, list) and len(v) > 3:
                print(f"    {k}: [{len(v)} items]")
                if k in ['columns', 'dp_fields', 'direct_dp_fields']:
                    print(f"      {v[:15]}")
                elif k in ['data', 'dp_data']:
                    for row in v[:3]:
                        print(f"      {json.dumps(row, ensure_ascii=False)[:200]}")
            else:
                print(f"    {k}: {v}")

        # Step 5: 2025년 조회
        print("\n" + "=" * 60)
        print("Step 5: 2025년 조회")
        print("=" * 60)

        # 기수 변경: 9 → 8, 기간: 2026-01~2026-12 → 2025-01~2025-12
        try:
            page.evaluate("""() => {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                const inputs = document.querySelectorAll('input');
                for (const inp of inputs) {
                    if (!inp.offsetParent) continue;
                    // 기수 필드 (값이 "9")
                    if (inp.value === '9') {
                        setter.call(inp, '8');
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    // 기간 시작
                    if (inp.value === '2026-01') {
                        setter.call(inp, '2025-01');
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    // 기간 끝
                    if (inp.value === '2026-12') {
                        setter.call(inp, '2025-12');
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            }""")
            print("  기수 8, 기간 2025-01~2025-12 설정 완료")
            time.sleep(1)
        except Exception as e:
            print(f"  조건 변경 실패: {e}")

        # 재조회
        captured_apis.clear()
        try:
            page.evaluate("""() => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.textContent.trim() === '조회') { btn.click(); return; }
                }
            }""")
            print("  2025 조회 클릭")
            time.sleep(10)
        except Exception as e:
            print(f"  2025 조회 실패: {e}")

        capture(page, "budget_actual_v5_03_after_search_2025.png")

        all_results["search_2025_apis"] = list(captured_apis)
        print(f"  2025 API: {len(captured_apis)}개")
        for api in captured_apis:
            print(f"    {api['method']} {api['url']} → {api['status']}")
            if api['response_preview']:
                print(f"      RESP: {api['response_preview'][:500]}")

        # 2025 데이터 추출 (같은 방법)
        grid_data_2025 = page.evaluate("""() => {
            const result = {};
            const wrapper = document.querySelector('[class*="OBTDataGrid_root"]');
            if (!wrapper) return { error: 'no wrapper' };

            const wKeys = Object.keys(wrapper).filter(k => k.startsWith('__'));
            const wFiberKey = wKeys.find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
            if (!wFiberKey) return { error: 'no fiber' };

            let fiber = wrapper[wFiberKey];
            for (let d = 0; d < 25; d++) {
                if (!fiber) break;
                const sn = fiber.stateNode;
                if (sn && sn.state) {
                    const sk = Object.keys(sn.state);
                    if (sk.includes('interface')) {
                        const iface = sn.state.interface;
                        try { result.row_count = iface.getRowCount(); } catch(e) {}
                        try {
                            result.columns = iface.getColumns().map(c => ({
                                name: c.name || c.fieldName || '',
                                header: c.header?.text || c.header || '',
                            }));
                        } catch(e) {}
                        try {
                            const maxR = Math.min(iface.getRowCount(), 50);
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
                        } catch(e) {}
                        break;
                    }
                }
                fiber = fiber.return;
            }
            return result;
        }""")
        all_results["grid_data_2025"] = grid_data_2025
        print(f"  2025 데이터: row_count={grid_data_2025.get('row_count', 'N/A')}")

        # Step 6: 최종 스크린샷 + 컬럼 구조 저장
        capture(page, "budget_actual_v5_04_final.png")

        # 전체 결과 저장
        save_json(all_results, "budget_actual_v5_exploration.json")

        print("\n" + "=" * 60)
        print("탐색 완료!")
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    main()
