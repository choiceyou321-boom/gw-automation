"""
예실대비현황(상세) v7 — 금액 데이터 완전 추출

v6 발견:
- OBTDataGrid interface.getColumns() → 8개 (그룹 컬럼)
- projectHeader, 0 컬럼에 금액 데이터 미포함 → 서브컬럼 접근 필요
- 실제 grid에 보이는 컬럼: 예산액, 집행액, 잔액, 대비(%)

v7:
- RealGrid DataProvider 직접 접근 (getFields, getJsonRow)
- ColumnGroup의 서브컬럼 접근
- depth 3~20까지 다양한 state 키 탐색
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
    print("예실대비현황(상세) v7 — 금액 데이터 완전 추출")
    print("=" * 60)

    all_results = {}

    with sync_playwright() as pw:
        browser, context, page = login(pw)

        # API 캡처
        captured_apis = []
        def on_response(response):
            url = response.url
            if ('gw.glowseoul.co.kr' in url and '/bp/' in url and
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
                    "response_body": body,
                })
                print(f"  [API] {response.request.method} ...{url.split('/')[-1]} → {response.status}")
        page.on("response", on_response)

        # Step 1: 예실대비현황(상세) 이동
        page.goto("https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0020", wait_until="domcontentloaded")
        time.sleep(5)
        page.locator("text=예산장부").first.click()
        time.sleep(3)
        page.locator("text=예실대비현황(상세)").first.click()
        time.sleep(3)

        # canvas 대기
        for i in range(15):
            time.sleep(1)
            if page.evaluate("() => !!document.querySelector('canvas')"):
                break

        # Step 2: 프로젝트 입력 + 조회
        print("\n" + "=" * 60)
        print("Step 2: 프로젝트 입력 + 조회")
        print("=" * 60)

        proj_input = page.locator("input[placeholder='사업코드도움']").first
        proj_input.click()
        time.sleep(0.5)
        proj_input.fill("GS-25-0088")
        proj_input.press("Enter")
        time.sleep(2)

        # 조회
        captured_apis.clear()
        page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '조회') { btn.click(); return; }
            }
        }""")
        print("  조회 클릭")

        # 데이터 로드 대기
        for i in range(15):
            time.sleep(1)
            rc = page.evaluate("""() => {
                const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
                if (!gridEl) return -1;
                const fk = Object.keys(gridEl).find(k => k.startsWith('__reactInternalInstance'));
                if (!fk) return -2;
                let fiber = gridEl[fk];
                for (let d = 0; d < 10; d++) {
                    if (!fiber) break;
                    if (fiber.stateNode?.state?.interface) {
                        try { return fiber.stateNode.state.interface.getRowCount(); } catch(e) { return -3; }
                    }
                    fiber = fiber.return;
                }
                return -4;
            }""")
            if rc > 0:
                print(f"  데이터 로드 ({rc}행, {i+1}초)")
                break

        capture(page, "budget_actual_v7_01_loaded.png")

        # API 결과 저장
        all_results["search_apis"] = []
        for api in captured_apis:
            api_copy = dict(api)
            if api_copy.get('response_body'):
                api_copy['response_preview'] = str(api_copy['response_body'])[:3000]
            all_results["search_apis"].append(api_copy)
            print(f"  API: {api['method']} {api['url']} → {api['status']}")
            if api.get('post_data'):
                print(f"    POST: {api['post_data'][:300]}")

        # Step 3: 심층 데이터 추출
        print("\n" + "=" * 60)
        print("Step 3: 심층 데이터 추출")
        print("=" * 60)

        deep_data = page.evaluate("""() => {
            const result = {};

            const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
            if (!gridEl) return { error: 'no grid' };

            const fk = Object.keys(gridEl).find(k => k.startsWith('__reactInternalInstance'));
            if (!fk) return { error: 'no fiber' };

            let fiber = gridEl[fk];

            // depth별 state 키 전부 수집
            for (let d = 0; d < 25; d++) {
                if (!fiber) break;
                const sn = fiber.stateNode;
                if (sn) {
                    const snKeys = Object.keys(sn).filter(k => !k.startsWith('_') && k !== 'props' && k !== 'refs' && k !== 'context');
                    if (sn.state) {
                        const stateKeys = Object.keys(sn.state);
                        if (stateKeys.length > 0) {
                            result[`d${d}_stateKeys`] = stateKeys;

                            // interface 접근
                            if (sn.state.interface) {
                                const iface = sn.state.interface;
                                result.interface_depth = d;

                                // getColumns 깊이 분석 — 그룹 컬럼의 서브컬럼
                                try {
                                    const cols = iface.getColumns();
                                    const colDetail = cols.map(c => {
                                        const info = {
                                            name: c.name || '',
                                            fieldName: c.fieldName || '',
                                            header: c.header?.text || (typeof c.header === 'string' ? c.header : JSON.stringify(c.header || '')),
                                            type: c.type || '',
                                            width: c.width || 0,
                                        };
                                        // 그룹 컬럼 → columns 속성
                                        if (c.columns) {
                                            info.subColumns = c.columns.map(sc => ({
                                                name: sc.name || '',
                                                fieldName: sc.fieldName || '',
                                                header: sc.header?.text || (typeof sc.header === 'string' ? sc.header : ''),
                                                width: sc.width || 0,
                                            }));
                                        }
                                        // children 속성
                                        if (c.children) {
                                            info.children = c.children.map(sc => ({
                                                name: sc.name || '',
                                                fieldName: sc.fieldName || '',
                                                header: sc.header?.text || '',
                                            }));
                                        }
                                        return info;
                                    });
                                    result.columns_detail = colDetail;
                                } catch(e) { result.col_detail_err = e.message; }

                                // getColumnNames (RealGrid 메서드)
                                try {
                                    if (iface.getColumnNames) {
                                        result.column_names = iface.getColumnNames();
                                    }
                                } catch(e) {}

                                // getColumnCount
                                try {
                                    if (iface.getColumnCount) {
                                        result.column_count = iface.getColumnCount();
                                    }
                                } catch(e) {}

                                // getDataColumns (flat 컬럼)
                                try {
                                    if (iface.getDataColumns) {
                                        const dataCols = iface.getDataColumns();
                                        result.data_columns = dataCols.map(c => ({
                                            name: c.name || '',
                                            fieldName: c.fieldName || '',
                                            header: c.header?.text || '',
                                        }));
                                    }
                                } catch(e) {}

                                // getValue로 첫 행 전체 데이터 (모든 가능한 컬럼명)
                                try {
                                    const cols = iface.getColumns();
                                    const row0 = {};
                                    // 기본 컬럼
                                    for (const c of cols) {
                                        const fn = c.name || c.fieldName;
                                        try { row0[fn] = iface.getValue(0, fn); } catch(e) {}
                                        // 서브 컬럼도 시도
                                        if (c.columns) {
                                            for (const sc of c.columns) {
                                                const sfn = sc.name || sc.fieldName;
                                                try { row0[sfn] = iface.getValue(0, sfn); } catch(e) {}
                                            }
                                        }
                                    }
                                    result.row0_basic = row0;
                                } catch(e) {}

                                // 숫자 컬럼명으로도 시도 (0_0, 0_1 등)
                                try {
                                    const numericCols = {};
                                    const possibleNames = [];
                                    // 전체프로젝트 서브: projectHeader_bgtAmt, projectHeader_excAmt 등
                                    const suffixes = ['bgtAmt', 'excAmt', 'remAmt', 'ratio', 'bgtAmt2'];
                                    for (const prefix of ['projectHeader', '0', '1', '2', '3']) {
                                        for (const suffix of suffixes) {
                                            possibleNames.push(`${prefix}_${suffix}`);
                                            possibleNames.push(`${prefix}.${suffix}`);
                                        }
                                    }
                                    // 단순 숫자도 시도
                                    for (let i = 0; i < 20; i++) {
                                        possibleNames.push(String(i));
                                    }
                                    for (const name of possibleNames) {
                                        try {
                                            const val = iface.getValue(0, name);
                                            if (val !== undefined && val !== null) {
                                                numericCols[name] = val;
                                            }
                                        } catch(e) {}
                                    }
                                    result.numeric_col_values = numericCols;
                                } catch(e) {}

                                // interface 메서드 목록
                                try {
                                    const proto = Object.getPrototypeOf(iface);
                                    result.interface_methods = Object.getOwnPropertyNames(proto).filter(m => !m.startsWith('_')).slice(0, 60);
                                } catch(e) {}
                            }

                            // grid (RealGrid GridView 인스턴스)
                            if (sn.state.grid) {
                                result.grid_depth = d;
                                const g = sn.state.grid;

                                // GridView 메서드
                                try {
                                    const proto = Object.getPrototypeOf(g);
                                    result.gridview_methods = Object.getOwnPropertyNames(proto).filter(m => !m.startsWith('_')).slice(0, 80);
                                } catch(e) {}

                                // getDataSource → DataProvider
                                try {
                                    const dp = g.getDataSource();
                                    if (dp) {
                                        result.dp_found = true;
                                        try { result.dp_row_count = dp.getRowCount(); } catch(e) {}
                                        try {
                                            const fields = dp.getFields();
                                            result.dp_fields = fields.map(f => ({
                                                fieldName: f.fieldName || f.name || '',
                                                dataType: f.dataType || '',
                                            }));
                                        } catch(e) { result.dp_fields_err = e.message; }

                                        // getJsonRow으로 데이터 추출
                                        try {
                                            const maxR = Math.min(dp.getRowCount(), 10);
                                            const rows = [];
                                            for (let r = 0; r < maxR; r++) {
                                                try { rows.push(dp.getJsonRow(r)); } catch(e) {
                                                    // 개별 필드로
                                                    const row = {};
                                                    const fields = dp.getFields();
                                                    for (const f of fields) {
                                                        try { row[f.fieldName] = dp.getValue(r, f.fieldName); } catch(e2) {}
                                                    }
                                                    rows.push(row);
                                                }
                                            }
                                            result.dp_sample_data = rows;
                                        } catch(e) { result.dp_data_err = e.message; }
                                    }
                                } catch(e) { result.dp_err = e.message; }

                                // getColumns (GridView level)
                                try {
                                    const cols = g.getColumns();
                                    result.gv_columns = cols.map(c => ({
                                        name: c.name || '',
                                        fieldName: c.fieldName || '',
                                        header: c.header?.text || '',
                                        type: c.type || '',
                                        columns: c.columns ? c.columns.map(sc => ({
                                            name: sc.name || '',
                                            fieldName: sc.fieldName || '',
                                            header: sc.header?.text || '',
                                        })) : undefined,
                                    }));
                                } catch(e) { result.gv_cols_err = e.message; }

                                // getColumnNames
                                try {
                                    if (g.getColumnNames) {
                                        result.gv_col_names = g.getColumnNames();
                                    }
                                } catch(e) {}

                                // getItemCount
                                try { result.gv_item_count = g.getItemCount(); } catch(e) {}
                            }

                            // dataProvider 직접
                            if (sn.state.dataProvider) {
                                result.dp_direct_depth = d;
                                const dp = sn.state.dataProvider;
                                try { result.dp_direct_rows = dp.getRowCount(); } catch(e) {}
                                try {
                                    result.dp_direct_fields = dp.getFields().map(f => ({
                                        fieldName: f.fieldName || f.name || '',
                                        dataType: f.dataType || '',
                                    }));
                                } catch(e) {}
                                try {
                                    const maxR = Math.min(dp.getRowCount(), 5);
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
                                    result.dp_direct_data = rows;
                                } catch(e) {}
                            }
                        }
                    }
                }
                fiber = fiber.return;
            }

            return result;
        }""")

        all_results["deep_data"] = deep_data
        print(f"\n  결과 키: {list(deep_data.keys())}")

        # 주요 결과 출력
        if deep_data.get('columns_detail'):
            print(f"\n  컬럼 상세 ({len(deep_data['columns_detail'])}개):")
            for col in deep_data['columns_detail']:
                print(f"    name={col['name']} header='{col['header']}' type={col.get('type','')} w={col.get('width',0)}")
                if col.get('subColumns'):
                    for sc in col['subColumns']:
                        print(f"      sub: name={sc['name']} fieldName={sc['fieldName']} header='{sc['header']}'")

        if deep_data.get('dp_fields'):
            print(f"\n  DataProvider 필드 ({len(deep_data['dp_fields'])}개):")
            for f in deep_data['dp_fields']:
                print(f"    {f['fieldName']} (type={f.get('dataType','')})")

        if deep_data.get('dp_sample_data'):
            print(f"\n  DataProvider 샘플 ({len(deep_data['dp_sample_data'])}행):")
            for row in deep_data['dp_sample_data'][:3]:
                print(f"    {json.dumps(row, ensure_ascii=False)[:300]}")

        if deep_data.get('gv_columns'):
            print(f"\n  GridView 컬럼 ({len(deep_data['gv_columns'])}개):")
            for col in deep_data['gv_columns'][:15]:
                print(f"    name={col['name']} fieldName={col.get('fieldName','')} header='{col['header']}' type={col.get('type','')}")
                if col.get('columns'):
                    for sc in col['columns']:
                        print(f"      sub: {sc['name']} ({sc['header']})")

        if deep_data.get('numeric_col_values'):
            print(f"\n  숫자 컬럼 값 (row 0): {deep_data['numeric_col_values']}")

        if deep_data.get('interface_methods'):
            print(f"\n  Interface 메서드: {deep_data['interface_methods'][:30]}")

        if deep_data.get('gridview_methods'):
            print(f"\n  GridView 메서드: {deep_data['gridview_methods'][:30]}")

        # Step 4: 전체 데이터 추출 (DataProvider 사용)
        if deep_data.get('dp_found') or deep_data.get('dp_direct_depth') is not None:
            print("\n" + "=" * 60)
            print("Step 4: DataProvider 전체 데이터 추출")
            print("=" * 60)

            full_data = page.evaluate("""() => {
                const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
                const fk = Object.keys(gridEl).find(k => k.startsWith('__reactInternalInstance'));
                let fiber = gridEl[fk];

                for (let d = 0; d < 25; d++) {
                    if (!fiber) break;
                    const sn = fiber.stateNode;
                    if (sn?.state?.grid) {
                        const g = sn.state.grid;
                        try {
                            const dp = g.getDataSource();
                            if (dp) {
                                const fields = dp.getFields().map(f => f.fieldName || f.name);
                                const rowCount = dp.getRowCount();
                                const rows = [];
                                for (let r = 0; r < rowCount; r++) {
                                    try {
                                        rows.push(dp.getJsonRow(r));
                                    } catch(e) {
                                        const row = {};
                                        for (const fn of fields) {
                                            try { row[fn] = dp.getValue(r, fn); } catch(e2) {}
                                        }
                                        rows.push(row);
                                    }
                                }
                                return { fields, rowCount, data: rows };
                            }
                        } catch(e) { return { error: e.message }; }
                    }
                    if (sn?.state?.dataProvider) {
                        const dp = sn.state.dataProvider;
                        try {
                            const fields = dp.getFields().map(f => f.fieldName || f.name);
                            const rowCount = dp.getRowCount();
                            const rows = [];
                            for (let r = 0; r < rowCount; r++) {
                                try { rows.push(dp.getJsonRow(r)); } catch(e) {
                                    const row = {};
                                    for (const fn of fields) {
                                        try { row[fn] = dp.getValue(r, fn); } catch(e2) {}
                                    }
                                    rows.push(row);
                                }
                            }
                            return { fields, rowCount, data: rows };
                        } catch(e) { return { error: e.message }; }
                    }
                    fiber = fiber.return;
                }
                return { error: 'no data source found' };
            }""")

            all_results["full_data_2026"] = full_data
            print(f"  전체 데이터: {full_data.get('rowCount', 'N/A')}행")
            if full_data.get('fields'):
                print(f"  필드: {full_data['fields']}")
            if full_data.get('data'):
                for row in full_data['data'][:5]:
                    print(f"    {json.dumps(row, ensure_ascii=False)[:300]}")

            save_json(full_data, "budget_actual_v7_full_data_2026.json")

        # 저장
        save_json(all_results, "budget_actual_v7_exploration.json")

        print("\n" + "=" * 60)
        print("탐색 완료!")
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    main()
