"""
HP 지출결의서 탐색 Phase 5
문제: nav-item 클릭이 메뉴를 펼치지 않음
      → 스크린샷 확인: v (chevron) 아이콘으로 토글
전략:
  1. LNB chevron(v) 아이콘 클릭으로 "개인지출결의서" 펼치기
  2. 하위 메뉴 "개인지출결의현황" 클릭
  3. 또는 React Router로 직접 URL 네비게이션
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
    print("HP 지출결의서 탐색 Phase 5 — chevron 클릭 + React Router")
    print("=" * 60)

    api_calls = []
    api_responses = []

    def on_req(req):
        url = req.url
        if any(x in url for x in ['/gw/', '/personal/', 'hp', 'HP', 'hpm', 'HPM',
                                     'slip', 'expense', 'accSlip', 'voucher', 'transfer',
                                     'getList', 'search', 'query']):
            api_calls.append({
                "method": req.method,
                "url": url[:300],
                "post_data": req.post_data[:2000] if req.post_data else None,
            })

    def on_resp(resp):
        url = resp.url
        if any(x in url for x in ['hp', 'HP', 'hpm', 'HPM', 'personal', 'slip',
                                     'expense', 'accSlip', 'voucher', 'transfer', 'getList']):
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
        # Step 1: HP 모듈 진입
        # ──────────────────────────────────────────────
        print("\n[Step 1] HP 모듈 진입")
        page.goto(f"{GW_URL}/#/HP/HPM0110/HPM0110", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        close_popups(page)

        # LNB 전체 HTML 구조 덤프 (정확한 요소 파악)
        lnb_html = page.evaluate("""() => {
            // LNB 영역 찾기 (x < 200인 사이드바)
            const sideEls = document.querySelectorAll('[class*="lnb"], [class*="side"], [class*="nav-area"], nav');
            for (const el of sideEls) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 100 && rect.width < 300 && rect.x < 200) {
                    return el.outerHTML.substring(0, 30000);
                }
            }
            // 폴백: nav-item의 부모
            const navItem = document.querySelector('.nav-item.step-1');
            if (navItem) {
                let parent = navItem.parentElement;
                while (parent && parent.tagName !== 'BODY') {
                    const rect = parent.getBoundingClientRect();
                    if (rect.width > 100 && rect.width < 300) {
                        return parent.outerHTML.substring(0, 30000);
                    }
                    parent = parent.parentElement;
                }
            }
            return 'NOT FOUND';
        }""")
        with open(OUTPUT_DIR / "hp_v5_01_lnb_html.txt", "w", encoding="utf-8") as f:
            f.write(lnb_html)
        print(f"  LNB HTML: {len(lnb_html)}자 저장")

        # ──────────────────────────────────────────────
        # Step 2: "개인지출결의서" chevron 클릭으로 펼치기
        # ──────────────────────────────────────────────
        print("\n[Step 2] '개인지출결의서' 메뉴 chevron 클릭")

        # 모든 nav-item.step-1 내부 구조 상세 추출
        step1_details = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('.nav-item.step-1').forEach(el => {
                const clone = el.cloneNode(true);
                // 하위 nav-item 제거
                clone.querySelectorAll('.nav-item').forEach(c => c.remove());

                const children = [];
                for (const child of el.children) {
                    children.push({
                        tag: child.tagName,
                        className: child.className.substring ? child.className.substring(0, 100) : '',
                        text: child.textContent.trim().substring(0, 50),
                        type: child.getAttribute('type') || '',
                    });
                }

                result.push({
                    text: clone.textContent.trim().substring(0, 50),
                    className: el.className,
                    childrenCount: el.children.length,
                    directChildren: children,
                    innerHTML: el.innerHTML.substring(0, 500),
                });
            });
            return result;
        }""")
        save_json(step1_details, "hp_v5_02_step1_details")
        for item in step1_details:
            print(f"  '{item['text'][:30]}' children={item['childrenCount']}")
            for ch in item['directChildren']:
                print(f"    <{ch['tag']}> class={ch['className'][:40]} text={ch['text'][:30]}")

        # chevron / toggle 버튼 클릭 시도
        expand_result = page.evaluate("""() => {
            const results = [];
            const items = document.querySelectorAll('.nav-item.step-1');
            for (const el of items) {
                // 자식에서 텍스트만 추출
                const clone = el.cloneNode(true);
                clone.querySelectorAll('.nav-item').forEach(c => c.remove());
                const text = clone.textContent.trim();

                if (text.includes('개인지출결의서') || text.includes('지출결의/계산서')) {
                    // 클릭 대상 찾기: toggle 버튼, chevron 아이콘, 또는 첫 번째 자식
                    const targets = [
                        el.querySelector('.btn-toggle'),
                        el.querySelector('[class*="toggle"]'),
                        el.querySelector('[class*="arrow"]'),
                        el.querySelector('[class*="chevron"]'),
                        el.querySelector('[class*="expand"]'),
                        el.querySelector('svg'),
                        el.querySelector('i'),
                        el.querySelector('button'),
                        el.querySelector('span'),
                    ];

                    for (const target of targets) {
                        if (target) {
                            target.click();
                            results.push({text, clicked: target.tagName, className: target.className});
                            break;
                        }
                    }
                    if (results.length === 0 || !results[results.length-1].text?.includes(text)) {
                        // 직접 클릭
                        el.click();
                        results.push({text, clicked: 'self'});
                    }
                }
            }
            return results;
        }""")
        print(f"  클릭 결과: {json.dumps(expand_result, ensure_ascii=False)}")
        page.wait_for_timeout(3000)
        save(page, "hp_v5_02_after_expand")

        # 펼침 후 메뉴 재확인
        tree_after = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('.nav-item').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    const clone = el.cloneNode(true);
                    clone.querySelectorAll('.nav-item, ul').forEach(c => c.remove());
                    const text = clone.textContent.trim().substring(0, 50);
                    result.push({text, className: el.className});
                }
            });
            return result;
        }""")
        print(f"  펼침 후 메뉴: {len(tree_after)}개")
        for item in tree_after:
            cls = item['className']
            step = ""
            if "step-3" in cls: step = "      "
            elif "step-2" in cls: step = "    "
            elif "step-1" in cls: step = "  "
            flag = ""
            if "open" in cls: flag = " [O]"
            elif "close" in cls: flag = " [C]"
            if "selected" in cls: flag += " [S]"
            print(f"  {step}{item['text'][:40]}{flag}")

        # ──────────────────────────────────────────────
        # Step 3: 스크린샷에서 보인 하위 항목 (개인지출결의서작성, 개인지출결의현황, 증빙자료현황) 직접 클릭
        # ──────────────────────────────────────────────
        print("\n[Step 3] 하위 메뉴 아이템 직접 좌표 클릭")
        # Phase 1 스크린샷에서:
        # 개인지출결의서 확장 시 하위:
        #   개인지출결의서작성 (약 y=480~490)
        #   개인지출결의현황 (약 y=510)
        #   증빙자료현황 (약 y=530)
        # 하지만 현재 상태에서는 닫혀있을 수 있음

        # 먼저: Playwright locator로 텍스트 기반 클릭 시도
        for target_text in ["개인지출결의현황", "개인지출결의서작성", "결의현황", "증빙자료현황"]:
            try:
                loc = page.locator(f"text='{target_text}'").first
                if loc.is_visible(timeout=2000):
                    print(f"  '{target_text}' visible → 클릭")
                    loc.click(force=True)
                    page.wait_for_timeout(5000)
                    close_popups(page)
                    print(f"  URL: {page.url}")
                    save(page, "hp_v5_03_clicked")
                    break
            except Exception:
                continue
        else:
            print("  텍스트 기반 클릭 실패, 좌표 클릭 시도...")
            # "개인지출결의서" 메뉴 위치: x=48~193, y=559~594 (Phase 1 기준)
            # "개인지출결의서" 텍스트 자체를 클릭하면 토글될 수 있음
            # 스크린에서 보면 "개인지출결의서" 는 약 x=60, y=464

            # "개인지출결의서" 메뉴의 chevron (v) 아이콘 = 메뉴 우측
            page.mouse.click(166, 464)  # chevron 위치 (스크린샷 기준)
            page.wait_for_timeout(2000)
            save(page, "hp_v5_03_after_chevron_click")

            tree3 = page.evaluate("""() => {
                const result = [];
                document.querySelectorAll('.nav-item').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                        const clone = el.cloneNode(true);
                        clone.querySelectorAll('.nav-item, ul').forEach(c => c.remove());
                        result.push({
                            text: clone.textContent.trim().substring(0, 50),
                            className: el.className,
                            y: Math.round(rect.y),
                        });
                    }
                });
                return result;
            }""")
            print(f"  chevron 클릭 후 메뉴:")
            for item in tree3:
                cls = item['className']
                step = ""
                if "step-3" in cls: step = "      "
                elif "step-2" in cls: step = "    "
                elif "step-1" in cls: step = "  "
                flag = ""
                if "open" in cls: flag = " [O]"
                elif "close" in cls: flag = " [C]"
                if "selected" in cls: flag += " [S]"
                print(f"  {step}{item['text'][:40]}{flag}  y={item['y']}")

            # 하위 메뉴가 나타났으면 클릭
            for target in ["개인지출결의현황", "개인지출결의서작성", "증빙자료현황"]:
                for item in tree3:
                    if target in item['text']:
                        print(f"  '{target}' 발견 at y={item['y']} → 클릭")
                        page.mouse.click(100, item['y'])
                        page.wait_for_timeout(5000)
                        close_popups(page)
                        print(f"  URL: {page.url}")
                        break
                else:
                    continue
                break

        # ──────────────────────────────────────────────
        # Step 4: Playwright locator로 nav-item 텍스트 클릭 (더 정확하게)
        # ──────────────────────────────────────────────
        current_url = page.url
        if "HPM0110" in current_url:
            print("\n[Step 4] Playwright locator로 정확한 클릭 시도")
            # "개인지출결의서" 텍스트를 가진 step-1 item의 chevron 아이콘
            # Playwright에서 CSS + text 조합
            try:
                # step-1 nav-item 중 "개인지출결의서" 포함하는 것의 하위 버튼/아이콘
                loc = page.locator(".nav-item.step-1:has-text('개인지출결의서')").first
                if loc.is_visible(timeout=2000):
                    bbox = loc.bounding_box()
                    print(f"  '개인지출결의서' nav-item: {bbox}")
                    # 우측 chevron 클릭 (bbox 우측 끝)
                    if bbox:
                        page.mouse.click(bbox['x'] + bbox['width'] - 10, bbox['y'] + bbox['height'] / 2)
                        print("  chevron 우측 클릭")
                        page.wait_for_timeout(3000)
                        save(page, "hp_v5_04_after_precise_click")

                        # 하위 step-2 메뉴 확인
                        sub = page.evaluate("""() => {
                            const r = [];
                            document.querySelectorAll('.nav-item.step-2').forEach(el => {
                                const rect = el.getBoundingClientRect();
                                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                                    r.push({
                                        text: el.textContent.trim().substring(0, 50),
                                        className: el.className,
                                        y: Math.round(rect.y),
                                    });
                                }
                            });
                            return r;
                        }""")
                        print(f"  step-2 메뉴: {len(sub)}개")
                        for s in sub:
                            print(f"    {s['text'][:40]} y={s['y']}")
            except Exception as e:
                print(f"  실패: {e}")

        # ──────────────────────────────────────────────
        # Step 5: React Router 직접 네비게이션 시도
        # ──────────────────────────────────────────────
        if "HPM0110" in page.url:
            print("\n[Step 5] React Router / SPA 네비게이션 시도")

            # 더존 URL 패턴 추측: /#/HP/{moduleId}/{pageId}
            # 기존 URL: /#/HP/HPM0110/HPM0110 (개인인사정보조회)
            # 지출결의서 관련 가능한 URL 패턴:
            url_candidates = [
                # 개인지출결의서 관련
                "/#/HP/HPM0710/HPM0710",  # 개인지출결의서작성
                "/#/HP/HPM0720/HPM0720",  # 개인지출결의현황
                "/#/HP/HPM0730/HPM0730",  # 증빙자료현황
                "/#/HP/HPM0711/HPM0711",
                "/#/HP/HPM0721/HPM0721",
                # 지출결의/계산서 관련
                "/#/HP/HPM0610/HPM0610",
                "/#/HP/HPM0620/HPM0620",
                "/#/HP/HPM0630/HPM0630",
                "/#/HP/HPM0640/HPM0640",
                "/#/HP/HPM0611/HPM0611",
                "/#/HP/HPM0621/HPM0621",
                # 경비청구
                "/#/HP/HPM0510/HPM0510",
                "/#/HP/HPM0520/HPM0520",
                "/#/HP/HPM0530/HPM0530",
                "/#/HP/HPM0540/HPM0540",
            ]

            found_pages = []
            for url_path in url_candidates:
                api_calls_before = len(api_calls)
                try:
                    page.goto(f"{GW_URL}{url_path}", wait_until="domcontentloaded", timeout=10000)
                    page.wait_for_timeout(3000)
                    cur = page.url
                    text = page.evaluate("() => document.body ? document.body.innerText.substring(0, 500) : ''")

                    # 페이지가 로드됐는지 확인 (개인인사정보조회가 아닌 다른 페이지)
                    has_content = False
                    content_area = text[200:] if len(text) > 200 else text  # LNB 텍스트 건너뛰기
                    if len(content_area.strip()) > 50:
                        # 개인인사정보조회 텍스트가 아닌 경우
                        if "사용자기본정보" not in content_area and "프로필명" not in content_area:
                            has_content = True

                    new_apis = len(api_calls) - api_calls_before
                    label = "★ NEW" if has_content else "same"
                    print(f"    {url_path} → {cur[:60]} | {label} | APIs: {new_apis}")

                    if has_content:
                        found_pages.append(url_path)
                        page_name = url_path.replace("/#/HP/", "").replace("/", "_")
                        save(page, f"hp_v5_05_{page_name}")
                        # 텍스트 저장
                        full_text = page.evaluate("() => document.body ? document.body.innerText.substring(0, 15000) : ''")
                        with open(OUTPUT_DIR / f"hp_v5_05_{page_name}_text.txt", "w", encoding="utf-8") as f:
                            f.write(full_text)
                        print(f"      텍스트: {content_area[:120]}...")

                        # 이 페이지의 DOM 분석
                        page_elements = page.evaluate("""() => {
                            const r = {};
                            // 탭
                            const tabs = [];
                            document.querySelectorAll('.tab-item, [class*="OBTTabs"]').forEach(el => {
                                const rect = el.getBoundingClientRect();
                                if (el.offsetParent !== null && rect.x > 200 && rect.width > 0) {
                                    const text = el.textContent.trim().substring(0, 50);
                                    if (text.length < 40) tabs.push({text, selected: el.className.includes('on')});
                                }
                            });
                            r.tabs = tabs;

                            // 버튼
                            const btns = [];
                            document.querySelectorAll('button').forEach(el => {
                                const rect = el.getBoundingClientRect();
                                if (el.offsetParent !== null && rect.x > 200 && rect.width > 0) {
                                    const text = el.textContent.trim().substring(0, 40);
                                    if (text) btns.push(text);
                                }
                            });
                            r.buttons = btns;

                            // 입력
                            const inputs = [];
                            document.querySelectorAll('input, select').forEach(el => {
                                const rect = el.getBoundingClientRect();
                                if (el.offsetParent !== null && rect.x > 200 && rect.width > 0) {
                                    inputs.push({type: el.type, value: el.value.substring(0, 30), id: el.id});
                                }
                            });
                            r.inputs = inputs;

                            // 그리드
                            const grids = [];
                            document.querySelectorAll('[class*="OBTDataGrid"], canvas').forEach(el => {
                                const rect = el.getBoundingClientRect();
                                if (rect.width > 50 && rect.height > 50) {
                                    grids.push({
                                        className: (el.className?.substring ? el.className.substring(0, 100) : ''),
                                        size: rect.width + 'x' + rect.height,
                                    });
                                }
                            });
                            r.grids = grids;

                            return r;
                        }""")
                        save_json(page_elements, f"hp_v5_05_{page_name}_elements")
                        print(f"      탭: {page_elements.get('tabs', [])}")
                        print(f"      버튼: {page_elements.get('buttons', [])[:10]}")
                        print(f"      입력: {len(page_elements.get('inputs', []))}개")
                        print(f"      그리드: {len(page_elements.get('grids', []))}개")

                        # 그리드가 있으면 데이터 추출
                        if page_elements.get('grids'):
                            gd = page.evaluate("""() => {
                                try {
                                    const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
                                    if (!gridEl) return {error: 'no grid'};
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
                                                }));
                                            } catch(e) {}
                                            let data = [];
                                            for (let r = 0; r < Math.min(20, rc); r++) {
                                                const row = {};
                                                cols.forEach(c => {
                                                    try { row[c.name] = String(iface.getValue(r, c.name)).substring(0, 80); } catch(e) {}
                                                });
                                                data.push(row);
                                            }
                                            return {depth: i, rowCount: rc, columns: cols, data};
                                        }
                                        if (f) f = f.return;
                                    }
                                    return {error: 'no interface'};
                                } catch(e) { return {error: e.message}; }
                            }""")
                            save_json(gd, f"hp_v5_05_{page_name}_grid_data")
                            print(f"      그리드 데이터: {gd.get('rowCount', '?')}행, {len(gd.get('columns', []))}열")

                except Exception as e:
                    print(f"    {url_path} → 오류: {e}")

            if found_pages:
                print(f"\n  발견된 페이지: {found_pages}")
            else:
                print("\n  유효한 페이지 없음. 메뉴 코드 추출 시도...")

                # GW API로 메뉴 코드 조회
                menu_codes = page.evaluate("""() => {
                    // window.__menuData 등의 전역 변수 확인
                    const globals = {};
                    for (const key of Object.keys(window)) {
                        if (key.includes('menu') || key.includes('Menu') || key.includes('nav') || key.includes('Nav')) {
                            try {
                                const val = window[key];
                                if (val && typeof val === 'object') {
                                    globals[key] = JSON.stringify(val).substring(0, 500);
                                }
                            } catch(e) {}
                        }
                    }
                    return globals;
                }""")
                save_json(menu_codes, "hp_v5_05_window_menu_globals")
                print(f"  window 메뉴 관련 전역 변수: {list(menu_codes.keys())}")

        # ──────────────────────────────────────────────
        # Step 6: GW API로 메뉴 목록 직접 조회
        # ──────────────────────────────────────────────
        print("\n[Step 6] GW API로 HP 모듈 메뉴 목록 조회")

        # gw114A11 = 메뉴 정보 API로 보임 (v3에서 캡처됨)
        menu_api_result = page.evaluate("""async () => {
            try {
                // 방법 1: gw114A11 API 호출
                const resp1 = await fetch('/gw/APIHandler/gw114A11', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({moduleCode: 'HP'}),
                });
                const data1 = await resp1.json();
                return {api: 'gw114A11', data: data1};
            } catch(e) {
                return {error: e.message};
            }
        }""")
        save_json(menu_api_result, "hp_v5_06_menu_api")
        preview = json.dumps(menu_api_result, ensure_ascii=False)[:500]
        print(f"  gw114A11 결과: {preview}")

        # 방법 2: personal 모듈 메뉴 API
        menu_api2 = page.evaluate("""async () => {
            try {
                const resp = await fetch('/personal/menu/getMenuList', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({moduleCode: 'HP'}),
                });
                return await resp.json();
            } catch(e1) {
                try {
                    const resp = await fetch('/gw/gw015A43', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({moduleCode: 'HP'}),
                    });
                    return await resp.json();
                } catch(e2) {
                    return {error1: e1.message, error2: e2.message};
                }
            }
        }""")
        save_json(menu_api2, "hp_v5_06_menu_api2")
        preview2 = json.dumps(menu_api2, ensure_ascii=False)[:500]
        print(f"  메뉴 API2: {preview2}")

    except Exception as e:
        print(f"\n[오류] {e}")
        traceback.print_exc()
        save(page, "hp_v5_error")

    finally:
        save_json(api_calls, "hp_v5_api_calls")
        save_json(api_responses, "hp_v5_api_responses")
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

        for resp in api_responses[:15]:
            body = resp.get('body')
            if body:
                preview = json.dumps(body, ensure_ascii=False)[:200] if isinstance(body, (dict, list)) else str(body)[:200]
                print(f"    응답 [{resp['status']}] {resp['url'][:80]}: {preview}")

        print("\n" + "=" * 60)
        hp_files = sorted(OUTPUT_DIR.glob("hp_v5_*"))
        print(f"파일 ({len(hp_files)}개):")
        for f in hp_files:
            print(f"  {f.name:60s}  {f.stat().st_size:>8,} bytes")

        close_session(browser)


if __name__ == "__main__":
    main()
