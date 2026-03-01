"""신규 예약 폼의 단건(rs121A12) save 핸들러 추출 - case 34 이후"""
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

result = page.evaluate("""() => {
    const url = 'https://gw.glowseoul.co.kr/modules/schres/static/js/24.ef8091f1.chunk.js';
    return fetch(url).then(r => r.text()).then(text => {
        // 신규 폼의 save 핸들러 더 넓은 범위 (rs121A12 호출부 포함)
        const part1 = text.substring(539800, 542000);

        // subscriber 초기화 부분 (init 함수에서 resSubscriberList 설정)
        // "resSubscriberList" 다음에 나오는 초기화 코드
        const initParts = [];
        let idx = text.indexOf('.resSubscriberList=');
        while (idx !== -1 && initParts.length < 10) {
            initParts.push({
                offset: idx,
                context: text.substring(Math.max(0, idx - 100), Math.min(text.length, idx + 400))
            });
            idx = text.indexOf('.resSubscriberList=', idx + 18);
        }

        // "empSeq" + "2922" 또는 비슷한 하드코딩 확인
        let empSeqInit = [];
        idx = text.indexOf('empSeq');
        let count = 0;
        while (idx !== -1 && count < 30) {
            const ctx = text.substring(Math.max(0, idx - 50), Math.min(text.length, idx + 100));
            if (ctx.includes('ucUser') || ctx.includes('subscriber') || ctx.includes('Subscriber') || ctx.includes('init') || ctx.includes('push')) {
                empSeqInit.push({offset: idx, context: ctx});
            }
            idx = text.indexOf('empSeq', idx + 6);
            count++;
        }

        return {
            newFormSave: part1,
            subscriberInit: initParts,
            empSeqInit: empSeqInit,
        };
    });
}""")

print("=== 신규 폼 SAVE 핸들러 (offset 539800~542000) ===")
print(result['newFormSave'])

print(f"\n\n=== resSubscriberList= 초기화 ({len(result['subscriberInit'])}건) ===")
for m in result['subscriberInit']:
    print(f"\n[offset {m['offset']}]")
    print(m['context'])

print(f"\n\n=== empSeq 관련 초기화 ({len(result['empSeqInit'])}건) ===")
for m in result['empSeqInit']:
    print(f"  [offset {m['offset']}] {m['context']}")

close_session(browser)
pw.stop()
