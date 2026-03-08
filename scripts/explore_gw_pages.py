"""
더존 Amaranth10 그룹웨어 주요 페이지 탐색 스크립트
- 전자결재 홈, 회의실/자원 예약, 근태, 메일함 탐색
- 각 페이지의 버튼, 입력 필드, 스크린샷 저장
"""

import sys
import json
import time
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.auth.login import login_and_get_context, close_session, GW_URL

OUTPUT_DIR = PROJECT_ROOT / "data" / "dom_explore" / "gw_pages"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─── 공통 유틸 ────────────────────────────────────────────────

def save_screenshot(page, name: str):
    path = OUTPUT_DIR / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        print(f"  [스크린샷] {path.name}")
    except Exception as e:
        print(f"  [스크린샷 실패] {name}: {e}")


def dump_buttons(ctx, name: str) -> list:
    """보이는 버튼 목록 추출"""
    try:
        info = ctx.evaluate("""() => {
            const result = [];
            document.querySelectorAll('button, [role="button"], a[href], .btn').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                    result.push({
                        text: el.textContent.trim().substring(0, 60),
                        tag: el.tagName.toLowerCase(),
                        id: el.id,
                        href: el.href || '',
                        className: el.className.substring(0, 120),
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

    path = OUTPUT_DIR / f"{name}_buttons.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    visible_with_text = [b for b in info if b['text']]
    print(f"  [버튼] {path.name} ({len(info)}개, 텍스트 있음 {len(visible_with_text)}개)")
    for b in visible_with_text[:20]:
        print(f"    - \"{b['text'][:50]}\"  ({b['tag']}) id={b['id']}")
    return info


def dump_inputs(ctx, name: str) -> list:
    """입력 필드 목록 추출"""
    try:
        info = ctx.evaluate("""() => {
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
                    value: el.value.substring(0, 80),
                    className: el.className.substring(0, 100),
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                           w: Math.round(rect.width), h: Math.round(rect.height)},
                });
            });
            return result;
        }""")
    except Exception as e:
        print(f"  [입력 필드 추출 실패] {e}")
        info = []

    path = OUTPUT_DIR / f"{name}_inputs.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    visible = [i for i in info if i.get("visible")]
    print(f"  [입력] {path.name} (총 {len(info)}개, visible {len(visible)}개)")
    for v in visible[:15]:
        print(f"    - {v['tag']}[{v['type']}] id={v['id']} name={v['name']} ph={v['placeholder']}")
    return info


def dump_text_content(page, name: str) -> str:
    """페이지 텍스트 내용 추출 (메뉴 구조 파악용)"""
    try:
        text = page.evaluate("""() => {
            // 내비게이션 메뉴 텍스트
            const nav_texts = [];
            document.querySelectorAll('nav, .lnb, .gnb, .menu, [class*="menu"], [class*="nav"], [class*="side"]').forEach(el => {
                if (el.offsetParent !== null) {
                    nav_texts.push({
                        className: el.className.substring(0, 80),
                        text: el.textContent.trim().substring(0, 500)
                    });
                }
            });
            return nav_texts;
        }""")
    except Exception as e:
        print(f"  [텍스트 추출 실패] {e}")
        text = []

    path = OUTPUT_DIR / f"{name}_nav.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(text, f, ensure_ascii=False, indent=2)
    print(f"  [내비게이션] {path.name} ({len(text)}개 영역)")
    return text


def capture_api_calls(page, duration_sec: int = 5) -> list:
    """API 호출 URL 캡처"""
    calls = []

    def on_request(req):
        url = req.url
        if any(x in url for x in ['/api/', '/rs', '/gw/', 'ajax', '.json', 'Rest', 'Svc']):
            calls.append({
                "method": req.method,
                "url": url[:200],
                "resource_type": req.resource_type,
            })

    page.on("request", on_request)
    time.sleep(duration_sec)
    return calls


def get_page_url(page):
    return page.url


def navigate_to_module(page, module_keywords: list, wait_sec: int = 5) -> bool:
    """모듈 아이콘 또는 텍스트 링크로 페이지 이동"""
    for keyword in module_keywords:
        try:
            loc = page.locator(f"text={keyword}").first
            if loc.is_visible(timeout=3000):
                loc.click(force=True)
                print(f"  '{keyword}' 클릭 성공")
                time.sleep(wait_sec)
                return True
        except Exception:
            continue

    # CSS 클래스 기반 시도
    for kw in module_keywords:
        try:
            loc = page.locator(f"[title='{kw}'], [aria-label='{kw}']").first
            if loc.is_visible(timeout=2000):
                loc.click(force=True)
                time.sleep(wait_sec)
                return True
        except Exception:
            continue

    return False


# ─── 탐색 함수들 ──────────────────────────────────────────────

def explore_approval_home(page, context) -> dict:
    """전자결재 홈 탐색 - 결재대기함, 임시보관, 결재현황"""
    print("\n" + "=" * 50)
    print("[전자결재 홈] 탐색 시작")
    print("=" * 50)

    result = {"section": "approval_home", "status": "ok", "pages": []}
    api_calls = []

    def on_req(req):
        url = req.url
        if any(x in url for x in ['/rs', '/api/', 'eap', 'EA', 'approval', 'APB']):
            api_calls.append({"method": req.method, "url": url[:200]})

    page.on("request", on_req)

    try:
        # 전자결재 모듈로 이동
        navigated = False
        for selector in ["span.module-link.EA", "span[class*='EA']"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=3000):
                    el.click(force=True)
                    navigated = True
                    print(f"  CSS '{selector}' 클릭")
                    break
            except Exception:
                continue

        if not navigated:
            navigated = navigate_to_module(page, ["전자결재", "결재"], wait_sec=6)

        if not navigated:
            print("  [실패] 전자결재 모듈 접근 불가")
            result["status"] = "failed"
            return result

        time.sleep(5)
        save_screenshot(page, "01_approval_home")

        # 결재 HOME 확인
        current_url = page.url
        print(f"  현재 URL: {current_url}")
        result["url"] = current_url

        # 메인 페이지 분석
        page_info = {
            "name": "결재_홈",
            "url": current_url,
        }

        buttons = dump_buttons(page, "01_approval_home")
        inputs = dump_inputs(page, "01_approval_home")
        dump_text_content(page, "01_approval_home")

        page_info["button_count"] = len(buttons)
        page_info["input_count"] = len(inputs)
        result["pages"].append(page_info)

        # 결재대기함 탐색
        print("\n  -- 결재대기함 탐색 --")
        try:
            wait_btn = None
            for keyword in ["결재대기", "대기함", "결재 대기"]:
                try:
                    loc = page.locator(f"text={keyword}").first
                    if loc.is_visible(timeout=2000):
                        wait_btn = loc
                        break
                except Exception:
                    continue

            if wait_btn:
                wait_btn.click(force=True)
                time.sleep(4)
                save_screenshot(page, "01b_approval_waiting")
                dump_buttons(page, "01b_approval_waiting")
                print(f"  결재대기함 URL: {page.url}")
                result["pages"].append({"name": "결재대기함", "url": page.url})
        except Exception as e:
            print(f"  결재대기함 탐색 실패: {e}")

        # 임시보관 탐색
        print("\n  -- 임시보관 탐색 --")
        try:
            for keyword in ["임시보관", "임시저장", "보관함"]:
                try:
                    loc = page.locator(f"text={keyword}").first
                    if loc.is_visible(timeout=2000):
                        loc.click(force=True)
                        time.sleep(4)
                        save_screenshot(page, "01c_approval_draft")
                        dump_buttons(page, "01c_approval_draft")
                        print(f"  임시보관 URL: {page.url}")
                        result["pages"].append({"name": "임시보관", "url": page.url})
                        break
                except Exception:
                    continue
        except Exception as e:
            print(f"  임시보관 탐색 실패: {e}")

    except Exception as e:
        print(f"  [오류] 전자결재 탐색 실패: {e}")
        result["status"] = "error"
        result["error"] = str(e)
        save_screenshot(page, "01_approval_error")
    finally:
        page.remove_listener("request", on_req)

    result["api_calls"] = api_calls[:30]
    print(f"  API 호출 감지: {len(api_calls)}개")
    return result


def explore_meeting_room(page, context) -> dict:
    """회의실 예약 페이지 탐색"""
    print("\n" + "=" * 50)
    print("[회의실 예약] 탐색 시작")
    print("=" * 50)

    result = {"section": "meeting_room", "status": "ok", "pages": []}
    api_calls = []

    def on_req(req):
        url = req.url
        if any(x in url for x in ['/rs', '/api/', 'RS', 'schres', 'reserve', 'meeting', 'room']):
            api_calls.append({"method": req.method, "url": url[:200]})

    page.on("request", on_req)

    try:
        # 그룹웨어 메인으로 돌아가기
        page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # 회의실 예약 모듈 접근 시도
        navigated = False

        # CSS 클래스로 시도 (RS = 자원/시설)
        for selector in ["span.module-link.RS", "span[class*='RS']", "span.module-link.SR"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=3000):
                    el.click(force=True)
                    navigated = True
                    print(f"  CSS '{selector}' 클릭")
                    time.sleep(5)
                    break
            except Exception:
                continue

        if not navigated:
            navigated = navigate_to_module(
                page, ["회의실예약", "회의실 예약", "시설예약", "시설 예약", "회의실", "예약"], wait_sec=5
            )

        if not navigated:
            # 메뉴에서 탐색
            print("  메뉴 탐색으로 회의실 접근 시도...")
            try:
                # LNB 메뉴 목록 확인
                menu_items = page.evaluate("""() => {
                    const items = [];
                    document.querySelectorAll('[class*="menu-item"], [class*="lnb"] li, [class*="nav"] li').forEach(el => {
                        if (el.offsetParent !== null) {
                            items.push({text: el.textContent.trim().substring(0, 50), className: el.className.substring(0, 80)});
                        }
                    });
                    return items;
                }""")
                print(f"  메뉴 항목: {len(menu_items)}개")
                for m in menu_items[:20]:
                    print(f"    - {m['text']}")
            except Exception:
                pass

        save_screenshot(page, "02_meeting_attempt")
        current_url = page.url
        print(f"  현재 URL: {current_url}")

        if navigated:
            result["url"] = current_url

            # 회의실 목록 탐색
            buttons = dump_buttons(page, "02_meeting_home")
            inputs = dump_inputs(page, "02_meeting_home")
            dump_text_content(page, "02_meeting_home")

            result["pages"].append({
                "name": "회의실예약_홈",
                "url": current_url,
                "button_count": len(buttons),
                "input_count": len(inputs),
            })

            # 예약 버튼 클릭 시도
            print("\n  -- 예약 폼 탐색 --")
            for keyword in ["예약하기", "새 예약", "예약 등록", "예약등록", "신규예약", "+예약"]:
                try:
                    loc = page.locator(f"text={keyword}").first
                    if loc.is_visible(timeout=2000):
                        loc.click(force=True)
                        time.sleep(4)
                        save_screenshot(page, "02b_meeting_form")
                        dump_buttons(page, "02b_meeting_form")
                        dump_inputs(page, "02b_meeting_form")
                        print(f"  예약 폼 URL: {page.url}")
                        result["pages"].append({"name": "회의실예약_폼", "url": page.url})
                        break
                except Exception:
                    continue
        else:
            result["status"] = "failed"
            print("  [실패] 회의실 예약 모듈 접근 불가")

    except Exception as e:
        print(f"  [오류] 회의실 탐색 실패: {e}")
        result["status"] = "error"
        result["error"] = str(e)
        save_screenshot(page, "02_meeting_error")
    finally:
        page.remove_listener("request", on_req)

    result["api_calls"] = api_calls[:30]
    print(f"  API 호출 감지: {len(api_calls)}개")
    return result


def explore_resource_reservation(page, context) -> dict:
    """자원 예약 페이지 탐색 (기자재, 차량 등)"""
    print("\n" + "=" * 50)
    print("[자원 예약] 탐색 시작")
    print("=" * 50)

    result = {"section": "resource_reservation", "status": "ok", "pages": []}
    api_calls = []

    def on_req(req):
        url = req.url
        if any(x in url for x in ['/rs', '/api/', 'resource', 'equip', 'car', 'vehicle']):
            api_calls.append({"method": req.method, "url": url[:200]})

    page.on("request", on_req)

    try:
        page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # 자원/기자재 모듈 접근 시도
        navigated = False
        for selector in ["span.module-link.RE", "span.module-link.EQ", "span[class*='RE']"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=3000):
                    el.click(force=True)
                    navigated = True
                    print(f"  CSS '{selector}' 클릭")
                    time.sleep(5)
                    break
            except Exception:
                continue

        if not navigated:
            navigated = navigate_to_module(
                page, ["자원예약", "기자재", "차량예약", "비품", "물품", "자원"], wait_sec=5
            )

        save_screenshot(page, "03_resource_attempt")
        current_url = page.url
        print(f"  현재 URL: {current_url}")

        if navigated:
            result["url"] = current_url
            buttons = dump_buttons(page, "03_resource_home")
            inputs = dump_inputs(page, "03_resource_home")
            dump_text_content(page, "03_resource_home")

            result["pages"].append({
                "name": "자원예약_홈",
                "url": current_url,
                "button_count": len(buttons),
                "input_count": len(inputs),
            })
        else:
            result["status"] = "failed"
            print("  [실패] 자원 예약 모듈 접근 불가")

    except Exception as e:
        print(f"  [오류] 자원 예약 탐색 실패: {e}")
        result["status"] = "error"
        result["error"] = str(e)
    finally:
        page.remove_listener("request", on_req)

    result["api_calls"] = api_calls[:20]
    return result


def explore_attendance(page, context) -> dict:
    """근태 관련 페이지 탐색 - 연장근무, 외근 신청"""
    print("\n" + "=" * 50)
    print("[근태] 탐색 시작")
    print("=" * 50)

    result = {"section": "attendance", "status": "ok", "pages": []}
    api_calls = []

    def on_req(req):
        url = req.url
        if any(x in url for x in ['/rs', '/api/', 'AT', 'attend', 'work', 'overtime']):
            api_calls.append({"method": req.method, "url": url[:200]})

    page.on("request", on_req)

    try:
        page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # 근태 모듈 접근 시도
        navigated = False
        for selector in ["span.module-link.AT", "span.module-link.HR", "span[class*='AT']"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=3000):
                    el.click(force=True)
                    navigated = True
                    print(f"  CSS '{selector}' 클릭")
                    time.sleep(5)
                    break
            except Exception:
                continue

        if not navigated:
            navigated = navigate_to_module(
                page, ["근태", "근무", "연장근무", "외근", "HR", "인사"], wait_sec=5
            )

        save_screenshot(page, "04_attendance_attempt")
        current_url = page.url
        print(f"  현재 URL: {current_url}")

        if navigated:
            result["url"] = current_url
            buttons = dump_buttons(page, "04_attendance_home")
            inputs = dump_inputs(page, "04_attendance_home")
            dump_text_content(page, "04_attendance_home")

            result["pages"].append({
                "name": "근태_홈",
                "url": current_url,
                "button_count": len(buttons),
                "input_count": len(inputs),
            })

            # 연장근무 신청 탐색
            print("\n  -- 연장근무 신청 탐색 --")
            for keyword in ["연장근무", "초과근무", "야근", "연장근무신청"]:
                try:
                    loc = page.locator(f"text={keyword}").first
                    if loc.is_visible(timeout=2000):
                        loc.click(force=True)
                        time.sleep(4)
                        save_screenshot(page, "04b_overtime")
                        dump_buttons(page, "04b_overtime")
                        dump_inputs(page, "04b_overtime")
                        print(f"  연장근무 URL: {page.url}")
                        result["pages"].append({"name": "연장근무신청", "url": page.url})
                        break
                except Exception:
                    continue

            # 외근 신청 탐색
            print("\n  -- 외근 신청 탐색 --")
            for keyword in ["외근", "출장", "외근신청", "출장신청"]:
                try:
                    loc = page.locator(f"text={keyword}").first
                    if loc.is_visible(timeout=2000):
                        loc.click(force=True)
                        time.sleep(4)
                        save_screenshot(page, "04c_business_trip")
                        dump_buttons(page, "04c_business_trip")
                        dump_inputs(page, "04c_business_trip")
                        print(f"  외근신청 URL: {page.url}")
                        result["pages"].append({"name": "외근신청", "url": page.url})
                        break
                except Exception:
                    continue
        else:
            result["status"] = "failed"
            print("  [실패] 근태 모듈 접근 불가")

    except Exception as e:
        print(f"  [오류] 근태 탐색 실패: {e}")
        result["status"] = "error"
        result["error"] = str(e)
        save_screenshot(page, "04_attendance_error")
    finally:
        page.remove_listener("request", on_req)

    result["api_calls"] = api_calls[:20]
    return result


def explore_mail(page, context) -> dict:
    """메일함 홈 탐색"""
    print("\n" + "=" * 50)
    print("[메일함] 탐색 시작")
    print("=" * 50)

    result = {"section": "mail", "status": "ok", "pages": []}
    api_calls = []

    def on_req(req):
        url = req.url
        if any(x in url for x in ['/rs', '/api/', 'mail', 'NW', 'MW', 'inbox']):
            api_calls.append({"method": req.method, "url": url[:200]})

    page.on("request", on_req)

    try:
        page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # 메일 모듈 접근 시도
        navigated = False
        for selector in ["span.module-link.NW", "span.module-link.MW", "span.module-link.MAIL", "span[class*='NW']"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=3000):
                    el.click(force=True)
                    navigated = True
                    print(f"  CSS '{selector}' 클릭")
                    time.sleep(5)
                    break
            except Exception:
                continue

        if not navigated:
            navigated = navigate_to_module(
                page, ["메일", "메일함", "받은메일", "받은 메일함"], wait_sec=5
            )

        save_screenshot(page, "05_mail_attempt")
        current_url = page.url
        print(f"  현재 URL: {current_url}")

        if navigated:
            result["url"] = current_url
            buttons = dump_buttons(page, "05_mail_home")
            inputs = dump_inputs(page, "05_mail_home")
            dump_text_content(page, "05_mail_home")

            result["pages"].append({
                "name": "메일함_홈",
                "url": current_url,
                "button_count": len(buttons),
                "input_count": len(inputs),
            })

            # 메일 작성 탐색
            print("\n  -- 메일 작성 폼 탐색 --")
            for keyword in ["메일쓰기", "메일 쓰기", "새 메일", "편지쓰기", "쓰기"]:
                try:
                    loc = page.locator(f"text={keyword}").first
                    if loc.is_visible(timeout=2000):
                        loc.click(force=True)
                        time.sleep(4)
                        save_screenshot(page, "05b_mail_compose")
                        dump_buttons(page, "05b_mail_compose")
                        dump_inputs(page, "05b_mail_compose")
                        print(f"  메일 작성 URL: {page.url}")
                        result["pages"].append({"name": "메일작성", "url": page.url})
                        break
                except Exception:
                    continue
        else:
            result["status"] = "failed"
            print("  [실패] 메일 모듈 접근 불가")

    except Exception as e:
        print(f"  [오류] 메일 탐색 실패: {e}")
        result["status"] = "error"
        result["error"] = str(e)
        save_screenshot(page, "05_mail_error")
    finally:
        page.remove_listener("request", on_req)

    result["api_calls"] = api_calls[:20]
    return result


def explore_main_modules(page, context) -> dict:
    """메인 페이지 모듈 목록 캡처"""
    print("\n" + "=" * 50)
    print("[메인 페이지] 모듈 목록 캡처")
    print("=" * 50)

    result = {"section": "main_page", "status": "ok"}

    try:
        page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)

        save_screenshot(page, "00_main_page")

        # 모든 module-link 요소 추출
        modules = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('[class*="module"], [class*="app-icon"], [class*="shortcut"]').forEach(el => {
                if (el.offsetParent !== null) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        result.push({
                            text: el.textContent.trim().substring(0, 50),
                            className: el.className.substring(0, 120),
                            id: el.id,
                            href: el.getAttribute('href') || '',
                            title: el.getAttribute('title') || '',
                            rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                                   w: Math.round(rect.width), h: Math.round(rect.height)},
                        });
                    }
                }
            });
            return result;
        }""")

        path = OUTPUT_DIR / "00_modules.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(modules, f, ensure_ascii=False, indent=2)

        print(f"  [모듈] {len(modules)}개 발견")
        for m in modules[:30]:
            if m['text'] or m['className']:
                print(f"    - text='{m['text'][:30]}' class={m['className'][:60]}")

        result["modules"] = modules
        result["url"] = page.url

        # 전체 페이지 버튼/링크 목록
        dump_buttons(page, "00_main_page")

    except Exception as e:
        print(f"  [오류] 메인 페이지 탐색 실패: {e}")
        result["status"] = "error"
        result["error"] = str(e)

    return result


