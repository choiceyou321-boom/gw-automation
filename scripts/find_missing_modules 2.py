"""
빠진 모듈 탐지
- 좌측 세로 사이드바의 모든 아이콘 dump
- 좌상단 ▦ 격자 아이콘(앱 메뉴) 클릭 → 펼친 모듈 그리드 dump
- 모든 module-link 변형 셀렉터 시도
- moduleCode= 패턴이 들어간 모든 onClick/href 수집
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
logger = logging.getLogger("missing")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "missing_modules.json"
SCR = ROOT / "data" / "amaranth_screens"

JS_PROBE = r"""
() => {
    const out = {
        url: location.href,
        // 1) 좌측 세로 사이드바 (보통 x < 50)
        left_sidebar: [],
        // 2) 모든 module-link 변형
        module_links: [],
        // 3) moduleCode 패턴 포함 onClick/href
        with_module_code: [],
        // 4) 좌상단 햄버거/그리드 아이콘
        top_left_icons: [],
        // 5) 알려지지 않은 작은 아이콘 (x<60, h<60)
        leftbar_icons: [],
    };

    // 1) 좌측 세로 사이드바 — 보통 x<60, y>40 area
    document.querySelectorAll('*').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        if (r.x > 60 || r.y < 40) return;
        if (r.width > 60 || r.height > 60) return;
        const title = el.title || '';
        const aria = el.getAttribute('aria-label') || '';
        const alt = el.getAttribute('alt') || '';
        const cls = (el.className || '').toString();
        const src = el.getAttribute('src') || '';
        if (!title && !aria && !alt && !src && !cls.match(/icon|Icon|btn/)) return;
        out.left_sidebar.push({
            tag: el.tagName,
            x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
            title: title.slice(0,40), aria: aria.slice(0,40), alt: alt.slice(0,40),
            src: src.slice(-50), cls: cls.slice(0,80),
            text: (el.innerText || '').trim().slice(0, 30),
        });
    });

    // 2) module-link 변형
    document.querySelectorAll('[class*="module"], [class*="Module"]').forEach(el => {
        const cls = (el.className || '').toString();
        const txt = (el.innerText || el.textContent || '').trim();
        const r = el.getBoundingClientRect();
        out.module_links.push({
            tag: el.tagName,
            cls: cls.slice(0, 150),
            text: txt.slice(0, 40),
            x: Math.round(r.x), y: Math.round(r.y), visible: r.width > 0 && r.height > 0,
        });
    });

    // 3) onClick/href에 moduleCode 포함
    document.querySelectorAll('a, [onclick], [data-href]').forEach(el => {
        const href = el.getAttribute('href') || el.getAttribute('data-href') || '';
        const oc = el.getAttribute('onclick') || '';
        const combined = href + ' ' + oc;
        if (!combined.match(/moduleCode|#\/[A-Z]{2,4}\//)) return;
        const m = combined.match(/(?:moduleCode=|#\/)([A-Z]{2,4})/);
        out.with_module_code.push({
            tag: el.tagName,
            text: (el.innerText || '').trim().slice(0,40),
            href: href.slice(0,150),
            onclick: oc.slice(0,150),
            module_hint: m ? m[1] : null,
        });
    });

    // 4) 좌상단 햄버거/그리드 아이콘 (x<60, y<60)
    document.querySelectorAll('*').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        if (r.x > 80 || r.y > 60) return;
        out.top_left_icons.push({
            tag: el.tagName,
            cls: (el.className || '').toString().slice(0,80),
            title: (el.title || '').slice(0,40),
            x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
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

        results = {}
        # 1) 홈에서 진단
        page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4500)
        page.screenshot(path=str(SCR / "missing_home.png"), full_page=True)
        results["home"] = page.evaluate(JS_PROBE)

        # 2) 좌상단 ▦ 아이콘 클릭 시도 (앱 메뉴 펼침)
        # 보통 x<40, y<40 위치
        try:
            # Apps grid button 후보 셀렉터
            for sel in [
                "button[title*='앱']", "button[aria-label*='앱']",
                "[class*='AppMenu']", "[class*='appMenu']",
                "[class*='AppGrid']", "[class*='dock']",
                "header button:first-child",
            ]:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible(timeout=400):
                    loc.click(force=True, timeout=2000)
                    page.wait_for_timeout(2500)
                    logger.info(f"  ✓ 앱 그리드 클릭: {sel}")
                    page.screenshot(path=str(SCR / "missing_app_grid.png"))
                    results["app_grid"] = page.evaluate(JS_PROBE)
                    break
        except Exception as e:
            logger.warning(f"앱 그리드 진입 실패: {e}")

        # 3) 좌측 사이드바 모든 아이콘 hover → tooltip 수집 시도
        try:
            sidebar_icons = page.evaluate(r"""
                () => {
                    const icons = [];
                    document.querySelectorAll('*').forEach(el => {
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) return;
                        if (r.x > 50 || r.y < 40 || r.y > 800) return;
                        if (r.width > 50 || r.height > 50) return;
                        if (r.width < 15 || r.height < 15) return;
                        icons.push({x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)});
                    });
                    const seen = new Set();
                    return icons.filter(i => {
                        const k = i.x + ',' + i.y;
                        if (seen.has(k)) return false;
                        seen.add(k); return true;
                    });
                }
            """)
            logger.info(f"좌측 사이드바 아이콘 후보: {len(sidebar_icons)}")
            # 각 아이콘에 hover 후 tooltip 확인 (5개만)
            sidebar_tooltips = []
            for i, ic in enumerate(sidebar_icons[:15]):
                try:
                    page.mouse.move(ic["x"], ic["y"])
                    page.wait_for_timeout(800)
                    tooltip_text = page.evaluate(r"""
                        () => {
                            const tt = document.querySelector('[class*="tooltip"], [class*="Tooltip"], [role="tooltip"]');
                            if (tt) {
                                const r = tt.getBoundingClientRect();
                                if (r.width > 0 && r.height > 0) {
                                    return (tt.innerText || tt.textContent || '').trim().slice(0, 60);
                                }
                            }
                            return null;
                        }
                    """)
                    if tooltip_text:
                        sidebar_tooltips.append({"x": ic["x"], "y": ic["y"], "tooltip": tooltip_text})
                        logger.info(f"  [{i}] ({ic['x']},{ic['y']}) → '{tooltip_text}'")
                except Exception:
                    continue
            results["sidebar_tooltips"] = sidebar_tooltips
            page.screenshot(path=str(SCR / "missing_sidebar_hover.png"))
        except Exception as e:
            logger.warning(f"사이드바 hover 실패: {e}")

        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"저장: {OUT}")

        # 요약 출력
        home = results.get("home", {})
        logger.info(f"\n=== 홈 ===")
        logger.info(f"좌측 사이드바 요소: {len(home.get('left_sidebar', []))}")
        logger.info(f"module-link 변형: {len(home.get('module_links', []))}")
        logger.info(f"moduleCode 포함: {len(home.get('with_module_code', []))}")

        # 발견된 module-link 코드 unique
        codes_found = set()
        for ml in home.get("module_links", []):
            m = re.search(r"module-link\s+([A-Z]{2,4})", ml["cls"])
            if m:
                codes_found.add(m.group(1))
        for w in home.get("with_module_code", []):
            if w.get("module_hint"):
                codes_found.add(w["module_hint"])
        logger.info(f"발견된 모듈 코드(unique): {sorted(codes_found)}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
