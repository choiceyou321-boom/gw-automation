"""
근태신청현황 페이지 진입 → DOM 전체 dump → export 셀렉터 발견
- 페이지 진입 시퀀스는 cu_export_poc.py와 동일
- 모든 frame에서: button / a / span / div / img / i 요소의 텍스트+title+aria-label 수집
- 키워드(엑셀/다운로드/Excel/Export 등) 포함된 요소 별도 marker

저장: data/attendance_status_dom.json
"""
from __future__ import annotations
import json, logging, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright, Page
from src.shared.auth.login import login_and_get_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("dom_dump")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "attendance_status_dom.json"

KEYWORDS = ["엑셀", "다운로드", "내보내기", "출력", "인쇄", "Excel", "Export", "Download", "Print", "CSV", "PDF"]

JS_DUMP = r"""
(keywords) => {
    const out = { visible_clickables: [], keyword_matches: [], page_title: '', url: location.href };
    const titleEl = document.querySelector('h1, h2, [class*="PageTitle"], [class*="pageTitle"]');
    out.page_title = titleEl ? (titleEl.innerText || '').trim().slice(0, 100) : '';

    // 모든 클릭 가능한 요소: button, a, span, div, i, img
    const all = document.querySelectorAll('button, a, span, div, i, img, [role="button"]');
    const seen = new Set();
    all.forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        const txt = (el.innerText || el.textContent || '').trim();
        const title = el.title || '';
        const aria = el.getAttribute('aria-label') || '';
        const alt = el.getAttribute('alt') || '';
        const dataAttr = JSON.stringify(Array.from(el.attributes || []).filter(a => a.name.startsWith('data-')).reduce((acc,a)=>{acc[a.name]=a.value;return acc;},{}));
        // 키워드 매칭
        const combined = (txt + ' ' + title + ' ' + aria + ' ' + alt + ' ' + (el.className||'').toString()).toLowerCase();
        let matched_kw = null;
        for (const kw of keywords) {
            if (combined.includes(kw.toLowerCase())) {
                matched_kw = kw;
                break;
            }
        }
        const entry = {
            tag: el.tagName,
            text: txt.slice(0, 50),
            title: title.slice(0, 80),
            aria: aria.slice(0, 80),
            alt: alt.slice(0, 80),
            cls: (el.className || '').toString().slice(0, 150),
            id: el.id || '',
            x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height),
            data_attrs: dataAttr.length < 200 ? dataAttr : null,
        };
        // 키워드 매칭 별도 저장
        if (matched_kw) {
            out.keyword_matches.push({ ...entry, matched: matched_kw });
        }
        // 일반 클릭가능: 텍스트 있거나 title 있거나 cls에 Button/icon 포함
        const isClickable = (el.tagName === 'BUTTON' || el.tagName === 'A' ||
                            el.getAttribute('role') === 'button' ||
                            (el.className && el.className.toString().match(/Button|button|icon|Icon|btn/)));
        if (isClickable && (txt || title || aria || alt)) {
            const key = entry.tag + '|' + entry.text + '|' + entry.title + '|' + entry.x + ',' + entry.y;
            if (!seen.has(key)) {
                seen.add(key);
                out.visible_clickables.push(entry);
            }
        }
    });
    return out;
}
"""


def click_text(page: Page, text: str, timeout_ms: int = 4000) -> bool:
    targets = [page.main_frame] + [f for f in page.frames if f != page.main_frame]
    for fr in targets:
        for sel in [f"text='{text}'", f"li:has-text('{text}')", f"a:has-text('{text}')"]:
            try:
                loc = fr.locator(sel).first
                if loc.count() > 0 and loc.is_visible(timeout=500):
                    loc.click(force=True, timeout=timeout_ms)
                    return True
            except Exception:
                continue
    return False


def main():
    with sync_playwright() as pw:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=False,
            user_id="tgjeon",
        )
        try:
            page.set_viewport_size({"width": 1920, "height": 1080})
        except Exception:
            pass

        m = re.match(r"(https://[^/]+)", page.url)
        base = m.group(1) if m else "https://gw.glowseoul.co.kr"

        # 페이지 진입 — cu_export_poc 와 동일한 강건한 시퀀스
        page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        page.locator("span.module-link.HR").first.click(force=True, timeout=5000)
        page.wait_for_timeout(5000)
        logger.info("HR 진입")
        # 이미 열린 탭이 있으면 그것부터
        if click_text(page, "근태신청현황", timeout_ms=2000):
            page.wait_for_timeout(3500)
            logger.info("✓ 기존 탭의 근태신청현황")
        else:
            for step, wait_ms in [("근태관리", 2500), ("근태신청", 2500), ("근태신청현황", 4000)]:
                ok = click_text(page, step, timeout_ms=4000)
                if not ok:
                    page.wait_for_timeout(1500)
                    ok = click_text(page, step, timeout_ms=4000)
                if ok:
                    page.wait_for_timeout(wait_ms)
                    logger.info(f"✓ {step}")
                else:
                    logger.error(f"✗ {step}")

        # 그리드가 완전히 로드되도록 추가 대기
        page.wait_for_timeout(3000)
        page.screenshot(path=str(ROOT / "data" / "amaranth_screens" / "dom_dump_target.png"))

        # 모든 frame에서 DOM 덤프
        all_results = []
        for fr in [page.main_frame] + [f for f in page.frames if f != page.main_frame]:
            try:
                r = fr.evaluate(JS_DUMP, KEYWORDS)
                r["_frame_url"] = fr.url[:100]
                all_results.append(r)
            except Exception as e:
                logger.warning(f"frame evaluate 실패: {e}")

        OUT.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"저장: {OUT}")

        # 콘솔 요약
        for r in all_results:
            logger.info(f"\n--- frame: {r['_frame_url'][:60]} ---")
            logger.info(f"page_title: {r['page_title']}")
            logger.info(f"visible_clickables: {len(r['visible_clickables'])}, keyword_matches: {len(r['keyword_matches'])}")
            for km in r["keyword_matches"][:20]:
                logger.info(f"  ★ [{km['tag']}] '{km['text'][:30]}' title='{km['title'][:30]}' aria='{km['aria'][:30]}' kw={km['matched']}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
