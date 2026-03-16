"""그룹웨어 전체 분석 스크립트"""
import sys, os, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'config', '.env'))
from src.auth.login import login_and_get_context, close_session
from pathlib import Path

DATA = Path(__file__).parent.parent / 'data' / 'gw_analysis'
DATA.mkdir(parents=True, exist_ok=True)

# API 요청 캡처
api_log = []
def on_resp(resp):
    url = resp.url
    if any(k in url for k in ['/api/', '/rest/', 'Ajax', '.do', '/gw/', 'approval', 'sanction', 'cmmn', 'ubea']):
        api_log.append({'method': resp.request.method, 'url': url[:300], 'status': resp.status})

browser, context, page = login_and_get_context(headless=True)
page.on('response', on_resp)

# 새 창 캡처
popups = []
context.on('page', lambda p: popups.append(p))

# ============= 전자결재 HOME =============
print('=== 전자결재 이동 ===')
page.get_by_text('전자결재', exact=True).first.click()
page.wait_for_timeout(4000)
page.screenshot(path=str(DATA / '05_approval_home_full.png'), full_page=True)

# 전체 텍스트 저장
body_text = page.inner_text('body')
with open(DATA / 'approval_home_text.txt', 'w', encoding='utf-8') as f:
    f.write(body_text)
print('텍스트 저장 완료')

# ============= 추천양식 분석 =============
print('\n=== 추천양식 분석 ===')
JS_RECOMMENDED = """() => {
    const all = document.querySelectorAll('span, a, div');
    let results = [];
    for (const el of all) {
        const rect = el.getBoundingClientRect();
        const t = el.textContent.trim();
        if (rect.y > 220 && rect.y < 290 && rect.x > 280 && rect.x < 900
            && t.length > 2 && t.length < 30 && !results.some(r => r.text === t)) {
            results.push({text: t, x: Math.round(rect.x), y: Math.round(rect.y), tag: el.tagName});
        }
    }
    return results;
}"""
recommended = page.evaluate(JS_RECOMMENDED)
for r in recommended:
    print(f"  {r['text']}")

# ============= 기결문서 목록 =============
print('\n=== 기결문서 목록 ===')
JS_DOCS = """() => {
    const all = document.querySelectorAll('*');
    let results = [];
    for (const el of all) {
        const t = el.textContent.trim();
        if (t.startsWith('GS-') && t.length < 80 && el.children.length === 0) {
            results.push(t);
        }
    }
    return [...new Set(results)].slice(0, 30);
}"""
docs = page.evaluate(JS_DOCS)
for d in docs:
    print(f"  {d}")

# ============= 결재 현황 통계 =============
print('\n=== 결재 현황 통계 ===')
JS_STATS = """() => {
    const all = document.querySelectorAll('*');
    let stats = {};
    for (const el of all) {
        const t = el.textContent.trim();
        const rect = el.getBoundingClientRect();
        // 오른쪽 영역 (x > 940)에 있는 통계 수치
        if (rect.x > 940 && rect.y > 150 && el.children.length === 0 && t.length > 0 && t.length < 50) {
            const key = Math.round(rect.y) + '_' + Math.round(rect.x);
            stats[key] = t;
        }
    }
    return stats;
}"""
stats = page.evaluate(JS_STATS)
for k in sorted(stats.keys()):
    print(f"  {stats[k]}")

# ============= 상신함 이동 =============
print('\n=== 상신함 (내가 올린 결재) 이동 ===')
try:
    # 사이드바에서 상신함 찾기
    sent_link = page.get_by_text('상신함').first
    if sent_link.is_visible(timeout=3000):
        sent_link.click()
        page.wait_for_timeout(3000)
        print(f'URL: {page.url}')
        page.screenshot(path=str(DATA / '07_sent_list.png'))

        # 상신함 목록
        sent_text = page.inner_text('body')
        with open(DATA / 'sent_list_text.txt', 'w', encoding='utf-8') as f:
            f.write(sent_text)
        print('상신함 텍스트 저장')
except Exception as e:
    print(f'상신함 이동 실패: {e}')
    # URL 직접 이동 시도
    try:
        # 사이드바 메뉴를 전부 캡처
        sidebar_text = page.evaluate("""() => {
            const aside = document.querySelector('aside') || document.querySelector('[class*=aside]') || document.querySelector('[class*=lnb]');
            return aside ? aside.innerText : 'aside not found';
        }""")
        print(f'사이드바 텍스트:\n{sidebar_text[:500]}')
    except:
        pass

