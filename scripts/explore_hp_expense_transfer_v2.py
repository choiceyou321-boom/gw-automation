"""
HP(임직원업무관리) - 지출결의서 이체완료 탐색 Phase 2
Phase 1에서 발견:
- HP 모듈 URL: /#/HP/HPM0110/HPM0110
- LNB 메뉴: "지출결의/계산서" (step-1, nav-item-close), "개인지출결의서" (step-1)
- 이 메뉴들은 접혀있음 (nav-item-close)

이번 탐색:
1. HP 모듈 진입
2. "지출결의/계산서" 메뉴 클릭 → 하위 메뉴 확인
3. "개인지출결의서" 메뉴 클릭
4. 지출결의서 목록 페이지에서 이체완료 탭/필터 찾기
5. 기간 설정 + 조회 + 데이터 구조 파악
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


def save_screenshot(page, name: str):
    path = OUTPUT_DIR / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        print(f"  [스크린샷] {path.name}")
    except Exception as e:
        print(f"  [스크린샷 실패] {name}: {e}")


def dump_json(data, name: str):
    path = OUTPUT_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [저장] {path.name}")
    return path


def close_popups(page, wait_ms=2000):
    try:
        pages = page.context.pages
        closed = 0
        for p in pages:
            try:
                if "popup" in p.url.lower() or "notice" in p.url.lower():
                    p.close()
                    closed += 1
            except Exception:
                pass
        if closed:
            print(f"  [팝업] {closed}개 닫음")
        page.wait_for_timeout(wait_ms)
    except Exception:
        pass


def extract_visible_text(page):
    """페이지 전체 텍스트"""
    try:
        return page.evaluate("() => document.body ? document.body.innerText.substring(0, 15000) : ''")
    except Exception:
        return ""


def extract_all_elements(page_or_frame, prefix=""):
    """모든 visible 요소 추출 (버튼, 입력, 탭, 테이블, 그리드)"""
    result = {}

    # 버튼
    try:
        btns = page_or_frame.evaluate("""() => {
            const r = [];
            document.querySelectorAll('button, [role="button"], [class*="btn"], [class*="Btn"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    r.push({
                        text: el.textContent.trim().substring(0, 80),
                        tag: el.tagName.toLowerCase(),
                        id: el.id, className: (el.className.substring ? el.className.substring(0, 150) : ''),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return r;
        }""")
        result['buttons'] = btns
    except Exception as e:
        result['buttons'] = []
        print(f"    {prefix}버튼 추출 실패: {e}")

    # 입력 필드
    try:
        inputs = page_or_frame.evaluate("""() => {
            const r = [];
            document.querySelectorAll('input, select, textarea').forEach(el => {
                const rect = el.getBoundingClientRect();
                r.push({
                    tag: el.tagName.toLowerCase(), id: el.id, name: el.name,
                    type: el.type || '', placeholder: el.placeholder || '',
                    disabled: el.disabled,
                    visible: el.offsetParent !== null && rect.width > 0,
                    value: el.value ? el.value.substring(0, 80) : '',
                    className: (el.className.substring ? el.className.substring(0, 120) : ''),
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                });
            });
            return r;
        }""")
        result['inputs'] = inputs
    except Exception as e:
        result['inputs'] = []
        print(f"    {prefix}입력 추출 실패: {e}")

    # 탭
    try:
        tabs = page_or_frame.evaluate("""() => {
            const r = [];
            document.querySelectorAll('[role="tab"], [class*="tab"], [class*="Tab"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    r.push({
                        text: el.textContent.trim().substring(0, 80),
                        id: el.id,
                        className: (el.className.substring ? el.className.substring(0, 150) : ''),
                        ariaSelected: el.getAttribute('aria-selected') || '',
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return r;
        }""")
        result['tabs'] = tabs
    except Exception as e:
        result['tabs'] = []

    # 테이블
    try:
        tables = page_or_frame.evaluate("""() => {
            const r = [];
            document.querySelectorAll('table').forEach((table, idx) => {
                const rect = table.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    const headers = [];
                    table.querySelectorAll('thead th, thead td, tr:first-child th').forEach(th => {
                        headers.push(th.textContent.trim().substring(0, 50));
                    });
                    const rows = table.querySelectorAll('tbody tr');
                    const sampleRows = [];
                    for (let i = 0; i < Math.min(5, rows.length); i++) {
                        const cells = [];
                        rows[i].querySelectorAll('td').forEach(td => {
                            cells.push(td.textContent.trim().substring(0, 60));
                        });
                        sampleRows.push(cells);
                    }
                    r.push({index: idx, headers, rowCount: rows.length, sampleRows,
                            className: table.className.substring(0, 100),
                            rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}});
                }
            });
            return r;
        }""")
        result['tables'] = tables
    except Exception as e:
        result['tables'] = []

    # OBTDataGrid
    try:
        grids = page_or_frame.evaluate("""() => {
            const r = [];
            document.querySelectorAll('[class*="OBTDataGrid"], [class*="RealGrid"], canvas').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 50 && rect.height > 50) {
                    r.push({
                        className: (el.className.substring ? el.className.substring(0, 150) : ''),
                        tagName: el.tagName,
                        hasCanvas: el.querySelector ? el.querySelector('canvas') !== null : (el.tagName === 'CANVAS'),
                        hasReactFiber: Object.keys(el).some(k => k.startsWith('__reactFiber')),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return r;
        }""")
        result['grids'] = grids
    except Exception as e:
        result['grids'] = []

    return result


def extract_grid_data(page_or_frame):
    """OBTDataGrid React Fiber를 통해 그리드 데이터 추출"""
    try:
        return page_or_frame.evaluate("""() => {
            try {
                const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
                if (!gridEl) return {error: 'OBTDataGrid not found'};

                const fiberKey = Object.keys(gridEl).find(k => k.startsWith('__reactFiber'));
                if (!fiberKey) return {error: 'No __reactFiber key'};

                let fiber = gridEl[fiberKey];
                for (let i = 0; i < 6; i++) {
                    if (fiber && fiber.stateNode && fiber.stateNode.state && fiber.stateNode.state.interface) {
                        const iface = fiber.stateNode.state.interface;
                        let rowCount = 0;
                        let columns = [];
                        try { rowCount = iface.getRowCount(); } catch(e) {}
                        try {
                            const cols = iface.getColumns();
                            columns = cols.map(c => ({
                                name: c.name || c.fieldName,
                                header: c.header && c.header.text ? c.header.text : (c.header || c.fieldName),
                                width: c.width,
                                visible: c.visible !== false,
                            }));
                        } catch(e) {}

                        // 모든 행 데이터 (최대 50행)
                        let allData = [];
                        try {
                            const maxRows = Math.min(rowCount, 50);
                            for (let r = 0; r < maxRows; r++) {
                                const row = {};
                                columns.forEach(col => {
                                    try {
                                        row[col.name] = String(iface.getValue(r, col.name)).substring(0, 80);
                                    } catch(e) {}
                                });
                                allData.push(row);
                            }
                        } catch(e) {}

                        return {depth: i, rowCount, columns, sampleData: allData};
                    }
                    if (fiber) fiber = fiber.return;
                }
                return {error: 'interface not found within 6 depths'};
            } catch(e) {
                return {error: e.message};
            }
        }""")
    except Exception as e:
        return {"error": str(e)}


def extract_lnb_menu(page):
    """좌측 메뉴 상세 추출"""
    try:
        return page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('.nav-item').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0) {
                    // 직접 텍스트만 추출 (자식 제외)
                    let directText = '';
                    for (const node of el.childNodes) {
                        if (node.nodeType === 3) directText += node.textContent.trim();
                        if (node.nodeType === 1 && node.tagName !== 'UL') {
                            directText += node.textContent.trim();
                        }
                    }
                    // 너무 길면 자식 포함이므로 첫 번째 텍스트 요소만
                    if (directText.length > 50) {
                        const spans = el.querySelectorAll(':scope > span, :scope > a, :scope > div');
                        if (spans.length > 0) directText = spans[0].textContent.trim();
                    }
                    result.push({
                        text: directText.substring(0, 50),
                        fullText: el.textContent.trim().substring(0, 100),
                        className: el.className,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return result;
        }""")
    except Exception as e:
        print(f"  메뉴 추출 실패: {e}")
        return []


def main():
    print("=" * 60)
    print("HP 지출결의서 이체완료 탐색 Phase 2")
    print("=" * 60)

    api_calls = []
    api_responses = []

    def on_request(req):
        url = req.url
        if any(x in url for x in ['/api/', '/rs', '/gw/', 'hp', 'HP', 'eap', 'EAP',
                                     'accSlip', 'voucher', 'expense', 'transfer',
                                     'personal', 'Rest', 'Svc']):
            entry = {
                "method": req.method,
                "url": url[:300],
                "post_data": req.post_data[:1000] if req.post_data else None,
            }
            api_calls.append(entry)

    def on_response(resp):
        url = resp.url
        # HP/personal 관련 + 주요 API 응답만 캡처
        if any(x in url for x in ['hp', 'HP', 'personal', 'accSlip', 'voucher',
                                     'expense', 'transfer', 'eap', 'EAP',
                                     'hpm', 'HPM', 'list', 'search', 'query']):
            body = None
            try:
                body = resp.json()
                body_str = json.dumps(body, ensure_ascii=False)
                if len(body_str) > 10000:
                    body = {"_truncated": True, "_size": len(body_str), "_preview": body_str[:3000]}
            except Exception:
                try:
                    body = resp.text()[:3000]
                except Exception:
                    pass
            api_responses.append({
                "status": resp.status,
                "url": url[:300],
                "body": body,
            })

    # 로그인
    print("\n[로그인]")
    browser, context, page = login_and_get_context(headless=False)
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.on("dialog", lambda d: d.accept())
    page.on("request", on_request)
    page.on("response", on_response)

    results = {}

    try:
        page.wait_for_timeout(3000)
        close_popups(page)

        # ──────────────────────────────────────────────
        # Step 1: HP 모듈 진입
        # ──────────────────────────────────────────────
        print("\n[Step 1] HP 모듈 진입")
        page.goto(f"{GW_URL}/#/HP", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        close_popups(page)
        print(f"  URL: {page.url}")
        save_screenshot(page, "hp_exp_v2_01_hp_home")

        # LNB 메뉴 확인
        menu = extract_lnb_menu(page)
        dump_json(menu, "hp_exp_v2_01_menu")
        print("  좌측 메뉴:")
        for m in menu:
            sel = " [SELECTED]" if "selected" in m.get('className', '') else ""
            open_close = " [OPEN]" if "open" in m.get('className', '') else (" [CLOSE]" if "close" in m.get('className', '') else "")
            print(f"    {m['text'][:40]}{sel}{open_close}  class={m['className'][:40]}")

        # ──────────────────────────────────────────────
        # Step 2: "경비청구" 메뉴 클릭 (지출결의서가 여기 하위일 수 있음)
        # ──────────────────────────────────────────────
        print("\n[Step 2] '경비청구' 메뉴 펼치기")
        clicked = page.evaluate("""() => {
            const items = document.querySelectorAll('.nav-item');
            for (const el of items) {
                const text = el.textContent.trim();
                // step-1 레벨의 "경비청구" 항목
                if (el.className.includes('step-1') && text.startsWith('경비청구')) {
                    el.click();
                    return '경비청구 clicked';
                }
            }
            return false;
        }""")
        print(f"  결과: {clicked}")
        page.wait_for_timeout(3000)
        save_screenshot(page, "hp_exp_v2_02_after_expense_click")

        menu2 = extract_lnb_menu(page)
        dump_json(menu2, "hp_exp_v2_02_menu")
        print("  메뉴 변화:")
        for m in menu2:
            if "경비" in m['text'] or "지출" in m['text'] or "이체" in m['text'] or "결의" in m['text']:
                open_close = " [OPEN]" if "open" in m.get('className', '') else (" [CLOSE]" if "close" in m.get('className', '') else "")
                print(f"    ★ {m['text'][:40]}{open_close}  class={m['className'][:60]}")

        # ──────────────────────────────────────────────
        # Step 3: "지출결의/계산서" 메뉴 클릭
        # ──────────────────────────────────────────────
        print("\n[Step 3] '지출결의/계산서' 메뉴 클릭")
        clicked = page.evaluate("""() => {
            const items = document.querySelectorAll('.nav-item');
            for (const el of items) {
                const spans = el.querySelectorAll(':scope > span, :scope > a, :scope > div');
                for (const s of spans) {
                    if (s.textContent.trim().includes('지출결의/계산서') || s.textContent.trim().includes('지출결의')) {
                        el.click();
                        return 'clicked: ' + s.textContent.trim().substring(0, 40);
                    }
                }
                // 직접 텍스트 비교
                let directText = '';
                for (const node of el.childNodes) {
                    if (node.nodeType === 3) directText += node.textContent.trim();
                }
                if (directText.includes('지출결의')) {
                    el.click();
                    return 'clicked direct: ' + directText.substring(0, 40);
                }
            }
            return false;
        }""")
        print(f"  결과: {clicked}")
        page.wait_for_timeout(3000)
        save_screenshot(page, "hp_exp_v2_03_after_voucher_click")

        menu3 = extract_lnb_menu(page)
        dump_json(menu3, "hp_exp_v2_03_menu")
        print("  메뉴:")
        for m in menu3:
            cls = m.get('className', '')
            if any(kw in m['fullText'] for kw in ['지출', '결의', '이체', '경비', '계산서', '전표']):
                open_close = " [OPEN]" if "open" in cls else (" [CLOSE]" if "close" in cls else "")
                print(f"    ★ {m['text'][:50]}{open_close}  full={m['fullText'][:60]}")

        # ──────────────────────────────────────────────
        # Step 4: "개인지출결의서" 메뉴 클릭
        # ──────────────────────────────────────────────
        print("\n[Step 4] '개인지출결의서' 메뉴 클릭")
        clicked = page.evaluate("""() => {
            const items = document.querySelectorAll('.nav-item');
            for (const el of items) {
                const text = el.textContent.trim();
                if (text === '개인지출결의서' || text.startsWith('개인지출결의서')) {
                    el.click();
                    return 'clicked: ' + text.substring(0, 40);
                }
            }
            // 텍스트 포함 검색
            for (const el of items) {
                if (el.textContent.trim().includes('개인지출결의서')) {
                    // 가장 깊은(가장 좁은) 요소 클릭
                    const deepest = el.querySelector('span, a') || el;
                    deepest.click();
                    return 'clicked deepest: ' + deepest.textContent.trim().substring(0, 40);
                }
            }
            return false;
        }""")
        print(f"  결과: {clicked}")
        page.wait_for_timeout(5000)
        close_popups(page)
        print(f"  URL: {page.url}")
        results["expense_list_url"] = page.url

        save_screenshot(page, "hp_exp_v2_04_expense_list")
        text4 = extract_visible_text(page)
        with open(OUTPUT_DIR / "hp_exp_v2_04_text.txt", "w", encoding="utf-8") as f:
            f.write(text4)
        print(f"  페이지 텍스트 ({len(text4)}자):")
        for line in text4.split('\n')[:30]:
            if line.strip():
                print(f"    {line.strip()[:80]}")

        els4 = extract_all_elements(page, prefix="04_")
        dump_json(els4, "hp_exp_v2_04_elements")
        print(f"  버튼: {len(els4['buttons'])}개, 입력: {len(els4['inputs'])}개")
        print(f"  탭: {len(els4['tabs'])}개, 테이블: {len(els4['tables'])}개, 그리드: {len(els4['grids'])}개")

        # 버튼 텍스트 출력
        for b in els4['buttons']:
            if b['text'].strip():
                print(f"    버튼: \"{b['text'][:60]}\" (id={b['id']})")
        # 탭 출력
        for t in els4['tabs']:
            sel = " [SEL]" if t.get('ariaSelected') == 'true' else ""
            print(f"    탭: \"{t['text'][:60]}\"{sel}")

        # ──────────────────────────────────────────────
        # Step 5: 모든 하위 메뉴 시도 - "지출결의/계산서" 펼쳐서 하위 항목 확인
        # ──────────────────────────────────────────────
        print("\n[Step 5] 지출결의/계산서 하위 메뉴 전체 탐색")

        # 먼저 현재 메뉴 상태에서 step-2, step-3 항목 확인
        sub_menus = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('.nav-item').forEach(el => {
                const cls = el.className || '';
                if (cls.includes('step-2') || cls.includes('step-3')) {
                    const rect = el.getBoundingClientRect();
                    if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                        // 첫 번째 텍스트 자식만
                        let text = '';
                        const direct = el.querySelector(':scope > span, :scope > a');
                        if (direct) text = direct.textContent.trim();
                        else text = el.textContent.trim().substring(0, 50);
                        result.push({
                            text: text,
                            fullText: el.textContent.trim().substring(0, 80),
                            className: cls,
                            rect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                        });
                    }
                }
            });
            return result;
        }""")
        dump_json(sub_menus, "hp_exp_v2_05_sub_menus")
        print(f"  하위 메뉴: {len(sub_menus)}개")
        for sm in sub_menus:
            print(f"    - {sm['text'][:50]}  class={sm['className'][:40]}")

        # "지출결의/계산서"가 펼쳐져 있으면 하위 메뉴 중 "이체" 관련 항목 클릭
        # 없으면 다른 메뉴 시도
        target_keywords = ['이체완료', '이체현황', '이체', '결의서현황', '결의현황', '결의서목록',
                           '지급현황', '지급완료', '지급', '조회']

        found_transfer = False
        for kw in target_keywords:
            for sm in sub_menus:
                if kw in sm['text'] or kw in sm['fullText']:
                    print(f"    ★ '{kw}' 발견! → {sm['text']}")
                    found_transfer = True
                    # 클릭
                    page.evaluate(f"""() => {{
                        const items = document.querySelectorAll('.nav-item');
                        for (const el of items) {{
                            if (el.textContent.trim().includes('{kw}')) {{
                                el.click();
                                return true;
                            }}
                        }}
                        return false;
                    }}""")
                    page.wait_for_timeout(5000)
                    break
            if found_transfer:
                break

        if not found_transfer:
            print("  이체 관련 하위 메뉴 못 찾음. 현재 페이지에서 탭/필터 탐색...")

        # ──────────────────────────────────────────────
        # Step 6: 현재 페이지 상세 탐색 (탭, 필터, 상태 셀렉트 등)
        # ──────────────────────────────────────────────
        print("\n[Step 6] 현재 페이지 상세 탐색")
        save_screenshot(page, "hp_exp_v2_06_current")
        print(f"  URL: {page.url}")

        text6 = extract_visible_text(page)
        with open(OUTPUT_DIR / "hp_exp_v2_06_text.txt", "w", encoding="utf-8") as f:
            f.write(text6)

        # 탭/상태 필터 상세 추출
        status_filters = page.evaluate("""() => {
            const result = [];
            // 다양한 상태 필터 패턴
            const patterns = [
                '[class*="status"]', '[class*="Status"]',
                '[class*="state"]', '[class*="State"]',
                '[class*="filter"]', '[class*="Filter"]',
                '[class*="radio"]', '[class*="Radio"]',
                '[class*="check"]', '[class*="Check"]',
                '[class*="combo"]', '[class*="Combo"]',
                '[class*="select"]', '[class*="Select"]',
                'label', '[class*="label"]',
            ];
            const seen = new Set();
            for (const pat of patterns) {
                document.querySelectorAll(pat).forEach(el => {
                    const text = el.textContent.trim().substring(0, 80);
                    const key = text + el.className;
                    if (text && !seen.has(key) && el.offsetParent !== null) {
                        seen.add(key);
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            result.push({
                                text: text,
                                tag: el.tagName,
                                className: (el.className.substring ? el.className.substring(0, 120) : ''),
                                rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                            });
                        }
                    }
                });
            }
            return result;
        }""")
        dump_json(status_filters, "hp_exp_v2_06_status_filters")
        print(f"  상태/필터 요소: {len(status_filters)}개")
        for sf in status_filters[:30]:
            print(f"    - \"{sf['text'][:50]}\" ({sf['tag']}) class={sf['className'][:40]}")

        # 날짜 관련 요소
        date_elements = page.evaluate("""() => {
            const r = [];
            document.querySelectorAll('[class*="date"], [class*="Date"], [class*="calendar"], [class*="Calendar"], [class*="period"], [class*="Period"], [class*="DatePicker"], [class*="OBTDate"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    r.push({
                        tag: el.tagName,
                        className: (el.className.substring ? el.className.substring(0, 150) : ''),
                        text: el.textContent.trim().substring(0, 50),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return r;
        }""")
        dump_json(date_elements, "hp_exp_v2_06_date_elements")
        print(f"  날짜 관련 요소: {len(date_elements)}개")
        for de in date_elements[:10]:
            print(f"    - \"{de['text'][:40]}\" class={de['className'][:60]}")

        els6 = extract_all_elements(page)
        dump_json(els6, "hp_exp_v2_06_elements")

        # 그리드가 있으면 데이터 추출
        if els6['grids']:
            print(f"\n  OBTDataGrid 발견! ({len(els6['grids'])}개)")
            grid_data = extract_grid_data(page)
            dump_json(grid_data, "hp_exp_v2_06_grid_data")
            print(f"  그리드 데이터: {json.dumps(grid_data, ensure_ascii=False)[:500]}")

        # iframe 탐색
        print("\n  iframe 탐색:")
        frames = page.frames
        print(f"  프레임 수: {len(frames)}")
        frame_results = []
        for i, frame in enumerate(frames):
            try:
                furl = frame.url
                fname = frame.name
                print(f"    [{i}] name={fname} url={furl[:100]}")
                if furl and furl != "about:blank" and i > 0:
                    frame_text = frame.evaluate("() => document.body ? document.body.innerText.substring(0, 3000) : ''")
                    if frame_text.strip():
                        frame_els = extract_all_elements(frame, prefix=f"frame{i}_")
                        frame_results.append({
                            "index": i, "name": fname, "url": furl[:200],
                            "text": frame_text[:1000],
                            "elements": frame_els,
                        })
                        print(f"      텍스트: {frame_text[:100]}...")
                        # 프레임 내 그리드
                        if frame_els.get('grids'):
                            fg_data = extract_grid_data(frame)
                            frame_results[-1]["grid_data"] = fg_data
                            print(f"      그리드: {json.dumps(fg_data, ensure_ascii=False)[:300]}")
            except Exception as e:
                frame_results.append({"index": i, "error": str(e)})
        dump_json(frame_results, "hp_exp_v2_06_frames")

        # ──────────────────────────────────────────────
        # Step 7: 추가 LNB 메뉴 탐색 - 경비청구 하위 메뉴도 확인
        # ──────────────────────────────────────────────
        if not found_transfer:
            print("\n[Step 7] '경비청구' 메뉴 펼치고 하위 탐색")
            page.evaluate("""() => {
                const items = document.querySelectorAll('.nav-item');
                for (const el of items) {
                    if (el.className.includes('step-1') && el.textContent.trim().startsWith('경비청구')) {
                        if (el.className.includes('close')) {
                            el.click();
                        }
                        return true;
                    }
                }
                return false;
            }""")
            page.wait_for_timeout(2000)

            expense_sub = extract_lnb_menu(page)
            dump_json(expense_sub, "hp_exp_v2_07_expense_sub_menu")
            print("  경비청구 하위 메뉴:")
            for m in expense_sub:
                if any(kw in m['fullText'] for kw in ['경비', '지출', '이체', '결의', '계산', '청구']):
                    print(f"    ★ {m['text'][:50]}  class={m['className'][:40]}")

            # "지출결의/계산서" 펼치기
            print("\n  '지출결의/계산서' 메뉴 펼치기")
            page.evaluate("""() => {
                const items = document.querySelectorAll('.nav-item');
                for (const el of items) {
                    if (el.className.includes('step-1') && el.textContent.trim().startsWith('지출결의')) {
                        if (el.className.includes('close')) {
                            el.click();
                        }
                        return true;
                    }
                }
                return false;
            }""")
            page.wait_for_timeout(2000)

            menu7 = extract_lnb_menu(page)
            dump_json(menu7, "hp_exp_v2_07_full_menu")
            save_screenshot(page, "hp_exp_v2_07_expanded_menu")
            print("  전체 메뉴:")
            for m in menu7:
                cls = m.get('className', '')
                level = ""
                if "step-1" in cls: level = "  "
                elif "step-2" in cls: level = "    "
                elif "step-3" in cls: level = "      "
                print(f"  {level}{m['text'][:50]}  class={cls[:40]}")

            # 모든 하위 메뉴 클릭 시도
            for m in menu7:
                text = m['text']
                if any(kw in text for kw in ['이체', '지급', '결의서현황', '전표현황', '처리현황']):
                    print(f"\n  '{text}' 클릭 시도...")
                    page.evaluate(f"""() => {{
                        const items = document.querySelectorAll('.nav-item');
                        for (const el of items) {{
                            if (el.textContent.trim() === '{text}') {{
                                el.click();
                                return true;
                            }}
                        }}
                        return false;
                    }}""")
                    page.wait_for_timeout(5000)
                    save_screenshot(page, f"hp_exp_v2_07_{text[:10]}")
                    print(f"    URL: {page.url}")
                    found_transfer = True
                    break

        # ──────────────────────────────────────────────
        # Step 8: URL 직접 접근 시도 (HP 모듈의 다른 페이지)
        # ──────────────────────────────────────────────
        if not found_transfer:
            print("\n[Step 8] URL 직접 접근 시도")
            # 더존 URL 패턴: /#/HP/{menuCode}/{pageCode}
            url_candidates = [
                "/#/HP/HPM0510",  # 지출결의
                "/#/HP/HPM0520",  # 지출결의서
                "/#/HP/HPM0530",  # 이체현황?
                "/#/HP/HPM0500",  # 지출/경비
                "/#/HP/HPM0511",
                "/#/HP/HPM0512",
                "/#/HP/HPM0610",  # 개인지출결의서?
                "/#/HP/HPM0620",
            ]
            for url_path in url_candidates:
                try:
                    api_calls.clear()  # 각 페이지별 API 분리
                    page.goto(f"{GW_URL}{url_path}", wait_until="domcontentloaded", timeout=10000)
                    page.wait_for_timeout(3000)
                    cur = page.url
                    text = extract_visible_text(page)[:200]
                    print(f"    {url_path} → {cur[:80]} | {text[:60]}")
                    if "이체" in text or "지출결의서" in text or "결의서" in text:
                        print(f"    ★ 관련 페이지 발견!")
                        save_screenshot(page, f"hp_exp_v2_08_{url_path.replace('/#/', '').replace('/', '_')}")
                        found_transfer = True
                except Exception:
                    pass

    except Exception as e:
        print(f"\n[오류] {e}")
        traceback.print_exc()
        save_screenshot(page, "hp_exp_v2_error")
        results["error"] = str(e)

    finally:
        # API 결과 저장
        dump_json(api_calls, "hp_exp_v2_api_calls")
        dump_json(api_responses, "hp_exp_v2_api_responses")

        print(f"\n  API 요청: {len(api_calls)}개, 응답: {len(api_responses)}개")

        # 고유 엔드포인트
        unique = {}
        for c in api_calls:
            base = c['url'].split('?')[0]
            if base not in unique:
                unique[base] = {"method": c['method'], "post_data": c.get('post_data', '')[:200] if c.get('post_data') else ''}
        print(f"\n  고유 API 엔드포인트 ({len(unique)}개):")
        for url, info in sorted(unique.items()):
            pd = f" | body={info['post_data'][:80]}" if info['post_data'] else ""
            print(f"    [{info['method']}] {url[:120]}{pd}")

        results["api_endpoints"] = list(unique.keys())
        dump_json(results, "hp_exp_v2_summary")

        print("\n" + "=" * 60)
        print("Phase 2 탐색 완료!")

        hp_files = sorted(OUTPUT_DIR.glob("hp_exp_v2_*"))
        print(f"\n생성된 파일 ({len(hp_files)}개):")
        for f in hp_files:
            size = f.stat().st_size
            print(f"  {f.name:60s}  {size:>8,} bytes")
        print("=" * 60)

        close_session(browser)


if __name__ == "__main__":
    main()
