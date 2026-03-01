"""
Playwright 네트워크 인터셉트로 rs121A API 인증 헤더 캡처
- /schres/ 경로 요청의 인증 헤더를 실시간으로 캡처
- 자원 예약 페이지에서 브라우저가 자동 호출하는 rs121A API 헤더 분석
- window 객체에서 wehago/schres 관련 전역 변수/함수 탐색
"""

import sys
import os
import json
import datetime

# 한국어 인코딩 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, 'config', '.env'))

from playwright.sync_api import sync_playwright
from src.auth.login import login_and_get_context, close_session
from pathlib import Path

# 결과 저장 경로
DATA_DIR = Path(PROJECT_ROOT) / 'data' / 'gw_analysis'
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 캡처된 헤더 목록
captured_headers = []


def on_request(request):
    """
    네트워크 요청 이벤트 핸들러 - /schres/ 경로 필터링 및 헤더 캡처
    """
    url = request.url
    if '/schres/' not in url:
        return

    try:
        headers = dict(request.headers)
        url_path = url.split('glowseoul.co.kr')[-1]

        # 요청 바디
        req_body = None
        if request.post_data:
            try:
                req_body = json.loads(request.post_data)
            except Exception:
                req_body = request.post_data[:2000]

        entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'url': url,
            'url_path': url_path,
            'method': request.method,
            'headers': headers,
            'body': req_body,
        }
        captured_headers.append(entry)

        # 콘솔 출력 (인증 관련 핵심 헤더 강조)
        print(f"\n[캡처] {request.method} {url_path}")
        for key in ['authorization', 'wehago-sign', 'timestamp', 'transaction-id']:
            val = headers.get(key, headers.get(key.upper(), '(없음)'))
            print(f"  {key}: {val}")

        # 나머지 헤더도 출력
        print("  [전체 헤더]")
        for k, v in headers.items():
            if k not in ['authorization', 'wehago-sign', 'timestamp', 'transaction-id']:
                print(f"    {k}: {v[:120]}")

        if req_body:
            body_str = json.dumps(req_body, ensure_ascii=False)
            print(f"  [요청 바디] {body_str[:300]}")

    except Exception as e:
        print(f"  [헤더 캡처 오류] {e}")


