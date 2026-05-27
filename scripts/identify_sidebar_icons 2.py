"""
좌측 세로 사이드바 아이콘을 하나씩 클릭해서 어떤 모듈로 진입하는지 식별
- tooltip은 검색 inputs와 충돌해 오인되므로 클릭 후 URL 변화로 판정
"""
from __future__ import annotations
import json, logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / "config" / ".env", override=True)
from playwright.sync_api import sync_playwright, Page
from src.shared.auth.login import login_and_get_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sidebar")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sidebar_modules.json"
SCR = ROOT / "data" / "amaranth_screens"


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

        page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4500)

        # 좌측 세로 사이드바 영역의 정확한 클릭 가능 요소 좌표 수집
        # 더 좁은 영역 (x<50, h<60, y>40)
        icons = page.evaluate(r"""
            () => {
                const out = [];
                const seen = new Set();
                document.querySelectorAll('a, button, [role="button"], li, span, div').forEach(el => {
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return;
                    if (r.x > 50 || r.y < 40 || r.y > 900) return;
                    if (r.width > 50 || r.height > 50) return;
                    if (r.width < 20 || r.height < 20) return;
                    const cx = Math.round(r.x + r.width/2);
                    const cy = Math.round(r.y + r.height/2);
                    const key = cx + ',' + cy;
                    if (seen.has(key)) return;
                    seen.add(key);
                    out.push({
                        tag: el.tagName, cx, cy,
                        cls: (el.className || '').toString().slice(0, 100),
                        title: (el.title || '').slice(0, 40),
                    });
                });
                return out;
            }
        """)
        logger.info(f"사이드바 아이콘 좌표: {len(icons)}개")
        for i, ic in enumerate(icons):
            logger.info(f"  [{i}] ({ic['cx']},{ic['cy']}) [{ic['tag']}] cls={ic['cls'][:50]}")

        # 각 아이콘 클릭 후 URL 변화 캡처
        results = []
        for i, ic in enumerate(icons):
            # 홈으로 복귀
            page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2500)
            url_before = page.url
            try:
                page.mouse.click(ic["cx"], ic["cy"])
                page.wait_for_timeout(2500)
                url_after = page.url
                # 모든 frame URL도 수집
                frame_urls = [fr.url for fr in page.frames if fr.url and "#/" in fr.url]
                deepest = max(frame_urls, key=len) if frame_urls else url_after
                results.append({
                    "index": i, "cx": ic["cx"], "cy": ic["cy"],
                    "cls": ic["cls"], "url_before": url_before,
                    "url_after": url_after, "deepest_frame": deepest,
                })
                logger.info(f"  [{i}] ({ic['cx']},{ic['cy']}) → {deepest[-100:]}")
            except Exception as e:
                logger.warning(f"  [{i}] 클릭 실패: {e}")

        OUT.write_text(json.dumps({"icons": icons, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"저장: {OUT}")

        # 모듈 코드 추출
        codes = set()
        for r in results:
            m = re.search(r"(?:moduleCode=|#/)([A-Z]{2,4})/", r["deepest_frame"])
            if m:
                codes.add(m.group(1))
        logger.info(f"\n사이드바에서 발견된 모듈 코드: {sorted(codes)}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
