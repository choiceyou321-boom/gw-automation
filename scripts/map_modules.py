"""
홈 모듈 12개 각각을 클릭해서 정확한 진입 URL 매핑 완성
"""
from __future__ import annotations
import json, logging, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / "config" / ".env", override=True)
from playwright.sync_api import sync_playwright
from src.shared.auth.login import login_and_get_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("map")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "module_mapping.json"

HOME_CODES = ["SET", "HR", "EA", "ML", "CL", "RM", "BD", "KS", "OF", "OC", "BPM", "UT"]


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

        results = []
        for code in HOME_CODES:
            page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            try:
                page.locator(f"span.module-link.{code}").first.click(force=True, timeout=4000)
                page.wait_for_timeout(5000)
            except Exception as e:
                logger.warning(f"[{code}] 클릭 실패: {e}")
                results.append({"home_code": code, "error": str(e)})
                continue

            # 모든 frame URL
            frame_urls = []
            for fr in page.frames:
                if fr.url and "#/" in fr.url:
                    frame_urls.append(fr.url)
            deepest = max(frame_urls, key=len) if frame_urls else page.url
            # 내부 모듈 코드 추출
            mm = re.search(r"moduleCode=([A-Z]{2,4})", deepest) or re.search(r"#/([A-Z]{2,4})/", deepest)
            inner = mm.group(1) if mm else None
            menu_match = re.search(r"menuCode=([A-Z0-9_]+)", deepest) or re.search(r"#/[A-Z]{2,4}/([A-Z0-9_]+)/", deepest)
            menu = menu_match.group(1) if menu_match else None
            page_match = re.search(r"pageCode=([A-Z0-9_]+)", deepest) or re.search(r"/[A-Z0-9_]+/([A-Z0-9_]+)$", deepest)
            page_code = page_match.group(1) if page_match else None

            results.append({
                "home_code": code, "url": deepest,
                "inner_module": inner, "menu_code": menu, "page_code": page_code,
            })
            logger.info(f"  [{code:4s}] inner={str(inner):5s} menu={str(menu):10s} page={str(page_code):10s} url={deepest[-80:]}")

        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"저장: {OUT}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
