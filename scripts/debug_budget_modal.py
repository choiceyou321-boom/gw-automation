"""예산과목 모달 DOM 분석 디버그 스크립트"""
import sys, os, time, json, logging
logging.basicConfig(level=logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth.login import login_and_get_context, close_session
from playwright.sync_api import sync_playwright
from datetime import datetime

pw = sync_playwright().start()
browser, context, page = login_and_get_context(playwright_instance=pw, headless=False)
page.set_viewport_size({"width": 1920, "height": 1080})

from src.approval.approval_automation import ApprovalAutomation
automation = ApprovalAutomation(page=page, context=context)

# 양식 채우기 (예산과목 제외)
data = {
    "title": "예산모달 디버그",
    "project": "GS-25-0088",
    "items": [{"item": "테스트", "amount": 1000000}],
    "date": datetime.now().strftime("%Y-%m-%d"),
    "usage_code": "5020",
    "budget_keyword": "",  # 빈값 → 예산과목 선택 건너뛰기
    "save_mode": "verify",
}
automation._navigate_to_approval_home()
automation._click_expense_form()
automation._wait_for_form_load()
automation._fill_expense_fields(data)

# 예산과목 필드 찾기 & 클릭 → 모달 열기
inp = page.locator("input[placeholder='예산과목']").first
if not inp.is_visible(timeout=3000):
    print("ERROR: 예산과목 필드 미발견")
    close_session(browser); pw.stop(); sys.exit(1)

inp.click()
print("예산과목 필드 클릭 완료")
time.sleep(4)  # 모달 렌더링 대기

# 모달 내 visible input 전수조사
JS_INPUTS = """() => {
    const inputs = [];
    document.querySelectorAll('input').forEach(inp => {
        if (!inp.offsetParent) return;
        const r = inp.getBoundingClientRect();
        if (r.width === 0) return;
        inputs.push({
            placeholder: inp.placeholder || '',
            value: inp.value || '',
            disabled: inp.disabled,
            x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height),
            cls: (inp.className || '').substring(0, 100)
        });
    });
    return inputs;
}"""

info = page.evaluate(JS_INPUTS)
print(f"\n=== Visible Inputs ({len(info)}) ===")
for i in info:
    ph = i["placeholder"]
    val = i["value"]
    dis = i["disabled"]
    pos = f"({i['x']},{i['y']})"
    sz = f"{i['w']}x{i['h']}"
    cls = i["cls"]
    print(f"  ph='{ph}' val='{val}' disabled={dis} pos={pos} size={sz}")
    print(f"    class='{cls}'")

# 셀렉터 테스트
for sel in ["text=공통 예산잔액 조회", "text=공통 예산잔액"]:
    count = page.locator(sel).count()
    try:
        vis = page.locator(sel).first.is_visible(timeout=2000)
    except:
        vis = "error"
    print(f"\nSelector '{sel}': count={count}, first_visible={vis}")

# 예산 관련 텍스트 노드 탐색
JS_BUDGET_TEXT = """() => {
    const results = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
        const txt = walker.currentNode.textContent.trim();
        if (txt.includes('예산') && txt.length < 100) {
            const p = walker.currentNode.parentElement;
            results.push({
                text: txt.substring(0, 60),
                tag: p.tagName,
                cls: (p.className || '').substring(0, 60)
            });
        }
    }
    return results.slice(0, 20);
}"""
budget_texts = page.evaluate(JS_BUDGET_TEXT)
print(f"\n=== '예산' 텍스트 노드 ({len(budget_texts)}) ===")
for e in budget_texts:
    print(f"  text='{e['text']}' tag={e['tag']} cls='{e['cls']}'")

# 모달 div 구조 확인
JS_MODAL = """() => {
    // 모달/팝업/레이어 클래스 검색
    const modals = document.querySelectorAll('[class*="modal"], [class*="popup"], [class*="layer"], [class*="Layer"]');
    const results = [];
    for (const m of modals) {
        if (!m.offsetParent && m.style.display !== '') continue;
        const r = m.getBoundingClientRect();
        if (r.width < 200 || r.height < 100) continue;
        const txt = (m.textContent || '').trim().substring(0, 100);
        results.push({
            tag: m.tagName,
            cls: (m.className || '').substring(0, 100),
            pos: `${Math.round(r.x)},${Math.round(r.y)}`,
            size: `${Math.round(r.width)}x${Math.round(r.height)}`,
            has_budget: txt.includes('예산'),
            text_preview: txt.substring(0, 80)
        });
    }
    return results;
}"""
modals = page.evaluate(JS_MODAL)
print(f"\n=== 모달/팝업 요소 ({len(modals)}) ===")
for m in modals:
    budget_mark = " *** 예산모달 ***" if m["has_budget"] else ""
    print(f"  {m['tag']} cls='{m['cls']}' pos={m['pos']} size={m['size']}{budget_mark}")
    if m["has_budget"]:
        print(f"    text: {m['text_preview']}")

# 결과 저장
result = {"inputs": info, "budget_texts": budget_texts, "modals": modals}
with open("data/gw_analysis/budget_modal_dom.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print("\n결과 저장: data/gw_analysis/budget_modal_dom.json")

time.sleep(1)
close_session(browser)
pw.stop()
