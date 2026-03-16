"""
예실대비현황(상세) Phase 0 DOM 탐색 v3

v2 발견:
- 더존은 micro-frontend 구조
- 예실대비현황(상세) 메뉴 클릭 → page.frames[0]에 실제 콘텐츠 (7MB HTML)
- 전역 변수: Grids(object), RealGridJS(object) → RealGrid 기반 그리드
- 메인 page의 DOM에는 빈 OBTPageContainer만 보임
- page.frames 접근이 핵심

v3 전략:
1. 메뉴 클릭 후 page.frames에서 NCC0630 frame 찾기
2. frame 내부에서 RealGridJS 데이터 추출
3. 조회 조건 (회계연도) 탐색 및 변경
4. API 캡처
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


def setup_api_capture(page):
    """API 캡처 - 예산 관련 API에 집중"""
    captured_apis = []

    def on_response(response):
        url = response.url
        if ('gw.glowseoul.co.kr' in url and
            not any(ext in url for ext in ['.png', '.jpg', '.css', '.js', '.woff', '.svg', '.ico', '.ttc', '.txt'])):
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
                "response_preview": str(body)[:3000] if body else None,
            })

    page.on("response", on_response)
    return captured_apis


def find_detail_frame(page):
    """예실대비현황(상세) 콘텐츠가 있는 frame 찾기"""
    print("\n── Frame 검색 ──")
    frames = page.frames
    print(f"  총 frame 수: {len(frames)}")

    for i, frame in enumerate(frames):
        url = frame.url
        name = frame.name
        print(f"  Frame[{i}]: name='{name}' url='{url[:100]}'")

        # NCC0630 또는 예실 관련 frame 찾기
        if 'NCC0630' in url or 'ncc0630' in url.lower():
            print(f"  → NCC0630 frame 발견!")
            return frame

    # frame이 없으면 main page 자체 확인
    # micro-frontend에서는 #contents div 내부에 micro-app이 mount됨
    # 실제 콘텐츠가 main frame에 있을 수도 있음
    print("  NCC0630 frame 미발견, main page에서 콘텐츠 확인")
    return None


def explore_frame_content(frame, label=""):
    """Frame/Page 내부 심층 탐색"""
    print(f"\n{'='*60}")
    print(f"Frame 내부 탐색: {label}")
    print(f"{'='*60}")
    result = {}

    # 1. 전체 visible 텍스트
    try:
        text = frame.evaluate("""() => {
            const main = document.querySelector('[class*="content"], [class*="Content"], main, #contents');
            return (main || document.body).innerText.substring(0, 5000);
        }""")
        result["page_text"] = text
        print(f"  페이지 텍스트 ({len(text)}자):")
        for line in text.split('\n')[:30]:
            if line.strip():
                print(f"    {line.strip()[:100]}")
    except Exception as e:
        print(f"  텍스트 추출 실패: {e}")

    # 2. 입력 필드
    try:
        inputs = frame.evaluate("""() => {
            const els = document.querySelectorAll('input, select, textarea');
            return Array.from(els).filter(el => el.offsetParent !== null || el.type !== 'hidden').map(el => {
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    type: el.type || '',
                    id: el.id || '',
                    name: el.name || '',
                    placeholder: el.placeholder || '',
                    value: el.value || '',
                    disabled: el.disabled,
                    cls: (el.className || '').substring(0, 200),
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    w: Math.round(rect.width), h: Math.round(rect.height),
                    visible: el.offsetParent !== null,
                    // 라벨 찾기
                    label: (() => {
                        // 이전 형제나 부모의 텍스트
                        const prev = el.previousElementSibling;
                        if (prev) return prev.textContent.trim().substring(0, 50);
                        const parent = el.closest('div, td, th, label');
                        if (parent) {
                            const label = parent.querySelector('label, span, div');
                            if (label && label !== el) return label.textContent.trim().substring(0, 50);
                        }
                        return '';
                    })(),
                };
            });
        }""")
        result["inputs"] = inputs
        visible = [i for i in inputs if i['visible']]
        print(f"\n  입력 필드: {len(inputs)}개 (visible: {len(visible)}개)")
        for inp in visible:
            print(f"    [{inp['tag']}] type={inp['type']} id='{inp['id']}' ph='{inp['placeholder']}' val='{inp['value']}' label='{inp['label']}' ({inp['x']},{inp['y']})")
    except Exception as e:
        print(f"  입력 필드 실패: {e}")

    # 3. 버튼
    try:
        buttons = frame.evaluate("""() => {
            const els = document.querySelectorAll('button, [role="button"], div[class*="Btn"], span[class*="btn"], a[class*="btn"]');
            return Array.from(els).filter(el => el.offsetParent !== null).map(el => {
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    text: (el.textContent || '').trim().substring(0, 80),
                    id: el.id || '',
                    cls: (el.className || '').substring(0, 150),
                    x: Math.round(rect.x), y: Math.round(rect.y),
                };
            }).filter(el => el.text);
        }""")
        result["buttons"] = buttons
        print(f"\n  버튼: {len(buttons)}개")
        for btn in buttons[:20]:
            print(f"    [{btn['tag']}] '{btn['text']}' ({btn['x']},{btn['y']}) cls={btn['cls'][:60]}")
    except Exception as e:
        print(f"  버튼 실패: {e}")

    # 4. RealGridJS 탐색 (전역 변수)
    try:
        realgrid_info = frame.evaluate("""() => {
            const result = {};

            // RealGridJS 전역 변수
            if (window.RealGridJS) {
                result.has_realgrid = true;
                result.realgrid_keys = Object.keys(window.RealGridJS).slice(0, 30);
            }

            // Grids 전역 변수
            if (window.Grids) {
                result.has_grids = true;
                result.grids_type = typeof window.Grids;
                if (typeof window.Grids === 'object') {
                    result.grids_keys = Object.keys(window.Grids).slice(0, 20);
                }
            }

            // gridView, dataProvider 등 일반 패턴
            const gridVars = ['gridView', 'dataProvider', 'grid', 'grd', 'grdView'];
            for (const v of gridVars) {
                if (window[v]) {
                    result[v] = typeof window[v];
                }
            }

            // window에서 RealGrid/grid 관련 모든 변수
            const gridRelated = {};
            for (const key of Object.keys(window)) {
                const lk = key.toLowerCase();
                if (lk.includes('grid') || lk.includes('realgrid') || lk.includes('dataprovider')) {
                    gridRelated[key] = typeof window[key];
                }
            }
            result.window_grid_vars = gridRelated;

            return result;
        }""")
        result["realgrid"] = realgrid_info
        print(f"\n  RealGridJS: {realgrid_info.get('has_realgrid', False)}")
        print(f"  Grids: {realgrid_info.get('has_grids', False)}, keys={realgrid_info.get('grids_keys', [])}")
        print(f"  Grid 관련 전역 변수: {realgrid_info.get('window_grid_vars', {})}")
    except Exception as e:
        print(f"  RealGrid 탐색 실패: {e}")

    # 5. OBTDataGrid / 그리드 DOM 요소
    try:
        grids = frame.evaluate("""() => {
            const result = {};

            // OBTDataGrid
            const obtGrids = document.querySelectorAll('[class*="OBTDataGrid"]');
            result.obtdatagrid_count = obtGrids.length;
            result.obtdatagrid_elements = Array.from(obtGrids).map(el => ({
                cls: (el.className || '').substring(0, 300),
                w: el.offsetWidth, h: el.offsetHeight,
                visible: el.offsetParent !== null,
            }));

            // Canvas (RealGrid는 canvas 렌더링)
            const canvases = document.querySelectorAll('canvas');
            result.canvas_count = canvases.length;
            result.canvases = Array.from(canvases).map(c => ({
                w: c.width, h: c.height,
                style_w: c.style.width, style_h: c.style.height,
                parentId: c.parentElement?.id || '',
                parentClass: (c.parentElement?.className || '').substring(0, 200),
                grandparentClass: (c.parentElement?.parentElement?.className || '').substring(0, 200),
                visible: c.offsetParent !== null,
            }));

            // div[id] 중 grid 관련
            const gridDivs = document.querySelectorAll('div[id*="grid"], div[id*="Grid"], div[id*="realgrid"], div[id*="RealGrid"]');
            result.grid_divs = Array.from(gridDivs).map(el => ({
                id: el.id,
                cls: (el.className || '').substring(0, 200),
                w: el.offsetWidth, h: el.offsetHeight,
            }));

            return result;
        }""")
        result["grid_dom"] = grids
        print(f"\n  OBTDataGrid 수: {grids.get('obtdatagrid_count', 0)}")
        print(f"  Canvas 수: {grids.get('canvas_count', 0)}")
        for c in grids.get('canvases', []):
            print(f"    canvas {c['w']}x{c['h']} parent_id='{c['parentId']}' parent_cls='{c['parentClass'][:60]}' visible={c['visible']}")
        print(f"  Grid DIV 수: {len(grids.get('grid_divs', []))}")
        for gd in grids.get('grid_divs', []):
            print(f"    div#{gd['id']} {gd['w']}x{gd['h']} cls={gd['cls'][:60]}")
    except Exception as e:
        print(f"  그리드 DOM 실패: {e}")

    # 6. OBTDataGrid React fiber 접근
    try:
        fiber = frame.evaluate("""() => {
            const result = {};
            const gridEls = document.querySelectorAll('[class*="OBTDataGrid_grid"]');
            if (gridEls.length === 0) {
                // 대안: 모든 div에서 __reactFiber가 있고 grid 관련인 것 찾기
                const allDivs = document.querySelectorAll('div');
                for (const div of allDivs) {
                    const cls = div.className || '';
                    if (cls.includes('OBTDataGrid') || cls.includes('grid')) {
                        const fk = Object.keys(div).find(k => k.startsWith('__reactFiber'));
                        if (fk) {
                            result.alt_grid_found = true;
                            result.alt_grid_cls = cls.substring(0, 200);
                            // fiber 탐색
                            let f = div[fk];
                            for (let d = 0; d < 5; d++) {
                                if (f && f.return) f = f.return;
                                if (f?.stateNode?.state?.interface) {
                                    result.interface_at_depth = d + 1;
                                    const iface = f.stateNode.state.interface;
                                    try { result.row_count = iface.getRowCount(); } catch(e) {}
                                    try {
                                        const cols = iface.getColumns();
                                        result.columns = cols.map(c => ({
                                            name: c.name || c.fieldName || '',
                                            header: c.header?.text || c.header || '',
                                            width: c.width || 0,
                                        }));
                                    } catch(e) {}
                                    break;
                                }
                            }
                            break;
                        }
                    }
                }
                if (!result.alt_grid_found) {
                    result.no_grid = true;
                }
                return result;
            }

            const gridEl = gridEls[0];
            result.grid_class = gridEl.className.substring(0, 300);
            const fiberKey = Object.keys(gridEl).find(k => k.startsWith('__reactFiber'));
            if (!fiberKey) {
                result.no_fiber = true;
                return result;
            }

            let fiber = gridEl[fiberKey];
            for (let d = 0; d < 5; d++) {
                if (fiber && fiber.return) fiber = fiber.return;
                if (fiber?.stateNode?.state?.interface) {
                    result.interface_at_depth = d + 1;
                    const iface = fiber.stateNode.state.interface;
                    try { result.row_count = iface.getRowCount(); } catch(e) { result.row_count_err = e.message; }
                    try {
                        const cols = iface.getColumns();
                        result.columns = cols.map(c => ({
                            name: c.name || c.fieldName || '',
                            header: c.header?.text || c.header || '',
                            width: c.width || 0,
                        }));
                    } catch(e) { result.columns_err = e.message; }
                    // 샘플 데이터 (처음 5행)
                    try {
                        const rowCount = Math.min(iface.getRowCount(), 5);
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
                        result.sample_data = rows;
                    } catch(e) { result.sample_err = e.message; }
                    break;
                }
            }
            return result;
        }""")
        result["fiber"] = fiber
        print(f"\n  OBTDataGrid Fiber: {json.dumps(fiber, ensure_ascii=False)[:800]}")
    except Exception as e:
        print(f"  Fiber 실패: {e}")

    # 7. 테이블 DOM (RealGrid 아닌 일반 HTML 테이블)
    try:
        tables = frame.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            return Array.from(tables).filter(t => t.offsetWidth > 100).map(t => {
                const headers = Array.from(t.querySelectorAll('th')).map(th => th.textContent.trim()).filter(Boolean);
                const rows = Array.from(t.querySelectorAll('tbody tr')).slice(0, 3).map(tr =>
                    Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim().substring(0, 50))
                );
                return {
                    w: t.offsetWidth, h: t.offsetHeight,
                    cls: (t.className || '').substring(0, 100),
                    headers: headers,
                    sample_rows: rows,
                    row_count: t.rows?.length || 0,
                };
            });
        }""")
        result["html_tables"] = tables
        print(f"\n  HTML 테이블: {len(tables)}개")
        for t in tables:
            print(f"    {t['w']}x{t['h']} rows={t['row_count']} headers={t['headers'][:15]}")
            for row in t['sample_rows'][:2]:
                print(f"      → {row[:10]}")
    except Exception as e:
        print(f"  테이블 실패: {e}")

    return result


