"""
RM(자원) 페이지 진입 후 우상단 export 아이콘의 정확한 셀렉터 발견
- 스크린샷에서 우상단 검색창 옆 영역(x>1850)에 작은 아이콘 3개 있음
- 그중 가운데가 엑셀 다운로드 아이콘
- 좌표 기반으로 클릭 시도도 시도
"""
from __future__ import annotations
import json, logging, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / "config" / ".env", override=True)
from playwright.sync_api import sync_playwright, Page
from src.shared.auth.login import login_and_get_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("dump_rm")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "rm_page_dom.json"

JS_FULL_DUMP = r"""
() => {
    const out = { url: location.href, elements: [] };
    // 모든 visible 요소 (위치 제한 없이)
    const all = document.querySelectorAll('*');
    const seen = new Set();
    all.forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        if (r.width > 200 || r.height > 200) return;  // 작은 요소만 (아이콘 후보)
        const title = el.title || '';
        const aria = el.getAttribute('aria-label') || '';
        const cls = (el.className || '').toString();
        const txt = (el.innerText || el.textContent || '').trim();
        // 우상단(x>1700, y<200) 영역의 요소 또는 title/aria/cls에 excel/엑셀 포함
        const inTopRight = r.x > 1700 && r.y < 250;
        const hasExcel = (title + aria + cls + txt).toLowerCase().match(/excel|엑셀|download|다운로드|export|내보내기/);
        if (!inTopRight && !hasExcel) return;
        const key = el.tagName + '|' + r.x + ',' + r.y + '|' + cls.slice(0,30);
        if (seen.has(key)) return;
        seen.add(key);
        out.elements.push({
            tag: el.tagName,
            text: txt.slice(0, 50),
            title: title.slice(0, 80),
            aria: aria.slice(0, 80),
            cls: cls.slice(0, 200),
            id: el.id || '',
            x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height),
            in_top_right: inTopRight,
            has_excel: !!hasExcel,
        });
    });
    return out;
}
"""


def main():
    with sync_playwright() as pw:
        browser, context, page = login_and_get_context(
            playwright_instance=pw, headless=False, user_id="tgjeon",
        )
        try:
            page.set_viewport_size({"width": 1920, "height": 1080})
        except Exception:
            pass
        m = re.match(r"(https://[^/]+)", page.url)
        base = m.group(1) if m else "https://gw.glowseoul.co.kr"

        # RM 진입
        page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)
        page.locator("span.module-link.RM").first.click(force=True, timeout=5000)
        page.wait_for_timeout(5500)
        logger.info("RM 진입")

        page.screenshot(path=str(ROOT / "data" / "amaranth_screens" / "dump_rm_target.png"))

        # 모든 frame dump
        results = []
        for fr in [page.main_frame] + [f for f in page.frames if f != page.main_frame]:
            try:
                r = fr.evaluate(JS_FULL_DUMP)
                r["_frame_url"] = fr.url[:100]
                results.append(r)
            except Exception as e:
                logger.warning(f"frame evaluate 실패: {e}")

        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"저장: {OUT}")

        # 콘솔 요약 — 우상단 또는 엑셀 키워드 요소
        for r in results:
            els = r.get("elements", [])
            if not els:
                continue
            logger.info(f"\n--- {r['_frame_url'][:60]} ---")
            for e in els[:50]:
                marker = "★" if e["has_excel"] else " "
                logger.info(
                    f" {marker}[{e['tag']:7s}] x={e['x']:4d} y={e['y']:4d} "
                    f"w={e['w']:3d}h={e['h']:3d} "
                    f"title='{e['title'][:30]}' aria='{e['aria'][:20]}' cls={e['cls'][:60]}"
                )

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
