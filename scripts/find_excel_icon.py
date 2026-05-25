"""
RM(자원) 페이지에서 엑셀 다운로드 아이콘 정확히 찾기
- main_frame 우선 dump (이전엔 iframe만 봐서 놓침)
- x>1500, y<300 영역의 모든 작은 클릭 가능 요소 수집
- 좌표 기반 다운로드 시도 (스크린샷 좌표 추정: 1855, 120 근처)
"""
from __future__ import annotations
import json, logging, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / "config" / ".env", override=True)
from playwright.sync_api import sync_playwright, Page, Download, TimeoutError as PWTimeout
from src.shared.auth.login import login_and_get_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("find_excel")

ROOT = Path(__file__).resolve().parent.parent
DL_DIR = ROOT / "data" / "amaranth_exports"
SCR_DIR = ROOT / "data" / "amaranth_screens"
DL_DIR.mkdir(parents=True, exist_ok=True)

# 넓은 영역 dump JS
JS_WIDE_DUMP = r"""
() => {
    const out = { url: location.href, candidates: [] };
    // 더 넓은 영역: x > 1400, y < 350 (검색창 옆 영역 모두 포함)
    document.querySelectorAll('*').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        if (r.width > 60 || r.height > 60) return;  // 아이콘 크기
        if (r.x < 1400 || r.x > 1920) return;
        if (r.y < 50 || r.y > 350) return;
        const title = el.title || '';
        const aria = el.getAttribute('aria-label') || '';
        const alt = el.getAttribute('alt') || '';
        const cls = (el.className || '').toString();
        const src = el.getAttribute('src') || '';
        // 정보가 있는 요소만
        if (!title && !aria && !alt && !cls.match(/[Ee]xcel|excel|button|Button|btn|icon|Icon|export/) && !src) return;
        out.candidates.push({
            tag: el.tagName,
            title: title.slice(0, 80),
            aria: aria.slice(0, 80),
            alt: alt.slice(0, 80),
            cls: cls.slice(0, 200),
            src: src.slice(0, 200),
            text: (el.innerText || '').trim().slice(0, 40),
            x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height),
            cx: Math.round(r.x + r.width/2),
            cy: Math.round(r.y + r.height/2),
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
        page.wait_for_timeout(6000)
        logger.info("RM 진입")

        # 모든 frame dump
        all_dumps = []
        frames_list = [page.main_frame] + [f for f in page.frames if f != page.main_frame]
        for i, fr in enumerate(frames_list):
            try:
                r = fr.evaluate(JS_WIDE_DUMP)
                r["_frame_index"] = i
                r["_frame_url"] = fr.url[:100]
                if r["candidates"]:
                    all_dumps.append(r)
            except Exception as e:
                logger.warning(f"frame {i} 실패: {e}")

        # 출력
        for d in all_dumps:
            logger.info(f"\n=== frame #{d['_frame_index']}: {d['_frame_url'][:60]} ===")
            for c in d["candidates"]:
                marker = "★" if (
                    "엑셀" in c["title"] or "엑셀" in c["aria"] or
                    "excel" in c["cls"].lower() or "Excel" in c["src"]
                ) else " "
                logger.info(
                    f" {marker}[{c['tag']:6s}] x={c['x']:4d} y={c['y']:4d} cx={c['cx']:4d} cy={c['cy']:4d} "
                    f"title='{c['title'][:25]}' alt='{c['alt'][:15]}' src='{c['src'][-30:]}' cls='{c['cls'][:60]}'"
                )

        OUT = ROOT / "data" / "rm_icons.json"
        OUT.write_text(json.dumps(all_dumps, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"저장: {OUT}")

        # 엑셀 후보 추출
        excel_candidates = []
        for d in all_dumps:
            for c in d["candidates"]:
                t = c["title"].lower() + c["aria"].lower() + c["alt"].lower() + c["cls"].lower() + c["src"].lower()
                if "엑셀" in c["title"] or "excel" in t or "다운로드" in c["title"]:
                    excel_candidates.append(c)

        logger.info(f"\n★ 엑셀 후보 {len(excel_candidates)}개")
        if not excel_candidates:
            logger.warning("엑셀 후보를 찾지 못함 — 좌표 기반 시도로 폴백")
            # 스크린샷 추정 좌표 (검색창 우측 끝 약간 안쪽)
            fallback_coords = [(1855, 120), (1830, 120), (1880, 120), (1855, 150)]
            for cx, cy in fallback_coords:
                logger.info(f"  좌표 클릭 시도: ({cx}, {cy})")
                try:
                    with page.expect_download(timeout=8000) as dl_info:
                        page.mouse.click(cx, cy)
                    dl = dl_info.value
                    path = DL_DIR / f"rm_resource_{cx}_{cy}{Path(dl.suggested_filename).suffix or '.xlsx'}"
                    dl.save_as(str(path))
                    logger.info(f"  ★★★ 다운로드 성공: {path.name} ({path.stat().st_size}B)")
                    break
                except PWTimeout:
                    logger.info(f"    타임아웃 — 다음 좌표")
                except Exception as e:
                    logger.warning(f"    실패: {e}")
        else:
            # 후보별로 클릭 시도
            for c in excel_candidates:
                logger.info(f"  엑셀 후보 클릭: ({c['cx']}, {c['cy']}) title='{c['title']}'")
                try:
                    with page.expect_download(timeout=10000) as dl_info:
                        page.mouse.click(c["cx"], c["cy"])
                    dl = dl_info.value
                    path = DL_DIR / f"rm_resource{Path(dl.suggested_filename).suffix or '.xlsx'}"
                    dl.save_as(str(path))
                    logger.info(f"  ★★★ 다운로드 성공: {path.name} ({path.stat().st_size}B)")
                    break
                except PWTimeout:
                    logger.info(f"    타임아웃")
                except Exception as e:
                    logger.warning(f"    실패: {e}")

        # 최종 스크린샷
        page.screenshot(path=str(SCR_DIR / "find_excel_final.png"))

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
