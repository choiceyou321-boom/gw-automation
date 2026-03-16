"""
예실대비현황(상세) Phase 0 DOM 탐색 v2

v1에서 발견한 문제:
- 예실대비현황(상세) URL: #/BN/NCC0610/NCC0610 → 본문 영역 비어 있음
- 예실대비현황(상세) 메뉴 코드: NCC0630 (API 로그에서 확인)
- 콘텐츠가 iframe이나 lazy loading일 가능성

v2 개선:
1. 메뉴 클릭 후 더 긴 대기 (10초)
2. iframe 탐색
3. 전체 DOM 심층 분석 (shadow DOM, React 컴포넌트)
4. 직접 URL #/BN/NCC0630/NCC0630 시도
5. 더 넓은 API 캡처 범위
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
    """Network API 캡처 - 더 넓은 범위"""
    captured_apis = []

    def on_response(response):
        url = response.url
        # 더존 GW 내부 API만 (이미지/CSS/JS 제외)
        if ('gw.glowseoul.co.kr' in url and
            not any(ext in url for ext in ['.png', '.jpg', '.css', '.js', '.woff', '.svg', '.ico'])):
            try:
                ct = response.headers.get('content-type', '') or ''
                body = None
                if 'json' in ct:
                    body = response.json()
            except Exception:
                body = None
            entry = {
                "url": url,
                "status": response.status,
                "method": response.request.method,
                "post_data": response.request.post_data,
                "response_preview": str(body)[:3000] if body else None,
            }
            captured_apis.append(entry)
            print(f"  [API] {response.request.method} {url.split('?')[0]} → {response.status}")

    page.on("response", on_response)
    return captured_apis


def deep_dom_analysis(page, label=""):
    """페이지의 전체 DOM 심층 분석"""
    print(f"\n── DOM 심층 분석 ({label}) ──")
    result = {}

    # 1. iframe 탐색
    try:
        iframes = page.evaluate("""() => {
            const frames = document.querySelectorAll('iframe');
            return Array.from(frames).map(f => ({
                src: f.src || '',
                id: f.id || '',
                name: f.name || '',
                className: (f.className || '').substring(0, 200),
                w: f.offsetWidth,
                h: f.offsetHeight,
                visible: f.offsetParent !== null,
            }));
        }""")
        result["iframes"] = iframes
        print(f"  iframe 수: {len(iframes)}")
        for iframe in iframes:
            print(f"    iframe: src='{iframe['src']}' id='{iframe['id']}' {iframe['w']}x{iframe['h']} visible={iframe['visible']}")
    except Exception as e:
        print(f"  iframe 탐색 실패: {e}")

    # 2. 전체 body 직계 자식 구조
    try:
        body_children = page.evaluate("""() => {
            const children = document.body.children;
            return Array.from(children).map(el => ({
                tag: el.tagName,
                id: el.id || '',
                className: (el.className || '').toString().substring(0, 300),
                w: el.offsetWidth,
                h: el.offsetHeight,
                childCount: el.children.length,
                text_preview: (el.textContent || '').trim().substring(0, 200),
                visible: el.offsetParent !== null || el.tagName === 'BODY',
            }));
        }""")
        result["body_children"] = body_children
        print(f"  body 직계 자식: {len(body_children)}개")
        for child in body_children:
            if child['w'] > 0 or child['h'] > 0:
                print(f"    <{child['tag']}> id='{child['id']}' cls='{child['className'][:80]}' {child['w']}x{child['h']} children={child['childCount']}")
    except Exception as e:
        print(f"  body 자식 분석 실패: {e}")

    # 3. #app 내부 구조 (React SPA 앱)
    try:
        app_structure = page.evaluate("""() => {
            const app = document.querySelector('#app, #root, [id*="app"], [id*="root"]');
            if (!app) return { error: 'app container 없음' };

            function traverse(el, depth) {
                if (depth > 5) return null;
                const rect = el.getBoundingClientRect();
                const node = {
                    tag: el.tagName,
                    id: el.id || '',
                    cls: (el.className || '').toString().substring(0, 150),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                };
                // 콘텐츠 영역(큰 크기)만 자식 탐색
                if (rect.width > 200 && rect.height > 100) {
                    const kids = Array.from(el.children)
                        .filter(c => c.offsetWidth > 50 || c.offsetHeight > 50)
                        .map(c => traverse(c, depth + 1))
                        .filter(Boolean);
                    if (kids.length > 0) node.children = kids;
                }
                return node;
            }

            return traverse(app, 0);
        }""")
        result["app_structure"] = app_structure
        print(f"  앱 구조: {json.dumps(app_structure, ensure_ascii=False)[:500]}")
    except Exception as e:
        print(f"  앱 구조 분석 실패: {e}")

    # 4. 콘텐츠 영역 (메인 콘텐츠가 x > 240인 영역)
    try:
        content_area = page.evaluate("""() => {
            const allEls = document.querySelectorAll('div, section, article, main');
            const contents = [];
            for (const el of allEls) {
                const rect = el.getBoundingClientRect();
                // 콘텐츠 영역: x > 230 (사이드바 오른쪽), 크기 200 이상
                if (rect.x > 230 && rect.width > 200 && rect.height > 100) {
                    contents.push({
                        tag: el.tagName,
                        id: el.id || '',
                        cls: (el.className || '').toString().substring(0, 200),
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        w: Math.round(rect.width),
                        h: Math.round(rect.height),
                        childCount: el.children.length,
                        text_preview: (el.innerText || '').trim().substring(0, 300),
                        hasCanvas: el.querySelector('canvas') !== null,
                        hasTable: el.querySelector('table') !== null,
                        hasInput: el.querySelector('input') !== null,
                    });
                }
            }
            // 크기 순 정렬
            contents.sort((a, b) => (b.w * b.h) - (a.w * a.h));
            return contents.slice(0, 30);
        }""")
        result["content_area"] = content_area
        print(f"  콘텐츠 영역 요소: {len(content_area)}개")
        for ca in content_area[:10]:
            print(f"    <{ca['tag']}> id='{ca['id']}' cls='{ca['cls'][:60]}' {ca['w']}x{ca['h']} at ({ca['x']},{ca['y']}) children={ca['childCount']} canvas={ca['hasCanvas']} table={ca['hasTable']} input={ca['hasInput']}")
            if ca['text_preview']:
                print(f"      텍스트: {ca['text_preview'][:100]}")
    except Exception as e:
        print(f"  콘텐츠 영역 분석 실패: {e}")

    # 5. 모든 visible input/select 필드 (위치 무관)
    try:
        all_fields = page.evaluate("""() => {
            const els = document.querySelectorAll('input, select, textarea');
            return Array.from(els).map(el => {
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    type: el.type || '',
                    id: el.id || '',
                    name: el.name || '',
                    placeholder: el.placeholder || '',
                    value: el.value || '',
                    disabled: el.disabled,
                    cls: (el.className || '').substring(0, 150),
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                    visible: el.offsetParent !== null,
                    inFrame: el.ownerDocument !== document,
                };
            });
        }""")
        result["all_fields"] = all_fields
        visible_fields = [f for f in all_fields if f['visible']]
        print(f"  전체 필드: {len(all_fields)}개 (visible: {len(visible_fields)}개)")
        for f in visible_fields:
            print(f"    [{f['tag']}] type={f['type']} id='{f['id']}' ph='{f['placeholder']}' val='{f['value']}' ({f['x']},{f['y']}) {f['w']}x{f['h']}")
    except Exception as e:
        print(f"  필드 분석 실패: {e}")

    # 6. 모든 visible 버튼/클릭 가능 요소
    try:
        all_buttons = page.evaluate("""() => {
            const els = document.querySelectorAll('button, [role="button"], a[class*="btn"], div[class*="Btn"], span[class*="btn"]');
            return Array.from(els).filter(el => el.offsetParent !== null).map(el => {
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    text: (el.textContent || '').trim().substring(0, 80),
                    id: el.id || '',
                    cls: (el.className || '').substring(0, 150),
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                };
            });
        }""")
        result["all_buttons"] = all_buttons
        print(f"  visible 버튼: {len(all_buttons)}개")
        for btn in all_buttons:
            if btn['text']:
                print(f"    [{btn['tag']}] '{btn['text']}' ({btn['x']},{btn['y']})")
    except Exception as e:
        print(f"  버튼 분석 실패: {e}")

    return result


def explore_frames(page, context):
    """모든 frame 내부 탐색"""
    print("\n── iframe 내부 탐색 ──")
    result = {}

    frames = page.frames
    print(f"  총 frame 수: {len(frames)}")

    for i, frame in enumerate(frames):
        frame_url = frame.url
        frame_name = frame.name
        print(f"\n  Frame[{i}]: name='{frame_name}' url='{frame_url}'")

        if frame_url == 'about:blank' or frame_url == '':
            print(f"    빈 프레임, 건너뜀")
            continue

        try:
            # 프레임 내부 DOM
            frame_content = frame.evaluate("""() => {
                const result = {};
                result.title = document.title;
                result.body_text = (document.body?.innerText || '').substring(0, 3000);
                result.body_html_length = (document.body?.innerHTML || '').length;

                // input 필드
                const inputs = document.querySelectorAll('input, select, textarea');
                result.inputs = Array.from(inputs).map(el => ({
                    tag: el.tagName,
                    type: el.type || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    value: el.value || '',
                    cls: (el.className || '').substring(0, 150),
                }));

                // 테이블/그리드
                const grids = document.querySelectorAll('[class*="grid"], [class*="Grid"], table, canvas');
                result.grids = Array.from(grids).map(el => ({
                    tag: el.tagName,
                    cls: (el.className || '').substring(0, 200),
                    w: el.offsetWidth,
                    h: el.offsetHeight,
                }));

                // 버튼
                const btns = document.querySelectorAll('button, [role="button"]');
                result.buttons = Array.from(btns).map(el => ({
                    text: (el.textContent || '').trim().substring(0, 60),
                    cls: (el.className || '').substring(0, 100),
                }));

                return result;
            }""")
            result[f"frame_{i}"] = {
                "name": frame_name,
                "url": frame_url,
                "content": frame_content,
            }
            print(f"    제목: {frame_content.get('title', '')}")
            print(f"    body HTML 길이: {frame_content.get('body_html_length', 0)}")
            print(f"    inputs: {len(frame_content.get('inputs', []))}개")
            print(f"    grids: {len(frame_content.get('grids', []))}개")
            print(f"    buttons: {len(frame_content.get('buttons', []))}개")
            if frame_content.get('body_text'):
                print(f"    텍스트 미리보기: {frame_content['body_text'][:200]}")
        except Exception as e:
            print(f"    프레임 분석 실패: {e}")

    return result


def try_direct_url_navigation(page):
    """다양한 URL 패턴으로 예실대비현황(상세) 직접 이동"""
    print("\n" + "=" * 60)
    print("URL 직접 이동 시도")
    print("=" * 60)

    # NCC0630이 예실대비현황(상세) 코드일 가능성
    urls_to_try = [
        ("NCC0630", "https://gw.glowseoul.co.kr/#/BN/NCC0630/NCC0630"),
        ("NCC0610_sub", "https://gw.glowseoul.co.kr/#/BN/NCC0610/NCC0630"),
        ("BZA_budget_detail", "https://gw.glowseoul.co.kr/#/BN/NCH0010/NCC0630"),
    ]

    for label, url in urls_to_try:
        print(f"\n  [{label}] {url}")
        try:
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(5)
            print(f"    이동 후 URL: {page.url}")

            # 페이지 제목 확인
            title = page.evaluate("""() => {
                const h1 = document.querySelector('h1, h2, [class*="title"], [class*="Title"]');
                return h1 ? h1.textContent.trim() : '';
            }""")
            print(f"    페이지 제목: '{title}'")

            # 본문 텍스트 확인
            body_text = page.evaluate("""() => {
                const main = document.querySelector('[class*="content"], [class*="Content"], main');
                return (main || document.body).innerText.substring(0, 500);
            }""")
            print(f"    본문 텍스트: '{body_text[:200]}'")

            if title and ('예실' in title or '대비' in title):
                capture(page, f"budget_actual_v2_{label}.png")
                return url
        except Exception as e:
            print(f"    실패: {e}")

    return None


def main():
    print("=" * 60)
    print("예실대비현황(상세) Phase 0 DOM 탐색 v2")
    print("=" * 60)

    all_results = {}

    with sync_playwright() as pw:
        # 로그인
        browser, context, page = login(pw)

        # API 캡처
        captured_apis = setup_api_capture(page)

        # Step 1: 예산관리 모듈 → 예실대비현황(상세) 메뉴 클릭
        print("\n" + "=" * 60)
        print("Step 1: 예산관리 → 예실대비현황(상세)")
        print("=" * 60)

        page.goto("https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0020", wait_until="domcontentloaded")
        time.sleep(4)
        print(f"  예산관리 진입: {page.url}")

        # 예산장부 메뉴 펼치기
        try:
            el = page.locator("text=예산장부").first
            if el.is_visible(timeout=3000):
                el.click()
                time.sleep(2)
                print("  '예산장부' 펼침")
        except Exception:
            pass

        # 예실대비현황(상세) 클릭
        try:
            el = page.locator("text=예실대비현황(상세)").first
            if el.is_visible(timeout=3000):
                el.click()
                print("  '예실대비현황(상세)' 클릭 완료")
                # 충분히 대기 (10초)
                print("  페이지 로드 대기 10초...")
                time.sleep(10)
                print(f"  현재 URL: {page.url}")
        except Exception as e:
            print(f"  메뉴 클릭 실패: {e}")

        capture(page, "budget_actual_v2_01_detail_page.png")

        # Step 2: 심층 DOM 분석
        print("\n" + "=" * 60)
        print("Step 2: 심층 DOM 분석")
        print("=" * 60)

        dom_result = deep_dom_analysis(page, "예실대비현황(상세) 초기")
        all_results["initial_dom"] = dom_result

        # Step 3: iframe 탐색
        print("\n" + "=" * 60)
        print("Step 3: iframe 탐색")
        print("=" * 60)

        frame_result = explore_frames(page, context)
        all_results["frames"] = frame_result

        # Step 4: React 컴포넌트 트리 탐색
        print("\n" + "=" * 60)
        print("Step 4: React 컴포넌트 탐색")
        print("=" * 60)

        try:
            react_data = page.evaluate("""() => {
                const result = {};
                // React root 찾기
                const app = document.querySelector('#app');
                if (app) {
                    const fiberKey = Object.keys(app).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactContainer'));
                    result.has_react = !!fiberKey;
                    result.fiber_key = fiberKey || 'none';

                    if (fiberKey) {
                        let fiber = app[fiberKey];
                        // 컴포넌트 이름 수집 (depth 20까지)
                        const components = [];
                        let current = fiber;
                        for (let i = 0; i < 50 && current; i++) {
                            if (current.type) {
                                const name = typeof current.type === 'function'
                                    ? (current.type.displayName || current.type.name || '')
                                    : (typeof current.type === 'string' ? current.type : '');
                                if (name && !['div','span','a','ul','li','button','input'].includes(name)) {
                                    components.push(name);
                                }
                            }
                            // child 우선, 없으면 sibling
                            current = current.child || current.sibling || (current.return ? current.return.sibling : null);
                        }
                        result.component_names = [...new Set(components)].slice(0, 50);
                    }
                }

                // 전역 변수 탐색 (예산 관련)
                const globals = {};
                for (const key of Object.keys(window)) {
                    const lk = key.toLowerCase();
                    if (lk.includes('budget') || lk.includes('grid') || lk.includes('ncc') || lk.includes('bza')) {
                        globals[key] = typeof window[key];
                    }
                }
                result.budget_globals = globals;

                return result;
            }""")
            all_results["react"] = react_data
            print(f"  React: {react_data.get('has_react', False)}")
            print(f"  컴포넌트: {react_data.get('component_names', [])[:20]}")
            print(f"  전역 변수: {react_data.get('budget_globals', {})}")
        except Exception as e:
            print(f"  React 탐색 실패: {e}")

        # Step 5: 페이지 전체 HTML 크기 및 특정 패턴 검색
        print("\n" + "=" * 60)
        print("Step 5: HTML 패턴 분석")
        print("=" * 60)

        try:
            html_analysis = page.evaluate("""() => {
                const html = document.documentElement.outerHTML;
                const result = {
                    total_html_length: html.length,
                    has_obtdatagrid: html.includes('OBTDataGrid'),
                    has_realgrid: html.includes('RealGrid'),
                    has_canvas: html.includes('<canvas'),
                    has_table_tag: html.includes('<table'),
                    has_loading: html.includes('loading') || html.includes('Loading') || html.includes('spinner'),
                };

                // "예실" 포함 텍스트 검색
                const yesil_matches = [];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const text = walker.currentNode.textContent.trim();
                    if (text.includes('예실') || text.includes('예산') || text.includes('집행') || text.includes('잔액')) {
                        const parent = walker.currentNode.parentElement;
                        yesil_matches.push({
                            text: text.substring(0, 100),
                            parentTag: parent?.tagName || '',
                            parentClass: (parent?.className || '').substring(0, 100),
                        });
                    }
                }
                result.budget_text_matches = yesil_matches.slice(0, 30);

                return result;
            }""")
            all_results["html_analysis"] = html_analysis
            print(f"  HTML 크기: {html_analysis['total_html_length']}bytes")
            print(f"  OBTDataGrid: {html_analysis['has_obtdatagrid']}")
            print(f"  RealGrid: {html_analysis['has_realgrid']}")
            print(f"  Canvas: {html_analysis['has_canvas']}")
            print(f"  Table: {html_analysis['has_table_tag']}")
            print(f"  Loading: {html_analysis['has_loading']}")
            print(f"  예산 관련 텍스트: {len(html_analysis['budget_text_matches'])}개")
            for m in html_analysis['budget_text_matches'][:10]:
                print(f"    '{m['text'][:60]}' in <{m['parentTag']}> cls={m['parentClass'][:40]}")
        except Exception as e:
            print(f"  HTML 분석 실패: {e}")

        # Step 6: NCC0630 URL 직접 시도
        found_url = try_direct_url_navigation(page)
        if found_url:
            all_results["direct_url"] = found_url
            # 성공한 URL에서 DOM 분석
            dom2 = deep_dom_analysis(page, "직접 URL 이동 후")
            all_results["direct_url_dom"] = dom2

        # Step 7: 예실대비현황(상세) 페이지로 다시 이동 + 조회 실행
        print("\n" + "=" * 60)
        print("Step 7: 재이동 + 조회 실행")
        print("=" * 60)

        # 다시 예산관리 → 예실대비현황(상세)
        page.goto("https://gw.glowseoul.co.kr/#/BN/NCH0010/BZA0020", wait_until="domcontentloaded")
        time.sleep(3)

        # 예산장부 펼치기
        try:
            page.locator("text=예산장부").first.click()
            time.sleep(1)
        except Exception:
            pass

        # 예실대비현황(상세) 클릭
        try:
            page.locator("text=예실대비현황(상세)").first.click()
            time.sleep(3)
        except Exception:
            pass

        # 매 초마다 체크하며 최대 15초 대기
        print("  콘텐츠 로드 대기 (최대 15초)...")
        for i in range(15):
            time.sleep(1)
            has_content = page.evaluate("""() => {
                // 입력 필드나 그리드가 나타났는지 체크
                const inputs = document.querySelectorAll('input:not([type="hidden"])');
                const visible_inputs = Array.from(inputs).filter(el => el.offsetParent !== null);
                const grids = document.querySelectorAll('[class*="OBTDataGrid"], [class*="grid"], canvas, table');
                const visible_grids = Array.from(grids).filter(el => el.offsetParent !== null && el.offsetWidth > 100);
                return {
                    visible_inputs: visible_inputs.length,
                    visible_grids: visible_grids.length,
                    body_text_length: (document.body.innerText || '').length,
                };
            }""")
            print(f"    {i+1}초: inputs={has_content['visible_inputs']} grids={has_content['visible_grids']} text={has_content['body_text_length']}")
            if has_content['visible_inputs'] > 2 or has_content['visible_grids'] > 0:
                print("    콘텐츠 로드 감지!")
                break

        capture(page, "budget_actual_v2_02_after_wait.png")

        # 최종 DOM 분석
        final_dom = deep_dom_analysis(page, "최종")
        all_results["final_dom"] = final_dom

        # Step 8: 조회 조건이 있으면 조회 실행
        print("\n" + "=" * 60)
        print("Step 8: 조회 조건 + 조회 실행")
        print("=" * 60)

        # 조회 버튼 찾기/클릭
        try:
            search_btns = page.evaluate("""() => {
                const btns = document.querySelectorAll('button, [role="button"], div[class*="Btn"], span[class*="btn"]');
                return Array.from(btns).filter(el => {
                    const text = (el.textContent || '').trim();
                    return text.includes('조회') && el.offsetParent !== null;
                }).map(el => ({
                    tag: el.tagName,
                    text: (el.textContent || '').trim().substring(0, 50),
                    cls: (el.className || '').substring(0, 150),
                    x: Math.round(el.getBoundingClientRect().x),
                    y: Math.round(el.getBoundingClientRect().y),
                }));
            }""")
            print(f"  '조회' 버튼: {len(search_btns)}개")
            for btn in search_btns:
                print(f"    [{btn['tag']}] '{btn['text']}' at ({btn['x']},{btn['y']}) cls={btn['cls'][:60]}")
            all_results["search_buttons"] = search_btns

            if search_btns:
                # 첫 번째 조회 버튼 클릭
                page.locator("text=조회").first.click()
                time.sleep(5)
                print("  조회 클릭 후 5초 대기")
                capture(page, "budget_actual_v2_03_after_search.png")

                # 조회 후 DOM 재분석
                after_search_dom = deep_dom_analysis(page, "조회 후")
                all_results["after_search_dom"] = after_search_dom
        except Exception as e:
            print(f"  조회 실행 실패: {e}")

        # Step 9: OBTDataGrid 데이터 추출 시도
        print("\n" + "=" * 60)
        print("Step 9: OBTDataGrid 데이터 추출")
        print("=" * 60)

        try:
            grid_extract = page.evaluate("""() => {
                const result = {};

                // 1. OBTDataGrid 요소 찾기
                const gridEls = document.querySelectorAll('[class*="OBTDataGrid"]');
                result.obtdatagrid_count = gridEls.length;

                if (gridEls.length > 0) {
                    const gridEl = gridEls[0];
                    result.grid_class = gridEl.className;

                    // React fiber
                    const fiberKey = Object.keys(gridEl).find(k => k.startsWith('__reactFiber'));
                    result.has_fiber = !!fiberKey;

                    if (fiberKey) {
                        let fiber = gridEl[fiberKey];
                        // depth 1~5 탐색
                        for (let depth = 1; depth <= 5; depth++) {
                            if (fiber && fiber.return) {
                                fiber = fiber.return;
                            }
                            if (fiber?.stateNode?.state?.interface) {
                                result.interface_found_at_depth = depth;
                                const iface = fiber.stateNode.state.interface;
                                try {
                                    result.row_count = iface.getRowCount();
                                    const cols = iface.getColumns();
                                    result.columns = cols.map(c => ({
                                        name: c.name || c.fieldName || '',
                                        header: c.header?.text || c.header || '',
                                        width: c.width || 0,
                                    }));
                                    // 샘플 데이터 (5행)
                                    const rowCount = Math.min(iface.getRowCount(), 5);
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
                                } catch(e) {
                                    result.interface_error = e.message;
                                }
                                break;
                            }
                        }
                    }
                }

                // 2. canvas 기반 그리드
                const canvases = document.querySelectorAll('canvas');
                result.canvas_count = canvases.length;
                result.canvas_info = Array.from(canvases).map(c => ({
                    w: c.width, h: c.height,
                    parentClass: (c.parentElement?.className || '').substring(0, 200),
                }));

                // 3. 일반 table
                const tables = document.querySelectorAll('table');
                result.table_count = tables.length;
                result.tables = Array.from(tables).filter(t => t.offsetWidth > 100).map(t => {
                    const headers = Array.from(t.querySelectorAll('th')).map(th => th.textContent.trim());
                    const firstRow = t.querySelector('tr:nth-child(2) td, tbody tr:first-child td');
                    const cells = firstRow ? Array.from(firstRow.parentElement.querySelectorAll('td')).map(td => td.textContent.trim().substring(0, 50)) : [];
                    return {
                        headers: headers.slice(0, 20),
                        first_row: cells.slice(0, 20),
                        row_count: t.rows?.length || 0,
                        w: t.offsetWidth,
                        h: t.offsetHeight,
                    };
                });

                return result;
            }""")
            all_results["grid_extraction"] = grid_extract
            print(f"  OBTDataGrid 수: {grid_extract.get('obtdatagrid_count', 0)}")
            print(f"  Canvas 수: {grid_extract.get('canvas_count', 0)}")
            print(f"  Table 수: {grid_extract.get('table_count', 0)}")
            if grid_extract.get('columns'):
                print(f"  컬럼: {[c['header'] or c['name'] for c in grid_extract['columns']]}")
            if grid_extract.get('sample_data'):
                print(f"  샘플 데이터: {json.dumps(grid_extract['sample_data'][:2], ensure_ascii=False)[:500]}")
            if grid_extract.get('tables'):
                for t in grid_extract['tables']:
                    print(f"  Table headers: {t['headers']}")
                    print(f"  Table first row: {t['first_row']}")
        except Exception as e:
            print(f"  그리드 추출 실패: {e}")

        # API 결과 저장
        all_results["captured_apis"] = captured_apis
        save_json(captured_apis, "budget_actual_v2_apis.json")
        save_json(all_results, "budget_actual_v2_exploration.json")

        print("\n" + "=" * 60)
        print("탐색 완료!")
        print(f"캡처된 API: {len(captured_apis)}개")
        print(f"결과: {OUTPUT_DIR}")
        print("=" * 60)

        # 브라우저 닫기 (비대화형)
        browser.close()


if __name__ == "__main__":
    main()
