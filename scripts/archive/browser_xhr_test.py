"""브라우저 내부 XHR + Python 생성 서명으로 rs121A12 호출"""
import os, sys, json, time, hmac, hashlib, base64, urllib.parse
from uuid import uuid4
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv('config/.env')

from playwright.sync_api import sync_playwright
from src.auth.login import login_and_get_context, close_session

pw = sync_playwright().start()
browser, context, page = login_and_get_context(playwright_instance=pw, headless=True)

# 쿠키에서 인증 정보
cookies = context.cookies()
oauth_raw = ''
sign_key = ''
for c in cookies:
    if c['name'] == 'oAuthToken':
        oauth_raw = c['value']
    elif c['name'] == 'signKey':
        sign_key = c['value']

oauth = urllib.parse.unquote(oauth_raw)

page.goto('https://gw.glowseoul.co.kr/#/UK/UKA/UKA0000')
page.wait_for_timeout(5000)

# Python에서 서명 생성
pathname = '/schres/rs121A12'
tid = uuid4().hex
ts = str(int(time.time()))
msg = oauth + tid + ts + pathname
sig = base64.b64encode(hmac.new(sign_key.encode(), msg.encode(), hashlib.sha256).digest()).decode()

# 브라우저 XHR로 호출 (Python 생성 서명 사용)
body = {
    "companyInfo": {
        "compSeq": "1000",
        "groupSeq": "gcmsAmaranth36068",
        "deptSeq": "2017",
        "emailAddr": "tgjeon",
        "emailDomain": "glowseoul.co.kr"
    },
    "langCode": "kr",
    "resSeq": "46",
    "seqNum": "",
    "resIdx": "",
    "reqText": "BrowserXHR",
    "apprYn": "N",
    "alldayYn": "N",
    "startDatePk": "20260302",
    "createDatePk": "",
    "startDate": "202603021400",
    "endDate": "202603021500",
    "descText": "",
    "resSubscriberList": [{"groupSeq": "gcmsAmaranth36068", "compSeq": "1000", "deptSeq": "2017", "empSeq": "2922"}],
    "uidList": "",
    "repeatType": "10",
    "repeatEndDay": "",
    "repeatByDay": "",
    "resName": "2번 회의실",
}

print('=== 브라우저 XHR (subscriber 있음) ===')
result = page.evaluate("""(args) => {
    return new Promise((resolve) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", args.pathname, true);
        xhr.setRequestHeader("transaction-id", args.tid);
        xhr.setRequestHeader("Content-type", "application/json");
        xhr.withCredentials = false;
        xhr.setRequestHeader("Authorization", "Bearer " + args.oauth);
        xhr.setRequestHeader("timestamp", args.ts);
        xhr.setRequestHeader("wehago-sign", args.sig);

        xhr.onload = function() {
            try {
                const resp = JSON.parse(xhr.response);
                resolve({
                    status: xhr.status,
                    resultCode: resp.resultCode,
                    resultMsg: resp.resultMsg,
                    resultData: JSON.stringify(resp.resultData || null).substring(0, 500),
                });
            } catch(e) {
                resolve({status: xhr.status, raw: xhr.response.substring(0, 500)});
            }
        };
        xhr.onerror = function() { resolve({error: 'XHR error'}); };
        xhr.send(args.bodyStr);
    });
}""", {"pathname": pathname, "tid": tid, "ts": ts, "oauth": oauth, "sig": sig, "bodyStr": json.dumps(body)})

print(json.dumps(result, ensure_ascii=False, indent=2))

# subscriber 빈 배열 테스트
tid2 = uuid4().hex
ts2 = str(int(time.time()))
sig2 = base64.b64encode(hmac.new(sign_key.encode(), (oauth + tid2 + ts2 + pathname).encode(), hashlib.sha256).digest()).decode()

body2 = dict(body)
body2['resSubscriberList'] = []
body2['reqText'] = 'BrowserXHR-empty'

print('\n=== 브라우저 XHR (subscriber 빈 배열) ===')
result2 = page.evaluate("""(args) => {
    return new Promise((resolve) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", args.pathname, true);
        xhr.setRequestHeader("transaction-id", args.tid);
        xhr.setRequestHeader("Content-type", "application/json");
        xhr.withCredentials = false;
        xhr.setRequestHeader("Authorization", "Bearer " + args.oauth);
        xhr.setRequestHeader("timestamp", args.ts);
        xhr.setRequestHeader("wehago-sign", args.sig);
        xhr.onload = function() {
            try { resolve(JSON.parse(xhr.response)); }
            catch(e) { resolve({raw: xhr.response.substring(0, 500)}); }
        };
        xhr.onerror = function() { resolve({error: 'XHR error'}); };
        xhr.send(args.bodyStr);
    });
}""", {"pathname": pathname, "tid": tid2, "ts": ts2, "oauth": oauth, "sig": sig2, "bodyStr": json.dumps(body2)})

print(json.dumps(result2, ensure_ascii=False, indent=2))

close_session(browser)
pw.stop()
