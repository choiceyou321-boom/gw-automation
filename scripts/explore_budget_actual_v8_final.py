"""
예실대비현황(상세) v8 — 전체 데이터 완전 추출 (최종)

v7 발견:
- 서브컬럼명으로 getValue 성공!
  - 전체프로젝트: abgtSumAm(예산액), unitAm(집행액), subAm(잔액), sumRt(대비%)
  - [프로젝트]: T0AbgtSumAm, T0UnitAm, T0SubAm, T0SumRt, T0TotalSumRt
- grid/dataProvider state 미발견 → interface.getValue로 직접 추출
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


def navigate_and_search(page, project_code="GS-25-0088"):
    """예실대비현황(상세) 이동 + 프로젝트 입력 + 조회"""
    page.goto("https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0020", wait_until="domcontentloaded")
    time.sleep(5)
    page.locator("text=예산장부").first.click()
    time.sleep(3)
    page.locator("text=예실대비현황(상세)").first.click()
    time.sleep(3)

    # canvas 대기
    for _ in range(15):
        time.sleep(1)
        if page.evaluate("() => !!document.querySelector('canvas')"):
            break

    # 프로젝트 입력
    proj_input = page.locator("input[placeholder='사업코드도움']").first
    proj_input.click()
    time.sleep(0.5)
    proj_input.fill(project_code)
    proj_input.press("Enter")
    time.sleep(2)

    # 조회
    page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const btn of btns) {
            if (btn.textContent.trim() === '조회') { btn.click(); return; }
        }
    }""")

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
            print(f"  데이터 로드 완료: {rc}행 ({i+1}초)")
            return rc
    print("  데이터 로드 실패")
    return 0


def extract_full_data(page):
    """서브컬럼 포함 전체 데이터 추출"""
    return page.evaluate("""() => {
        const result = {};

        const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
        if (!gridEl) return { error: 'no grid' };

        const fk = Object.keys(gridEl).find(k => k.startsWith('__reactInternalInstance'));
        if (!fk) return { error: 'no fiber' };

        let fiber = gridEl[fk];
        for (let d = 0; d < 10; d++) {
            if (!fiber) break;
            if (fiber.stateNode?.state?.interface) {
                const iface = fiber.stateNode.state.interface;

                // 1. 컬럼 구조 (서브컬럼 포함)
                const cols = iface.getColumns();
                const allFieldNames = [];
                const columnStructure = [];

                for (const c of cols) {
                    if (c.type === 'group' && c.columns) {
                        const group = {
                            name: c.name,
                            header: c.header?.text || c.header || '',
                            type: 'group',
                            subColumns: c.columns.map(sc => {
                                const scName = sc.name || sc.fieldName;
                                allFieldNames.push(scName);
                                return {
                                    name: scName,
                                    header: sc.header?.text || sc.header || '',
                                };
                            }),
                        };
                        columnStructure.push(group);
                    } else {
                        const name = c.name || c.fieldName;
                        allFieldNames.push(name);
                        columnStructure.push({
                            name: name,
                            header: c.header?.text || c.header || '',
                            type: c.type || 'data',
                        });
                    }
                }

                result.column_structure = columnStructure;
                result.all_field_names = allFieldNames;

                // 2. 전체 데이터 추출
                const rowCount = iface.getRowCount();
                result.row_count = rowCount;

                const rows = [];
                for (let r = 0; r < rowCount; r++) {
                    const row = {};
                    for (const fn of allFieldNames) {
                        try {
                            row[fn] = iface.getValue(r, fn);
                        } catch(e) {}
                    }
                    rows.push(row);
                }
                result.data = rows;

                break;
            }
            fiber = fiber.return;
        }

        return result;
    }""")


def main():
    print("=" * 60)
    print("예실대비현황(상세) v8 — 전체 데이터 추출 (최종)")
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
        page.on("response", on_response)

        # ═══ 2026년, GS-25-0088 ═══
        print("\n" + "=" * 60)
        print("2026년 GS-25-0088 조회")
        print("=" * 60)

        rc = navigate_and_search(page, "GS-25-0088")
        capture(page, "budget_actual_v8_2026_GS250088.png")

        if rc > 0:
            data_2026 = extract_full_data(page)
            all_results["2026_GS250088"] = data_2026
            print(f"  행수: {data_2026.get('row_count')}")
            print(f"  필드: {data_2026.get('all_field_names')}")
            print(f"  컬럼 구조:")
            for col in data_2026.get('column_structure', []):
                if col.get('type') == 'group':
                    print(f"    [{col['header']}] (group)")
                    for sc in col.get('subColumns', []):
                        print(f"      - {sc['name']}: {sc['header']}")
                else:
                    print(f"    {col['name']}: {col['header']}")

            print(f"\n  샘플 데이터 (처음 5행):")
            for i, row in enumerate(data_2026.get('data', [])[:5]):
                print(f"    [{i}] {json.dumps(row, ensure_ascii=False)[:250]}")

            # 합계행 찾기
            for row in data_2026.get('data', []):
                if row.get('bgtNm') and ('합계' in str(row.get('bgtNm', '')) or '잔액' in str(row.get('defNm', ''))):
                    print(f"\n  합계행: {json.dumps(row, ensure_ascii=False)[:300]}")

            save_json(data_2026, "budget_actual_v8_2026_GS250088.json")

        # ═══ API 분석 ═══
        print("\n" + "=" * 60)
        print("API 분석")
        print("=" * 60)

        # BP API만 필터
        bp_apis = [a for a in captured_apis if '/bp/' in a['url'] and a['method'] == 'POST']
        print(f"  BP POST API: {len(bp_apis)}개")
        for api in bp_apis:
            endpoint = api['url'].split('/')[-1]
            print(f"\n  ── {endpoint} ──")
            print(f"    URL: {api['url']}")
            if api['post_data']:
                print(f"    POST: {api['post_data'][:500]}")
            if api['response_body']:
                body = api['response_body']
                if isinstance(body, dict):
                    print(f"    RESP keys: {list(body.keys())}")
                    if 'resultData' in body:
                        rd = body['resultData']
                        if isinstance(rd, list):
                            print(f"    resultData: {len(rd)} items")
                            if rd:
                                print(f"    첫 항목 키: {list(rd[0].keys()) if isinstance(rd[0], dict) else type(rd[0])}")
                                print(f"    첫 항목: {json.dumps(rd[0], ensure_ascii=False)[:300]}")
                        elif isinstance(rd, dict):
                            print(f"    resultData keys: {list(rd.keys())}")
                else:
                    print(f"    RESP: {str(body)[:300]}")

        all_results["bp_apis"] = [{
            "url": a['url'],
            "method": a['method'],
            "post_data": a['post_data'],
            "response_body": a['response_body'],
        } for a in bp_apis]

        save_json(all_results, "budget_actual_v8_final.json")

        print("\n" + "=" * 60)
        print("Phase 0 탐색 완료!")
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    main()
