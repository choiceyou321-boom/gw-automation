"""
HP 개인지출결의현황 Phase 6 — 최종 데이터 탐색
페이지 URL: /#/HP/NPA0030/NPA0030
API: POST /personal/NPA0030/0hr00004
필터: 작성구분(전체), 결의일(기간), 작성자
테이블 컬럼: 작성구분, 결의일, 순번, 결의구분, 집행용도, 총금액, 진행상태

목표:
1. 날짜 범위 2025-01-01 ~ 2026-12-31 설정
2. 조회 → 데이터 확인
3. "진행상태" 컬럼에서 "이체완료" 필터 확인
4. 전체 데이터 구조 + API 엔드포인트 파악
"""

import sys
import json
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.auth.login import login_and_get_context, close_session, GW_URL

OUTPUT_DIR = PROJECT_ROOT / "data" / "gw_analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def save(page, name):
    page.screenshot(path=str(OUTPUT_DIR / f"{name}.png"), full_page=True)
    print(f"  [SS] {name}.png")

def save_json(data, name):
    with open(OUTPUT_DIR / f"{name}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [JSON] {name}.json")

def close_popups(page):
    try:
        for p in page.context.pages:
            if "popup" in p.url.lower() or "notice" in p.url.lower():
                p.close()
        page.wait_for_timeout(1000)
    except Exception:
        pass


