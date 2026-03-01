"""
실제 브라우저에서 예약 폼을 채우고 등록 버튼을 눌러
rs121A12 요청 body를 캡처하는 스크립트.
XHR 인터셉트 방식으로 정확한 payload를 획득.
"""
import os, sys, json, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv('config/.env')

from playwright.sync_api import sync_playwright
from src.auth.login import login_and_get_context, close_session

captured = []

pw = sync_playwright().start()
browser, context, page = login_and_get_context(playwright_instance=pw, headless=False)  # headless=False로 디버깅

def on_request(req):
    if '/schres/' in req.url and req.method == 'POST':
        ep = req.url.split('/schres/')[-1]
        body = req.post_data
        entry = {'ep': ep, 'body': body}
        captured.append(entry)
        if 'rs121A12' in ep or 'rs121A14' in ep or 'rs121A15' in ep:
            print(f'\n*** [CAPTURED REQUEST] {ep} ***')
            if body:
                try:
                    b = json.loads(body)
                    print(json.dumps(b, ensure_ascii=False, indent=2))
                except:
                    print(body[:1000])

def on_response(resp):
    if '/schres/' in resp.url and ('rs121A12' in resp.url or 'rs121A14' in resp.url):
        ep = resp.url.split('/schres/')[-1]
        try:
            body = resp.text()
            r = json.loads(body)
            print(f'\n*** [RESPONSE] {ep} resultCode={r.get("resultCode")}, msg={r.get("resultMsg", "")} ***')
        except:
            pass

page.on('request', on_request)
page.on('response', on_response)

# 자원예약 페이지
print('=== 1. 자원예약 페이지 이동 ===')
page.goto('https://gw.glowseoul.co.kr/#/UK/UKA/UKA0000')
page.wait_for_timeout(5000)

# XHR/fetch 인터셉트 설치 (더 상세한 캡처)
page.evaluate("""() => {
    // XHR 인터셉트
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function(body) {
        if (this._url && this._url.includes('rs121A12')) {
            console.log('[XHR-CAPTURE] rs121A12 body:', body);
            window.__captured_rs121A12_body = body;
        }
        return origSend.call(this, body);
    };
    const origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        this._url = url;
        return origOpen.call(this, method, url, ...args);
    };
}""")

# 자원 예약 버튼 클릭
print('\n=== 2. 자원 예약 버튼 클릭 ===')
btn = page.locator('button:has-text("자원 예약")')
btn.click()
page.wait_for_timeout(2000)

# 예약 폼이 열렸는지 확인
print('\n=== 3. 폼 분석 ===')

# 제목 필드 찾기 - placeholder로 검색
title_input = page.locator('input[placeholder="예약명을 입력해주세요"]')
if title_input.count() > 0:
    title_input.fill('자동화테스트예약')
    print('제목 입력 완료')

# 자원(회의실) 선택 필드 찾기
# "대상을 입력하세요" 필드가 자원 선택
resource_input = page.locator('input[placeholder="대상을 입력하세요"]')
if resource_input.count() > 0:
    resource_input.click()
    page.wait_for_timeout(1000)
    # 드롭다운/팝업에서 2번 회의실 선택
    room_option = page.locator('text=2번 회의실')
    if room_option.count() > 0:
        room_option.first.click()
        page.wait_for_timeout(1000)
        print('2번 회의실 선택 완료')
    else:
        print('회의실 옵션 못찾음, 직접 입력 시도')
        resource_input.fill('2번 회의실')
        page.wait_for_timeout(1000)
        # 검색 결과 클릭
        result = page.locator('[class*=result] >> text=2번 회의실, [class*=list] >> text=2번 회의실, [class*=option] >> text=2번 회의실')
        if result.count() > 0:
            result.first.click()
            page.wait_for_timeout(500)
            print('검색 결과에서 선택')
        else:
            print('자원 선택 실패')

# 현재 폼 상태 스냅샷
print('\n=== 4. 폼 상태 ===')
form_state = page.evaluate("""() => {
    const inputs = document.querySelectorAll('input[type=text]');
    const result = [];
    inputs.forEach(inp => {
        if (inp.value) {
            result.push({
                ph: inp.placeholder || '',
                val: inp.value.substring(0, 50),
            });
        }
    });
    return result;
}""")
for f in form_state:
    print(f"  [{f['ph']}] = {f['val']}")

# 시간 셀 클릭으로 시간 설정 (기본 시간이 이미 설정되어 있을 수 있음)
# 스크린샷 저장
page.screenshot(path='data/gw_analysis/reservation_form.png')
print('\n스크린샷 저장: data/gw_analysis/reservation_form.png')

# 등록 버튼 찾기 (폼 내부의 등록 버튼)
print('\n=== 5. 등록 시도 ===')
# 모든 버튼 확인
visible_buttons = page.evaluate("""() => {
    const btns = document.querySelectorAll('button');
    return Array.from(btns)
        .filter(b => b.offsetParent !== null && b.textContent.trim())
        .map(b => ({
            text: b.textContent.trim().substring(0, 30),
            class: b.className.substring(0, 50),
            visible: b.offsetParent !== null,
        }));
}""")
print('보이는 버튼:')
for b in visible_buttons:
    print(f"  [{b['text']}] class={b['class']}")

# "등록" 버튼 클릭 (visible한 것만)
reg_btn = page.locator('button:visible:has-text("등록")')
if reg_btn.count() > 0:
    print(f'\n등록 버튼 {reg_btn.count()}개, 클릭...')
    reg_btn.first.click()
    page.wait_for_timeout(5000)

    # 확인 다이얼로그
    confirm = page.locator('button:visible:has-text("확인")')
    if confirm.count() > 0:
        confirm.first.click()
        page.wait_for_timeout(3000)

# 캡처된 XHR body 확인
xhr_body = page.evaluate("() => window.__captured_rs121A12_body || null")
if xhr_body:
    print(f'\n=== XHR 캡처된 rs121A12 body ===')
    try:
        b = json.loads(xhr_body)
        print(json.dumps(b, ensure_ascii=False, indent=2))
    except:
        print(xhr_body[:1000])

print(f'\n총 캡처 요청: {len(captured)}건')

# 저장
from pathlib import Path
out = Path('data/gw_analysis')
out.mkdir(parents=True, exist_ok=True)
with open(out / 'real_reservation_capture.json', 'w', encoding='utf-8') as f:
    json.dump(captured, f, ensure_ascii=False, indent=2)

close_session(browser)
pw.stop()
