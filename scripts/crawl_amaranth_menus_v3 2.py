"""
아마란스 메뉴 + Export 크롤링 v3 (클릭 기반)
────────────────────────────────────────
v2 발견: LNB가 <a href>가 아닌 React onClick 라우팅 → href 비어있음
v3 전략:
  1) 홈에서 모듈 12개 수집 (span.module-link.{code})
  2) 각 모듈 클릭 → LNB 텍스트 수집 (저장!)
  3) 각 LNB 항목을 텍스트로 클릭 → URL 변화 캡처 + export 버튼 탐지
  4) 결과: data/amaranth_menus_v3.json, docs/AMARANTH_MENUS_v3.md
"""
from __future__ import annotations
import argparse, json, logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright, Page, Frame
from src.shared.auth.login import login_and_get_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("crawl_v3")

GW_USER = "tgjeon"
ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = ROOT / "data" / "amaranth_menus_v3.json"
OUT_MD = ROOT / "docs" / "AMARANTH_MENUS_v3.md"
SCREENSHOT_DIR = ROOT / "data" / "amaranth_screens"

EXPORT_KEYWORDS = [
    "엑셀", "엑셀다운", "엑셀저장", "엑셀출력", "엑셀변환",
    "CSV", "PDF", "다운로드", "내보내기", "Excel", "Export", "Download",
    "출력", "인쇄",
]

JS_HOME_MODULES = r"""
() => {
    const out = [];
    document.querySelectorAll('span.module-link, [class*="module-link"]').forEach(el => {
        const cls = (el.className || '').toString();
        const m = cls.match(/module-link\s+([A-Z]{2,4})/) || cls.match(/\b([A-Z]{2,4})\b/);
        const code = m ? m[1] : null;
        const text = (el.innerText || el.textContent || el.title || '').trim();
        out.push({ code, text, cls });
    });
    // 중복 제거
    const seen = new Set();
    return out.filter(o => {
        if (!o.code || seen.has(o.code)) return false;
        seen.add(o.code); return true;
    });
}
"""

# LNB 항목 수집 — 페이지(or frame) 안에서 보이는 메뉴 텍스트들
# 더존 LNB는 보통 ul > li > span 구조이거나 OBTLeftMenu 컴포넌트
JS_LNB_TEXTS = r"""
() => {
    const out = [];
    const seen = new Set();
    const sels = [
        '[class*="OBTLeftMenu"] li',
        '[class*="LeftMenu"] li',
        '[class*="LNB"] li',
        '[class*="lnb"] li',
        '[class*="TreeMenu"] li',
        '[class*="Tree"] li',
        '[class*="menu"] li',
        '[role="treeitem"]',
        '[role="menuitem"]',
        'aside li',
        'nav li',
    ];
    sels.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) return;
            // 가장 작은 단위 텍스트 노드 우선 (자식 li가 있으면 직접 텍스트만)
            const directText = Array.from(el.childNodes)
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim())
                .filter(Boolean)
                .join(' ');
            const fullText = (el.innerText || el.textContent || '').trim().split('\n')[0];
            const txt = directText || fullText;
            if (!txt || txt.length > 60) return;
            if (seen.has(txt)) return;
            seen.add(txt);
            out.push({
                text: txt,
                cls: (el.className || '').toString().slice(0, 80),
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height),
            });
        });
    });
    return out;
}
"""

JS_BUTTONS = r"""
(keywords) => {
    const out = { title: '', buttons: [], export_candidates: [] };
    const t = document.querySelector('[class*="PageTitle"], [class*="pageTitle"], h1, h2');
    out.title = t ? (t.innerText || '').trim().slice(0, 80) : '';
    const seen = new Set();
    document.querySelectorAll('button, a[role="button"], [class*="Button"], [role="button"]').forEach(el => {
        const txt = (el.innerText || el.textContent || el.title || el.getAttribute('aria-label') || '').trim();
        if (!txt || txt.length > 25) return;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        if (seen.has(txt)) return;
        seen.add(txt);
        const btn = {
            text: txt,
            title: el.title || '',
            aria: el.getAttribute('aria-label') || '',
            cls: (el.className || '').toString().slice(0, 80),
        };
        out.buttons.push(btn);
        for (const kw of keywords) {
            if (txt.includes(kw) || btn.title.includes(kw) || btn.aria.includes(kw)) {
                out.export_candidates.push({ ...btn, matched: kw });
                break;
            }
        }
    });
    return out;
}
"""