def explore_realgrid_in_frame(frame):
    """Frame 내 RealGridJS 심층 탐색"""
    print(f"\n{'='*60}")
    print("RealGridJS 심층 탐색")
    print(f"{'='*60}")

    result = {}

    try:
        rg_data = frame.evaluate("""() => {
            const result = {};

            // 1. RealGridJS 객체 분석
            if (window.RealGridJS) {
                const rg = window.RealGridJS;
                result.version = rg.getVersion ? rg.getVersion() : (rg.version || 'unknown');
                result.keys = Object.keys(rg).slice(0, 50);
            }

            // 2. Grids 객체 분석 (RealGrid가 생성한 그리드 인스턴스 목록)
            if (window.Grids) {
                result.grids_keys = Object.keys(window.Grids);
                // 각 그리드 인스턴스 분석
                result.grid_instances = {};
                for (const [key, grid] of Object.entries(window.Grids)) {
                    const ginfo = { type: typeof grid };
                    if (grid && typeof grid === 'object') {
                        // GridView 메서드/속성
                        const proto = Object.getPrototypeOf(grid);
                        ginfo.methods = proto ? Object.getOwnPropertyNames(proto).filter(m => !m.startsWith('_')).slice(0, 50) : [];
                        ginfo.own_keys = Object.keys(grid).slice(0, 30);

                        // getRowCount, getColumnCount
                        try { ginfo.row_count = grid.getItemCount ? grid.getItemCount() : (grid.getRowCount ? grid.getRowCount() : -1); } catch(e) { ginfo.row_count_err = e.message; }

                        // DataProvider 찾기
                        try {
                            const dp = grid.getDataSource ? grid.getDataSource() : (grid.dataProvider || grid._dataProvider);
                            if (dp) {
                                ginfo.has_data_provider = true;
                                ginfo.dp_row_count = dp.getRowCount ? dp.getRowCount() : -1;
                                // 필드 정보
                                if (dp.getFields) {
                                    const fields = dp.getFields();
                                    ginfo.fields = fields.map(f => ({
                                        fieldName: f.fieldName || f.name || '',
                                        dataType: f.dataType || '',
                                    }));
                                }
                                // 첫 5행 데이터
                                if (dp.getRowCount && dp.getRowCount() > 0) {
                                    const rowCount = Math.min(dp.getRowCount(), 5);
                                    const rows = [];
                                    for (let r = 0; r < rowCount; r++) {
                                        try {
                                            const row = dp.getJsonRow ? dp.getJsonRow(r) : dp.getOutputRow({}, r);
                                            rows.push(row);
                                        } catch(e) {
                                            // getValue 시도
                                            try {
                                                const row = {};
                                                const fields = dp.getFields();
                                                for (const f of fields) {
                                                    const fn = f.fieldName || f.name;
                                                    row[fn] = dp.getValue(r, fn);
                                                }
                                                rows.push(row);
                                            } catch(e2) {}
                                        }
                                    }
                                    ginfo.sample_data = rows;
                                }
                            }
                        } catch(e) { ginfo.dp_error = e.message; }

                        // 컬럼 정보
                        try {
                            const cols = grid.getColumns ? grid.getColumns() : [];
                            ginfo.columns = cols.map(c => ({
                                name: c.name || c.fieldName || '',
                                fieldName: c.fieldName || '',
                                header: c.header ? (c.header.text || c.header) : '',
                                width: c.width || 0,
                                visible: c.visible !== false,
                            }));
                        } catch(e) { ginfo.cols_error = e.message; }
                    }
                    result.grid_instances[key] = ginfo;
                }
            }

            // 3. 전역 gridView/dataProvider 패턴 검색
            const gridPatterns = {};
            for (const key of Object.keys(window)) {
                const val = window[key];
                if (val && typeof val === 'object') {
                    try {
                        if (val.getColumns || val.getItemCount || val.getRowCount) {
                            gridPatterns[key] = {
                                type: val.constructor?.name || typeof val,
                                hasGetColumns: !!val.getColumns,
                                hasGetItemCount: !!val.getItemCount,
                                hasGetRowCount: !!val.getRowCount,
                                hasDataSource: !!val.getDataSource,
                            };
                        }
                    } catch(e) {}
                }
            }
            result.grid_patterns = gridPatterns;

            return result;
        }""")
        result = rg_data
        print(f"  RealGridJS version: {rg_data.get('version', 'N/A')}")
        print(f"  Grids keys: {rg_data.get('grids_keys', [])}")
        for key, ginfo in rg_data.get('grid_instances', {}).items():
            print(f"\n  Grid '{key}':")
            print(f"    row_count: {ginfo.get('row_count', 'N/A')}")
            print(f"    has_data_provider: {ginfo.get('has_data_provider', False)}")
            print(f"    dp_row_count: {ginfo.get('dp_row_count', 'N/A')}")
            if ginfo.get('fields'):
                print(f"    필드: {[f['fieldName'] for f in ginfo['fields']]}")
            if ginfo.get('columns'):
                print(f"    컬럼: {[(c['name'], c['header']) for c in ginfo['columns'][:15]]}")
            if ginfo.get('sample_data'):
                print(f"    샘플: {json.dumps(ginfo['sample_data'][:2], ensure_ascii=False)[:500]}")
            if ginfo.get('methods'):
                print(f"    메서드(일부): {ginfo['methods'][:20]}")
        print(f"\n  Grid 패턴 전역변수: {rg_data.get('grid_patterns', {})}")
    except Exception as e:
        print(f"  RealGrid 분석 실패: {e}")
        result["error"] = str(e)

    return result