# ─── 메인 ─────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("더존 Amaranth10 그룹웨어 주요 페이지 탐색")
    print(f"결과 저장: {OUTPUT_DIR}")
    print("=" * 60)

    print("\n[로그인 중...]")
    browser, context, page = login_and_get_context(headless=True)
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.on("dialog", lambda d: d.accept())

    summary = {
        "gw_url": GW_URL,
        "output_dir": str(OUTPUT_DIR),
        "sections": [],
    }

    sections = [
        ("메인 모듈 목록", explore_main_modules),
        ("전자결재 홈", explore_approval_home),
        ("회의실 예약", explore_meeting_room),
        ("자원 예약", explore_resource_reservation),
        ("근태", explore_attendance),
        ("메일함", explore_mail),
    ]

    try:
        for section_name, func in sections:
            print(f"\n{'=' * 60}")
            print(f">>> {section_name} 탐색 시작")
            print(f"{'=' * 60}")
            try:
                result = func(page, context)
                summary["sections"].append(result)
                print(f"  [완료] {section_name}: {result.get('status', 'ok')}")
            except Exception as e:
                print(f"  [오류] {section_name} 탐색 중 예외: {e}")
                summary["sections"].append({
                    "section": section_name,
                    "status": "exception",
                    "error": str(e),
                })

    finally:
        close_session(browser)

    # 요약 저장
    summary_path = OUTPUT_DIR / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("탐색 완료!")
    print(f"요약 파일: {summary_path}")

    # 결과 파일 목록
    files = sorted(OUTPUT_DIR.iterdir())
    print(f"\n생성된 파일 ({len(files)}개):")
    for f in files:
        size = f.stat().st_size
        print(f"  {f.name:50s}  {size:>8,} bytes")
    print("=" * 60)


if __name__ == "__main__":
    main()
