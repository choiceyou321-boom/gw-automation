"""
HP 지출결의서 이체완료 탐색 Phase 4
스크린샷에서 발견된 LNB 구조:
- 개인지출결의서 (펼침):
  - 개인지출결의서작성
  - 개인지출결의현황  ← 이체완료 목록이 여기 있을 가능성 높음
  - 증빙자료현황
- 지출결의/계산서 (펼침 필요):
  - 하위 메뉴 확인 필요

전략: 스크롤해서 보이는 메뉴 클릭, a 태그 href로 직접 네비게이션
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
    print("HP 지출결의서 탐색 Phase 4 — 하위 메뉴 직접 접근")
    print("=" * 60)

    api_calls = []
    api_responses = []

    def on_req(req):
        url = req.url
        if any(x in url for x in ['/gw/', '/personal/', 'hp', 'HP', 'hpm', 'HPM',
                                     'eap', 'expense', 'accSlip', 'voucher', 'transfer',
                                     'getList', 'search', 'query', 'slip']):
            api_calls.append({
                "method": req.method,
                "url": url[:300],
                "post_data": req.post_data[:2000] if req.post_data else None,
            })

    def on_resp(resp):
        url = resp.url
        if any(x in url for x in ['hp', 'HP', 'hpm', 'HPM', 'personal',
                                     'expense', 'accSlip', 'slip', 'voucher', 'transfer',
                                     'getList']):
            body = None
            try:
                body = resp.json()
                bs = json.dumps(body, ensure_ascii=False)
                if len(bs) > 10000:
                    body = {"_truncated": True, "_size": len(bs),
                            "_keys": list(body.keys()) if isinstance(body, dict) else None,
                            "_preview": bs[:5000]}
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
        # Step 1: HPM0110 진입 + LNB 전체 구조 (a 태그 href 포함)
        # ──────────────────────────────────────────────
        print("\n[Step 1] HPM0110 진입 → LNB a 태그 href 추출")
        page.goto(f"{GW_URL}/#/HP/HPM0110/HPM0110", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        close_popups(page)

        # LNB 내 모든 a 태그 + 클릭 가능한 요소의 href 추출
        lnb_links = page.evaluate("""() => {
            const result = [];
            // 모든 nav-item 내 a 태그
            document.querySelectorAll('.nav-item a, .lnb a, [class*="lnb"] a, [class*="side"] a, [class*="menu"] a').forEach(el => {
                if (el.offsetParent !== null) {
                    result.push({
                        text: el.textContent.trim().substring(0, 50),
                        href: el.href || el.getAttribute('href') || '',
                        className: el.className.substring ? el.className.substring(0, 100) : '',
                        parentClass: el.parentElement ? (el.parentElement.className.substring ? el.parentElement.className.substring(0, 80) : '') : '',
                    });
                }
            });
            return result;
        }""")
        save_json(lnb_links, "hp_v4_01_lnb_links")
        print(f"  LNB 링크: {len(lnb_links)}개")
        for link in lnb_links:
            print(f"    {link['text'][:30]:30s}  href={link['href'][:80]}")

        # nav-item 전체 트리 구조 (부모-자식 관계 포함)
        full_tree = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('.nav-item').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    // 자식 nav-item 제외한 직접 텍스트
                    const clone = el.cloneNode(true);
                    clone.querySelectorAll('.nav-item, ul').forEach(c => c.remove());
                    const text = clone.textContent.trim().substring(0, 50);

                    // a 태그 href
                    const link = el.querySelector(':scope > a');
                    const href = link ? (link.href || link.getAttribute('href') || '') : '';

                    result.push({
                        text: text,
                        className: el.className,
                        href: href,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return result;
        }""")
        save_json(full_tree, "hp_v4_01_nav_tree")
        print(f"\n  Nav 트리: {len(full_tree)}개")
        for item in full_tree:
            cls = item['className']
            step = ""
            if "step-3" in cls: step = "      "
            elif "step-2" in cls: step = "    "
            elif "step-1" in cls: step = "  "
            flag = ""
            if "open" in cls: flag = " [O]"
            elif "close" in cls: flag = " [C]"
            if "selected" in cls: flag += " [S]"
            href_info = f"  → {item['href'][:60]}" if item['href'] else ""
            print(f"  {step}{item['text'][:40]:40s}{flag}{href_info}")

        # ──────────────────────────────────────────────
        # Step 2: "개인지출결의서" 펼치기 (step-1 클릭)
        # ──────────────────────────────────────────────
        print("\n[Step 2] '개인지출결의서' 메뉴 펼치기")
        # 스크린샷에서 보면 이미 펼쳐져 있었으나, 여기서는 close 상태
        # step-1 클릭 시 toggle
        toggle_result = page.evaluate("""() => {
            const items = document.querySelectorAll('.nav-item.step-1');
            const results = [];
            for (const el of items) {
                const clone = el.cloneNode(true);
                clone.querySelectorAll('.nav-item, ul').forEach(c => c.remove());
                const text = clone.textContent.trim();
                if (text.includes('개인지출결의서')) {
                    // 닫혀있으면 클릭
                    if (el.className.includes('close')) {
                        const toggle = el.querySelector(':scope > .btn-toggle, :scope > a, :scope > span, :scope > div');
                        if (toggle) toggle.click();
                        else el.click();
                        results.push({clicked: text, wasClose: true});
                    } else {
                        results.push({alreadyOpen: text});
                    }
                }
                if (text.includes('지출결의/계산서')) {
                    if (el.className.includes('close')) {
                        const toggle = el.querySelector(':scope > .btn-toggle, :scope > a, :scope > span, :scope > div');
                        if (toggle) toggle.click();
                        else el.click();
                        results.push({clicked: text, wasClose: true});
                    } else {
                        results.push({alreadyOpen: text});
                    }
                }
            }
            return results;
        }""")
        print(f"  토글 결과: {toggle_result}")
        page.wait_for_timeout(2000)

        # 펼친 후 다시 트리 확인
        tree2 = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('.nav-item').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    const clone = el.cloneNode(true);
                    clone.querySelectorAll('.nav-item, ul').forEach(c => c.remove());
                    const text = clone.textContent.trim().substring(0, 50);
                    const link = el.querySelector(':scope > a');
                    const href = link ? (link.href || link.getAttribute('href') || '') : '';
                    result.push({
                        text: text, className: el.className, href: href,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                    });
                }
            });
            return result;
        }""")
        save_json(tree2, "hp_v4_02_tree_expanded")
        save(page, "hp_v4_02_expanded")
        print(f"  펼친 후 트리: {len(tree2)}개")
        for item in tree2:
            cls = item['className']
            step = ""
            if "step-3" in cls: step = "      "
            elif "step-2" in cls: step = "    "
            elif "step-1" in cls: step = "  "
            flag = ""
            if "open" in cls: flag = " [O]"
            elif "close" in cls: flag = " [C]"
            if "selected" in cls: flag += " [S]"
            href_info = f"  → {item['href'][:60]}" if item['href'] else ""
            print(f"  {step}{item['text'][:40]:40s}{flag}{href_info}")

        # ──────────────────────────────────────────────
        # Step 3: "개인지출결의현황" 클릭
        # ──────────────────────────────────────────────
        print("\n[Step 3] '개인지출결의현황' 클릭")
        api_calls.clear()
        api_responses.clear()

        nav_result = page.evaluate("""() => {
            const items = document.querySelectorAll('.nav-item');
            for (const el of items) {
                const clone = el.cloneNode(true);
                clone.querySelectorAll('.nav-item, ul').forEach(c => c.remove());
                const text = clone.textContent.trim();
                if (text.includes('개인지출결의현황') || text.includes('결의현황') || text.includes('결의서현황')) {
                    const link = el.querySelector('a') || el;
                    link.click();
                    return {clicked: text, href: link.href || link.getAttribute('href') || ''};
                }
            }
            // 없으면 "지출결의현황" 등 시도
            for (const el of items) {
                const clone = el.cloneNode(true);
                clone.querySelectorAll('.nav-item, ul').forEach(c => c.remove());
                const text = clone.textContent.trim();
                if (text.includes('지출') && text.includes('현황')) {
                    const link = el.querySelector('a') || el;
                    link.click();
                    return {clicked: text, href: link.href || link.getAttribute('href') || ''};
                }
            }
            return {error: 'not found'};
        }""")
        print(f"  결과: {nav_result}")
        page.wait_for_timeout(6000)
        close_popups(page)
        print(f"  URL: {page.url}")

        save(page, "hp_v4_03_expense_status")

        text3 = page.evaluate("() => document.body ? document.body.innerText.substring(0, 15000) : ''")
        with open(OUTPUT_DIR / "hp_v4_03_text.txt", "w", encoding="utf-8") as f:
            f.write(text3)

        # 핵심 텍스트 라인 출력
        print(f"  페이지 텍스트 ({len(text3)}자):")
        for line in text3.split('\n'):
            line = line.strip()
            if line and len(line) > 2 and not any(x in line for x in ['위로', '아래로', '부가서비스', 'ONEFFICE', 'ONECHAMBER', '오피스케어']):
                print(f"    {line[:100]}")

        # ──────────────────────────────────────────────
        # Step 4: 페이지 분석 — 탭, 버튼, 그리드, 필터
        # ──────────────────────────────────────────────
        print("\n[Step 4] 페이지 DOM 분석")

        # 상단 탭 (컨텐츠 영역)
        content_tabs = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('.tab-item, [class*="OBTTabs_tab"], [role="tab"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0 && rect.x > 200) {
                    // 컨텐츠 영역 (x > 200은 LNB 우측)
                    r.push({
                        text: el.textContent.trim().substring(0, 50),
                        className: (el.className.substring ? el.className.substring(0, 100) : ''),
                        selected: el.className.includes('on') || el.className.includes('selected') || el.className.includes('Selected') || el.getAttribute('aria-selected') === 'true',
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                    });
                }
            });
            return r;
        }""")
        save_json(content_tabs, "hp_v4_04_content_tabs")
        print(f"  컨텐츠 탭: {len(content_tabs)}개")
        for t in content_tabs:
            sel = " [SEL]" if t['selected'] else ""
            print(f"    \"{t['text'][:40]}\"{sel}")

        # 버튼
        content_buttons = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('button, [role="button"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0 && rect.x > 200) {
                    const text = el.textContent.trim().substring(0, 60);
                    if (text) {
                        r.push({text, id: el.id, className: (el.className.substring ? el.className.substring(0, 100) : ''),
                                rect: {x: Math.round(rect.x), y: Math.round(rect.y)}});
                    }
                }
            });
            return r;
        }""")
        save_json(content_buttons, "hp_v4_04_buttons")
        print(f"  버튼: {len(content_buttons)}개")
        for b in content_buttons[:20]:
            print(f"    \"{b['text'][:50]}\" id={b['id'][:20]}")

        # visible input
        vis_inputs = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('input, select, textarea').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0 && rect.x > 200) {
                    r.push({
                        tag: el.tagName.toLowerCase(), id: el.id, name: el.name,
                        type: el.type || '', value: el.value ? el.value.substring(0, 50) : '',
                        placeholder: el.placeholder || '', disabled: el.disabled,
                        className: (el.className.substring ? el.className.substring(0, 100) : ''),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width)},
                    });
                }
            });
            return r;
        }""")
        save_json(vis_inputs, "hp_v4_04_inputs")
        print(f"  visible 입력 (x>200): {len(vis_inputs)}개")
        for inp in vis_inputs:
            print(f"    {inp['tag']}[{inp['type']}] id={inp['id'][:20]} val={inp['value'][:30]} ph={inp['placeholder'][:20]} at ({inp['rect']['x']},{inp['rect']['y']})")

        # 테이블
        tables = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('table').forEach((t, i) => {
                const rect = t.getBoundingClientRect();
                if (rect.width > 100 && rect.height > 50 && rect.x > 200) {
                    const headers = [];
                    t.querySelectorAll('thead th, thead td, tr:first-child th').forEach(h => {
                        headers.push(h.textContent.trim().substring(0, 40));
                    });
                    const rows = t.querySelectorAll('tbody tr');
                    const sample = [];
                    for (let j = 0; j < Math.min(5, rows.length); j++) {
                        const cells = [];
                        rows[j].querySelectorAll('td').forEach(td => cells.push(td.textContent.trim().substring(0, 60)));
                        sample.push(cells);
                    }
                    r.push({index: i, headers, rowCount: rows.length, sampleRows: sample});
                }
            });
            return r;
        }""")
        save_json(tables, "hp_v4_04_tables")
        print(f"  테이블 (x>200): {len(tables)}개")
        for t in tables:
            print(f"    [{t['index']}] {t['rowCount']}행, 헤더={t['headers'][:10]}")
            for sr in t['sampleRows'][:3]:
                print(f"      {sr[:8]}")

        # 그리드
        grids = page.evaluate("""() => {
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
        save_json(grids, "hp_v4_04_grids")
        print(f"  그리드: {len(grids)}개")
        for g in grids:
            print(f"    {g['tagName']} class={g['className'][:60]} at ({g['rect']['x']},{g['rect']['y']}) {g['rect']['w']}x{g['rect']['h']}")

        if grids:
            grid_data = page.evaluate("""() => {
                try {
                    const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
                    if (!gridEl) return {error: 'no OBTDataGrid'};
                    const fk = Object.keys(gridEl).find(k => k.startsWith('__reactFiber'));
                    if (!fk) return {error: 'no fiber'};
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
                                }));
                            } catch(e) {}
                            let data = [];
                            for (let r = 0; r < Math.min(100, rc); r++) {
                                const row = {};
                                cols.forEach(c => {
                                    try { row[c.name] = String(iface.getValue(r, c.name)).substring(0, 100); } catch(e) {}
                                });
                                data.push(row);
                            }
                            return {depth: i, rowCount: rc, columns: cols, data};
                        }
                        if (f) f = f.return;
                    }
                    return {error: 'no interface in 8 depths'};
                } catch(e) { return {error: e.message}; }
            }""")
            save_json(grid_data, "hp_v4_04_grid_data")
            print(f"  그리드 데이터: {grid_data.get('rowCount', '?')}행, {len(grid_data.get('columns', []))}열")
            if grid_data.get('columns'):
                print(f"  컬럼: {[c['header'] or c['name'] for c in grid_data['columns'][:15]]}")
            if grid_data.get('data'):
                for row in grid_data['data'][:5]:
                    print(f"    → {json.dumps(row, ensure_ascii=False)[:120]}")

        # ──────────────────────────────────────────────
        # Step 5: 이체완료 탭/필터 탐색 + 상태 드롭다운
        # ──────────────────────────────────────────────
        print("\n[Step 5] 이체/상태 필터 탐색")

        # 상태 관련 모든 leaf 요소 (이체, 지급, 완료, 상태, 진행, 처리)
        status_els = page.evaluate("""() => {
            const r = [];
            const keywords = ['이체', '지급', '완료', '처리', '상태', '진행', '전체', '미처리', '대기'];
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
            while (walker.nextNode()) {
                const el = walker.currentNode;
                if (el.children.length === 0 || ['SPAN', 'BUTTON', 'A', 'OPTION', 'LABEL', 'LI', 'DIV'].includes(el.tagName)) {
                    const text = el.textContent.trim();
                    if (text.length > 0 && text.length < 20) {
                        for (const kw of keywords) {
                            if (text.includes(kw)) {
                                const rect = el.getBoundingClientRect();
                                if (el.offsetParent !== null && rect.width > 0 && rect.x > 200) {
                                    r.push({
                                        text, tag: el.tagName,
                                        className: (el.className?.substring ? el.className.substring(0, 80) : ''),
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
        save_json(status_els, "hp_v4_05_status_elements")
        print(f"  상태 관련 요소: {len(status_els)}개")
        for se in status_els[:20]:
            print(f"    \"{se['text']}\" ({se['tag']}) at ({se['rect']['x']},{se['rect']['y']})")

        # OBTDropDownList / select
        dropdowns = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('[class*="DropDown"], [class*="dropdown"], [class*="Combo"], [class*="combo"], select').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.x > 200) {
                    let options = [];
                    if (el.tagName === 'SELECT') {
                        el.querySelectorAll('option').forEach(o => options.push({v: o.value, t: o.textContent.trim()}));
                    }
                    r.push({
                        tag: el.tagName, className: (el.className?.substring ? el.className.substring(0, 120) : ''),
                        text: el.textContent.trim().substring(0, 60), options,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width)},
                    });
                }
            });
            return r;
        }""")
        save_json(dropdowns, "hp_v4_05_dropdowns")
        print(f"  드롭다운: {len(dropdowns)}개")
        for d in dropdowns:
            print(f"    \"{d['text'][:40]}\" class={d['className'][:50]}")

        # ──────────────────────────────────────────────
        # Step 6: "이체완료" 클릭 or 상태 변경
        # ──────────────────────────────────────────────
        print("\n[Step 6] 이체완료 필터/탭 클릭 시도")
        for te in status_els:
            if '이체완료' in te['text']:
                print(f"  '이체완료' 클릭 시도 ({te['tag']} at {te['rect']})")
                page.evaluate(f"""() => {{
                    const els = document.querySelectorAll('{te["tag"]}');
                    for (const el of els) {{
                        if (el.textContent.trim() === '{te["text"]}' && el.offsetParent !== null) {{
                            el.click();
                            return true;
                        }}
                    }}
                    return false;
                }}""")
                page.wait_for_timeout(5000)
                save(page, "hp_v4_06_after_transfer_click")
                break

        # 날짜 범위
        date_inputs = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('input').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.x > 200) {
                    const val = el.value || '';
                    const cls = el.className || '';
                    if (val.match(/\\d{4}[-./]\\d{2}/) || cls.includes('Date') || cls.includes('date') || cls.includes('OBTDate')) {
                        r.push({id: el.id, value: val, className: cls.substring(0, 80),
                                rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width)}});
                    }
                }
            });
            return r;
        }""")
        save_json(date_inputs, "hp_v4_06_date_inputs")
        print(f"  날짜 입력: {len(date_inputs)}개")
        for d in date_inputs:
            print(f"    id={d['id'][:20]} val={d['value']} at ({d['rect']['x']},{d['rect']['y']})")

        # ──────────────────────────────────────────────
        # Step 7: iframe 내부 탐색 (더존은 iframe 사용 많음)
        # ──────────────────────────────────────────────
        print("\n[Step 7] iframe 탐색")
        frames = page.frames
        print(f"  프레임: {len(frames)}개")
        for i, frame in enumerate(frames):
            try:
                furl = frame.url
                print(f"    [{i}] name={frame.name} url={furl[:100]}")
                if furl and furl != "about:blank" and i > 0:
                    ft = frame.evaluate("() => document.body ? document.body.innerText.substring(0, 3000) : ''")
                    if ft.strip():
                        print(f"      텍스트: {ft[:200]}...")
                        with open(OUTPUT_DIR / f"hp_v4_07_frame{i}_text.txt", "w", encoding="utf-8") as f:
                            f.write(ft)
            except Exception as e:
                print(f"    [{i}] 오류: {e}")

    except Exception as e:
        print(f"\n[오류] {e}")
        traceback.print_exc()
        save(page, "hp_v4_error")

    finally:
        save_json(api_calls, "hp_v4_api_calls")
        save_json(api_responses, "hp_v4_api_responses")
        print(f"\n  API 요청: {len(api_calls)}개, 응답: {len(api_responses)}개")

        unique = {}
        for c in api_calls:
            base = c['url'].split('?')[0]
            if base not in unique:
                unique[base] = {"method": c['method'], "post_data": (c.get('post_data') or '')[:200]}
        print(f"  고유 엔드포인트 ({len(unique)}개):")
        for url, info in sorted(unique.items()):
            pd = f" | {info['post_data'][:80]}" if info['post_data'] else ""
            print(f"    [{info['method']}] {url[:120]}{pd}")

        for resp in api_responses[:10]:
            body = resp.get('body')
            if body:
                preview = json.dumps(body, ensure_ascii=False)[:200] if isinstance(body, (dict, list)) else str(body)[:200]
                print(f"    응답 [{resp['status']}] {resp['url'][:80]}: {preview}")

        print("\n" + "=" * 60)
        hp_files = sorted(OUTPUT_DIR.glob("hp_v4_*"))
        print(f"파일 ({len(hp_files)}개):")
        for f in hp_files:
            print(f"  {f.name:60s}  {f.stat().st_size:>8,} bytes")

        close_session(browser)


if __name__ == "__main__":
    main()
