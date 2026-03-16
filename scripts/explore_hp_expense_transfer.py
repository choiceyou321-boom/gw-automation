"""
임직원업무관리(HP) 모듈 - 지출결의서 이체완료 내역 탐색 스크립트
Phase 0: DOM 탐색 + API 캡처
- HP 모듈 진입 → 좌측 메뉴 파악
- 지출결의서 목록 페이지 이동
- 이체완료 탭/필터 탐색
- 기간 설정 (2025-01-01 ~ 2026-12-31)
- 테이블 구조, API 엔드포인트 파악
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


# ─── 공통 유틸 ────────────────────────────────────────────────

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
    print(f"  [저장] {path.name} ({len(data) if isinstance(data, (list, dict)) else '?'})")
    return path


def dump_buttons(page_or_frame, name: str) -> list:
    """보이는 버튼 목록 추출"""
    try:
        info = page_or_frame.evaluate("""() => {
            const result = [];
            document.querySelectorAll('button, [role="button"], a[href], .btn, [class*="btn"], [class*="Btn"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    result.push({
                        text: el.textContent.trim().substring(0, 80),
                        tag: el.tagName.toLowerCase(),
                        id: el.id,
                        href: el.href || '',
                        className: el.className.substring ? el.className.substring(0, 150) : '',
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                               w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return result;
        }""")
    except Exception as e:
        print(f"  [버튼 추출 실패] {e}")
        info = []

    dump_json(info, f"{name}_buttons")
    visible_with_text = [b for b in info if b['text']]
    print(f"  [버튼] 총 {len(info)}개, 텍스트 있음 {len(visible_with_text)}개")
    for b in visible_with_text[:25]:
        print(f"    - \"{b['text'][:60]}\"  ({b['tag']}) id={b['id']}")
    return info


def dump_inputs(page_or_frame, name: str) -> list:
    """입력 필드 목록 추출"""
    try:
        info = page_or_frame.evaluate("""() => {
            const result = [];
            document.querySelectorAll('input, select, textarea').forEach(el => {
                const rect = el.getBoundingClientRect();
                result.push({
                    tag: el.tagName.toLowerCase(),
                    id: el.id,
                    name: el.name,
                    type: el.type || '',
                    placeholder: el.placeholder || '',
                    disabled: el.disabled,
                    visible: el.offsetParent !== null && rect.width > 0,
                    value: el.value ? el.value.substring(0, 80) : '',
                    className: el.className.substring ? el.className.substring(0, 120) : '',
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                           w: Math.round(rect.width), h: Math.round(rect.height)},
                });
            });
            return result;
        }""")
    except Exception as e:
        print(f"  [입력 필드 추출 실패] {e}")
        info = []

    dump_json(info, f"{name}_inputs")
    visible = [i for i in info if i.get("visible")]
    print(f"  [입력] 총 {len(info)}개, visible {len(visible)}개")
    for v in visible[:20]:
        print(f"    - {v['tag']}[{v['type']}] id={v['id']} name={v['name']} val={v['value'][:30]}")
    return info


def dump_tabs(page_or_frame, name: str) -> list:
    """탭/필터 버튼 추출"""
    try:
        info = page_or_frame.evaluate("""() => {
            const result = [];
            document.querySelectorAll('[role="tab"], [class*="tab"], [class*="Tab"], [class*="filter"], [class*="Filter"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    result.push({
                        text: el.textContent.trim().substring(0, 80),
                        tag: el.tagName.toLowerCase(),
                        id: el.id,
                        className: el.className.substring ? el.className.substring(0, 150) : '',
                        ariaSelected: el.getAttribute('aria-selected') || '',
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                               w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return result;
        }""")
    except Exception as e:
        print(f"  [탭 추출 실패] {e}")
        info = []

    dump_json(info, f"{name}_tabs")
    for t in info[:20]:
        sel = f" [SELECTED]" if t.get('ariaSelected') == 'true' else ''
        print(f"    탭: \"{t['text'][:50]}\"{sel}  class={t['className'][:60]}")
    return info


def dump_tables(page_or_frame, name: str) -> list:
    """테이블 구조 추출 (헤더 + 행 수)"""
    try:
        info = page_or_frame.evaluate("""() => {
            const result = [];
            document.querySelectorAll('table').forEach((table, idx) => {
                const rect = table.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    const headers = [];
                    table.querySelectorAll('thead th, thead td, tr:first-child th, tr:first-child td').forEach(th => {
                        headers.push(th.textContent.trim().substring(0, 50));
                    });
                    const rows = table.querySelectorAll('tbody tr');
                    const sampleRows = [];
                    for (let i = 0; i < Math.min(3, rows.length); i++) {
                        const cells = [];
                        rows[i].querySelectorAll('td').forEach(td => {
                            cells.push(td.textContent.trim().substring(0, 50));
                        });
                        sampleRows.push(cells);
                    }
                    result.push({
                        index: idx,
                        className: table.className.substring(0, 100),
                        headers: headers,
                        rowCount: rows.length,
                        sampleRows: sampleRows,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                               w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return result;
        }""")
    except Exception as e:
        print(f"  [테이블 추출 실패] {e}")
        info = []

    dump_json(info, f"{name}_tables")
    for t in info:
        print(f"    테이블[{t['index']}]: {t['rowCount']}행, 헤더={t['headers'][:10]}")
    return info


def dump_left_menu(page, name: str) -> list:
    """좌측 LNB 메뉴 구조 추출"""
    try:
        info = page.evaluate("""() => {
            const result = [];
            // 다양한 LNB 셀렉터 시도
            const selectors = [
                '.lnb li', '[class*="lnb"] li', '[class*="Lnb"] li',
                '[class*="side"] li', '[class*="Side"] li',
                '[class*="menu"] li', '[class*="Menu"] li',
                'nav li', '.tree li', '[class*="tree"] li'
            ];
            const seen = new Set();
            for (const sel of selectors) {
                document.querySelectorAll(sel).forEach(el => {
                    const text = el.textContent.trim().substring(0, 80);
                    if (text && !seen.has(text) && el.offsetParent !== null) {
                        seen.add(text);
                        const rect = el.getBoundingClientRect();
                        result.push({
                            text: text,
                            className: el.className.substring ? el.className.substring(0, 120) : '',
                            depth: el.querySelectorAll('ul').length,
                            rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                                   w: Math.round(rect.width), h: Math.round(rect.height)},
                        });
                    }
                });
            }
            return result;
        }""")
    except Exception as e:
        print(f"  [메뉴 추출 실패] {e}")
        info = []

    dump_json(info, f"{name}_menu")
    print(f"  [좌측메뉴] {len(info)}개 항목")
    for m in info[:30]:
        indent = "  " * m.get('depth', 0)
        print(f"    {indent}▸ {m['text'][:50]}  (x={m['rect']['x']})")
    return info


def dump_page_text(page, name: str) -> str:
    """전체 페이지 텍스트 추출"""
    try:
        text = page.evaluate("""() => {
            return document.body ? document.body.innerText.substring(0, 10000) : '';
        }""")
    except Exception as e:
        print(f"  [텍스트 추출 실패] {e}")
        text = ""

    path = OUTPUT_DIR / f"{name}_text.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  [텍스트] {path.name} ({len(text)}자)")
    return text


def close_popups(page, wait_ms=2000):
    """팝업 창 닫기"""
    try:
        pages = page.context.pages
        closed = 0
        for p in pages:
            try:
                url = p.url.lower()
                if "popup" in url or "notice" in url or "alert" in url:
                    p.close()
                    closed += 1
            except Exception:
                pass
        if closed:
            print(f"  [팝업] {closed}개 닫음")
        page.wait_for_timeout(wait_ms)
    except Exception as e:
        print(f"  [팝업 닫기 실패] {e}")


# ─── 메인 탐색 ────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("HP(임직원업무관리) 모듈 - 지출결의서 이체완료 내역 탐색")
    print(f"결과 저장: {OUTPUT_DIR}")
    print("=" * 60)

    # API 캡처 리스트
    api_calls = []
    api_responses = []

    def on_request(req):
        url = req.url
        if any(x in url for x in ['/api/', '/rs', '/gw/', 'ajax', '.json', 'Rest', 'Svc',
                                     'hp', 'HP', 'eap', 'EAP', 'expense', 'transfer',
                                     'accSlip', 'voucher']):
            api_calls.append({
                "method": req.method,
                "url": url[:300],
                "resource_type": req.resource_type,
                "post_data": req.post_data[:500] if req.post_data else None,
            })

    def on_response(resp):
        url = resp.url
        if any(x in url for x in ['/api/', '/rs', 'hp', 'HP', 'eap', 'EAP',
                                     'accSlip', 'voucher', 'expense', 'transfer',
                                     'A01', 'A02', 'A03', 'A04', 'A05', 'A06',
                                     'A07', 'A08', 'A09', 'A10']):
            body = None
            try:
                body = resp.json()
                # 너무 크면 줄임
                body_str = json.dumps(body, ensure_ascii=False)
                if len(body_str) > 5000:
                    body = {"_truncated": True, "_size": len(body_str), "_preview": body_str[:2000]}
            except Exception:
                try:
                    body = resp.text()[:2000]
                except Exception:
                    pass

            api_responses.append({
                "status": resp.status,
                "url": url[:300],
                "body_preview": body,
            })

    print("\n[1/7] 로그인 중...")
    browser, context, page = login_and_get_context(headless=False)
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.on("dialog", lambda d: d.accept())
    page.on("request", on_request)
    page.on("response", on_response)

    results = {"gw_url": GW_URL, "steps": []}

    try:
        # 팝업 닫기
        page.wait_for_timeout(3000)
        close_popups(page)

        # ──────────────────────────────────────────────
        # Step 1: 메인 페이지 → HP 모듈 찾기
        # ──────────────────────────────────────────────
        print("\n[2/7] 메인 페이지에서 HP(임직원업무관리) 모듈 찾기...")
        page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        close_popups(page)

        save_screenshot(page, "hp_expense_00_main")

        # 모듈 목록 추출
        modules = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('span[class*="module-link"], [class*="module"], [class*="shortcut"]').forEach(el => {
                if (el.offsetParent !== null) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0) {
                        result.push({
                            text: el.textContent.trim().substring(0, 50),
                            className: el.className.substring ? el.className.substring(0, 120) : '',
                            tagName: el.tagName,
                        });
                    }
                }
            });
            return result;
        }""")
        dump_json(modules, "hp_expense_00_modules")
        print(f"  모듈 목록:")
        for m in modules[:20]:
            print(f"    - {m['text'][:40]}  class={m['className'][:60]}")

        # ──────────────────────────────────────────────
        # Step 2: HP 모듈 클릭
        # ──────────────────────────────────────────────
        print("\n[3/7] HP(임직원업무관리) 모듈로 이동...")
        navigated = False

        # 방법1: CSS 셀렉터로 HP 모듈 클릭
        for selector in ["span.module-link.HP", "span[class*='module-link'][class*='HP']"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=3000):
                    el.click(force=True)
                    navigated = True
                    print(f"  CSS '{selector}' 클릭 성공")
                    break
            except Exception:
                continue

        # 방법2: 텍스트로 시도
        if not navigated:
            for keyword in ["임직원업무관리", "임직원 업무관리", "임직원업무", "HP"]:
                try:
                    loc = page.locator(f"text={keyword}").first
                    if loc.is_visible(timeout=3000):
                        loc.click(force=True)
                        navigated = True
                        print(f"  텍스트 '{keyword}' 클릭 성공")
                        break
                except Exception:
                    continue

        # 방법3: 전체 모듈 중 HP 포함 요소
        if not navigated:
            try:
                navigated = page.evaluate("""() => {
                    const els = document.querySelectorAll('span[class*="module-link"]');
                    for (const el of els) {
                        const cls = el.className || '';
                        const text = el.textContent || '';
                        if (cls.includes('HP') || text.includes('임직원') || text.includes('업무관리')) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                if navigated:
                    print("  JS evaluate로 HP 모듈 클릭 성공")
            except Exception:
                pass

        if not navigated:
            print("  [경고] HP 모듈 직접 접근 실패, URL로 직접 이동 시도...")
            # 더존 URL 패턴: /#/app/HP
            for url_path in ["/#/app/HP", "/#/HP", "/#/app/hp"]:
                try:
                    page.goto(f"{GW_URL}{url_path}", wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(5000)
                    if "/login" not in page.url.lower():
                        navigated = True
                        print(f"  URL '{url_path}' 직접 이동 성공")
                        break
                except Exception:
                    continue

        page.wait_for_timeout(5000)
        close_popups(page)

        current_url = page.url
        print(f"  현재 URL: {current_url}")
        results["steps"].append({"step": "hp_module", "url": current_url, "navigated": navigated})

        save_screenshot(page, "hp_expense_01_hp_home")
        dump_page_text(page, "hp_expense_01_hp_home")

        # ──────────────────────────────────────────────
        # Step 3: 좌측 메뉴 구조 파악
        # ──────────────────────────────────────────────
        print("\n[4/7] 좌측 메뉴 구조 파악...")
        menu_items = dump_left_menu(page, "hp_expense_01_hp_home")
        dump_buttons(page, "hp_expense_01_hp_home")
        dump_inputs(page, "hp_expense_01_hp_home")
        dump_tabs(page, "hp_expense_01_hp_home")

        # ──────────────────────────────────────────────
        # Step 4: 지출결의서 메뉴 찾기 및 클릭
        # ──────────────────────────────────────────────
        print("\n[5/7] 지출결의서 메뉴 찾기...")
        expense_found = False

        # 메뉴에서 "지출결의서", "결의서", "지출" 키워드 클릭
        for keyword in ["지출결의서", "결의서", "지출결의", "지출", "이체", "전표"]:
            try:
                # 텍스트가 정확히 매칭되는 요소 찾기
                loc = page.locator(f"text='{keyword}'").first
                if loc.is_visible(timeout=2000):
                    loc.click(force=True)
                    expense_found = True
                    print(f"  '{keyword}' 클릭 성공")
                    break
            except Exception:
                pass
            # 부분 매칭도 시도
            try:
                loc = page.locator(f"text={keyword}").first
                if loc.is_visible(timeout=2000):
                    loc.click(force=True)
                    expense_found = True
                    print(f"  텍스트 '{keyword}' (부분매칭) 클릭 성공")
                    break
            except Exception:
                continue

        # JS 방식으로 메뉴 클릭 시도
        if not expense_found:
            try:
                expense_found = page.evaluate("""() => {
                    const keywords = ['지출결의서', '결의서', '지출결의', '지출', '이체현황', '전표'];
                    const allEls = document.querySelectorAll('li, a, span, div, button');
                    for (const kw of keywords) {
                        for (const el of allEls) {
                            const text = el.textContent.trim();
                            if (text === kw || (text.includes(kw) && text.length < kw.length + 10)) {
                                if (el.offsetParent !== null) {
                                    el.click();
                                    return true;
                                }
                            }
                        }
                    }
                    return false;
                }""")
                if expense_found:
                    print("  JS 메뉴 클릭 성공")
            except Exception:
                pass

        page.wait_for_timeout(5000)
        close_popups(page)
        current_url = page.url
        print(f"  현재 URL: {current_url}")
        results["steps"].append({"step": "expense_menu", "url": current_url, "found": expense_found})

        save_screenshot(page, "hp_expense_02_expense_list")
        dump_page_text(page, "hp_expense_02_expense_list")
        dump_buttons(page, "hp_expense_02_expense_list")
        dump_inputs(page, "hp_expense_02_expense_list")
        dump_tabs(page, "hp_expense_02_expense_list")
        dump_tables(page, "hp_expense_02_expense_list")
        dump_left_menu(page, "hp_expense_02_expense_list")

        # ──────────────────────────────────────────────
        # Step 5: 이체완료 탭/필터 찾기
        # ──────────────────────────────────────────────
        print("\n[6/7] 이체완료 탭/필터 찾기...")
        transfer_found = False

        for keyword in ["이체완료", "이체", "완료", "지급완료", "지급"]:
            try:
                loc = page.locator(f"text='{keyword}'").first
                if loc.is_visible(timeout=2000):
                    loc.click(force=True)
                    transfer_found = True
                    print(f"  '{keyword}' 클릭 성공")
                    break
            except Exception:
                pass
            try:
                loc = page.locator(f"text={keyword}").first
                if loc.is_visible(timeout=2000):
                    loc.click(force=True)
                    transfer_found = True
                    print(f"  '{keyword}' (부분매칭) 클릭 성공")
                    break
            except Exception:
                continue

        # JS 방식 시도
        if not transfer_found:
            try:
                transfer_found = page.evaluate("""() => {
                    const keywords = ['이체완료', '이체', '지급완료', '완료'];
                    // 탭 요소 먼저 탐색
                    const tabEls = document.querySelectorAll('[role="tab"], [class*="tab"], [class*="Tab"], li, span, a, button');
                    for (const kw of keywords) {
                        for (const el of tabEls) {
                            const text = el.textContent.trim();
                            if (text === kw || (text.includes(kw) && text.length < kw.length + 5)) {
                                if (el.offsetParent !== null) {
                                    el.click();
                                    return true;
                                }
                            }
                        }
                    }
                    return false;
                }""")
                if transfer_found:
                    print("  JS 탭 클릭 성공")
            except Exception:
                pass

        page.wait_for_timeout(5000)
        close_popups(page)
        current_url = page.url
        print(f"  현재 URL: {current_url}")
        results["steps"].append({"step": "transfer_tab", "url": current_url, "found": transfer_found})

        save_screenshot(page, "hp_expense_03_transfer")
        dump_page_text(page, "hp_expense_03_transfer")
        dump_buttons(page, "hp_expense_03_transfer")
        dump_inputs(page, "hp_expense_03_transfer")
        dump_tabs(page, "hp_expense_03_transfer")
        dump_tables(page, "hp_expense_03_transfer")

        # ──────────────────────────────────────────────
        # Step 6: 조회 기간 설정 시도 (2025-01-01 ~ 2026-12-31)
        # ──────────────────────────────────────────────
        print("\n[7/7] 조회 기간 설정 시도...")

        # 날짜 입력 필드 찾기
        date_inputs = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('input').forEach(el => {
                const val = el.value || '';
                const ph = el.placeholder || '';
                const cls = el.className || '';
                const id = el.id || '';
                // 날짜 관련 입력 필드 (value에 날짜 형식, 또는 date 타입, 또는 관련 클래스)
                if (el.type === 'date' || val.match(/\\d{4}[-./]\\d{2}/) ||
                    ph.includes('날짜') || ph.includes('일자') || ph.includes('기간') ||
                    cls.includes('date') || cls.includes('Date') ||
                    id.includes('date') || id.includes('Date') ||
                    cls.includes('calendar') || cls.includes('Calendar') ||
                    cls.includes('OBTDatePicker') || cls.includes('DatePicker')) {
                    const rect = el.getBoundingClientRect();
                    result.push({
                        id: el.id,
                        name: el.name,
                        type: el.type,
                        value: val.substring(0, 30),
                        placeholder: ph,
                        className: cls.substring(0, 120),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                               w: Math.round(rect.width), h: Math.round(rect.height)},
                        visible: el.offsetParent !== null && rect.width > 0,
                    });
                }
            });
            return result;
        }""")
        dump_json(date_inputs, "hp_expense_03_date_inputs")
        print(f"  날짜 입력 필드: {len(date_inputs)}개")
        for d in date_inputs:
            print(f"    - id={d['id']} val={d['value']} type={d['type']} visible={d['visible']}")

        # 셀렉트 박스 (드롭다운) - 기간 선택용
        selects = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('select, [class*="combo"], [class*="Combo"], [class*="dropdown"], [class*="DropDown"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0) {
                    const options = [];
                    if (el.tagName === 'SELECT') {
                        el.querySelectorAll('option').forEach(opt => {
                            options.push({value: opt.value, text: opt.textContent.trim()});
                        });
                    }
                    result.push({
                        tag: el.tagName,
                        id: el.id,
                        className: el.className.substring ? el.className.substring(0, 120) : '',
                        text: el.textContent.trim().substring(0, 60),
                        options: options.slice(0, 20),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                               w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
            });
            return result;
        }""")
        dump_json(selects, "hp_expense_03_selects")
        print(f"  셀렉트/드롭다운: {len(selects)}개")
        for s in selects[:10]:
            print(f"    - {s['tag']} id={s['id']} text={s['text'][:30]}")

        # 기간 설정 시도: visible 날짜 입력 필드에 값 설정
        for d in date_inputs:
            if d['visible'] and d['value']:
                try:
                    # 시작일 설정 시도
                    if 'from' in d['id'].lower() or 'start' in d['id'].lower() or 'begin' in d['id'].lower():
                        page.evaluate(f"""() => {{
                            const el = document.getElementById('{d['id']}');
                            if (el) {{
                                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                    window.HTMLInputElement.prototype, 'value').set;
                                nativeInputValueSetter.call(el, '2025-01-01');
                                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            }}
                        }}""")
                        print(f"    시작일 설정 시도: {d['id']}")
                except Exception as e:
                    print(f"    날짜 설정 실패: {e}")

        # 조회 버튼 찾기 및 클릭
        search_clicked = False
        for keyword in ["조회", "검색", "Search", "찾기"]:
            try:
                loc = page.locator(f"text='{keyword}'").first
                if loc.is_visible(timeout=2000):
                    loc.click(force=True)
                    search_clicked = True
                    print(f"  '{keyword}' 버튼 클릭")
                    break
            except Exception:
                continue

        if search_clicked:
            page.wait_for_timeout(5000)
            save_screenshot(page, "hp_expense_04_after_search")
            dump_tables(page, "hp_expense_04_after_search")
            dump_page_text(page, "hp_expense_04_after_search")

        # ──────────────────────────────────────────────
        # 추가 탐색: OBTDataGrid 확인
        # ──────────────────────────────────────────────
        print("\n[추가] OBTDataGrid 존재 여부 확인...")
        grid_info = page.evaluate("""() => {
            const grids = document.querySelectorAll('[class*="OBTDataGrid"], [class*="grid"], [class*="Grid"]');
            const result = [];
            grids.forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 50 && rect.height > 50) {
                    result.push({
                        className: el.className.substring ? el.className.substring(0, 150) : '',
                        tagName: el.tagName,
                        childCount: el.children.length,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                               w: Math.round(rect.width), h: Math.round(rect.height)},
                        hasCanvas: el.querySelector('canvas') !== null,
                        hasReactFiber: Object.keys(el).some(k => k.startsWith('__reactFiber')),
                    });
                }
            });
            return result;
        }""")
        dump_json(grid_info, "hp_expense_04_grid_info")
        print(f"  그리드 요소: {len(grid_info)}개")
        for g in grid_info:
            print(f"    class={g['className'][:60]} canvas={g['hasCanvas']} react={g['hasReactFiber']}")

        # OBTDataGrid React Fiber 접근 시도 (데이터 구조 파악)
        if grid_info:
            print("\n[추가] OBTDataGrid React Fiber 접근 시도...")
            grid_data = page.evaluate("""() => {
                try {
                    const gridEl = document.querySelector('[class*="OBTDataGrid_grid"]');
                    if (!gridEl) return {error: 'OBTDataGrid not found'};

                    // React Fiber 키 찾기
                    const fiberKey = Object.keys(gridEl).find(k => k.startsWith('__reactFiber'));
                    if (!fiberKey) return {error: 'No __reactFiber key'};

                    let fiber = gridEl[fiberKey];
                    // depth 3까지 탐색하여 interface 찾기
                    for (let i = 0; i < 5; i++) {
                        if (fiber && fiber.stateNode && fiber.stateNode.state && fiber.stateNode.state.interface) {
                            const iface = fiber.stateNode.state.interface;
                            const methods = Object.keys(iface).filter(k => typeof iface[k] === 'function').slice(0, 30);
                            let rowCount = 0;
                            let columns = [];
                            try { rowCount = iface.getRowCount(); } catch(e) {}
                            try {
                                const cols = iface.getColumns();
                                columns = cols.map(c => ({name: c.name, header: c.header || c.fieldName})).slice(0, 30);
                            } catch(e) {}

                            // 샘플 데이터 (첫 3행)
                            let sampleData = [];
                            try {
                                for (let r = 0; r < Math.min(3, rowCount); r++) {
                                    const row = {};
                                    columns.forEach(col => {
                                        try {
                                            row[col.name] = String(iface.getValue(r, col.name)).substring(0, 50);
                                        } catch(e) {}
                                    });
                                    sampleData.push(row);
                                }
                            } catch(e) {}

                            return {
                                depth: i,
                                methods: methods,
                                rowCount: rowCount,
                                columns: columns,
                                sampleData: sampleData,
                            };
                        }
                        if (fiber) fiber = fiber.return;
                    }
                    return {error: 'interface not found within 5 depths'};
                } catch(e) {
                    return {error: e.message};
                }
            }""")
            dump_json(grid_data, "hp_expense_04_grid_data")
            print(f"  그리드 데이터: {json.dumps(grid_data, ensure_ascii=False)[:500]}")

        # ──────────────────────────────────────────────
        # 전체 페이지 HTML 구조 (간략)
        # ──────────────────────────────────────────────
        print("\n[추가] 전체 HTML 구조 저장...")
        html_structure = page.evaluate("""() => {
            function getStructure(el, depth) {
                if (depth > 4 || !el || !el.children) return null;
                const children = [];
                for (const child of el.children) {
                    if (child.offsetParent !== null || child.tagName === 'IFRAME') {
                        const rect = child.getBoundingClientRect();
                        if (rect.width > 0 || child.tagName === 'IFRAME') {
                            const childInfo = {
                                tag: child.tagName.toLowerCase(),
                                id: child.id || undefined,
                                class: child.className ? (child.className.substring ? child.className.substring(0, 80) : '') : '',
                                text: child.children.length === 0 ? child.textContent.trim().substring(0, 50) : undefined,
                            };
                            if (child.tagName === 'IFRAME') {
                                childInfo.src = child.src ? child.src.substring(0, 200) : '';
                            }
                            const sub = getStructure(child, depth + 1);
                            if (sub && sub.length > 0) childInfo.children = sub;
                            children.push(childInfo);
                        }
                    }
                }
                return children.length > 0 ? children : null;
            }
            return getStructure(document.body, 0);
        }""")
        dump_json(html_structure or [], "hp_expense_04_html_structure")

        # ──────────────────────────────────────────────
        # iframe 탐색 (더존은 iframe 많이 사용)
        # ──────────────────────────────────────────────
        print("\n[추가] iframe 탐색...")
        frames = page.frames
        print(f"  프레임 수: {len(frames)}")
        frame_info = []
        for i, frame in enumerate(frames):
            try:
                info = {
                    "index": i,
                    "name": frame.name,
                    "url": frame.url[:200] if frame.url else "",
                }
                frame_info.append(info)
                print(f"    [{i}] name={frame.name} url={frame.url[:100]}")

                # 주요 프레임 내부 탐색
                if frame.url and frame.url != "about:blank" and i > 0:
                    try:
                        frame_text = frame.evaluate("() => document.body ? document.body.innerText.substring(0, 2000) : ''")
                        info["text_preview"] = frame_text[:500]
                        if frame_text.strip():
                            print(f"      텍스트: {frame_text[:100]}...")
                    except Exception:
                        pass

                    # 프레임 내 테이블
                    try:
                        frame_tables = frame.evaluate("""() => {
                            const result = [];
                            document.querySelectorAll('table').forEach((table, idx) => {
                                const headers = [];
                                table.querySelectorAll('thead th, tr:first-child th').forEach(th => {
                                    headers.push(th.textContent.trim().substring(0, 50));
                                });
                                const rows = table.querySelectorAll('tbody tr');
                                result.push({index: idx, headers: headers, rowCount: rows.length});
                            });
                            return result;
                        }""")
                        if frame_tables:
                            info["tables"] = frame_tables
                            for t in frame_tables:
                                print(f"      테이블[{t['index']}]: {t['rowCount']}행, 헤더={t['headers'][:8]}")
                    except Exception:
                        pass
            except Exception as e:
                frame_info.append({"index": i, "error": str(e)})

        dump_json(frame_info, "hp_expense_04_frames")

    except Exception as e:
        print(f"\n[오류] {e}")
        traceback.print_exc()
        save_screenshot(page, "hp_expense_error")
        results["error"] = str(e)

    finally:
        # API 캡처 결과 저장
        dump_json(api_calls, "hp_expense_api_calls")
        dump_json(api_responses, "hp_expense_api_responses")
        print(f"\n  API 요청 캡처: {len(api_calls)}개")
        print(f"  API 응답 캡처: {len(api_responses)}개")

        # 주요 API 엔드포인트 출력
        unique_urls = {}
        for call in api_calls:
            # URL에서 쿼리 파라미터 제거하고 유니크한 것만
            base_url = call['url'].split('?')[0]
            if base_url not in unique_urls:
                unique_urls[base_url] = call['method']
        print(f"\n  고유 API 엔드포인트 ({len(unique_urls)}개):")
        for url, method in sorted(unique_urls.items()):
            print(f"    [{method}] {url[:120]}")

        # 결과 요약 저장
        results["api_call_count"] = len(api_calls)
        results["api_response_count"] = len(api_responses)
        results["unique_endpoints"] = list(unique_urls.keys())
        dump_json(results, "hp_expense_summary")

        print("\n" + "=" * 60)
        print("탐색 완료!")
        print(f"결과 파일: {OUTPUT_DIR}/hp_expense_*.json|png|txt")

        # 생성 파일 목록
        hp_files = sorted(OUTPUT_DIR.glob("hp_expense_*"))
        print(f"\n생성된 파일 ({len(hp_files)}개):")
        for f in hp_files:
            size = f.stat().st_size
            print(f"  {f.name:60s}  {size:>8,} bytes")
        print("=" * 60)

        # 브라우저 종료
        close_session(browser)


if __name__ == "__main__":
    main()