# ============= 기결문서 첫번째 상세 보기 =============
print('\n=== 기결문서 상세 확인 ===')
# 전자결재 HOME으로 돌아가기
page.get_by_text('전자결재', exact=True).first.click()
page.wait_for_timeout(3000)

try:
    # 첫번째 GS- 문서 클릭
    doc_el = page.locator('text=/GS-25-/').first
    if doc_el.is_visible(timeout=3000):
        doc_el.click()
        page.wait_for_timeout(4000)

        # 새 창 확인
        if popups:
            popup = popups[-1]
            popup.wait_for_load_state('domcontentloaded', timeout=15000)
            popup.wait_for_timeout(3000)
            print(f'팝업 URL: {popup.url}')
            popup.screenshot(path=str(DATA / '08_doc_popup.png'))

            # 문서 상세 텍스트
            detail = popup.inner_text('body')
            with open(DATA / 'doc_detail_text.txt', 'w', encoding='utf-8') as f:
                f.write(detail)
            print('문서 상세 텍스트 저장')

            # input/select/textarea 필드
            JS_INPUTS = """() => {
                const inputs = document.querySelectorAll('input, select, textarea');
                return Array.from(inputs).slice(0, 50).map(el => ({
                    tag: el.tagName, id: el.id, name: el.name,
                    type: el.type || '', value: (el.value || '').substring(0, 100),
                    placeholder: el.placeholder || '',
                }));
            }"""
            inputs = popup.evaluate(JS_INPUTS)
            with open(DATA / 'doc_detail_inputs.json', 'w', encoding='utf-8') as f:
                json.dump(inputs, f, ensure_ascii=False, indent=2)
            print(f'문서 상세 input 필드: {len(inputs)}개')
            for inp in inputs[:15]:
                print(f"  {inp['tag']} id={inp['id']} name={inp['name']} type={inp['type']} val={inp['value'][:50]}")

            # 결재선 정보
            JS_LINE = """() => {
                const all = document.querySelectorAll('[class*=approval], [class*=sign], [class*=line], [class*=stamp]');
                return Array.from(all).slice(0, 20).map(el => ({
                    cls: el.className.substring(0, 60),
                    text: el.textContent.trim().substring(0, 100),
                }));
            }"""
            approval_line = popup.evaluate(JS_LINE)
            print('\n결재선 요소:')
            for al in approval_line:
                print(f"  cls={al['cls']} text={al['text']}")

            popup.close()
        else:
            # 같은 페이지
            print(f'같은 페이지 URL: {page.url}')
            page.screenshot(path=str(DATA / '08_doc_detail.png'))
except Exception as e:
    print(f'문서 상세 확인 실패: {e}')

# ============= 자원(회의실) 메뉴 분석 =============
print('\n=== 자원(회의실) 메뉴 분석 ===')
try:
    res_link = page.get_by_text('자원', exact=True).first
    if res_link.is_visible(timeout=2000):
        res_link.click()
        page.wait_for_timeout(3000)
        print(f'자원 URL: {page.url}')
        page.screenshot(path=str(DATA / '09_resource.png'))

        res_text = page.inner_text('body')
        with open(DATA / 'resource_text.txt', 'w', encoding='utf-8') as f:
            f.write(res_text)
except Exception as e:
    print(f'자원 메뉴 이동 실패: {e}')

# ============= 메일 메뉴 분석 =============
print('\n=== 메일 메뉴 분석 ===')
try:
    mail_link = page.get_by_text('메일', exact=True).first
    if mail_link.is_visible(timeout=2000):
        mail_link.click()
        page.wait_for_timeout(3000)
        print(f'메일 URL: {page.url}')
        page.screenshot(path=str(DATA / '10_mail.png'))
except Exception as e:
    print(f'메일 메뉴 이동 실패: {e}')

# ============= API 로그 저장 =============
print(f'\n=== API 요청 총 {len(api_log)}개 ===')
for a in api_log[:30]:
    print(f"  {a['method']} [{a['status']}] {a['url'][:120]}")
with open(DATA / 'api_log.json', 'w', encoding='utf-8') as f:
    json.dump(api_log, f, ensure_ascii=False, indent=2)

close_session(browser)
print('\n=== 전체 분석 완료 ===')