def try_search_in_frame(frame, page, year=2026):
    """Frame 내에서 조회 실행"""
    print(f"\n{'='*60}")
    print(f"조회 실행 (연도: {year})")
    print(f"{'='*60}")

    result = {}

    # 연도 입력 필드 찾기
    try:
        year_field = frame.evaluate(f"""() => {{
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {{
                // 4자리 연도 형태 값
                if (/^20\\d{{2}}$/.test(inp.value)) {{
                    return {{
                        found: true,
                        value: inp.value,
                        id: inp.id,
                        cls: inp.className.substring(0, 200),
                        placeholder: inp.placeholder,
                    }};
                }}
            }}
            // select에서 연도 찾기
            const selects = document.querySelectorAll('select');
            for (const sel of selects) {{
                const opts = Array.from(sel.options).map(o => ({{ value: o.value, text: o.text }}));
                if (opts.some(o => /^20\\d{{2}}$/.test(o.value))) {{
                    return {{
                        found: true, type: 'select',
                        value: sel.value,
                        id: sel.id,
                        options: opts.slice(0, 10),
                    }};
                }}
            }}
            return {{ found: false }};
        }}""")
        result["year_field"] = year_field
        print(f"  연도 필드: {json.dumps(year_field, ensure_ascii=False)}")

        # 연도 변경
        if year_field.get('found') and year_field.get('id'):
            if year_field.get('type') == 'select':
                frame.select_option(f"#{year_field['id']}", str(year))
            else:
                inp = frame.locator(f"#{year_field['id']}").first
                if inp.is_visible(timeout=2000):
                    inp.triple_click()
                    inp.fill(str(year))
                    inp.press("Tab")
                    time.sleep(1)
                    print(f"  연도 {year} 입력 완료")
    except Exception as e:
        print(f"  연도 변경 실패: {e}")

    # 조회 버튼 클릭
    try:
        frame.locator("text=조회").first.click()
        time.sleep(5)
        print("  조회 클릭 → 5초 대기")
    except Exception:
        # page에서도 시도
        try:
            page.locator("text=조회").first.click()
            time.sleep(5)
            print("  (page에서) 조회 클릭 → 5초 대기")
        except Exception as e:
            print(f"  조회 버튼 클릭 실패: {e}")

    capture(page, f"budget_actual_v3_search_{year}.png")
    return result


