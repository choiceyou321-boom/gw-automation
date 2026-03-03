"""rs121A API 테스트 v2 - 브라우저에서 인증 헤더 캡처 후 httpx로 호출"""
import sys, os, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'config', '.env'))
from src.auth.login import login_and_get_context, close_session
from pathlib import Path
import httpx

DATA = Path(__file__).parent.parent / 'data' / 'gw_analysis'

browser, context, page = login_and_get_context(headless=True)
cookies = context.cookies()
cookie_str = '; '.join(f"{c['name']}={c['value']}" for c in cookies)

# ★ 핵심: 브라우저에서 실제 API 호출 시 사용하는 헤더 캡처
auth_headers = {}
api_calls = []

def capture_headers(resp):
    url = resp.url
    if 'rs121' in url or 'gw114' in url or 'gw096' in url:
        req = resp.request
        h = dict(req.headers)
        auth_headers.update(h)
        req_body = None
        if req.post_data:
            try: req_body = json.loads(req.post_data)
            except: req_body = req.post_data[:1000]
        resp_body = None
        try: resp_body = resp.json()
        except: pass
        api_calls.append({
            'url': url,
            'method': req.method,
            'headers': h,
            'req_body': req_body,
            'resp_body': resp_body,
            'status': resp.status,
        })
        url_short = url.split('glowseoul.co.kr')[-1][:60]
        print(f'  [캡처] {req.method} {url_short} ({resp.status})')

page.on('response', capture_headers)

# 자원 페이지 이동
print('=== 자원 페이지 이동 ===')
page.goto(
    'https://gw.glowseoul.co.kr/#/UK/UKA/UKA0000',
    wait_until='domcontentloaded', timeout=15000
)
page.wait_for_timeout(6000)

# 자원 예약 클릭
print('\n=== 자원 예약 클릭 ===')
page.get_by_text('자원 예약').first.click()
page.wait_for_timeout(4000)

# 캡처된 인증 헤더 분석
print(f'\n=== 캡처된 인증 헤더 ===')
important_headers = ['authorization', 'timestamp', 'transaction-id', 'wehago-sign', 'cookie', 'content-type']
for key in important_headers:
    val = auth_headers.get(key, 'NOT FOUND')
    if key == 'cookie':
        val = val[:100] + '...' if len(val) > 100 else val
    print(f'  {key}: {val[:150]}')

# 전체 헤더 저장
with open(DATA / 'rs121_auth_headers.json', 'w', encoding='utf-8') as f:
    # cookie 값 마스킹 (보안)
    safe_headers = {k: v[:200] for k, v in auth_headers.items()}
    json.dump(safe_headers, f, ensure_ascii=False, indent=2)

# 캡처된 API 호출 저장
print(f'\n=== 캡처된 API 호출: {len(api_calls)}개 ===')
for call in api_calls:
    url_short = call['url'].split('glowseoul.co.kr')[-1][:60]
    print(f'  {call["method"]} {url_short}')
    if call['req_body']:
        print(f'    REQ: {json.dumps(call["req_body"], ensure_ascii=False)[:300]}')
    if call['resp_body']:
        rd = call['resp_body'].get('resultData')
        if rd:
            rd_str = json.dumps(rd, ensure_ascii=False)
            print(f'    RESP resultData ({len(rd_str)} chars): {rd_str[:300]}')

# ★ httpx로 동일한 헤더 사용해서 API 호출
print('\n\n=== httpx로 API 테스트 ===')
client = httpx.Client(
    base_url='https://gw.glowseoul.co.kr',
    headers={
        'Cookie': auth_headers.get('cookie', cookie_str),
        'Content-Type': auth_headers.get('content-type', 'application/json;charset=UTF-8'),
        'Accept': auth_headers.get('accept', 'application/json'),
        'User-Agent': auth_headers.get('user-agent', 'Mozilla/5.0'),
        'authorization': auth_headers.get('authorization', ''),
        'timestamp': auth_headers.get('timestamp', ''),
        'transaction-id': auth_headers.get('transaction-id', ''),
        'wehago-sign': auth_headers.get('wehago-sign', ''),
        'Referer': 'https://gw.glowseoul.co.kr/',
    },
    verify=False,
    timeout=30,
)

# 테스트 1: rs121A01 자원 목록
print('\n--- rs121A01: 자원 목록 ---')
try:
    resp = client.post('/gw/APIHandler/rs121A01', json={})
    data = resp.json()
    print(f'  status: {resp.status_code}, resultCode: {data.get("resultCode")}, msg: {data.get("resultMsg")}')
    if data.get('resultData'):
        rd = data['resultData']
        if isinstance(rd, list):
            print(f'  자원 수: {len(rd)}')
            for item in rd[:10]:
                print(f'    {json.dumps(item, ensure_ascii=False)[:200]}')
        with open(DATA / 'rs121A01_success.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
except Exception as e:
    print(f'  실패: {e}')

# 테스트 2: rs121A03 자원 검색
print('\n--- rs121A03: 자원 검색 ---')
try:
    resp = client.post('/gw/APIHandler/rs121A03', json={"searchText": "회의실"})
    data = resp.json()
    print(f'  status: {resp.status_code}, resultCode: {data.get("resultCode")}')
    if data.get('resultData'):
        rd = data['resultData']
        if isinstance(rd, list):
            print(f'  결과: {len(rd)}개')
            for item in rd[:10]:
                print(f'    {json.dumps(item, ensure_ascii=False)[:200]}')
        with open(DATA / 'rs121A03_success.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
except Exception as e:
    print(f'  실패: {e}')

# 테스트 3: rs121A05 이벤트 목록
print('\n--- rs121A05: 이벤트 목록 ---')
try:
    resp = client.post('/gw/APIHandler/rs121A05', json={
        "startDate": "20260301",
        "endDate": "20260302",
    })
    data = resp.json()
    print(f'  status: {resp.status_code}, resultCode: {data.get("resultCode")}')
    if data.get('resultData'):
        rd = data['resultData']
        if isinstance(rd, list):
            print(f'  이벤트 수: {len(rd)}')
            for item in rd[:5]:
                print(f'    {json.dumps(item, ensure_ascii=False)[:200]}')
        with open(DATA / 'rs121A05_success.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
except Exception as e:
    print(f'  실패: {e}')

# 테스트 4: rs121A14 중복 체크
print('\n--- rs121A14: 중복 체크 ---')
try:
    resp = client.post('/gw/APIHandler/rs121A14', json={
        "startDate": "2026030109",
        "endDate": "2026030110",
    })
    data = resp.json()
    print(f'  status: {resp.status_code}, resultCode: {data.get("resultCode")}')
    print(f'  결과: {json.dumps(data, ensure_ascii=False)[:500]}')
    with open(DATA / 'rs121A14_success.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
except Exception as e:
    print(f'  실패: {e}')

# 캡처된 API 전체 저장
safe_calls = []
for call in api_calls:
    safe = {
        'url': call['url'],
        'method': call['method'],
        'status': call['status'],
        'req_body': call['req_body'],
    }
    if call.get('resp_body'):
        r = json.dumps(call['resp_body'], ensure_ascii=False)
        safe['resp_body'] = call['resp_body'] if len(r) < 5000 else r[:3000]
    safe_calls.append(safe)

with open(DATA / 'rs121_browser_api_calls.json', 'w', encoding='utf-8') as f:
    json.dump(safe_calls, f, ensure_ascii=False, indent=2)

close_session(browser)
client.close()
print('\n=== 완료 ===')
