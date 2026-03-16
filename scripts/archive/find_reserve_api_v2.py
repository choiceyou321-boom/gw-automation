"""자원 페이지 로드 후 동적 JS에서 API 탐색"""
import sys, os, json, re
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
headers = {
    'Cookie': '; '.join(f"{c['name']}={c['value']}" for c in cookies),
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
}

# 자원 페이지 이동 (schres 모듈 로드 트리거)
print('=== 자원 페이지 이동 ===')
page.goto(
    'https://gw.glowseoul.co.kr/#/UK/UKA/UKA0000?specialLnb=Y&moduleCode=UK&menuCode=UKA&pageCode=UKA0000',
    wait_until='domcontentloaded', timeout=15000
)
page.wait_for_timeout(5000)

# 자원 예약 클릭 (추가 JS 로드 트리거)
page.get_by_text('자원 예약').first.click()
page.wait_for_timeout(3000)

# 동적으로 로드된 모든 스크립트 URL
js_urls = page.evaluate("""() => {
    // script 태그
    const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
    // performance에 기록된 JS 리소스
    const perf = performance.getEntriesByType('resource')
        .filter(r => r.initiatorType === 'script' || r.name.endsWith('.js'))
        .map(r => r.name);
    return [...new Set([...scripts, ...perf])].filter(u => u.includes('.js'));
}""")
print(f'로드된 JS 파일: {len(js_urls)}개')

schres_urls = [u for u in js_urls if 'schres' in u]
print(f'schres 모듈 JS: {len(schres_urls)}개')
for u in schres_urls:
    print(f'  {u.split("/")[-1]}')

# schres JS 다운로드 및 API 패턴 분석
all_endpoints = {}
client = httpx.Client(headers=headers, verify=False, timeout=30)

for url in schres_urls:
    fname = url.split('/')[-1]
    print(f'\n=== {fname} ===')
    try:
        resp = client.get(url)
        js = resp.text
        print(f'  크기: {len(js)} bytes')

        # API 엔드포인트 패턴 (rs + 숫자 or gw + 숫자)
        endpoints = re.findall(r'["\']([rg][sw]\d{3}[A-Z]\d{2})["\']', js)
        endpoints += re.findall(r'["\']([RG][SW]\d{3}[A-Z]\d{2})["\']', js)
        # APIHandler 경로
        api_handler = re.findall(r'APIHandler[/\\]+([a-zA-Z0-9]+)', js)
        # 직접 gw/ 경로
        gw_direct = re.findall(r'gw[/\\]+([a-zA-Z0-9]{5,12})', js)

        all_found = sorted(set(endpoints + api_handler + gw_direct))
        if all_found:
            print(f'  엔드포인트: {all_found}')
            for ep in all_found:
                all_endpoints[ep] = fname

        # save/insert/create 관련 컨텍스트
        for keyword in ['save', 'insert', 'create', 'regist', 'submit']:
            indices = [m.start() for m in re.finditer(keyword, js, re.IGNORECASE)]
            for idx in indices[:3]:
                ctx = js[max(0, idx-100):idx+200]
                # API 코드가 포함된 컨텍스트만
                if re.search(r'[rg][sw]\d{3}|APIHandler|gw\d{3}', ctx, re.IGNORECASE):
                    print(f'  [{keyword}] ...{ctx.strip()[:200]}...')

        # 예약 관련 필드명
        fields = re.findall(r'(?:startDt|endDt|resourceSeq|reserveSeq|reserveName|resrcName|schTitle|schContent|allDay|repeatType|empSeq|deptSeq)["\s:,]', js, re.IGNORECASE)
        if fields:
            print(f'  필드명: {sorted(set(f.strip(":, \"") for f in fields))}')

    except Exception as e:
        print(f'  실패: {e}')

# 결과 정리
print(f'\n=== 전체 발견된 엔드포인트 ({len(all_endpoints)}개) ===')
for ep, src in sorted(all_endpoints.items()):
    print(f'  {ep} (from {src})')

with open(DATA / 'schres_api_endpoints.json', 'w', encoding='utf-8') as f:
    json.dump(all_endpoints, f, ensure_ascii=False, indent=2)

close_session(browser)
client.close()
