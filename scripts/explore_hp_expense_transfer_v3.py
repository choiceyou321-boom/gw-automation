"""
HP 지출결의서 이체완료 탐색 Phase 3
문제점: /#/HP → 포탈 대시보드 (LNB 없음)
해결: /#/HP/HPM0110/HPM0110 (개인인사정보) 먼저 진입 → LNB 메뉴 사용
      또는 module-link.HR 클릭 → LNB에서 "지출결의/계산서" 클릭
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
    print(f"  [스크린샷] {name}.png")

def save_json(data, name):
    with open(OUTPUT_DIR / f"{name}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [저장] {name}.json")

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
    print("HP 지출결의서 탐색 Phase 3 — LNB 메뉴 직접 클릭")
    print("=" * 60)

    api_calls = []
    api_responses = []

    def on_req(req):
        url = req.url
        if any(x in url for x in ['/gw/', '/personal/', 'hp', 'HP', 'hpm', 'HPM',
                                     'eap', 'EAP', 'expense', 'accSlip', 'voucher',
                                     'transfer', 'getList', 'search', 'query']):
            api_calls.append({
                "method": req.method,
                "url": url[:300],
                "post_data": req.post_data[:2000] if req.post_data else None,
            })

    def on_resp(resp):
        url = resp.url
        if any(x in url for x in ['hp', 'HP', 'hpm', 'HPM', 'personal',
                                     'expense', 'accSlip', 'voucher', 'transfer',
                                     'getList', 'eap']):
            body = None
            try:
                body = resp.json()
                bs = json.dumps(body, ensure_ascii=False)
                if len(bs) > 10000:
                    body = {"_truncated": True, "_size": len(bs), "_keys": list(body.keys()) if isinstance(body, dict) else None, "_preview": bs[:3000]}
            except Exception:
                try:
                    body = resp.text()[:3000]
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
        # Step 1: HPM0110 페이지로 진입 (LNB가 있는 페이지)
        # ──────────────────────────────────────────────
        print("\n[Step 1] HP 모듈 페이지 진입 (HPM0110)")
        page.goto(f"{GW_URL}/#/HP/HPM0110/HPM0110", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        close_popups(page)
        print(f"  URL: {page.url}")

        # LNB 메뉴 확인
        menu = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('.nav-item').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    // 직접 텍스트 (첫 번째 레벨 자식만)
                    let text = '';
                    for (const node of el.childNodes) {
                        if (node.nodeType === 3) {
                            text += node.textContent.trim();
                        } else if (node.nodeType === 1 && node.tagName !== 'UL' && !node.classList.contains('nav-item')) {
                            // span, a, div 등 바로 하위 텍스트 요소
                            const innerText = node.textContent.trim();
                            if (innerText.length < 30) text += innerText;
                        }
                    }
                    if (!text) text = el.textContent.trim().substring(0, 30);
                    result.push({
                        text: text.substring(0, 50),
                        className: el.className,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return result;
        }""")
        save_json(menu, "hp_v3_01_menu")
        print(f"  LNB 메뉴: {len(menu)}개")
        for m in menu:
            flag = ""
            if "open" in m['className']: flag = " [OPEN]"
            elif "close" in m['className']: flag = " [CLOSE]"
            if "selected" in m['className']: flag += " [SEL]"
            step = ""
            if "step-1" in m['className']: step = "  "
            elif "step-2" in m['className']: step = "    "
            elif "step-3" in m['className']: step = "      "
            print(f"  {step}{m['text'][:40]}{flag}")

        # ──────────────────────────────────────────────
        # Step 2: "지출결의/계산서" 메뉴 클릭하여 펼치기
        # ──────────────────────────────────────────────
        print("\n[Step 2] '지출결의/계산서' 클릭")
        result = page.evaluate("""() => {
            const items = document.querySelectorAll('.nav-item.step-1');
            for (const el of items) {
                // 직접 자식의 텍스트
                const link = el.querySelector(':scope > a, :scope > span, :scope > div');
                const text = link ? link.textContent.trim() : el.textContent.trim().substring(0, 30);
                if (text.includes('지출결의') || text.includes('계산서')) {
                    el.click();
                    return {clicked: text, className: el.className};
                }
            }
            // 넓은 범위로 시도
            const allItems = document.querySelectorAll('.nav-item');
            for (const el of allItems) {
                const text = el.textContent.trim();
                if (text.length < 20 && (text.includes('지출결의') || text === '지출결의/계산서')) {
                    el.click();
                    return {clicked: text, className: el.className};
                }
            }
            return {error: 'not found'};
        }""")
        print(f"  결과: {result}")
        page.wait_for_timeout(3000)

        # 메뉴 재확인 (펼쳐진 상태)
        menu2 = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('.nav-item').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    let text = '';
                    for (const node of el.childNodes) {
                        if (node.nodeType === 3) text += node.textContent.trim();
                        else if (node.nodeType === 1 && node.tagName !== 'UL' && !node.classList.contains('nav-item')) {
                            const t = node.textContent.trim();
                            if (t.length < 30) text += t;
                        }
                    }
                    if (!text) text = el.textContent.trim().substring(0, 30);
                    result.push({
                        text: text.substring(0, 50),
                        className: el.className,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                    });
                }
            });
            return result;
        }""")
        save_json(menu2, "hp_v3_02_menu_expanded")
        save(page, "hp_v3_02_menu_expanded")
        print(f"  펼친 후 메뉴: {len(menu2)}개")
        for m in menu2:
            flag = ""
            if "open" in m['className']: flag = " [OPEN]"
            elif "close" in m['className']: flag = " [CLOSE]"
            if "selected" in m['className']: flag += " [SEL]"
            step = ""
            if "step-1" in m['className']: step = "  "
            elif "step-2" in m['className']: step = "    "
            elif "step-3" in m['className']: step = "      "
            print(f"  {step}{m['text'][:40]}{flag}")

        # ──────────────────────────────────────────────
        # Step 3: 하위 메뉴에서 클릭 가능한 항목 찾기
        # ──────────────────────────────────────────────
        print("\n[Step 3] 지출결의/계산서 하위 메뉴 클릭")
        # "개인지출결의서" 클릭 시도
        clicked_item = page.evaluate("""() => {
            // step-2 또는 step-3 중 "지출결의서" 포함 항목
            const items = document.querySelectorAll('.nav-item');
            const targets = ['개인지출결의서', '지출결의서', '이체현황', '결의서현황', '이체완료'];
            for (const target of targets) {
                for (const el of items) {
                    const text = el.textContent.trim();
                    if (text === target || (text.includes(target) && text.length < target.length + 10)) {
                        if (el.offsetParent !== null) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0) {
                                // a 또는 span 클릭
                                const link = el.querySelector('a') || el.querySelector('span') || el;
                                link.click();
                                return {clicked: target, fullText: text.substring(0, 50), className: el.className};
                            }
                        }
                    }
                }
            }
            return {error: 'no target found'};
        }""")
        print(f"  클릭 결과: {clicked_item}")
        page.wait_for_timeout(6000)
        close_popups(page)
        print(f"  URL: {page.url}")

        save(page, "hp_v3_03_expense_page")

        # 페이지 텍스트 확인
        text3 = page.evaluate("() => document.body ? document.body.innerText.substring(0, 10000) : ''")
        with open(OUTPUT_DIR / "hp_v3_03_text.txt", "w", encoding="utf-8") as f:
            f.write(text3)
        print(f"  텍스트 ({len(text3)}자):")
        for line in text3.split('\n')[:40]:
            line = line.strip()
            if line and len(line) > 1:
                print(f"    {line[:80]}")

        # ──────────────────────────────────────────────
        # Step 4: 페이지 DOM 분석
        # ──────────────────────────────────────────────
        print("\n[Step 4] 페이지 DOM 분석")

        # 탭 요소
        tabs = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('[role="tab"], [class*="tab"], [class*="Tab"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    const text = el.textContent.trim().substring(0, 80);
                    // 짧은 탭 텍스트만 (실제 탭)
                    if (text.length < 40 || el.getAttribute('role') === 'tab') {
                        r.push({
                            text: text,
                            className: (el.className.substring ? el.className.substring(0, 120) : ''),
                            ariaSelected: el.getAttribute('aria-selected') || '',
                            rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                        });
                    }
                }
            });
            return r;
        }""")
        save_json(tabs, "hp_v3_04_tabs")
        print(f"  탭: {len(tabs)}개")
        for t in tabs:
            sel = " [SEL]" if t.get('ariaSelected') == 'true' else ""
            print(f"    \"{t['text'][:50]}\"{sel}  class={t['className'][:50]}")

        # 버튼
        btns = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('button, [role="button"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    const text = el.textContent.trim().substring(0, 60);
                    if (text) {
                        r.push({text, id: el.id, className: (el.className.substring ? el.className.substring(0, 100) : ''),
                                rect: {x: Math.round(rect.x), y: Math.round(rect.y)}});
                    }
                }
            });
            return r;
        }""")
        save_json(btns, "hp_v3_04_buttons")
        print(f"  버튼: {len(btns)}개")
        for b in btns[:25]:
            print(f"    \"{b['text'][:50]}\" (id={b['id'][:20]})")

        # 입력 필드
        inputs = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('input, select, textarea').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    r.push({
                        tag: el.tagName.toLowerCase(), id: el.id, name: el.name,
                        type: el.type || '', value: el.value ? el.value.substring(0, 50) : '',
                        placeholder: el.placeholder || '',
                        disabled: el.disabled,
                        className: (el.className.substring ? el.className.substring(0, 100) : ''),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return r;
        }""")
        save_json(inputs, "hp_v3_04_inputs")
        print(f"  visible 입력: {len(inputs)}개")
        for inp in inputs:
            print(f"    {inp['tag']}[{inp['type']}] id={inp['id'][:20]} val={inp['value'][:30]} ph={inp['placeholder'][:20]}")

        # 테이블
        tables = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('table').forEach((t, i) => {
                const rect = t.getBoundingClientRect();
                if (rect.width > 100 && rect.height > 50) {
                    const headers = [];
                    t.querySelectorAll('thead th, thead td, tr:first-child th').forEach(h => {
                        headers.push(h.textContent.trim().substring(0, 40));
                    });
                    const rows = t.querySelectorAll('tbody tr');
                    const sample = [];
                    for (let j = 0; j < Math.min(5, rows.length); j++) {
                        const cells = [];
                        rows[j].querySelectorAll('td').forEach(td => cells.push(td.textContent.trim().substring(0, 50)));
                        sample.push(cells);
                    }
                    r.push({index: i, headers, rowCount: rows.length, sampleRows: sample});
                }
            });
            return r;
        }""")
        save_json(tables, "hp_v3_04_tables")
        print(f"  테이블: {len(tables)}개")
        for t in tables:
            print(f"    [{t['index']}] {t['rowCount']}행, 헤더={t['headers'][:8]}")
            for sr in t['sampleRows'][:3]:
                print(f"      → {sr[:6]}")

        # OBTDataGrid
        grids = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('[class*="OBTDataGrid"], [class*="realgrid"], canvas').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 50 && rect.height > 50) {
                    r.push({
                        className: (el.className.substring ? el.className.substring(0, 150) : ''),
                        tagName: el.tagName,
                        hasCanvas: el.querySelector ? el.querySelector('canvas') !== null : el.tagName === 'CANVAS',
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return r;
        }""")
        save_json(grids, "hp_v3_04_grids")
        print(f"  그리드: {len(grids)}개")

        if grids:
            grid_data = page.evaluate("""() => {
                try {
                    const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
                    if (!gridEl) return {error: 'no grid'};
                    const fiberKey = Object.keys(gridEl).find(k => k.startsWith('__reactFiber'));
                    if (!fiberKey) return {error: 'no fiber'};
                    let fiber = gridEl[fiberKey];
                    for (let i = 0; i < 6; i++) {
                        if (fiber?.stateNode?.state?.interface) {
                            const iface = fiber.stateNode.state.interface;
                            let rowCount = 0, columns = [];
                            try { rowCount = iface.getRowCount(); } catch(e) {}
                            try {
                                columns = iface.getColumns().map(c => ({
                                    name: c.name || c.fieldName,
                                    header: c.header?.text || c.header || c.fieldName,
                                    width: c.width,
                                }));
                            } catch(e) {}
                            let data = [];
                            for (let r = 0; r < Math.min(50, rowCount); r++) {
                                const row = {};
                                columns.forEach(c => {
                                    try { row[c.name] = String(iface.getValue(r, c.name)).substring(0, 80); } catch(e) {}
                                });
                                data.push(row);
                            }
                            return {depth: i, rowCount, columns, data};
                        }
                        if (fiber) fiber = fiber.return;
                    }
                    return {error: 'no interface'};
                } catch(e) { return {error: e.message}; }
            }""")
            save_json(grid_data, "hp_v3_04_grid_data")
            print(f"  그리드 데이터: rowCount={grid_data.get('rowCount', '?')}, columns={len(grid_data.get('columns', []))}")

        # iframe 탐색
        frames = page.frames
        print(f"\n  iframe: {len(frames)}개")
        for i, frame in enumerate(frames):
            print(f"    [{i}] name={frame.name} url={frame.url[:100]}")

        # ──────────────────────────────────────────────
        # Step 5: 이체완료 탭/필터 찾기 — 페이지 내 텍스트 기반
        # ──────────────────────────────────────────────
        print("\n[Step 5] 이체완료 탭/상태 필터 탐색")

        # "이체완료" 텍스트 포함 요소 모두 찾기
        transfer_elements = page.evaluate("""() => {
            const r = [];
            const keywords = ['이체', '지급', '완료', '처리', '상태', '진행'];
            const all = document.querySelectorAll('*');
            for (const el of all) {
                if (el.children.length === 0 || el.tagName === 'BUTTON' || el.tagName === 'A' || el.tagName === 'SPAN' || el.tagName === 'OPTION') {
                    const text = el.textContent.trim();
                    if (text.length > 0 && text.length < 30) {
                        for (const kw of keywords) {
                            if (text.includes(kw)) {
                                const rect = el.getBoundingClientRect();
                                if (el.offsetParent !== null && rect.width > 0) {
                                    r.push({
                                        text: text,
                                        tag: el.tagName,
                                        className: (el.className.substring ? el.className.substring(0, 100) : ''),
                                        rect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                                    });
                                    break;
                                }
                            }
                        }
                    }
                }
            }
            return r;
        }""")
        save_json(transfer_elements, "hp_v3_05_transfer_elements")
        print(f"  이체/지급/완료/상태 관련 요소: {len(transfer_elements)}개")
        for te in transfer_elements[:20]:
            print(f"    \"{te['text']}\" ({te['tag']}) at ({te['rect']['x']},{te['rect']['y']})")

        # ──────────────────────────────────────────────
        # Step 6: 각 상태 탭 클릭 시도
        # ──────────────────────────────────────────────
        print("\n[Step 6] 상태별 탭 클릭")
        # 이체완료 관련 텍스트를 가진 요소 클릭
        for te in transfer_elements:
            if '이체완료' in te['text'] or te['text'] == '이체완료':
                print(f"  '이체완료' 요소 클릭 시도...")
                page.evaluate("""(text) => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        if (el.textContent.trim() === text && el.offsetParent !== null) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""", te['text'])
                page.wait_for_timeout(5000)
                save(page, "hp_v3_06_after_transfer_click")
                print(f"    URL: {page.url}")
                break

        # OBTComboBox / 상태 드롭다운 탐색
        combos = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('[class*="OBTDropDownList"], [class*="OBTComboBox"], [class*="combo"], [class*="Combo"], select').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0) {
                    r.push({
                        tag: el.tagName,
                        className: (el.className.substring ? el.className.substring(0, 120) : ''),
                        text: el.textContent.trim().substring(0, 80),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width)},
                    });
                }
            });
            return r;
        }""")
        save_json(combos, "hp_v3_06_combos")
        print(f"  콤보/드롭다운: {len(combos)}개")
        for c in combos:
            print(f"    \"{c['text'][:40]}\" class={c['className'][:50]}")

        # ──────────────────────────────────────────────
        # Step 7: 날짜 설정 + 조회
        # ──────────────────────────────────────────────
        print("\n[Step 7] 날짜 입력 필드 탐색 + 값 설정")
        date_inputs = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('input').forEach(el => {
                const rect = el.getBoundingClientRect();
                const val = el.value || '';
                const cls = el.className || '';
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    // 날짜 패턴 or DatePicker 클래스
                    if (val.match(/\\d{4}[-./]\\d{2}[-./]?\\d{0,2}/) ||
                        cls.includes('Date') || cls.includes('date') ||
                        cls.includes('calendar') || cls.includes('period')) {
                        r.push({
                            id: el.id, value: val, className: cls.substring(0, 100),
                            placeholder: el.placeholder || '',
                            rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width)},
                        });
                    }
                }
            });
            return r;
        }""")
        save_json(date_inputs, "hp_v3_07_date_inputs")
        print(f"  날짜 입력: {len(date_inputs)}개")
        for d in date_inputs:
            print(f"    id={d['id'][:20]} val={d['value']} ph={d['placeholder'][:20]} at ({d['rect']['x']},{d['rect']['y']})")

        # 시작일/종료일 설정 시도
        if len(date_inputs) >= 2:
            print("  날짜 설정 시도: 2025-01-01 ~ 2026-12-31")
            for i, (date_val, target) in enumerate([(date_inputs[0], "2025-01-01"), (date_inputs[1], "2026-12-31")]):
                try:
                    if date_val['id']:
                        page.evaluate(f"""() => {{
                            const el = document.getElementById('{date_val["id"]}');
                            if (el) {{
                                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                                setter.call(el, '{target}');
                                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                                el.dispatchEvent(new Event('blur', {{bubbles: true}}));
                            }}
                        }}""")
                    else:
                        # id 없으면 좌표로 포커스 후 입력
                        page.click(f"input >> nth={i}", force=True)
                        page.keyboard.press("Control+a")
                        page.keyboard.type(target)
                        page.keyboard.press("Tab")
                    print(f"    [{i}] → {target}")
                except Exception as e:
                    print(f"    [{i}] 설정 실패: {e}")

            page.wait_for_timeout(2000)

        # 조회 버튼
        print("  조회 버튼 클릭 시도")
        search_result = page.evaluate("""() => {
            const keywords = ['조회', '검색', 'Search'];
            const btns = document.querySelectorAll('button, [role="button"], [class*="btn"], [class*="Btn"]');
            for (const kw of keywords) {
                for (const btn of btns) {
                    const text = btn.textContent.trim();
                    if (text === kw || (text.includes(kw) && text.length < kw.length + 5)) {
                        if (btn.offsetParent !== null) {
                            btn.click();
                            return {clicked: text};
                        }
                    }
                }
            }
            return {error: 'no search button'};
        }""")
        print(f"  조회: {search_result}")
        page.wait_for_timeout(5000)

        save(page, "hp_v3_07_after_search")

        # 조회 후 데이터 재확인
        text7 = page.evaluate("() => document.body ? document.body.innerText.substring(0, 15000) : ''")
        with open(OUTPUT_DIR / "hp_v3_07_text.txt", "w", encoding="utf-8") as f:
            f.write(text7)
        print(f"  조회 후 텍스트 ({len(text7)}자):")
        for line in text7.split('\n')[:40]:
            line = line.strip()
            if line and len(line) > 2:
                print(f"    {line[:100]}")

        # 조회 후 테이블
        tables7 = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('table').forEach((t, i) => {
                const rect = t.getBoundingClientRect();
                if (rect.width > 100 && rect.height > 50) {
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
                    r.push({index: i, headers, rowCount: rows.length, sampleRows: sample});
                }
            });
            return r;
        }""")
        save_json(tables7, "hp_v3_07_tables")
        for t in tables7:
            print(f"    테이블[{t['index']}] {t['rowCount']}행, 헤더={t['headers'][:8]}")

        # 조회 후 그리드
        grids7 = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('[class*="OBTDataGrid"], canvas').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 50 && rect.height > 50) {
                    r.push({
                        className: (el.className?.substring ? el.className.substring(0, 150) : ''),
                        tagName: el.tagName,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return r;
        }""")
        if grids7:
            print(f"  그리드 발견: {len(grids7)}개")
            gd7 = page.evaluate("""() => {
                try {
                    const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
                    if (!gridEl) return {error: 'no grid'};
                    const fk = Object.keys(gridEl).find(k => k.startsWith('__reactFiber'));
                    if (!fk) return {error: 'no fiber'};
                    let f = gridEl[fk];
                    for (let i = 0; i < 6; i++) {
                        if (f?.stateNode?.state?.interface) {
                            const iface = f.stateNode.state.interface;
                            let rc = 0, cols = [];
                            try { rc = iface.getRowCount(); } catch(e) {}
                            try {
                                cols = iface.getColumns().map(c => ({
                                    name: c.name || c.fieldName,
                                    header: c.header?.text || c.header || '',
                                }));
                            } catch(e) {}
                            let data = [];
                            for (let r = 0; r < Math.min(50, rc); r++) {
                                const row = {};
                                cols.forEach(c => { try { row[c.name] = String(iface.getValue(r, c.name)).substring(0, 80); } catch(e) {} });
                                data.push(row);
                            }
                            return {depth: i, rowCount: rc, columns: cols, data};
                        }
                        if (f) f = f.return;
                    }
                    return {error: 'no interface'};
                } catch(e) { return {error: e.message}; }
            }""")
            save_json(gd7, "hp_v3_07_grid_data")
            print(f"  그리드: {gd7.get('rowCount', '?')}행, {len(gd7.get('columns', []))}열")

    except Exception as e:
        print(f"\n[오류] {e}")
        traceback.print_exc()
        save(page, "hp_v3_error")

    finally:
        save_json(api_calls, "hp_v3_api_calls")
        save_json(api_responses, "hp_v3_api_responses")
        print(f"\n  API 요청: {len(api_calls)}개, 응답: {len(api_responses)}개")

        unique = {}
        for c in api_calls:
            base = c['url'].split('?')[0]
            if base not in unique:
                unique[base] = c['method']
        print(f"  고유 엔드포인트 ({len(unique)}개):")
        for url, method in sorted(unique.items()):
            print(f"    [{method}] {url[:120]}")

        # API 응답 중 주요 데이터 출력
        for resp in api_responses[:10]:
            body = resp.get('body')
            if body and isinstance(body, dict):
                preview = json.dumps(body, ensure_ascii=False)[:200]
                print(f"    응답 [{resp['status']}] {resp['url'][:80]}: {preview}")

        print("\n" + "=" * 60)
        hp_files = sorted(OUTPUT_DIR.glob("hp_v3_*"))
        print(f"파일 ({len(hp_files)}개):")
        for f in hp_files:
            print(f"  {f.name:60s}  {f.stat().st_size:>8,} bytes")

        close_session(browser)


if __name__ == "__main__":
    main()
