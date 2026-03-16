"""
브라우저에서 실제 예약 등록 시 rs121A12 요청 body를 캡처하는 스크립트.
"""
import os, sys, json, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv('config/.env')

from playwright.sync_api import sync_playwright
from src.auth.login import login_and_get_context, close_session

captured_requests = []
captured_responses = []

pw = sync_playwright().start()
browser, context, page = login_and_get_context(playwright_instance=pw, headless=True)

def on_request(request):
    url = request.url
    if '/schres/rs121A1' in url:
        body = request.post_data
        captured_requests.append({'url': url, 'body': body})
        ep = url.split('/schres/')[-1]
        print(f'  [REQ] {ep}')
        if body:
            try:
                b = json.loads(body)
                print(json.dumps(b, ensure_ascii=False, indent=2))
            except:
                print(f'  RAW: {body[:500]}')

def on_response(response):
    url = response.url
    if '/schres/rs121A1' in url:
        try:
            resp_body = response.text()
        except:
            resp_body = ''
        captured_responses.append({'url': url, 'status': response.status, 'body': resp_body[:2000]})
        ep = url.split('/schres/')[-1]
        print(f'  [RESP] {ep} status={response.status}')
        if resp_body:
            try:
                r = json.loads(resp_body)
                rc = r.get('resultCode', '?')
                rm = r.get('resultMsg', '')[:100]
                print(f'    resultCode={rc}, msg={rm}')
            except:
                print(f'    {resp_body[:200]}')

page.on('request', on_request)
page.on('response', on_response)

# 자원예약 페이지 이동
page.goto('https://gw.glowseoul.co.kr/#/UK/UKA/UKA0000')
page.wait_for_timeout(4000)

# 자원 예약 버튼 클릭
print('=== 1. 자원 예약 버튼 클릭 ===')
btn = page.query_selector('button:has-text("자원 예약")')
btn.click()
page.wait_for_timeout(3000)

# 폼 구조 분석
print('\n=== 2. 폼 구조 ===')
form_info = page.evaluate("""() => {
    const fields = [];
    document.querySelectorAll('input, select, textarea').forEach(el => {
        fields.push({
            tag: el.tagName,
            type: el.type || '',
            name: el.name || '',
            id: el.id || '',
            placeholder: el.placeholder || '',
            value: (el.value || '').substring(0, 50),
            className: (el.className || '').substring(0, 80),
        });
    });

    const labels = [];
    document.querySelectorAll('label, th, .tit, [class*=label], [class*=tit]').forEach(el => {
        const txt = el.textContent.trim().substring(0, 40);
        if (txt && txt.length < 40) labels.push(txt);
    });

    return { fields: fields, labels: [...new Set(labels)].slice(0, 30) };
}""")

print(f"라벨: {form_info['labels']}")
print(f"\n필드 ({len(form_info['fields'])}개):")
for f in form_info['fields']:
    if f['name'] or f['id'] or f['value'] or f['placeholder']:
        print(f"  {f['tag']} type={f['type']} name={f['name']} id={f['id']} ph={f['placeholder']} val={f['value']}")

# 제목 입력
print('\n=== 3. 폼 입력 ===')
title_input = page.query_selector('input[placeholder*="제목"], input[placeholder*="예약"]')
if not title_input:
    # 좀 더 넓은 범위
    all_inputs = page.query_selector_all('input[type="text"]')
    for inp in all_inputs:
        ph = inp.get_attribute('placeholder') or ''
        val = inp.input_value()
        print(f"  text input: ph='{ph}', val='{val}'")
    if all_inputs:
        title_input = all_inputs[0]

if title_input:
    title_input.fill('API캡처테스트')
    print('제목 입력 완료')
else:
    print('제목 필드 못찾음')

# 등록 버튼 클릭
print('\n=== 4. 등록 버튼 클릭 ===')
reg_btn = page.query_selector('button:has-text("등록")')
if reg_btn:
    print(f'등록 버튼: {reg_btn.inner_text().strip()}')
    reg_btn.click()
    page.wait_for_timeout(5000)

    # 확인 다이얼로그가 있으면 클릭
    confirm_btn = page.query_selector('button:has-text("확인")')
    if confirm_btn:
        print('확인 버튼 클릭')
        confirm_btn.click()
        page.wait_for_timeout(3000)

print(f'\n총 캡처 요청: {len(captured_requests)}건')
print(f'총 캡처 응답: {len(captured_responses)}건')

close_session(browser)
pw.stop()

# 저장
from pathlib import Path
out_dir = Path('data/gw_analysis')
out_dir.mkdir(parents=True, exist_ok=True)
with open(out_dir / 'rs121A12_capture.json', 'w', encoding='utf-8') as f:
    json.dump({
        'requests': captured_requests,
        'responses': captured_responses,
    }, f, ensure_ascii=False, indent=2)
print('\n저장 완료: data/gw_analysis/rs121A12_capture.json')
