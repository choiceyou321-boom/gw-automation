"""
예실대비현황(상세) Phase 0 DOM 탐색 v4

v3 발견:
- micro-frontend: page.frames[0] URL = #/BN/NCC0630/NCC0630
- 조회 조건: 회계단위(1000), 기수(9=2026), 기간(2026-01~2026-12), 프로젝트, 차수(1),
             출력구분(전체), 예산과목, 과목구분(세세세목), 금액없는라인/프로젝트(미표시)
- 그리드: RealGridJS v1.0 (canvas 기반), OBTDataGrid 래핑
- grid div id: grid_edb553e0-2150-11f1-904e-296554fb07b8
- gridWrapper div id: gridWrapper_edb74fb0-2150-11f1-904e-296554fb07b8
- 조회 버튼: button.OBTButton_root → "조회" (tooltip으로 가려짐 → frame.locator 사용)
- 데이터 접근: OBTDataGrid fiber → no_fiber → React fiber 대신 grid div의
  __reactInternalInstance 또는 RealGrid getActiveGrid() 사용

v4 전략:
1. frame 찾기 (NCC0630)
2. frame 내에서 조회 버튼 클릭 (OBTButton 셀렉터)
3. API 캡처로 데이터 엔드포인트 식별
4. RealGrid getActiveGrid()로 인스턴스 접근
5. 기수 변경 → 2025년 데이터도 조회
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


def setup_api_capture(context):
    """API 캡처 — context 레벨 (모든 page/frame의 요청)"""
    captured_apis = []

    def on_response(response):
        url = response.url
        if ('gw.glowseoul.co.kr' in url and
            '/bp/' in url and  # 예산 관련 API 집중
            not any(ext in url for ext in ['.png', '.jpg', '.css', '.js', '.woff', '.svg'])):
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
            print(f"  [BP-API] {response.request.method} {url} → {response.status}")

    # page 레벨이 아닌 모든 frame에서도 캡처하기 위해 context 레벨은 불가
    # page.on으로 대체 — frame의 network도 page에서 캡처됨
    return captured_apis


def find_ncc0630_frame(page, max_wait=10):
    """NCC0630 frame 찾기 (최대 max_wait초 대기)"""
    for i in range(max_wait):
        for frame in page.frames:
            if 'NCC0630' in frame.url:
                print(f"  NCC0630 frame 발견 ({i+1}초)")
                return frame
        time.sleep(1)
    print("  NCC0630 frame 미발견")
    return None


def click_search_button(frame, page):
    """조회 버튼 클릭 (frame 내부의 OBTButton)"""
    print("\n── 조회 버튼 클릭 ──")

    # 방법 1: frame 내에서 button 텍스트로 찾기
    try:
        btn = frame.locator("button:has-text('조회')").first
        if btn.is_visible(timeout=3000):
            btn.click(force=True)
            print("  조회 버튼 클릭 (frame, button:has-text)")
            return True
    except Exception as e:
        print(f"  방법 1 실패: {e}")

    # 방법 2: OBTButton 클래스
    try:
        btn = frame.locator("button.OBTButton_root__1g4ov:has-text('조회')").first
        btn.click(force=True)
        print("  조회 버튼 클릭 (frame, OBTButton class)")
        return True
    except Exception as e:
        print(f"  방법 2 실패: {e}")

    # 방법 3: 돋보기 아이콘 (조회 옆)
    try:
        # 스크린샷에서 돋보기 아이콘은 조회조건 오른쪽에 있음
        btn = frame.locator("[class*='search'], [class*='Search'], [class*='inquiry']").first
        if btn.is_visible(timeout=2000):
            btn.click(force=True)
            print("  조회 버튼 클릭 (search icon)")
            return True
    except Exception:
        pass

    # 방법 4: JS로 직접 클릭
    try:
        clicked = frame.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '조회') {
                    btn.click();
                    return 'clicked: ' + btn.className;
                }
            }
            // OBTButton 내부 span 클릭
            const spans = document.querySelectorAll('span');
            for (const span of spans) {
                if (span.textContent.trim() === '조회') {
                    span.click();
                    return 'span-clicked: ' + span.className;
                }
            }
            return 'not found';
        }""")
        print(f"  JS 클릭 결과: {clicked}")
        return 'clicked' in clicked
    except Exception as e:
        print(f"  방법 4 실패: {e}")

    return False