def main():
    print("=" * 60)
    print("HP 개인지출결의현황 — 최종 데이터 탐색")
    print("=" * 60)

    api_calls = []
    api_responses = []

    def on_req(req):
        url = req.url
        if any(x in url for x in ['/personal/', 'NPA', 'npa', '0hr', 'slip',
                                     'expense', 'transfer', 'getList',
                                     '/gw/gw999', '/gw/gw027', '/gw/gw066']):
            api_calls.append({
                "method": req.method,
                "url": url[:300],
                "post_data": req.post_data[:3000] if req.post_data else None,
            })

    def on_resp(resp):
        url = resp.url
        if any(x in url for x in ['NPA', 'npa', '0hr', 'slip', 'expense',
                                     'transfer', 'getList']):
            body = None
            try:
                body = resp.json()
                bs = json.dumps(body, ensure_ascii=False)
                if len(bs) > 50000:
                    body = {"_truncated": True, "_size": len(bs),
                            "_keys": list(body.keys()) if isinstance(body, dict) else None,
                            "_preview": bs[:10000]}
            except Exception:
                try:
                    body = resp.text()[:5000]
                except Exception:
                    pass
            api_responses.append({"status": resp.status, "url": url[:300], "body": body})

    print("\n[로그인]")
    browser, context, page = login_and_get_context(headless=False)
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.on("dialog", lambda d: d.accept())
    page.on("request", on_req)
    page.on("response", on_resp)

    try:
        page.wait_for_timeout(3000)
        close_popups(page)

        # ──────────────────────────────────────────────
        # Step 1: 직접 URL 접근
        # ──────────────────────────────────────────────
        print("\n[Step 1] 개인지출결의현황 직접 접근")
        page.goto(f"{GW_URL}/#/HP/NPA0030/NPA0030", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)
        close_popups(page)
        print(f"  URL: {page.url}")
        save(page, "hp_v6_01_initial")

        # ──────────────────────────────────────────────
        # Step 2: 페이지 요소 분석
        # ──────────────────────────────────────────────
        print("\n[Step 2] 페이지 요소 분석")

        # visible 입력 필드
        inputs = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('input, select, textarea').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0 && rect.x > 180) {
                    r.push({
                        tag: el.tagName.toLowerCase(), id: el.id, name: el.name,
                        type: el.type || '', value: el.value ? el.value.substring(0, 80) : '',
                        placeholder: el.placeholder || '', disabled: el.disabled, readOnly: el.readOnly,
                        className: (el.className?.substring ? el.className.substring(0, 120) : ''),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return r;
        }""")
        save_json(inputs, "hp_v6_02_inputs")
        print(f"  입력 필드: {len(inputs)}개")
        for inp in inputs:
            print(f"    {inp['tag']}[{inp['type']}] id={inp['id'][:20]} val={inp['value'][:30]} at ({inp['rect']['x']},{inp['rect']['y']}) {inp['rect']['w']}x{inp['rect']['h']} {'RO' if inp['readOnly'] else ''}")

        # 버튼
        buttons = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('button, [role="button"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0 && rect.x > 180) {
                    const text = el.textContent.trim().substring(0, 60);
                    if (text) r.push({text, id: el.id, rect: {x: Math.round(rect.x), y: Math.round(rect.y)}});
                }
            });
            return r;
        }""")
        save_json(buttons, "hp_v6_02_buttons")
        print(f"  버튼: {len(buttons)}개")
        for b in buttons:
            print(f"    \"{b['text'][:40]}\" at ({b['rect']['x']},{b['rect']['y']})")

        # 드롭다운/콤보
        combos = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('[class*="OBTDropDownList"], [class*="Combo"], [class*="combo"], [class*="OBTSingle"], select').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.x > 180) {
                    r.push({
                        tag: el.tagName,
                        className: (el.className?.substring ? el.className.substring(0, 120) : ''),
                        text: el.textContent.trim().substring(0, 60),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width)},
                    });
                }
            });
            return r;
        }""")
        save_json(combos, "hp_v6_02_combos")
        print(f"  콤보/드롭다운: {len(combos)}개")
        for c in combos:
            print(f"    \"{c['text'][:40]}\" class={c['className'][:50]} at ({c['rect']['x']},{c['rect']['y']})")

        # 라벨+입력 영역 (검색 조건)
        labels = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('[class*="label"], [class*="Label"], th, dt, label').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.x > 180 && rect.y < 200) {
                    const text = el.textContent.trim().substring(0, 40);
                    if (text) r.push({text, tag: el.tagName, rect: {x: Math.round(rect.x), y: Math.round(rect.y)}});
                }
            });
            return r;
        }""")
        print(f"  검색 영역 라벨:")
        for l in labels:
            print(f"    \"{l['text']}\" at ({l['rect']['x']},{l['rect']['y']})")

        # ──────────────────────────────────────────────
        # Step 3: 날짜 범위 변경 (2025-01-01 ~ 2026-12-31)
        # ──────────────────────────────────────────────
        print("\n[Step 3] 날짜 범위 변경: 2025-01-01 ~ 2026-12-31")

        # 날짜 입력 필드 찾기 (value에 날짜 패턴)
        date_fields = [inp for inp in inputs if inp['value'] and
                       any(c.isdigit() for c in inp['value']) and
                       ('-' in inp['value'] or '/' in inp['value'] or '.' in inp['value']) and
                       len(inp['value']) >= 8]
        print(f"  날짜 필드 후보: {len(date_fields)}개")
        for df in date_fields:
            print(f"    val={df['value']} at ({df['rect']['x']},{df['rect']['y']}) {df['rect']['w']}x{df['rect']['h']}")

        # OBTDatePicker 방식으로 날짜 변경 시도
        # React 방식: input에 직접 값을 설정하고 이벤트 발생
        date_set_result = page.evaluate("""() => {
            const results = [];
            // 모든 visible input 중 날짜 값을 가진 것 찾기
            const dateInputs = [];
            document.querySelectorAll('input').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.x > 180 && rect.y < 200) {
                    const val = el.value || '';
                    if (val.match(/\\d{4}-\\d{2}-\\d{2}/)) {
                        dateInputs.push({el, val, x: rect.x});
                    }
                }
            });

            // x 좌표순 정렬 (왼쪽=시작일, 오른쪽=종료일)
            dateInputs.sort((a, b) => a.x - b.x);

            const dates = ['2025-01-01', '2026-12-31'];
            for (let i = 0; i < Math.min(dateInputs.length, 2); i++) {
                const el = dateInputs[i].el;
                const oldVal = el.value;
                const newVal = dates[i];

                // React input value setter
                const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                nativeSetter.call(el, newVal);
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                el.dispatchEvent(new Event('blur', {bubbles: true}));

                results.push({old: oldVal, new: newVal, x: dateInputs[i].x});
            }
            return results;
        }""")
        print(f"  날짜 설정 결과: {json.dumps(date_set_result, ensure_ascii=False)}")
        page.wait_for_timeout(1000)

        # ──────────────────────────────────────────────
        # Step 4: 조회 버튼 클릭
        # ──────────────────────────────────────────────
        print("\n[Step 4] 조회 실행")
        api_calls.clear()
        api_responses.clear()

        # 돋보기(검색) 아이콘 버튼 또는 "조회" 텍스트 버튼 클릭
        search_result = page.evaluate("""() => {
            // 1. 아이콘 버튼 (검색 아이콘)
            const searchBtns = document.querySelectorAll('[class*="search"], [class*="Search"], [class*="btn-search"], [class*="icon-btn-search"]');
            for (const btn of searchBtns) {
                const rect = btn.getBoundingClientRect();
                if (btn.offsetParent !== null && rect.width > 0 && rect.y < 200) {
                    btn.click();
                    return {clicked: 'search icon', className: (btn.className?.substring ? btn.className.substring(0, 80) : '')};
                }
            }
            // 2. 버튼 중 검색 관련
            const btns = document.querySelectorAll('button, [role="button"]');
            for (const btn of btns) {
                const text = btn.textContent.trim();
                const rect = btn.getBoundingClientRect();
                if (rect.y < 200 && rect.x > 1000 && btn.offsetParent !== null && rect.width > 0) {
                    if (text === '조회' || text === '검색' || text === '') {
                        btn.click();
                        return {clicked: text || 'empty button', x: Math.round(rect.x), y: Math.round(rect.y)};
                    }
                }
            }
            // 3. img 검색 아이콘
            const imgs = document.querySelectorAll('img[src*="search"], img[alt*="검색"], img[alt*="조회"]');
            for (const img of imgs) {
                const rect = img.getBoundingClientRect();
                if (img.offsetParent !== null && rect.y < 200) {
                    img.click();
                    return {clicked: 'search img'};
                }
            }
            return {error: 'no search button found'};
        }""")
        print(f"  검색: {search_result}")

        # 돋보기 아이콘이 스크린샷에서 보이는 위치 (약 x=1415, y=142) 로 직접 클릭
        if 'error' in search_result:
            print("  직접 좌표 클릭 시도 (돋보기 아이콘 위치)")
            page.mouse.click(1415, 142)

        page.wait_for_timeout(6000)
        save(page, "hp_v6_04_after_search")

        # 조회 결과 텍스트
        text4 = page.evaluate("() => document.body ? document.body.innerText.substring(0, 15000) : ''")
        with open(OUTPUT_DIR / "hp_v6_04_text.txt", "w", encoding="utf-8") as f:
            f.write(text4)
        # 핵심 라인만 출력
        for line in text4.split('\n'):
            line = line.strip()
            if line and len(line) > 2 and not any(x in line for x in ['위로', '아래로', 'ONEFFICE', 'ONECHAMBER', '오피스케어', '부가서비스']):
                if any(kw in line for kw in ['결의', '이체', '총금액', '진행', '합계', '프로젝트',
                                               '예산', '결제', '코드', '거래', '공급', '세액',
                                               '작성', '순번', '용도', '상태', '데이터']):
                    print(f"    {line[:100]}")

        # ──────────────────────────────────────────────
        # Step 5: OBTDataGrid 데이터 추출
        # ──────────────────────────────────────────────
        print("\n[Step 5] OBTDataGrid 데이터 추출")

        grids = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('[class*="OBTDataGrid"], canvas').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 50 && rect.height > 50) {
                    r.push({
                        className: (el.className?.substring ? el.className.substring(0, 150) : ''),
                        tagName: el.tagName,
                        hasReactFiber: Object.keys(el).some(k => k.startsWith('__reactFiber')),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return r;
        }""")
        save_json(grids, "hp_v6_05_grids")
        print(f"  그리드: {len(grids)}개")
        for g in grids:
            print(f"    {g['tagName']} class={g['className'][:60]} fiber={g['hasReactFiber']} {g['rect']['w']}x{g['rect']['h']}")

        # 각 그리드에서 데이터 추출
        all_grid_data = page.evaluate("""() => {
            const results = [];
            const gridEls = document.querySelectorAll('[class*="OBTDataGrid_grid"]');
            gridEls.forEach((gridEl, idx) => {
                try {
                    const fk = Object.keys(gridEl).find(k => k.startsWith('__reactFiber'));
                    if (!fk) { results.push({index: idx, error: 'no fiber'}); return; }
                    let f = gridEl[fk];
                    for (let i = 0; i < 8; i++) {
                        if (f?.stateNode?.state?.interface) {
                            const iface = f.stateNode.state.interface;
                            let rc = 0, cols = [];
                            try { rc = iface.getRowCount(); } catch(e) {}
                            try {
                                cols = iface.getColumns().map(c => ({
                                    name: c.name || c.fieldName,
                                    header: c.header?.text || c.header || '',
                                    width: c.width, visible: c.visible !== false,
                                    fieldName: c.fieldName || '',
                                }));
                            } catch(e) {}
                            let data = [];
                            for (let r = 0; r < Math.min(200, rc); r++) {
                                const row = {};
                                cols.forEach(c => {
                                    try { row[c.name] = String(iface.getValue(r, c.name)).substring(0, 100); } catch(e) {}
                                });
                                data.push(row);
                            }
                            results.push({index: idx, depth: i, rowCount: rc, columns: cols, data});
                            return;
                        }
                        if (f) f = f.return;
                    }
                    results.push({index: idx, error: 'no interface in 8 depths'});
                } catch(e) {
                    results.push({index: idx, error: e.message});
                }
            });
            return results;
        }""")
        save_json(all_grid_data, "hp_v6_05_grid_data")
        for gd in all_grid_data:
            if gd.get('error'):
                print(f"  그리드[{gd['index']}]: {gd['error']}")
            else:
                print(f"  그리드[{gd['index']}]: {gd['rowCount']}행, {len(gd.get('columns', []))}열 (depth={gd['depth']})")
                if gd.get('columns'):
                    print(f"    컬럼: {[(c['header'] or c['name']) for c in gd['columns']]}")
                if gd.get('data'):
                    for row in gd['data'][:10]:
                        print(f"    → {json.dumps(row, ensure_ascii=False)[:150]}")

        # ──────────────────────────────────────────────
        # Step 6: 테이블 (HTML 테이블) 데이터 확인
        # ──────────────────────────────────────────────
        print("\n[Step 6] HTML 테이블 확인")
        tables = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('table').forEach((t, i) => {
                const rect = t.getBoundingClientRect();
                if (rect.width > 100 && rect.height > 30 && rect.x > 180) {
                    const headers = [];
                    t.querySelectorAll('thead th, thead td, tr:first-child th').forEach(h => {
                        headers.push(h.textContent.trim().substring(0, 40));
                    });
                    const rows = t.querySelectorAll('tbody tr');
                    const sample = [];
                    for (let j = 0; j < Math.min(10, rows.length); j++) {
                        const cells = [];
                        rows[j].querySelectorAll('td').forEach(td => cells.push(td.textContent.trim().substring(0, 60)));
                        sample.push(cells);
                    }
                    r.push({index: i, headers, rowCount: rows.length, sampleRows: sample,
                            rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}});
                }
            });
            return r;
        }""")
        save_json(tables, "hp_v6_06_tables")
        for t in tables:
            print(f"  테이블[{t['index']}] {t['rowCount']}행, 헤더={t['headers'][:10]} at ({t['rect']['x']},{t['rect']['y']})")
            for sr in t['sampleRows'][:5]:
                print(f"    → {sr[:10]}")

        # ──────────────────────────────────────────────
        # Step 7: "작성구분" 드롭다운 옵션 확인
        # ──────────────────────────────────────────────
        print("\n[Step 7] 작성구분 드롭다운 옵션 확인")
        dropdown_options = page.evaluate("""() => {
            // OBTDropDownList의 React state에서 옵션 추출
            const dropdowns = document.querySelectorAll('[class*="OBTDropDownList"], [class*="OBTSingleComboBox"]');
            const results = [];
            dropdowns.forEach((dd, idx) => {
                const rect = dd.getBoundingClientRect();
                if (dd.offsetParent !== null && rect.width > 0 && rect.x > 180) {
                    const fk = Object.keys(dd).find(k => k.startsWith('__reactFiber'));
                    if (fk) {
                        let fiber = dd[fk];
                        for (let i = 0; i < 10; i++) {
                            if (fiber?.stateNode?.state?.data || fiber?.stateNode?.props?.data || fiber?.memoizedProps?.data) {
                                const data = fiber.stateNode?.state?.data || fiber.stateNode?.props?.data || fiber.memoizedProps?.data;
                                results.push({
                                    index: idx,
                                    depth: i,
                                    text: dd.textContent.trim().substring(0, 40),
                                    data: Array.isArray(data) ? data.slice(0, 20) : data,
                                    rect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                                });
                                return;
                            }
                            if (fiber) fiber = fiber.return;
                        }
                    }
                    results.push({index: idx, text: dd.textContent.trim().substring(0, 40), data: null});
                }
            });
            return results;
        }""")
        save_json(dropdown_options, "hp_v6_07_dropdown_options")
        for d in dropdown_options:
            print(f"  드롭다운[{d['index']}] \"{d['text'][:30]}\" data={json.dumps(d.get('data', 'null'), ensure_ascii=False)[:200]}")

        # ──────────────────────────────────────────────
        # Step 8: API 호출로 직접 데이터 조회
        # ──────────────────────────────────────────────
        print("\n[Step 8] API 직접 호출 (전체 기간)")
        api_result = page.evaluate("""async () => {
            try {
                // 조회 API: /personal/NPA0030/0hr00004
                const resp = await fetch('/personal/NPA0030/0hr00004', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        vPCoCd: '1000',
                        coCd: '1000',
                    }),
                });
                return await resp.json();
            } catch(e) { return {error: e.message}; }
        }""")
        bs = json.dumps(api_result, ensure_ascii=False)
        if len(bs) > 50000:
            save_json({"_truncated": True, "_size": len(bs), "_preview": bs[:20000]}, "hp_v6_08_api_result")
        else:
            save_json(api_result, "hp_v6_08_api_result")
        print(f"  API 결과: {bs[:300]}...")

        # 주요 API 목록 조회
        print("\n  기타 API 시도...")
        for api_path, params in [
            ("/personal/NPA0030/0hr00001", {"vPCoCd": "1000", "coCd": "1000", "fromDate": "20250101", "toDate": "20261231"}),
            ("/personal/NPA0030/0hr00002", {"vPCoCd": "1000", "coCd": "1000", "fromDate": "20250101", "toDate": "20261231"}),
            ("/personal/NPA0030/0hr00003", {"vPCoCd": "1000", "coCd": "1000"}),
            ("/personal/NPA0030/0hr00005", {"vPCoCd": "1000", "coCd": "1000"}),
            ("/personal/NPA0030/search", {"coCd": "1000", "fromDate": "20250101", "toDate": "20261231"}),
            ("/personal/NPA0030/getList", {"coCd": "1000", "fromDate": "20250101", "toDate": "20261231"}),
        ]:
            try:
                result = page.evaluate(f"""async () => {{
                    try {{
                        const resp = await fetch('{api_path}', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({json.dumps(params)}),
                        }});
                        const text = await resp.text();
                        try {{ return JSON.parse(text); }} catch(e) {{ return text.substring(0, 500); }}
                    }} catch(e) {{ return {{error: e.message}}; }}
                }}""")
                rs = json.dumps(result, ensure_ascii=False)[:200]
                print(f"    {api_path}: {rs}")
                if result and not isinstance(result, str) and not result.get('error'):
                    save_json(result, f"hp_v6_08_{api_path.split('/')[-1]}")
            except Exception as e:
                print(f"    {api_path}: 실패 - {e}")

    except Exception as e:
        print(f"\n[오류] {e}")
        traceback.print_exc()
        save(page, "hp_v6_error")

    finally:
        save_json(api_calls, "hp_v6_api_calls")
        save_json(api_responses, "hp_v6_api_responses")
        print(f"\n  캡처된 API 요청: {len(api_calls)}개, 응답: {len(api_responses)}개")

        unique = {}
        for c in api_calls:
            base = c['url'].split('?')[0]
            if base not in unique:
                unique[base] = {"method": c['method'], "post_data": (c.get('post_data') or '')[:300]}
        print(f"  고유 엔드포인트 ({len(unique)}개):")
        for url, info in sorted(unique.items()):
            pd = f"\n      body: {info['post_data'][:150]}" if info['post_data'] else ""
            print(f"    [{info['method']}] {url[:120]}{pd}")

        # API 응답 출력
        for resp in api_responses[:10]:
            body = resp.get('body')
            if body:
                preview = json.dumps(body, ensure_ascii=False)[:300] if isinstance(body, (dict, list)) else str(body)[:300]
                print(f"    응답 [{resp['status']}] {resp['url'][:80]}: {preview}")

        print("\n" + "=" * 60)
        hp_files = sorted(OUTPUT_DIR.glob("hp_v6_*"))
        print(f"파일 ({len(hp_files)}개):")
        for f in hp_files:
            print(f"  {f.name:60s}  {f.stat().st_size:>8,} bytes")

        close_session(browser)


if __name__ == "__main__":
    main()