def collect_from_all_frames(page: Page, js, *args) -> list:
    """page.main_frame + 모든 iframe에서 JS 실행 결과 누적"""
    out = []
    try:
        r = page.evaluate(js, *args) if args else page.evaluate(js)
        if isinstance(r, list):
            out.extend(r)
        elif isinstance(r, dict):
            out.append({"_where": "main", **r})
    except Exception:
        pass
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        try:
            r = fr.evaluate(js, *args) if args else fr.evaluate(js)
            if isinstance(r, list):
                for it in r:
                    if isinstance(it, dict):
                        it["_frame"] = fr.url[:80]
                out.extend(r)
            elif isinstance(r, dict):
                out.append({"_where": "iframe", "_frame": fr.url[:80], **r})
        except Exception:
            continue
    return out


def click_module(page: Page, code: str) -> bool:
    sel = f"span.module-link.{code}"
    try:
        loc = page.locator(sel).first
        if loc.count() == 0:
            return False
        loc.click(force=True, timeout=3000)
        page.wait_for_timeout(3500)
        return True
    except Exception as e:
        logger.warning(f"  모듈 {code} 클릭 실패: {e}")
        return False


def click_lnb_text(page: Page, text: str) -> bool:
    """LNB 텍스트 매칭 항목 클릭. page + iframe 모두 시도."""
    # main page
    for target in [page.main_frame, *[f for f in page.frames if f != page.main_frame]]:
        try:
            # 정확 일치 우선
            loc = target.locator(f"li:has-text('{text}')").first
            if loc.count() > 0 and loc.is_visible():
                loc.click(force=True, timeout=2500)
                return True
            # 폴백: text=
            loc = target.locator(f"text='{text}'").first
            if loc.count() > 0 and loc.is_visible():
                loc.click(force=True, timeout=2500)
                return True
        except Exception:
            continue
    return False