def extract_grid_via_realgrid(frame):
    """RealGrid getActiveGrid / grid div 기반 데이터 추출"""
    print("\n── RealGrid 데이터 추출 ──")

    try:
        data = frame.evaluate("""() => {
            const result = {};

            // 1. RealGridJS.getActiveGrid()
            if (window.RealGridJS && typeof window.RealGridJS.getActiveGrid === 'function') {
                try {
                    const activeGrid = window.RealGridJS.getActiveGrid();
                    result.active_grid = activeGrid ? 'found' : 'null';
                    if (activeGrid) {
                        result.active_grid_type = activeGrid.constructor?.name || typeof activeGrid;
                        // 메서드 목록
                        const proto = Object.getPrototypeOf(activeGrid);
                        result.active_grid_methods = proto ? Object.getOwnPropertyNames(proto).filter(m => !m.startsWith('_')).slice(0, 80) : [];
                    }
                } catch(e) {
                    result.active_grid_error = e.message;
                }
            }

            // 2. grid div에서 RealGrid 인스턴스 직접 접근
            const gridDivs = document.querySelectorAll('div[id^="grid_"]');
            result.grid_div_count = gridDivs.length;

            for (const gridDiv of gridDivs) {
                const gridId = gridDiv.id;
                result.grid_div_id = gridId;

                // __reactFiber 또는 __reactInternalInstance
                const keys = Object.keys(gridDiv);
                result.grid_div_keys = keys.filter(k => k.startsWith('__'));

                // __reactFiber로 접근
                const fiberKey = keys.find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                if (fiberKey) {
                    result.has_fiber = true;
                    result.fiber_key = fiberKey;

                    let fiber = gridDiv[fiberKey];
                    // depth 순회
                    for (let d = 0; d < 20; d++) {
                        if (!fiber) break;

                        const stateNode = fiber.stateNode;
                        if (stateNode && stateNode !== gridDiv) {
                            // stateNode의 속성 검사
                            const stateKeys = Object.keys(stateNode).filter(k => !k.startsWith('_'));
                            const stateStateKeys = stateNode.state ? Object.keys(stateNode.state) : [];

                            if (stateNode.state) {
                                // interface (OBTDataGrid 패턴)
                                if (stateNode.state.interface) {
                                    result.interface_at_depth = d;
                                    const iface = stateNode.state.interface;
                                    try { result.iface_row_count = iface.getRowCount(); } catch(e) {}
                                    try {
                                        const cols = iface.getColumns();
                                        result.iface_columns = cols.map(c => ({
                                            name: c.name || c.fieldName || '',
                                            header: c.header?.text || c.header || '',
                                        }));
                                    } catch(e) {}
                                }

                                // grid 속성
                                if (stateNode.state.grid) {
                                    result.state_grid_at_depth = d;
                                    const g = stateNode.state.grid;
                                    result.state_grid_type = g.constructor?.name || typeof g;
                                    try { result.state_grid_row_count = g.getItemCount ? g.getItemCount() : -1; } catch(e) {}
                                    try {
                                        const dp = g.getDataSource ? g.getDataSource() : null;
                                        if (dp) {
                                            result.state_grid_dp_rows = dp.getRowCount ? dp.getRowCount() : -1;
                                            if (dp.getFields) {
                                                result.state_grid_fields = dp.getFields().map(f => f.fieldName || f.name);
                                            }
                                            // 데이터 추출
                                            if (dp.getRowCount && dp.getRowCount() > 0) {
                                                const maxR = Math.min(dp.getRowCount(), 10);
                                                const rows = [];
                                                for (let r = 0; r < maxR; r++) {
                                                    try {
                                                        rows.push(dp.getJsonRow(r));
                                                    } catch(e) {
                                                        const row = {};
                                                        const flds = dp.getFields();
                                                        for (const f of flds) {
                                                            try { row[f.fieldName || f.name] = dp.getValue(r, f.fieldName || f.name); } catch(e2) {}
                                                        }
                                                        rows.push(row);
                                                    }
                                                }
                                                result.sample_data = rows;
                                            }
                                        }
                                    } catch(e) { result.state_grid_dp_error = e.message; }
                                    try {
                                        const cols = g.getColumns ? g.getColumns() : [];
                                        result.state_grid_columns = cols.map(c => ({
                                            name: c.name || c.fieldName || '',
                                            fieldName: c.fieldName || '',
                                            header: c.header ? (c.header.text || c.header) : '',
                                            width: c.width || 0,
                                        }));
                                    } catch(e) {}
                                }

                                // 기타 state 키 보고
                                if (stateStateKeys.length > 0 && !result.state_keys_reported) {
                                    result[`state_keys_depth_${d}`] = stateStateKeys;
                                    result.state_keys_reported = true;
                                }
                            }
                        }

                        fiber = fiber.return;
                    }
                }

                // __reactInternalInstance → _currentElement 패턴 (구버전 React)
                const internalKey = keys.find(k => k.startsWith('__reactInternalInstance'));
                if (internalKey && !result.has_fiber) {
                    result.has_internal_instance = true;
                    let inst = gridDiv[internalKey];
                    // React 15 패턴
                    for (let d = 0; d < 20; d++) {
                        if (!inst) break;
                        if (inst._instance && inst._instance.state) {
                            const state = inst._instance.state;
                            result[`internal_state_keys_${d}`] = Object.keys(state);
                            if (state.grid) {
                                result.internal_grid_found = d;
                                break;
                            }
                        }
                        inst = inst._hostParent || inst.return;
                    }
                }
            }

            // 3. gridWrapper에서 접근
            const wrapperDivs = document.querySelectorAll('div[id^="gridWrapper_"]');
            for (const wrapper of wrapperDivs) {
                const wKeys = Object.keys(wrapper).filter(k => k.startsWith('__'));
                result.wrapper_id = wrapper.id;
                result.wrapper_keys = wKeys;

                const wFiberKey = wKeys.find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                if (wFiberKey) {
                    let fiber = wrapper[wFiberKey];
                    for (let d = 0; d < 15; d++) {
                        if (!fiber) break;
                        const sn = fiber.stateNode;
                        if (sn && sn.state) {
                            const sk = Object.keys(sn.state);
                            if (sk.includes('interface') || sk.includes('grid') || sk.includes('gridView') || sk.includes('dataProvider')) {
                                result.wrapper_state_at_depth = d;
                                result.wrapper_state_keys = sk;

                                // interface
                                if (sn.state.interface) {
                                    const iface = sn.state.interface;
                                    try { result.w_iface_rows = iface.getRowCount(); } catch(e) {}
                                    try {
                                        result.w_iface_cols = iface.getColumns().map(c => ({
                                            name: c.name || c.fieldName || '',
                                            header: c.header?.text || c.header || '',
                                        }));
                                    } catch(e) {}
                                }
                                // gridView / dataProvider
                                if (sn.state.gridView) {
                                    const gv = sn.state.gridView;
                                    try { result.w_gv_rows = gv.getItemCount(); } catch(e) {}
                                }
                                if (sn.state.dataProvider) {
                                    const dp = sn.state.dataProvider;
                                    try {
                                        result.w_dp_rows = dp.getRowCount();
                                        result.w_dp_fields = dp.getFields().map(f => f.fieldName || f.name);
                                    } catch(e) {}
                                    // 샘플 데이터
                                    try {
                                        const maxR = Math.min(dp.getRowCount(), 10);
                                        const rows = [];
                                        for (let r = 0; r < maxR; r++) {
                                            rows.push(dp.getJsonRow(r));
                                        }
                                        result.w_sample_data = rows;
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
        }""")

        print(f"  결과 키: {list(data.keys())}")
        for key, val in data.items():
            if isinstance(val, list) and len(val) > 5:
                print(f"  {key}: [{len(val)} items] {str(val[:3])[:200]}...")
            elif isinstance(val, str) and len(val) > 200:
                print(f"  {key}: {val[:200]}...")
            else:
                print(f"  {key}: {val}")

        return data
    except Exception as e:
        print(f"  추출 실패: {e}")
        return {"error": str(e)}


