"""
save 핸들러의 uidList(c), startDatePk(b), createDatePk(T) 등 변수 정의 추출.
offset 444080~445756 사이의 코드를 더 넓게 추출.
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

# save 핸들러 전체 코드 추출 (offset 443000~447000)
print('=== save 핸들러 전체 코드 추출 ===')

result = page.evaluate("""() => {
    const url = 'https://gw.glowseoul.co.kr/modules/schres/static/js/24.ef8091f1.chunk.js';
    return fetch(url).then(r => r.text()).then(text => {
        // save 핸들러 전체 (offset 443000~447000)
        const saveHandler = text.substring(443000, 447500);

        // 신규 예약 save 핸들러 (offset 537000~541000) - 두번째 컴포넌트
        const saveHandler2 = text.substring(537000, 541000);

        // subscriber 초기화 로직 (offset 433000~434500)
        const initSubscriber = text.substring(433000, 434500);

        // schUserToOrg 함수 정의
        let schUserToOrgDef = '';
        const idx = text.indexOf('schUserToOrg=function');
        if (idx !== -1) {
            schUserToOrgDef = text.substring(idx, idx + 500);
        }

        return {
            saveHandler: saveHandler,
            saveHandler2: saveHandler2,
            initSubscriber: initSubscriber,
            schUserToOrgDef: schUserToOrgDef,
        };
    });
}""")

print("=== 1. SAVE 핸들러 (수정 폼, offset 443000~447500) ===")
print(result['saveHandler'])

print("\n\n=== 2. SAVE 핸들러 (신규 폼, offset 537000~541000) ===")
print(result['saveHandler2'])

print("\n\n=== 3. Subscriber 초기화 (offset 433000~434500) ===")
print(result['initSubscriber'])

print("\n\n=== 4. schUserToOrg 함수 정의 ===")
print(result['schUserToOrgDef'])

# 저장
with open('data/gw_analysis/save_handler_full.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print('\n저장: data/gw_analysis/save_handler_full.json')

close_session(browser)
pw.stop()