def get_current_iframe_url(page: Page) -> str:
    """가장 큰 iframe(콘텐츠 영역)의 URL 추정"""
    urls = []
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        if fr.url and "#/" in fr.url:
            urls.append(fr.url)
    # 가장 긴 URL = 가장 깊은 경로일 가능성
    return max(urls, key=len) if urls else page.url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--limit_per_module", type=int, default=25)
    ap.add_argument("--only", type=str, default=None, help="모듈 코드 필터 (쉼표구분)")
    args = ap.parse_args()

    only = set(args.only.split(",")) if args.only else None

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "gw_user": GW_USER,
        "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "home_modules": [],
        "modules": [],  # {code, text, lnb: [{text, url, export_candidates, buttons_count}]}
        "errors": [],
    }

    with sync_playwright() as pw:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=args.headless,
            user_id=GW_USER,
        )
        m = re.match(r"(https://[^/]+)", page.url)
        base = m.group(1) if m else "https://gw.glowseoul.co.kr"

        # 홈 진입 → 모듈 12개 수집
        page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        modules = page.evaluate(JS_HOME_MODULES)
        result["home_modules"] = modules
        logger.info(f"홈 모듈: {len(modules)}개")

        for mod in modules:
            code = mod["code"]
            if only and code not in only:
                continue
            text = mod.get("text") or code
            logger.info(f"\n=== [{code}] {text} ===")

            # 홈으로 복귀 → 모듈 클릭
            page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            if not click_module(page, code):
                result["errors"].append({"phase": "module_click", "code": code})
                continue
            try:
                page.screenshot(path=str(SCREENSHOT_DIR / f"mod_{code}.png"))
            except Exception:
                pass

            # LNB 텍스트 수집 (page + iframe)
            lnb_items = collect_from_all_frames(page, JS_LNB_TEXTS)
            # 텍스트 중복 제거
            dedup = {}
            for it in lnb_items:
                t = it.get("text")
                if not t or t in dedup:
                    continue
                dedup[t] = it
            lnb_unique = list(dedup.values())
            logger.info(f"  LNB 항목: {len(lnb_unique)}")

            module_entry = {"code": code, "text": text, "lnb": []}

            # 각 LNB 항목 클릭 → URL + export 탐지
            for idx, item in enumerate(lnb_unique[: args.limit_per_module]):
                lnb_text = item["text"]
                logger.info(f"  [{idx+1}/{min(len(lnb_unique), args.limit_per_module)}] '{lnb_text}'")
                clicked = click_lnb_text(page, lnb_text)
                if not clicked:
                    module_entry["lnb"].append({
                        "text": lnb_text, "clicked": False, "url": "",
                        "page_title": "", "buttons_count": 0,
                        "export_candidates": [],
                    })
                    continue
                page.wait_for_timeout(2000)
                # URL 추출
                url = get_current_iframe_url(page)
                # 버튼/export 수집
                btn_results = collect_from_all_frames(page, JS_BUTTONS, EXPORT_KEYWORDS)
                # 합치기
                all_buttons = []
                all_exports = []
                title = ""
                seen_btn = set()
                for r in btn_results:
                    if not title and r.get("title"):
                        title = r["title"]
                    for b in r.get("buttons", []):
                        if b["text"] in seen_btn:
                            continue
                        seen_btn.add(b["text"])
                        all_buttons.append(b)
                    all_exports.extend(r.get("export_candidates", []))

                entry = {
                    "text": lnb_text,
                    "clicked": True,
                    "url": url,
                    "page_title": title,
                    "buttons_count": len(all_buttons),
                    "buttons": all_buttons[:30],
                    "export_candidates": all_exports,
                }
                module_entry["lnb"].append(entry)
                if all_exports:
                    names = sorted({e["text"] for e in all_exports})
                    logger.info(f"    ★ EXPORT: {names}")

            result["modules"].append(module_entry)

        context.close()
        browser.close()

    # 저장
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"JSON 저장: {OUT_JSON}")

    # MD
    lines = [f"# 아마란스 메뉴 + Export 재크롤링 (v3, 클릭 기반)", ""]
    lines.append(f"- 계정: `{GW_USER}` / 시각: {result['crawled_at']}")
    lines.append(f"- 홈 모듈: {len(result['home_modules'])}")
    lines.append("")

    has_export_all = []
    for me in result["modules"]:
        for li in me["lnb"]:
            if li.get("export_candidates"):
                has_export_all.append((me["code"], me["text"], li))
    lines.append(f"## ★ Export 가능 메뉴 ({len(has_export_all)}개)")
    lines.append("| 모듈 | 메뉴 | URL | Export 버튼 |")
    lines.append("|---|---|---|---|")
    for code, mod_text, li in has_export_all:
        names = " / ".join(sorted({e["text"] for e in li["export_candidates"]}))
        url = li.get("url", "")
        lines.append(f"| [{code}] {mod_text} | {li['text']} | `{url}` | {names} |")
    lines.append("")

    lines.append("## 모듈별 전체 메뉴")
    for me in result["modules"]:
        lines.append(f"\n### [{me['code']}] {me['text']} ({len(me['lnb'])}개)")
        lines.append("| 메뉴 | URL | 버튼 수 | Export |")
        lines.append("|---|---|---|---|")
        for li in me["lnb"]:
            ex = "✅" if li.get("export_candidates") else ""
            url = li.get("url", "")
            lines.append(f"| {li['text']} | `{url}` | {li.get('buttons_count',0)} | {ex} |")

    OUT_MD.parent.mkdir(exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"MD 저장: {OUT_MD}")

    total_menus = sum(len(me["lnb"]) for me in result["modules"])
    logger.info("=" * 60)
    logger.info(f"모듈: {len(result['modules'])} / 메뉴: {total_menus} / Export: {len(has_export_all)}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
