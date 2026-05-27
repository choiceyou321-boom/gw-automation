"""
비활성 6개 모듈(BD/KS/OF/OC/BPM/UT) 클릭 진단
- 클릭 직전/직후 스크린샷
- 새 탭이 열리는지(context.pages 증가 여부) 확인
- 팝업/모달/에러 메시지 모두 수집
- 모든 frame URL 수집
"""
from __future__ import annotations
import json, logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / "config" / ".env", override=True)
from playwright.sync_api import sync_playwright
from src.shared.auth.login import login_and_get_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("probe")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "inactive_modules_probe.json"
SCR = ROOT / "data" / "amaranth_screens"
SCR.mkdir(parents=True, exist_ok=True)

INACTIVE_CODES = ["BD", "KS", "OF", "OC", "BPM", "UT"]

# alert/modal/error 텍스트 캡처 JS
JS_PROBE_AFTER = r"""
() => {
    const out = {
        url: location.href,
        alert_texts: [],
        modal_texts: [],
        toast_texts: [],
        body_text_sample: '',
        new_overlays: 0,
    };
    // OBTAlert 텍스트
    document.querySelectorAll('[class*="OBTAlert"]').forEach(el => {
        const t = (el.innerText || '').trim();
        if (t && t.length < 200) out.alert_texts.push(t);
    });
    // 모달
    document.querySelectorAll('[role="dialog"], [class*="Modal"], [class*="modal"], [class*="Dialog"]').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0) return;
        const t = (el.innerText || '').trim();
        if (t && t.length < 300) out.modal_texts.push(t);
    });
    // 토스트/스낵바
    document.querySelectorAll('[class*="Toast"], [class*="toast"], [class*="snackbar"], [class*="Snackbar"]').forEach(el => {
        const t = (el.innerText || '').trim();
        if (t) out.toast_texts.push(t);
    });
    // body 텍스트 샘플 (처음 300자)
    out.body_text_sample = (document.body.innerText || '').trim().slice(0, 300);
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

        # 새 탭 자동 감지
        new_pages = []
        context.on("page", lambda p: new_pages.append(p))

        m = re.match(r"(https://[^/]+)", page.url)
        base = m.group(1) if m else "https://gw.glowseoul.co.kr"

        all_results = []
        for code in INACTIVE_CODES:
            logger.info(f"\n=== [{code}] 진단 ===")
            page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            # 클릭 직전 스크린샷
            page.screenshot(path=str(SCR / f"probe_{code}_before.png"))

            pages_before = len(context.pages)
            new_pages.clear()

            try:
                page.locator(f"span.module-link.{code}").first.click(force=True, timeout=4000)
            except Exception as e:
                logger.warning(f"  클릭 실패: {e}")
                all_results.append({"code": code, "click_error": str(e)})
                continue

            page.wait_for_timeout(5000)

            # 클릭 후 상태 캡처
            page.screenshot(path=str(SCR / f"probe_{code}_after.png"))
            try:
                state = page.evaluate(JS_PROBE_AFTER)
            except Exception as e:
                state = {"error": str(e)}

            # 새 탭 정보
            new_tabs = []
            for np in new_pages:
                try:
                    np.wait_for_load_state("domcontentloaded", timeout=5000)
                    np_url = np.url
                    np_title = np.title()
                    np.screenshot(path=str(SCR / f"probe_{code}_newtab.png"))
                    new_tabs.append({"url": np_url, "title": np_title})
                    logger.info(f"  ★ 새 탭: {np_url[:100]}")
                except Exception as e:
                    new_tabs.append({"error": str(e)})

            # 모든 frame URL
            frame_urls = [fr.url for fr in page.frames if fr.url]

            result = {
                "code": code,
                "main_url": page.url,
                "frame_urls": frame_urls,
                "new_tab_count": len(new_pages),
                "new_tabs": new_tabs,
                "alert_texts": state.get("alert_texts", []),
                "modal_texts": state.get("modal_texts", []),
                "toast_texts": state.get("toast_texts", []),
                "body_text_sample": state.get("body_text_sample", "")[:200],
            }
            all_results.append(result)
            logger.info(f"  main_url: {page.url[:80]}")
            logger.info(f"  new_tab: {len(new_pages)}")
            if state.get("alert_texts"):
                logger.info(f"  alerts: {state['alert_texts']}")
            if state.get("modal_texts"):
                logger.info(f"  modals: {[t[:60] for t in state['modal_texts']]}")

            # 새 탭 닫기 (다음 모듈에 영향 없도록)
            for np in list(new_pages):
                try:
                    np.close()
                except Exception:
                    pass

        OUT.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"\n저장: {OUT}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