def main():
    print("=" * 60)
    print("예실대비현황(상세) Phase 0 DOM 탐색 v4")
    print("=" * 60)

    all_results = {}

    with sync_playwright() as pw:
        browser, context, page = login(pw)

        # API 캡처 (page 레벨 — frame의 network도 여기서 잡힘)
        captured_apis = []

        def on_response(response):
            url = response.url
            # 예산 관련 API만 (static 파일 제외)
            if ('gw.glowseoul.co.kr' in url and
                '/bp/' in url and
                '/static/' not in url and
                '/mxGraph/' not in url and
                not any(ext in url for ext in ['.css', '.js', '.png', '.jpg', '.woff', '.svg', '.txt', '.ttc', '.json?timestamp'])):
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
                print(f"  [BP-API] {response.request.method} {url} → {response.status}")

        page.on("response", on_response)

        # Step 1: 예산관리 → 예실대비현황(상세)
        print("\n" + "=" * 60)
        print("Step 1: 예산관리 → 예실대비현황(상세)")
        print("=" * 60)

        page.goto("https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0020", wait_until="domcontentloaded")
        time.sleep(5)

        # 예산장부 → 예실대비현황(상세)
        try:
            page.locator("text=예산장부").first.click()
            time.sleep(3)
            print("  '예산장부' 펼침")
            page.locator("text=예실대비현황(상세)").first.click()
            time.sleep(5)
            print(f"  메뉴 클릭 완료, URL: {page.url}")
        except Exception as e:
            print(f"  메뉴 클릭 실패: {e}")

        # Step 2: NCC0630 frame 찾기
        print("\n" + "=" * 60)
        print("Step 2: NCC0630 frame 대기")
        print("=" * 60)

        frame = find_ncc0630_frame(page, max_wait=20)
        if not frame:
            print("  NCC0630 frame 못찾음 — 전체 frame 목록:")
            for i, f in enumerate(page.frames):
                print(f"    Frame[{i}]: url='{f.url}' name='{f.name}'")
            # 대안: 모든 frame 중 main이 아닌 것
            for f in page.frames:
                if f.url != page.url and f.url != 'about:blank':
                    frame = f
                    print(f"  대안 frame 사용: {f.url}")
                    break
            if not frame:
                print("  FATAL: 적합한 frame 없음")
                capture(page, "budget_actual_v4_no_frame.png")
                browser.close()
                return

        # frame 내 콘텐츠 로드 대기
        print("  frame 콘텐츠 로드 대기...")
        for i in range(15):
            time.sleep(1)
            check = frame.evaluate("""() => {
                const inputs = document.querySelectorAll('input');
                const vis = Array.from(inputs).filter(el => el.offsetParent !== null);
                const canvas = document.querySelector('canvas');
                return { inputs: vis.length, hasCanvas: !!canvas };
            }""")
            print(f"    {i+1}초: inputs={check['inputs']} canvas={check['hasCanvas']}")
            if check['inputs'] > 3 and check['hasCanvas']:
                break

        capture(page, "budget_actual_v4_01_loaded.png")

        # Step 3: 조회 조건 상세 분석
        print("\n" + "=" * 60)
        print("Step 3: 조회 조건 상세")
        print("=" * 60)

        try:
            conditions = frame.evaluate("""() => {
                const result = {};
                // 모든 visible input
                const inputs = document.querySelectorAll('input');
                result.inputs = Array.from(inputs).filter(el => el.offsetParent !== null).map(el => {
                    const rect = el.getBoundingClientRect();
                    // 근처 라벨 찾기
                    let labelText = '';
                    // OBTFormPanel 패턴: 부모 div 안의 다른 요소
                    const parent = el.closest('[class*="FormPanel"], [class*="formPanel"], tr, div');
                    if (parent) {
                        const labelEl = parent.querySelector('[class*="title"], [class*="Title"], label, th');
                        if (labelEl) labelText = labelEl.textContent.trim();
                    }
                    return {
                        placeholder: el.placeholder || '',
                        value: el.value || '',
                        type: el.type || '',
                        cls: (el.className || '').substring(0, 150),
                        x: Math.round(rect.x), y: Math.round(rect.y),
                        label: labelText,
                    };
                });

                // select (콤보)
                const selects = document.querySelectorAll('select');
                result.selects = Array.from(selects).filter(el => el.offsetParent !== null).map(el => ({
                    id: el.id,
                    value: el.value,
                    options: Array.from(el.options).map(o => ({ value: o.value, text: o.text })),
                    cls: (el.className || '').substring(0, 100),
                }));

                // OBTDropDownList (더존 커스텀 드롭다운)
                const dropdowns = document.querySelectorAll('[class*="OBTDropDownList"], [class*="OBTCombo"]');
                result.dropdowns = Array.from(dropdowns).filter(el => el.offsetParent !== null).map(el => ({
                    cls: (el.className || '').substring(0, 200),
                    text: (el.textContent || '').trim().substring(0, 100),
                    x: Math.round(el.getBoundingClientRect().x),
                    y: Math.round(el.getBoundingClientRect().y),
                }));

                return result;
            }""")
            all_results["conditions"] = conditions
            print(f"  입력 필드: {len(conditions.get('inputs', []))}개")
            for inp in conditions.get('inputs', []):
                print(f"    ph='{inp['placeholder']}' val='{inp['value']}' label='{inp['label']}' ({inp['x']},{inp['y']})")
            print(f"  Select: {len(conditions.get('selects', []))}개")
            print(f"  Dropdowns: {len(conditions.get('dropdowns', []))}개")
            for dd in conditions.get('dropdowns', []):
                print(f"    '{dd['text']}' ({dd['x']},{dd['y']})")
        except Exception as e:
            print(f"  조건 분석 실패: {e}")

        # Step 4: 조회 버튼 클릭
        print("\n" + "=" * 60)
        print("Step 4: 조회 실행")
        print("=" * 60)

        # API 캡처 리셋
        captured_apis.clear()

        clicked = click_search_button(frame, page)
        if clicked:
            time.sleep(8)  # 데이터 로드 대기
            print("  조회 후 8초 대기 완료")
        else:
            print("  조회 버튼 클릭 실패 — 스크린샷 확인")

        capture(page, "budget_actual_v4_02_after_search.png")

        # Step 5: 조회 후 API 결과 확인
        print("\n" + "=" * 60)
        print("Step 5: API 결과")
        print("=" * 60)

        all_results["search_apis"] = list(captured_apis)
        print(f"  캡처된 API: {len(captured_apis)}개")
        for api in captured_apis:
            print(f"    {api['method']} {api['url']} → {api['status']}")
            if api['post_data']:
                print(f"      POST: {api['post_data'][:200]}")
            if api['response_preview']:
                print(f"      RESP: {api['response_preview'][:300]}")

        # Step 6: RealGrid 데이터 추출
        print("\n" + "=" * 60)
        print("Step 6: RealGrid 데이터 추출")
        print("=" * 60)

        grid_data = extract_grid_via_realgrid(frame)
        all_results["grid_data_2026"] = grid_data

        # Step 7: 기수 변경 (2025 = 기수 8) 시도
        print("\n" + "=" * 60)
        print("Step 7: 2025년 (기수 8) 조회")
        print("=" * 60)

        try:
            # 기수 select/input 찾기 (기수=9인 필드 → 8로 변경)
            year_changed = frame.evaluate("""() => {
                // 기수 입력란 (값이 "9"인 input)
                const inputs = document.querySelectorAll('input');
                for (const inp of inputs) {
                    if (inp.value === '9' && inp.offsetParent !== null) {
                        // React state 업데이트를 위해 네이티브 이벤트 사용
                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeInputValueSetter.call(inp, '8');
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                        return { changed: true, from: '9', to: '8' };
                    }
                }
                // 기간도 변경 시도
                return { changed: false };
            }""")
            print(f"  기수 변경: {year_changed}")

            # 기간도 2025-01 ~ 2025-12로 변경
            frame.evaluate("""() => {
                const inputs = document.querySelectorAll('input');
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                for (const inp of inputs) {
                    if (inp.value === '2026-01') {
                        setter.call(inp, '2025-01');
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    if (inp.value === '2026-12') {
                        setter.call(inp, '2025-12');
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            }""")
            time.sleep(1)

            # 재조회
            captured_apis.clear()
            clicked = click_search_button(frame, page)
            if clicked:
                time.sleep(8)
                print("  2025 조회 후 8초 대기")

            capture(page, "budget_actual_v4_03_search_2025.png")

            all_results["search_2025_apis"] = list(captured_apis)
            print(f"  2025 API: {len(captured_apis)}개")
            for api in captured_apis:
                print(f"    {api['method']} {api['url']} → {api['status']}")
                if api['response_preview']:
                    print(f"      RESP: {api['response_preview'][:500]}")

            # 2025 그리드 데이터
            grid_data_2025 = extract_grid_via_realgrid(frame)
            all_results["grid_data_2025"] = grid_data_2025

        except Exception as e:
            print(f"  2025 조회 실패: {e}")

        # 최종 스크린샷
        capture(page, "budget_actual_v4_04_final.png")

        # 결과 저장
        save_json(all_results, "budget_actual_v4_exploration.json")

        print("\n" + "=" * 60)
        print("탐색 완료!")
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    main()
