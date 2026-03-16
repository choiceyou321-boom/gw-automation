"""
예산관리(BN/BM) 모듈 - 예실대비현황(상세) Phase 0 DOM 탐색

목적:
1. 예산관리 모듈 진입 → 예실대비현황(상세) 메뉴 찾기
2. 조회 조건 (회계연도, 프로젝트 등) 파악
3. 테이블 컬럼 구조 (예산과목, 예산액, 집행액, 잔액 등)
4. OBTDataGrid React fiber 데이터 추출 시도
5. Network API 캡처

결과물: data/gw_analysis/budget_actual_*.json, budget_actual_*.png
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
    """GW 로그인"""
    from src.auth.login import login_and_get_context
    print("로그인 시도...")
    browser, context, page = login_and_get_context(
        playwright_instance=pw_instance,
        headless=False,
    )
    print(f"로그인 완료: {page.url}")

    # 팝업 닫기
    time.sleep(2)
    for p in context.pages[1:]:
        try:
            p.close()
        except Exception:
            pass

    return browser, context, page


def setup_api_capture(page):
    """Network API 요청/응답 캡처 설정"""
    captured_apis = []

    def on_response(response):
        url = response.url
        # 예산 관련 API만 캡처
        if any(kw in url.lower() for kw in ['bza', 'bma', 'bn', 'budget', 'bud', 'bga']):
            try:
                body = response.json() if 'json' in (response.headers.get('content-type', '') or '') else None
            except Exception:
                body = None
            captured_apis.append({
                "url": url,
                "status": response.status,
                "method": response.request.method,
                "post_data": response.request.post_data,
                "response_body_preview": str(body)[:2000] if body else None,
            })
            print(f"  [API] {response.request.method} {url} → {response.status}")

    page.on("response", on_response)
    return captured_apis


def navigate_to_budget_module(page):
    """예산관리 모듈로 이동"""
    print("\n" + "=" * 60)
    print("Step 1: 예산관리 모듈 진입")
    print("=" * 60)

    # 방법 1: URL 직접 이동
    page.goto("https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0020", wait_until="domcontentloaded")
    time.sleep(4)
    print(f"  URL 이동 후: {page.url}")
    capture(page, "budget_actual_01_module_home.png")

    # URL이 리다이렉트됐는지 확인
    if "BN" not in page.url and "BM" not in page.url:
        print("  URL 직접 이동 실패, 모듈 클릭 시도...")
        # 방법 2: 모듈 클릭
        page.goto("https://gw.glowseoul.co.kr/#/", wait_until="domcontentloaded")
        time.sleep(3)

        # span.module-link.BM 또는 텍스트로 찾기
        selectors = [
            "span.module-link.BM",
            "span.module-link.BN",
            "text=예산관리",
            "a:has-text('예산')",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click()
                    time.sleep(3)
                    print(f"  '{sel}' 클릭 → {page.url}")
                    break
            except Exception:
                continue

    capture(page, "budget_actual_02_after_module.png")
    return page.url


def explore_sidebar_menus(page):
    """좌측 사이드바 메뉴 구조 탐색"""
    print("\n" + "=" * 60)
    print("Step 2: 좌측 메뉴 구조 탐색")
    print("=" * 60)

    result = {}

    # 전체 메뉴 텍스트 추출 (JS)
    try:
        menu_data = page.evaluate("""() => {
            const result = [];
            // LNB 사이드바 영역 탐색
            const selectors = [
                '[class*="lnb"]', '[class*="Lnb"]', '[class*="side"]',
                '[class*="Side"]', '[class*="tree"]', '[class*="Tree"]',
                'nav', '[class*="menu"]', '[class*="Menu"]'
            ];
            let container = null;
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.offsetParent !== null) {
                    container = el;
                    break;
                }
            }
            if (!container) {
                // 전체 body에서 찾기
                container = document.body;
            }

            const items = container.querySelectorAll('a, li, span, div[class*="node"]');
            const seen = new Set();
            items.forEach(el => {
                const text = (el.textContent || '').trim();
                if (text && text.length < 40 && !seen.has(text)) {
                    seen.add(text);
                    const rect = el.getBoundingClientRect();
                    // 좌측 사이드바 영역 (x < 350)에 있는 것만
                    if (rect.x < 350 && rect.width > 0) {
                        result.push({
                            tag: el.tagName,
                            text: text,
                            href: el.href || '',
                            className: (el.className || '').toString().substring(0, 150),
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            w: Math.round(rect.width),
                            h: Math.round(rect.height),
                        });
                    }
                }
            });
            return result;
        }""")
        result["sidebar_items"] = menu_data
        print(f"  사이드바 메뉴 항목: {len(menu_data)}개")
        for item in menu_data:
            print(f"    [{item['tag']}] {item['text']} (x={item['x']}, y={item['y']})")
    except Exception as e:
        print(f"  사이드바 메뉴 추출 실패: {e}")

    # "예산장부" 메뉴 펼치기
    print("\n── 예산장부 메뉴 펼치기 시도 ──")
    expand_targets = ["예산장부", "예산집행현황", "예실대비"]
    for target in expand_targets:
        try:
            el = page.locator(f"text={target}").first
            if el.is_visible(timeout=2000):
                el.click()
                time.sleep(1)
                print(f"  '{target}' 클릭 완료")
        except Exception as e:
            print(f"  '{target}' 클릭 실패: {e}")

    capture(page, "budget_actual_03_menus_expanded.png")

    # 펼친 후 재탐색
    try:
        expanded = page.evaluate("""() => {
            const result = [];
            const allEls = document.querySelectorAll('a, span, li, div');
            const seen = new Set();
            allEls.forEach(el => {
                const text = (el.textContent || '').trim();
                if (text && text.length < 40 && text.includes('예실') && !seen.has(text)) {
                    seen.add(text);
                    const rect = el.getBoundingClientRect();
                    result.push({
                        tag: el.tagName,
                        text: text,
                        href: el.href || '',
                        className: (el.className || '').toString().substring(0, 200),
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                    });
                }
            });
            return result;
        }""")
        result["yesil_menu_items"] = expanded
        print(f"  '예실' 포함 항목: {len(expanded)}개")
        for item in expanded:
            print(f"    {item['text']} ({item['tag']}, x={item['x']}, y={item['y']})")
    except Exception as e:
        print(f"  예실 메뉴 탐색 실패: {e}")

    save_json(result, "budget_actual_sidebar.json")
    return result


def navigate_to_budget_actual_detail(page):
    """예실대비현황(상세) 페이지로 이동"""
    print("\n" + "=" * 60)
    print("Step 3: 예실대비현황(상세) 페이지 이동")
    print("=" * 60)

    # 다양한 셀렉터로 시도
    selectors_to_try = [
        "text=예실대비현황(상세)",
        "text=예실대비현황 (상세)",
        "a:has-text('예실대비현황(상세)')",
        "span:has-text('예실대비현황(상세)')",
        "text=예실대비현황",
        "a:has-text('예실대비')",
    ]

    for sel in selectors_to_try:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                time.sleep(3)
                print(f"  '{sel}' 클릭 → {page.url}")
                capture(page, "budget_actual_04_detail_page.png")
                return True
        except Exception:
            continue

    # URL 직접 이동 시도 (일반적인 더존 URL 패턴)
    budget_urls = [
        "https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0040",
        "https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0050",
        "https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0060",
        "https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0030",
        "https://gw.glowseoul.co.kr/#/BM/NCH0010/BZA0040",
        "https://gw.glowseoul.co.kr/#/BM/NCH0010/BZA0050",
    ]
    for url in budget_urls:
        try:
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(3)
            title = page.evaluate("() => document.querySelector('h1, h2, .title, [class*=\"title\"]')?.textContent?.trim() || ''")
            print(f"  URL {url} → 제목: '{title}'")
            if "예실" in title or "대비" in title:
                capture(page, "budget_actual_04_detail_page.png")
                return True
        except Exception:
            continue

    print("  예실대비현황(상세) 직접 찾기 실패, 전체 URL 스캔 필요")
    capture(page, "budget_actual_04_not_found.png")
    return False


def explore_detail_page(page):
    """예실대비현황(상세) 페이지 DOM 탐색"""
    print("\n" + "=" * 60)
    print("Step 4: 예실대비현황(상세) 페이지 DOM 탐색")
    print("=" * 60)

    result = {}

    # 4-1. 페이지 제목/현재 URL
    result["url"] = page.url
    try:
        title = page.evaluate("() => document.querySelector('h1, h2, .title, [class*=\"title\"]')?.textContent?.trim() || ''")
        result["page_title"] = title
        print(f"  페이지 제목: {title}")
    except Exception:
        result["page_title"] = ""

    # 4-2. 전체 페이지 텍스트 (조건 영역)
    try:
        page_text = page.evaluate("""() => {
            const main = document.querySelector('[class*="content"], [class*="Content"], main, #app');
            return (main || document.body).innerText.substring(0, 5000);
        }""")
        result["page_text_preview"] = page_text
        print(f"  페이지 텍스트 길이: {len(page_text)}")
    except Exception as e:
        print(f"  텍스트 추출 실패: {e}")

    # 4-3. 조회 조건 영역 (input, select, 버튼)
    print("\n── 4-3. 조회 조건 필드 ──")
    try:
        inputs = page.evaluate("""() => {
            const inputs = document.querySelectorAll('input, select, textarea');
            return Array.from(inputs).filter(el => el.offsetParent !== null).map(el => ({
                tag: el.tagName,
                type: el.type || '',
                id: el.id || '',
                name: el.name || '',
                placeholder: el.placeholder || '',
                value: el.value || '',
                disabled: el.disabled,
                className: (el.className || '').substring(0, 200),
                rect: el.getBoundingClientRect().toJSON(),
            }));
        }""")
        result["input_fields"] = inputs
        print(f"  입력 필드: {len(inputs)}개")
        for inp in inputs:
            print(f"    [{inp['tag']}] type={inp['type']} placeholder='{inp['placeholder']}' value='{inp['value']}' id='{inp['id']}'")
    except Exception as e:
        print(f"  입력 필드 추출 실패: {e}")

    # 4-4. 버튼 목록
    print("\n── 4-4. 버튼 목록 ──")
    try:
        buttons = page.evaluate("""() => {
            const btns = document.querySelectorAll('button, [role="button"], div[class*="Btn"], div[class*="btn"], a[class*="btn"]');
            return Array.from(btns).filter(el => el.offsetParent !== null).map(el => ({
                tag: el.tagName,
                text: (el.textContent || '').trim().substring(0, 80),
                id: el.id || '',
                className: (el.className || '').substring(0, 200),
                rect: el.getBoundingClientRect().toJSON(),
            }));
        }""")
        result["buttons"] = buttons
        print(f"  버튼: {len(buttons)}개")
        for btn in buttons:
            if btn['text']:
                print(f"    [{btn['tag']}] '{btn['text']}' cls={btn['className'][:60]}")
    except Exception as e:
        print(f"  버튼 추출 실패: {e}")

    # 4-5. 테이블/그리드 구조
    print("\n── 4-5. 테이블/그리드 구조 ──")
    try:
        grids = page.evaluate("""() => {
            const result = [];
            // OBTDataGrid 찾기
            const obtGrids = document.querySelectorAll('[class*="OBTDataGrid"], [class*="RealGrid"], [class*="datagrid"], [class*="DataGrid"]');
            obtGrids.forEach(el => {
                const rect = el.getBoundingClientRect();
                result.push({
                    type: 'OBTDataGrid',
                    className: (el.className || '').substring(0, 300),
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                    childCount: el.children.length,
                });
            });
            // 일반 table 찾기
            const tables = document.querySelectorAll('table');
            tables.forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 100 && rect.height > 50) {
                    const headers = Array.from(el.querySelectorAll('th')).map(th => th.textContent.trim()).filter(t => t);
                    result.push({
                        type: 'table',
                        className: (el.className || '').substring(0, 200),
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        w: Math.round(rect.width),
                        h: Math.round(rect.height),
                        rowCount: el.rows?.length || 0,
                        headers: headers.slice(0, 30),
                    });
                }
            });
            return result;
        }""")
        result["grids_and_tables"] = grids
        print(f"  그리드/테이블: {len(grids)}개")
        for g in grids:
            print(f"    [{g['type']}] {g.get('w', 0)}x{g.get('h', 0)} cls={g.get('className', '')[:80]}")
            if 'headers' in g:
                print(f"      컬럼: {g['headers']}")
    except Exception as e:
        print(f"  그리드 추출 실패: {e}")

    # 4-6. OBTDataGrid React fiber 접근 시도
    print("\n── 4-6. OBTDataGrid React fiber 접근 ──")
    try:
        fiber_data = page.evaluate("""() => {
            const result = {};
            // OBTDataGrid_grid__22Vfl 찾기
            const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
            if (!gridEl) {
                result.error = 'OBTDataGrid_grid 요소 없음';
                // 대안: canvas 기반 그리드 찾기
                const canvases = document.querySelectorAll('canvas');
                result.canvas_count = canvases.length;
                result.canvas_info = Array.from(canvases).map(c => ({
                    w: c.width, h: c.height,
                    className: c.className,
                    parentClass: c.parentElement?.className?.substring(0, 200) || '',
                }));
                return result;
            }

            result.grid_class = gridEl.className;

            // React fiber 접근
            const fiberKey = Object.keys(gridEl).find(k => k.startsWith('__reactFiber'));
            if (!fiberKey) {
                result.error = '__reactFiber 없음';
                return result;
            }

            result.has_fiber = true;
            let fiber = gridEl[fiberKey];

            // depth 3까지 탐색
            for (let i = 0; i < 3; i++) {
                if (fiber && fiber.return) {
                    fiber = fiber.return;
                }
            }

            if (fiber && fiber.stateNode && fiber.stateNode.state) {
                const state = fiber.stateNode.state;
                result.state_keys = Object.keys(state);

                if (state.interface) {
                    const iface = state.interface;
                    result.interface_methods = Object.getOwnPropertyNames(Object.getPrototypeOf(iface) || {}).slice(0, 50);

                    // 데이터 추출 시도
                    try {
                        if (typeof iface.getRowCount === 'function') {
                            result.row_count = iface.getRowCount();
                        }
                    } catch(e) { result.row_count_error = e.message; }

                    try {
                        if (typeof iface.getColumns === 'function') {
                            const cols = iface.getColumns();
                            result.columns = Array.isArray(cols) ? cols.map(c => ({
                                name: c.name || c.fieldName || '',
                                header: c.header?.text || c.header || '',
                                width: c.width || 0,
                                visible: c.visible !== false,
                            })) : String(cols).substring(0, 500);
                        }
                    } catch(e) { result.columns_error = e.message; }

                    // 첫 5행 데이터
                    try {
                        if (typeof iface.getRowCount === 'function' && typeof iface.getValue === 'function') {
                            const rowCount = Math.min(iface.getRowCount(), 5);
                            const cols = iface.getColumns ? iface.getColumns() : [];
                            const rows = [];
                            for (let r = 0; r < rowCount; r++) {
                                const row = {};
                                for (const col of cols.slice(0, 20)) {
                                    const name = col.name || col.fieldName;
                                    try {
                                        row[name] = iface.getValue(r, name);
                                    } catch(e) {}
                                }
                                rows.push(row);
                            }
                            result.sample_data = rows;
                        }
                    } catch(e) { result.sample_data_error = e.message; }
                }
            }

            // depth 12: 폼 컴포넌트
            fiber = gridEl[fiberKey];
            for (let i = 0; i < 12; i++) {
                if (fiber && fiber.return) fiber = fiber.return;
            }
            if (fiber && fiber.stateNode && fiber.stateNode.state) {
                result.depth12_state_keys = Object.keys(fiber.stateNode.state);
            }

            return result;
        }""")
        result["obtdatagrid_fiber"] = fiber_data
        print(f"  React fiber 결과: {json.dumps(fiber_data, ensure_ascii=False, indent=2)[:1000]}")
    except Exception as e:
        print(f"  React fiber 접근 실패: {e}")
        result["obtdatagrid_fiber"] = {"error": str(e)}

    save_json(result, "budget_actual_detail_dom.json")
    return result


def try_search_with_year(page, year):
    """특정 회계연도로 조회"""
    print(f"\n── 회계연도 {year} 조회 시도 ──")

    # 연도 입력 필드 찾기 (DatePicker 또는 연도 select)
    try:
        # 연도 관련 input 찾기
        year_input = page.evaluate(f"""() => {{
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {{
                const val = inp.value;
                const ph = inp.placeholder;
                // 연도 형태의 값이 있는 input
                if (/^20\\d{{2}}$/.test(val) || ph.includes('연도') || ph.includes('회계')) {{
                    return {{
                        found: true,
                        value: val,
                        placeholder: ph,
                        className: inp.className.substring(0, 200),
                        id: inp.id,
                    }};
                }}
            }}
            // select 요소에서 연도 찾기
            const selects = document.querySelectorAll('select');
            for (const sel of selects) {{
                const opts = Array.from(sel.options).map(o => o.value);
                if (opts.some(v => /^20\\d{{2}}$/.test(v))) {{
                    return {{
                        found: true,
                        type: 'select',
                        value: sel.value,
                        options: opts.slice(0, 10),
                    }};
                }}
            }}
            return {{ found: false }};
        }}""")
        print(f"  연도 입력 필드: {json.dumps(year_input, ensure_ascii=False)}")

        if year_input.get('found'):
            if year_input.get('type') == 'select':
                # select인 경우
                print(f"  select 연도 변경: {year}")
                # TODO: select 값 변경
            else:
                # input인 경우 - 값 클리어하고 입력
                sel = f"input#{year_input['id']}" if year_input.get('id') else f"input[value='{year_input.get('value', '')}']"
                try:
                    inp = page.locator(sel).first
                    if inp.is_visible(timeout=2000):
                        inp.triple_click()
                        inp.fill(str(year))
                        inp.press("Enter")
                        time.sleep(2)
                        print(f"  연도 {year} 입력 완료")
                except Exception:
                    pass
    except Exception as e:
        print(f"  연도 입력 실패: {e}")

    # 조회 버튼 클릭
    try:
        search_btn = page.locator("text=조회").first
        if not search_btn.is_visible(timeout=2000):
            search_btn = page.locator("button:has-text('조회')").first
        if search_btn.is_visible(timeout=2000):
            search_btn.click()
            time.sleep(3)
            print(f"  조회 버튼 클릭 완료")
    except Exception as e:
        print(f"  조회 버튼 클릭 실패: {e}")

    capture(page, f"budget_actual_05_year_{year}.png")

    # 조회 결과 데이터 추출 시도
    try:
        grid_data = page.evaluate("""() => {
            const result = {};
            // OBTDataGrid fiber에서 데이터 추출
            const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
            if (gridEl) {
                const fiberKey = Object.keys(gridEl).find(k => k.startsWith('__reactFiber'));
                if (fiberKey) {
                    let fiber = gridEl[fiberKey];
                    for (let i = 0; i < 3; i++) {
                        if (fiber && fiber.return) fiber = fiber.return;
                    }
                    if (fiber?.stateNode?.state?.interface) {
                        const iface = fiber.stateNode.state.interface;
                        try { result.row_count = iface.getRowCount(); } catch(e) {}
                        try {
                            const cols = iface.getColumns();
                            result.columns = cols.map(c => ({
                                name: c.name || c.fieldName || '',
                                header: c.header?.text || c.header || '',
                            }));
                        } catch(e) {}
                        // 전체 데이터 (최대 100행)
                        try {
                            const rowCount = Math.min(iface.getRowCount(), 100);
                            const cols = iface.getColumns();
                            const rows = [];
                            for (let r = 0; r < rowCount; r++) {
                                const row = {};
                                for (const col of cols) {
                                    const name = col.name || col.fieldName;
                                    try { row[name] = iface.getValue(r, name); } catch(e) {}
                                }
                                rows.push(row);
                            }
                            result.data = rows;
                        } catch(e) { result.data_error = e.message; }
                    }
                }
            }
            return result;
        }""")
        print(f"  그리드 데이터: 행수={grid_data.get('row_count', 'N/A')}, 컬럼수={len(grid_data.get('columns', []))}")
        return grid_data
    except Exception as e:
        print(f"  데이터 추출 실패: {e}")
        return {}


def explore_all_budget_menus(page):
    """예산관리 모듈 내 전체 메뉴 URL 스캔"""
    print("\n" + "=" * 60)
    print("Step 2-B: 전체 메뉴 URL 스캔")
    print("=" * 60)

    # 좌측 메뉴의 모든 링크 수집
    try:
        all_links = page.evaluate("""() => {
            const links = document.querySelectorAll('a[href]');
            return Array.from(links).map(a => ({
                text: (a.textContent || '').trim().substring(0, 60),
                href: a.href,
                visible: a.offsetParent !== null,
            })).filter(l => l.text && l.visible);
        }""")
        print(f"  전체 visible 링크: {len(all_links)}개")
        for link in all_links:
            print(f"    '{link['text']}' → {link['href']}")
        return all_links
    except Exception as e:
        print(f"  링크 수집 실패: {e}")
        return []


def main():
    print("=" * 60)
    print("예산관리 - 예실대비현황(상세) Phase 0 DOM 탐색")
    print("=" * 60)

    all_results = {}

    with sync_playwright() as pw:
        # 로그인
        browser, context, page = login(pw)

        # API 캡처 설정
        captured_apis = setup_api_capture(page)

        # Step 1: 예산관리 모듈 진입
        module_url = navigate_to_budget_module(page)
        all_results["module_url"] = module_url

        # Step 2: 사이드바 메뉴 탐색
        sidebar = explore_sidebar_menus(page)
        all_results["sidebar"] = sidebar

        # Step 2-B: 전체 메뉴 링크 스캔
        all_links = explore_all_budget_menus(page)
        all_results["all_menu_links"] = all_links

        # Step 3: 예실대비현황(상세) 이동
        found = navigate_to_budget_actual_detail(page)
        all_results["detail_page_found"] = found

        if found:
            # Step 4: DOM 탐색
            detail_dom = explore_detail_page(page)
            all_results["detail_dom"] = detail_dom

            # Step 5: 2025년/2026년 조회
            data_2026 = try_search_with_year(page, 2026)
            all_results["data_2026"] = data_2026

            data_2025 = try_search_with_year(page, 2025)
            all_results["data_2025"] = data_2025
        else:
            # 못 찾은 경우: 현재 페이지의 DOM이라도 탐색
            print("\n  예실대비현황(상세) 못 찾음 - 현재 페이지 DOM 탐색")
            detail_dom = explore_detail_page(page)
            all_results["current_page_dom"] = detail_dom

        # API 캡처 결과 저장
        all_results["captured_apis"] = captured_apis
        save_json(captured_apis, "budget_actual_apis.json")

        # 전체 결과 저장
        save_json(all_results, "budget_actual_exploration.json")

        print("\n" + "=" * 60)
        print("탐색 완료!")
        print(f"결과 디렉토리: {OUTPUT_DIR}")
        print(f"캡처된 API: {len(captured_apis)}개")
        print("=" * 60)

        # 브라우저 열어둠 (수동 확인용)
        input("엔터를 누르면 브라우저를 닫습니다...")
        browser.close()


if __name__ == "__main__":
    main()