def extract_all_grid_data(frame):
    """Frame에서 전체 그리드 데이터 추출"""
    print(f"\n{'='*60}")
    print("전체 그리드 데이터 추출")
    print(f"{'='*60}")

    try:
        data = frame.evaluate("""() => {
            const result = {};

            if (!window.Grids) return { error: 'Grids 없음' };

            for (const [key, grid] of Object.entries(window.Grids)) {
                const gdata = {};

                // DataProvider에서 전체 데이터
                try {
                    const dp = grid.getDataSource ? grid.getDataSource() : grid.dataProvider;
                    if (dp && dp.getRowCount) {
                        gdata.total_rows = dp.getRowCount();

                        // 필드
                        const fields = dp.getFields ? dp.getFields() : [];
                        gdata.fields = fields.map(f => f.fieldName || f.name || '');

                        // 전체 데이터 (최대 200행)
                        const maxRows = Math.min(dp.getRowCount(), 200);
                        const rows = [];
                        for (let r = 0; r < maxRows; r++) {
                            try {
                                const row = dp.getJsonRow ? dp.getJsonRow(r) : {};
                                rows.push(row);
                            } catch(e) {
                                const row = {};
                                for (const f of fields) {
                                    const fn = f.fieldName || f.name;
                                    try { row[fn] = dp.getValue(r, fn); } catch(e2) {}
                                }
                                rows.push(row);
                            }
                        }
                        gdata.data = rows;
                    }
                } catch(e) {
                    gdata.extract_error = e.message;
                }

                // 컬럼 (헤더 포함)
                try {
                    const cols = grid.getColumns ? grid.getColumns() : [];
                    gdata.columns = cols.map(c => ({
                        name: c.name || c.fieldName || '',
                        fieldName: c.fieldName || '',
                        header: c.header ? (c.header.text || JSON.stringify(c.header)) : '',
                        width: c.width || 0,
                        visible: c.visible !== false,
                    }));
                } catch(e) { gdata.cols_error = e.message; }

                result[key] = gdata;
            }

            return result;
        }""")
        print(f"  그리드 수: {len(data)}")
        for key, gdata in data.items():
            print(f"\n  Grid '{key}':")
            print(f"    총 행수: {gdata.get('total_rows', 'N/A')}")
            print(f"    필드: {gdata.get('fields', [])}")
            if gdata.get('columns'):
                print(f"    컬럼 헤더: {[(c['name'], c['header']) for c in gdata['columns'][:20]]}")
            if gdata.get('data'):
                print(f"    첫 행: {json.dumps(gdata['data'][0], ensure_ascii=False)[:300]}")
        return data
    except Exception as e:
        print(f"  데이터 추출 실패: {e}")
        return {"error": str(e)}