def explore_window_globals(page) -> dict:
    """
    window 객체에서 wehago/schres 관련 전역 변수 및 함수 탐색
    """
    print("\n=== window 전역 변수 탐색 ===")

    result = page.evaluate("""() => {
        const findings = {};

        // 1) wehago/schres/sign 관련 키워드로 window 객체 필터링
        try {
            const allKeys = Object.keys(window);
            const filtered = allKeys.filter(k => {
                const lower = k.toLowerCase();
                return lower.includes('wehago') ||
                       lower.includes('sign') ||
                       lower.includes('schres') ||
                       lower.includes('token') ||
                       lower.includes('auth') ||
                       lower.includes('header') ||
                       lower.includes('crypto');
            });
            findings.keywordMatches = filtered;
        } catch(e) {
            findings.keywordMatchesError = e.toString();
        }

        // 2) window.WEHAGO 또는 유사 네임스페이스 탐색
        try {
            const namespaces = ['WEHAGO', 'wehago', 'WehagoSign', 'wehagoSign', 'GW', 'gw', 'SchRes', 'schRes'];
            findings.namespaceCheck = {};
            for (const ns of namespaces) {
                if (window[ns] !== undefined) {
                    const type = typeof window[ns];
                    let keys = [];
                    if (type === 'object' && window[ns] !== null) {
                        keys = Object.keys(window[ns]).slice(0, 30);
                    }
                    findings.namespaceCheck[ns] = { type, keys };
                }
            }
        } catch(e) {
            findings.namespaceCheckError = e.toString();
        }

        // 3) fetch/XHR 패치 여부 확인 (서명 미들웨어 탐색)
        try {
            findings.fetchType = typeof window.fetch;
            findings.xhrType = typeof window.XMLHttpRequest;
            // fetch가 네이티브인지 오버라이드인지 확인
            findings.fetchIsNative = window.fetch.toString().includes('[native code]');
            findings.xhrIsNative = window.XMLHttpRequest.prototype.open.toString().includes('[native code]');
        } catch(e) {
            findings.fetchCheckError = e.toString();
        }

        // 4) axios/인터셉터 탐색
        try {
            if (window.axios) {
                findings.axiosExists = true;
                findings.axiosInterceptors = {
                    requestCount: window.axios.interceptors?.request?.handlers?.length || 0,
                    responseCount: window.axios.interceptors?.response?.handlers?.length || 0,
                };
            }
        } catch(e) {}

        // 5) localStorage / sessionStorage에서 토큰 탐색
        try {
            const lsKeys = Object.keys(localStorage);
            findings.localStorageKeys = lsKeys;
            findings.localStorageAuthRelated = {};
            for (const k of lsKeys) {
                const lower = k.toLowerCase();
                if (lower.includes('token') || lower.includes('auth') || lower.includes('sign') || lower.includes('wehago')) {
                    findings.localStorageAuthRelated[k] = localStorage.getItem(k)?.substring(0, 200);
                }
            }
        } catch(e) {
            findings.localStorageError = e.toString();
        }

        // 6) 쿠키 확인
        try {
            findings.cookieCount = document.cookie.split(';').length;
            findings.cookies = document.cookie.split(';').map(c => c.trim().split('=')[0]);
        } catch(e) {}

        // 7) script 소스 목록 (schres 관련 JS 청크 찾기)
        try {
            const scripts = Array.from(document.querySelectorAll('script[src]'));
            findings.scriptSrcs = scripts
                .map(s => s.src)
                .filter(s => s.includes('schres') || s.includes('chunk') || s.includes('wehago'))
                .slice(0, 20);
        } catch(e) {}

        return findings;
    }""")

    # 결과 출력
    print(f"  키워드 매칭 키: {result.get('keywordMatches', [])}")
    print(f"  네임스페이스 발견: {list(result.get('namespaceCheck', {}).keys())}")
    print(f"  fetch 네이티브 여부: {result.get('fetchIsNative', '?')}")
    print(f"  XHR 네이티브 여부: {result.get('xhrIsNative', '?')}")
    print(f"  localStorage 관련 키: {list(result.get('localStorageAuthRelated', {}).keys())}")
    print(f"  쿠키 목록: {result.get('cookies', [])}")

    if result.get('namespaceCheck'):
        for ns, info in result['namespaceCheck'].items():
            print(f"  window.{ns}: type={info['type']}, keys={info.get('keys', [])[:10]}")

    return result


def trigger_schres_requests(page):
    """
    자원 예약 페이지를 탐색하며 schres API 요청을 유발
    - 회의실 예약 버튼 클릭 등 사용자 행동 시뮬레이션
    """
    print("\n=== 추가 schres 요청 유발 시도 ===")

    # 1) 회의실 예약 버튼 클릭 (있는 경우)
    try:
        reserve_btn = page.get_by_text('자원 예약').first
        if reserve_btn.is_visible(timeout=3000):
            reserve_btn.click()
            page.wait_for_timeout(3000)
            print("  '자원 예약' 버튼 클릭 완료")
    except Exception as e:
        print(f"  '자원 예약' 버튼 없음: {e}")

    # 2) 페이지 내 예약 관련 버튼 탐색
    try:
        btns = page.evaluate("""() => {
            const allBtns = document.querySelectorAll('button, [role=button], a');
            return Array.from(allBtns)
                .filter(el => el.offsetParent !== null)
                .map(el => ({
                    text: el.textContent.trim().substring(0, 30),
                    cls: (el.className || '').substring(0, 40),
                }))
                .filter(b => b.text.length > 0)
                .slice(0, 30);
        }""")
        print("  페이지 내 버튼 목록:")
        for btn in btns:
            print(f"    [{btn['text']}] cls={btn['cls'][:30]}")
    except Exception as e:
        print(f"  버튼 탐색 실패: {e}")

    # 3) 추가 대기 - 자동 호출 가능성
    page.wait_for_timeout(3000)


