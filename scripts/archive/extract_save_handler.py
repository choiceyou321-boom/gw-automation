"""
chunk_24 JS에서 save 핸들러와 resSubscriberList 구성 로직 추출.
"""
import os, sys, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv('config/.env')

from playwright.sync_api import sync_playwright
from src.auth.login import login_and_get_context, close_session

pw = sync_playwright().start()
browser, context, page = login_and_get_context(playwright_instance=pw, headless=True)

page.goto('https://gw.glowseoul.co.kr/#/UK/UKA/UKA0000')
page.wait_for_timeout(5000)

# chunk_24 JS를 직접 fetch해서 분석
print('=== chunk_24 JS 분석 ===')

result = page.evaluate("""() => {
    const url = 'https://gw.glowseoul.co.kr/modules/schres/static/js/24.ef8091f1.chunk.js';
    return fetch(url).then(r => r.text()).then(text => {
        const results = {};

        // 1. save 핸들러: "10"!== 패턴 (endpoint 선택 로직)
        const savePatterns = [];
        let idx = text.indexOf('"10"!==');
        while (idx !== -1 && savePatterns.length < 5) {
            savePatterns.push({
                offset: idx,
                before: text.substring(Math.max(0, idx - 800), idx),
                after: text.substring(idx, Math.min(text.length, idx + 800))
            });
            idx = text.indexOf('"10"!==', idx + 1);
        }
        results.savePatterns = savePatterns;

        // 2. resSubscriberList 모든 등장
        const subPatterns = [];
        idx = text.indexOf('resSubscriberList');
        while (idx !== -1 && subPatterns.length < 15) {
            subPatterns.push({
                offset: idx,
                context: text.substring(Math.max(0, idx - 200), Math.min(text.length, idx + 300))
            });
            idx = text.indexOf('resSubscriberList', idx + 17);
        }
        results.subscriberPatterns = subPatterns;

        // 3. subscriber 초기화 (ucUserInfo 관련)
        const ucPatterns = [];
        idx = text.indexOf('ucUserInfo');
        while (idx !== -1 && ucPatterns.length < 5) {
            ucPatterns.push({
                offset: idx,
                context: text.substring(Math.max(0, idx - 200), Math.min(text.length, idx + 400))
            });
            idx = text.indexOf('ucUserInfo', idx + 10);
        }
        results.ucUserInfoPatterns = ucPatterns;

        // 4. schUserToOrg 함수 (subscriber 변환)
        const orgPatterns = [];
        idx = text.indexOf('schUserToOrg');
        while (idx !== -1 && orgPatterns.length < 5) {
            orgPatterns.push({
                offset: idx,
                context: text.substring(Math.max(0, idx - 100), Math.min(text.length, idx + 500))
            });
            idx = text.indexOf('schUserToOrg', idx + 12);
        }
        results.schUserToOrgPatterns = orgPatterns;

        results.fileSize = text.length;
        return results;
    });
}""")

print(f"JS 파일 크기: {result['fileSize']}")

print(f"\n{'='*60}")
print(f"=== 1. Save 핸들러 ('10'!== 패턴) - {len(result['savePatterns'])}건 ===")
for i, m in enumerate(result['savePatterns']):
    print(f"\n--- [{i+1}] offset {m['offset']} ---")
    print("BEFORE:", m['before'][-500:])
    print("\nAFTER:", m['after'][:500])

print(f"\n{'='*60}")
print(f"=== 2. resSubscriberList 패턴 - {len(result['subscriberPatterns'])}건 ===")
for i, m in enumerate(result['subscriberPatterns']):
    print(f"\n--- [{i+1}] offset {m['offset']} ---")
    print(m['context'])

print(f"\n{'='*60}")
print(f"=== 3. ucUserInfo 패턴 - {len(result['ucUserInfoPatterns'])}건 ===")
for i, m in enumerate(result['ucUserInfoPatterns']):
    print(f"\n--- [{i+1}] offset {m['offset']} ---")
    print(m['context'])

print(f"\n{'='*60}")
print(f"=== 4. schUserToOrg 패턴 - {len(result['schUserToOrgPatterns'])}건 ===")
for i, m in enumerate(result['schUserToOrgPatterns']):
    print(f"\n--- [{i+1}] offset {m['offset']} ---")
    print(m['context'])

# 결과 저장
with open('data/gw_analysis/save_handler_analysis.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print('\n저장: data/gw_analysis/save_handler_analysis.json')

close_session(browser)
pw.stop()