def main():
    print("=" * 60)
    print("예실대비현황(상세) Phase 0 DOM 탐색 v3")
    print("=" * 60)

    all_results = {}

    with sync_playwright() as pw:
        browser, context, page = login(pw)
        captured_apis = setup_api_capture(page)

        # Step 1: 예산관리 → 예실대비현황(상세) 메뉴 클릭
        print("\n" + "=" * 60)
        print("Step 1: 예산관리 → 예실대비현황(상세)")
        print("=" * 60)

        page.goto("https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0020", wait_until="domcontentloaded")
        time.sleep(4)

        # 예산장부 펼치기
        try:
            page.locator("text=예산장부").first.click()
            time.sleep(2)
            print("  '예산장부' 펼침")
        except Exception:
            pass

        # 예실대비현황(상세) 클릭
        try:
            page.locator("text=예실대비현황(상세)").first.click()
            time.sleep(5)
            print(f"  '예실대비현황(상세)' 클릭 → URL: {page.url}")
        except Exception as e:
            print(f"  메뉴 클릭 실패: {e}")

        capture(page, "budget_actual_v3_01_menu_clicked.png")

        # Step 2: micro-app이 마운트될 때까지 대기
        print("\n" + "=" * 60)
        print("Step 2: micro-app 콘텐츠 로드 대기")
        print("=" * 60)

        # contents div 내부에 콘텐츠가 나타날 때까지 대기
        for i in range(20):
            time.sleep(1)
            check = page.evaluate("""() => {
                const contents = document.querySelector('#contents, [class*="OBTPageContainer_contents"]');
                if (!contents) return { found: false, reason: 'no container' };
                return {
                    found: true,
                    childCount: contents.children.length,
                    innerTextLen: (contents.innerText || '').length,
                    hasInput: !!contents.querySelector('input'),
                    hasCanvas: !!contents.querySelector('canvas'),
                    hasGrid: !!contents.querySelector('[class*="grid"], [class*="Grid"]'),
                    html_snippet: contents.innerHTML.substring(0, 500),
                };
            }""")
            frames_count = len(page.frames)
            print(f"  {i+1}초: children={check.get('childCount', 0)} text={check.get('innerTextLen', 0)} input={check.get('hasInput')} canvas={check.get('hasCanvas')} grid={check.get('hasGrid')} frames={frames_count}")
            if check.get('hasInput') or check.get('hasCanvas') or check.get('hasGrid'):
                print("  콘텐츠 로드 감지!")
                break

        capture(page, "budget_actual_v3_02_after_wait.png")

        # Step 3: Frame 탐색
        print("\n" + "=" * 60)
        print("Step 3: Frame 탐색")
        print("=" * 60)

        # 모든 frames 정보
        for i, f in enumerate(page.frames):
            print(f"  Frame[{i}]: url='{f.url[:120]}' name='{f.name}'")

        detail_frame = find_detail_frame(page)

        if detail_frame:
            # Frame 내부 탐색
            frame_content = explore_frame_content(detail_frame, "NCC0630 Frame")
            all_results["frame_content"] = frame_content

            # RealGridJS 심층 탐색
            rg_result = explore_realgrid_in_frame(detail_frame)
            all_results["realgrid"] = rg_result

            # 조회 실행 (2026)
            search_result_2026 = try_search_in_frame(detail_frame, page, 2026)
            all_results["search_2026"] = search_result_2026

            # 데이터 추출
            grid_data_2026 = extract_all_grid_data(detail_frame)
            all_results["grid_data_2026"] = grid_data_2026

            # 스크린샷
            capture(page, "budget_actual_v3_03_data_2026.png")

            # 2025 조회
            search_result_2025 = try_search_in_frame(detail_frame, page, 2025)
            all_results["search_2025"] = search_result_2025
            time.sleep(3)

            grid_data_2025 = extract_all_grid_data(detail_frame)
            all_results["grid_data_2025"] = grid_data_2025
            capture(page, "budget_actual_v3_04_data_2025.png")

        else:
            # Frame을 못 찾은 경우 — main page에서 직접 탐색
            print("\n  NCC0630 frame 미발견, main page에서 콘텐츠 탐색")

            # #contents 내부의 micro-app mount 확인
            try:
                micro_app_info = page.evaluate("""() => {
                    const contents = document.querySelector('#contents');
                    if (!contents) return { error: 'no #contents' };

                    // micro-menu 요소 찾기
                    const microMenus = contents.querySelectorAll('[id^="micro-menu"]');
                    const result = {
                        micro_menu_count: microMenus.length,
                        micro_menus: Array.from(microMenus).map(m => ({
                            id: m.id,
                            childCount: m.children.length,
                            innerTextLen: (m.innerText || '').length,
                            innerHTML_snippet: m.innerHTML.substring(0, 500),
                        })),
                    };

                    // OBTPageContainer 내부
                    const containers = contents.querySelectorAll('[class*="OBTPageContainer"]');
                    result.containers = Array.from(containers).map(c => ({
                        cls: c.className.substring(0, 200),
                        childCount: c.children.length,
                        w: c.offsetWidth, h: c.offsetHeight,
                    }));

                    return result;
                }""")
                all_results["micro_app"] = micro_app_info
                print(f"  micro-menu 수: {micro_app_info.get('micro_menu_count', 0)}")
                for mm in micro_app_info.get('micro_menus', []):
                    print(f"    {mm['id']}: children={mm['childCount']} text={mm['innerTextLen']}")
                    print(f"    HTML: {mm['innerHTML_snippet'][:200]}")
            except Exception as e:
                print(f"  micro-app 확인 실패: {e}")

            # main page에서도 RealGridJS 전역 변수 확인
            try:
                main_rg = page.evaluate("""() => {
                    return {
                        has_Grids: !!window.Grids,
                        Grids_keys: window.Grids ? Object.keys(window.Grids) : [],
                        has_RealGridJS: !!window.RealGridJS,
                    };
                }""")
                print(f"  Main page - Grids: {main_rg}")
                all_results["main_realgrid"] = main_rg

                if main_rg.get('has_Grids') and main_rg.get('Grids_keys'):
                    # main page에서 직접 데이터 추출
                    print("  Main page에서 RealGrid 데이터 추출 시도...")
                    rg_result = explore_realgrid_in_frame(page)
                    all_results["main_realgrid_detail"] = rg_result

                    grid_data = extract_all_grid_data(page)
                    all_results["main_grid_data"] = grid_data
            except Exception as e:
                print(f"  main RealGrid 확인 실패: {e}")

            # main page 콘텐츠 탐색
            frame_content = explore_frame_content(page, "Main Page")
            all_results["main_content"] = frame_content

        # API 결과
        all_results["captured_apis"] = captured_apis
        save_json(captured_apis, "budget_actual_v3_apis.json")
        save_json(all_results, "budget_actual_v3_exploration.json")

        print("\n" + "=" * 60)
        print("탐색 완료!")
        print(f"캡처된 API: {len(captured_apis)}개")
        print(f"결과: {OUTPUT_DIR}")
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    main()