def main():
    print("=" * 70)
    print("rs121A API 인증 헤더 캡처 스크립트")
    print(f"실행 시각: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    pw = sync_playwright().start()
    browser = None

    try:
        # Step 1: 로그인
        print("\n[1단계] 그룹웨어 로그인...")
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=False  # 헤더 캡처 디버깅을 위해 브라우저 창 표시
        )
        print("  로그인 성공!")

        # Step 2: 네트워크 요청 인터셉트 등록
        print("\n[2단계] 네트워크 인터셉트 등록...")
        page.on("request", on_request)
        print("  /schres/ 경로 요청 감지 준비 완료")

        # Step 3: 자원 예약 페이지로 이동
        print("\n[3단계] 자원 예약 페이지 이동...")
        page.goto(
            "https://gw.glowseoul.co.kr/#/UK/UKA/UKA0000",
            wait_until="domcontentloaded",
            timeout=30000
        )
        # 페이지 완전 로드 및 자동 API 호출 대기
        page.wait_for_timeout(6000)
        print(f"  현재 URL: {page.url}")
        print(f"  지금까지 캡처된 헤더: {len(captured_headers)}건")

        # Step 4: window 전역 변수 탐색
        window_globals = explore_window_globals(page)

        # Step 5: 추가 schres 요청 유발
        trigger_schres_requests(page)
        page.wait_for_timeout(3000)

        # Step 6: 스크린샷
        screenshot_path = DATA_DIR / 'capture_auth_screenshot.png'
        page.screenshot(path=str(screenshot_path))
        print(f"\n  스크린샷 저장: {screenshot_path}")

        # Step 7: 결과 저장
        print(f"\n[4단계] 결과 저장...")
        print(f"  총 캡처된 /schres/ 요청: {len(captured_headers)}건")

        # 캡처된 인증 헤더 저장
        output_path = DATA_DIR / 'auth_headers_live.json'
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(captured_headers, f, ensure_ascii=False, indent=2)
        print(f"  헤더 저장: {output_path}")

        # window 전역 변수 분석 결과 저장
        window_globals_path = DATA_DIR / 'window_globals_analysis.json'
        with open(window_globals_path, 'w', encoding='utf-8') as f:
            json.dump(window_globals, f, ensure_ascii=False, indent=2)
        print(f"  window 분석 저장: {window_globals_path}")

        # Step 8: 콘솔 요약 출력
        print("\n" + "=" * 70)
        print("캡처 결과 요약")
        print("=" * 70)

        if captured_headers:
            print(f"\n★ /schres/ 인증 헤더 {len(captured_headers)}건 캡처 성공!")
            for i, entry in enumerate(captured_headers, 1):
                print(f"\n  [{i}] {entry['method']} {entry['url_path']}")
                h = entry['headers']
                print(f"    authorization : {h.get('authorization', '(없음)')[:80]}")
                print(f"    wehago-sign   : {h.get('wehago-sign', '(없음)')[:80]}")
                print(f"    timestamp     : {h.get('timestamp', '(없음)')}")
                print(f"    transaction-id: {h.get('transaction-id', '(없음)')}")
        else:
            print("\n  주의: /schres/ 요청이 캡처되지 않았습니다.")
            print("  - 페이지에서 자동 호출이 없었거나, 이미 캐시된 상태일 수 있습니다.")
            print("  - headless=False 상태에서 수동으로 자원 예약 페이지를 탐색해보세요.")

        # window 분석 요약
        print("\n--- window 전역 변수 분석 ---")
        kw_matches = window_globals.get('keywordMatches', [])
        print(f"  인증 관련 전역 키 ({len(kw_matches)}개): {kw_matches[:15]}")
        ns_check = window_globals.get('namespaceCheck', {})
        if ns_check:
            print(f"  발견된 네임스페이스: {list(ns_check.keys())}")
        ls_auth = window_globals.get('localStorageAuthRelated', {})
        if ls_auth:
            print(f"  localStorage 토큰/인증 키:")
            for k, v in ls_auth.items():
                print(f"    {k}: {str(v)[:100]}")

    except Exception as e:
        print(f"\n[오류] {e}")
        import traceback
        traceback.print_exc()

    finally:
        if browser:
            close_session(browser)
        pw.stop()
        print("\n브라우저 종료 완료")


if __name__ == "__main__":
    main()
