"""
아마란스(Amaranth10) 메뉴 + Export 재크롤링 v2
─────────────────────────────────────────────
- 홈 화면의 `span.module-link` 요소(=모듈 아이콘) 전체 수집
- 각 모듈 클릭 → 모듈 진입 후 좌측 메뉴(LNB) 탐색
- 메뉴는 iframe 안에 있을 수 있으므로 page.frames 순회
- 각 메뉴 페이지에서 export 버튼(엑셀/CSV/PDF/다운로드) 탐지
- 결과: data/amaranth_menus_v2.json, docs/AMARANTH_MENUS_v2.md

실행: .venv/bin/python scripts/crawl_amaranth_menus_v2.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright, Page, Frame
from src.shared.auth.login import login_and_get_context

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("crawl_v2")

GW_USER = "tgjeon"
ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = ROOT / "data" / "amaranth_menus_v2.json"
OUT_MD = ROOT / "docs" / "AMARANTH_MENUS_v2.md"
SCREENSHOT_DIR = ROOT / "data" / "amaranth_screens"

EXPORT_KEYWORDS = [
    "엑셀", "엑셀다운", "엑셀저장", "엑셀출력", "엑셀변환",
    "CSV", "PDF", "다운로드", "내보내기", "Excel", "Export", "Download",
    "출력", "인쇄",
]

# 홈 화면 모듈 아이콘 수집 JS
JS_HOME_MODULES = r"""
() => {
    const out = [];
    document.querySelectorAll('span.module-link, [class*="module-link"]').forEach(el => {
        const cls = (el.className || '').toString();
        const m = cls.match(/module-link\s+([A-Z]{2,4})/) || cls.match(/\b([A-Z]{2,4})\b/);
        const code = m ? m[1] : null;
        const text = (el.innerText || el.textContent || el.title || '').trim();
        const r = el.getBoundingClientRect();
        out.push({ code, text, cls, x: Math.round(r.x), y: Math.round(r.y) });
    });
    return out;
}
"""

# 모듈 진입 후 LNB(좌측 메뉴) 수집 JS - main page + iframe 모두 적용 가능
JS_LNB = r"""
() => {
    const items = [];
    // 후보 셀렉터: LNB / TreeMenu / LeftMenu 류
    const sels = [
        '[class*="LNB"] a', '[class*="lnb"] a',
        '[class*="LeftMenu"] a', '[class*="leftMenu"] a',
        '[class*="TreeMenu"] a', '[class*="treeMenu"] a',
        '[class*="Menu"] li', '[class*="menu"] li',
        '[class*="Tree"] li', 'aside li', 'nav li',
        '[role="treeitem"]', '[role="menuitem"]',
    ];
    const seen = new Set();
    sels.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => {
            const txt = (el.innerText || el.textContent || '').trim().split('\n')[0];
            if (!txt || txt.length > 60) return;
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) return;
            const href = el.getAttribute('href') || el.querySelector('a')?.getAttribute('href') || '';
            const key = txt + '|' + href;
            if (seen.has(key)) return;
            seen.add(key);
            const m = href.match(/#\/([A-Z]{2,4})\/([A-Z0-9_]+)\/([A-Z0-9_]+)/);
            items.push({
                text: txt, href,
                module: m ? m[1] : null, menu: m ? m[2] : null, page: m ? m[3] : null,
                cls: (el.className || '').toString().slice(0, 80),
                x: Math.round(r.x), y: Math.round(r.y),
            });
        });
    });
    return { url: location.href, count: items.length, items };
}
"""

# 페이지 진입 후 export 버튼 + 액션 버튼 수집 JS
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


def collect_lnb_all_frames(page: Page) -> list:
    """page + iframe 모두에서 LNB 수집 (병합)"""
    all_items = []
    # main
    try:
        r = page.evaluate(JS_LNB)
        for it in r.get("items", []):
            it["frame_url"] = r["url"]
            it["where"] = "main"
            all_items.append(it)
    except Exception as e:
        logger.warning(f"main LNB 수집 실패: {e}")
    # iframes
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        try:
            r = fr.evaluate(JS_LNB)
            for it in r.get("items", []):
                it["frame_url"] = r["url"]
                it["where"] = "iframe"
                all_items.append(it)
        except Exception:
            continue
    return all_items


def collect_buttons_all_frames(page: Page) -> dict:
    """page + iframe 모두에서 export/버튼 수집"""
    merged = {"title": "", "buttons": [], "export_candidates": []}
    seen = set()
    try:
        r = page.evaluate(JS_BUTTONS, EXPORT_KEYWORDS)
        merged["title"] = r.get("title") or merged["title"]
        for b in r.get("buttons", []):
            if b["text"] in seen:
                continue
            seen.add(b["text"])
            merged["buttons"].append(b)
        merged["export_candidates"].extend(r.get("export_candidates", []))
    except Exception:
        pass
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        try:
            r = fr.evaluate(JS_BUTTONS, EXPORT_KEYWORDS)
            if not merged["title"]:
                merged["title"] = r.get("title") or ""
            for b in r.get("buttons", []):
                if b["text"] in seen:
                    continue
                seen.add(b["text"])
                merged["buttons"].append(b)
            merged["export_candidates"].extend(r.get("export_candidates", []))
        except Exception:
            continue
    return merged


def click_module_icon(page: Page, code: str) -> bool:
    """span.module-link.{code} 아이콘 클릭"""
    sel = f"span.module-link.{code}"
    try:
        loc = page.locator(sel).first
        if loc.count() == 0:
            return False
        loc.click(force=True, timeout=3000)
        page.wait_for_timeout(3000)
        return True
    except Exception as e:
        logger.warning(f"  모듈 {code} 클릭 실패: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "gw_user": GW_USER,
        "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "home_modules": [],
        "menus": [],
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

        # 홈 진입
        page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)

        # 모듈 아이콘 수집
        modules = page.evaluate(JS_HOME_MODULES)
        # 중복 제거 (코드 기준)
        seen_codes = set()
        unique_modules = []
        for mod in modules:
            code = mod.get("code")
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            unique_modules.append(mod)
        result["home_modules"] = unique_modules
        logger.info(f"홈 모듈 아이콘: {len(modules)}개 → 고유 코드 {len(unique_modules)}개")
        for mod in unique_modules:
            logger.info(f"  • [{mod['code']}] {mod['text']}")

        # 홈 스크린샷
        try:
            page.screenshot(path=str(SCREENSHOT_DIR / "00_home.png"))
        except Exception:
            pass

        # 각 모듈 진입 → LNB 수집
        all_lnb_items = []
        for mod in unique_modules:
            code = mod["code"]
            text = mod.get("text") or code
            logger.info(f"\n=== 모듈 [{code}] {text} ===")
            # 홈으로 복귀 후 모듈 클릭
            page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            ok = click_module_icon(page, code)
            if not ok:
                result["errors"].append({"phase": "module_click", "module": code, "text": text})
                continue
            # 진입 후 LNB 수집
            lnb_items = collect_lnb_all_frames(page)
            logger.info(f"  LNB {len(lnb_items)}개")
            try:
                page.screenshot(path=str(SCREENSHOT_DIR / f"01_mod_{code}.png"))
            except Exception:
                pass
            for it in lnb_items:
                it["parent_module"] = code
                it["parent_module_text"] = text
                all_lnb_items.append(it)

        # 메뉴 중복 제거 (href + text)
        dedup = {}
        for it in all_lnb_items:
            key = (it.get("href") or "") + "|" + (it.get("text") or "")
            if key not in dedup:
                dedup[key] = it
        unique_menus = list(dedup.values())
        # href 없는 메뉴는 클릭 기반이라 지금은 스킵하지 않고 그대로 보존
        with_href = [m for m in unique_menus if m.get("href")]
        logger.info(f"\n고유 메뉴 페이지: {len(unique_menus)} (href 보유: {len(with_href)})")

        # 각 메뉴 페이지 진입 → export 탐지
        for idx, mi in enumerate(with_href[: args.limit]):
            href = mi["href"]
            full = href if href.startswith("http") else f"{base}/{href.lstrip('/')}"
            label = mi.get("text") or "?"
            logger.info(f"[{idx+1}/{min(len(with_href), args.limit)}] {label} → {href}")
            try:
                page.goto(full, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
            except Exception as e:
                logger.warning(f"  goto 실패: {e}")
                result["errors"].append({"phase": "menu_goto", "menu": mi, "error": str(e)})
                continue
            info = collect_buttons_all_frames(page)
            entry = {
                "module": mi.get("module") or mi.get("parent_module"),
                "menu_code": mi.get("menu"),
                "page_code": mi.get("page"),
                "label": label,
                "url": href,
                "parent_module": mi.get("parent_module"),
                "parent_module_text": mi.get("parent_module_text"),
                "page_title": info.get("title", ""),
                "buttons_count": len(info.get("buttons", [])),
                "buttons": info.get("buttons", [])[:30],
                "export_candidates": info.get("export_candidates", []),
            }
            result["menus"].append(entry)
            if entry["export_candidates"]:
                names = sorted({e["text"] for e in entry["export_candidates"]})
                logger.info(f"  ★ EXPORT: {names}")

        context.close()
        browser.close()

    # 저장
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"JSON 저장: {OUT_JSON}")

    # Markdown 요약
    lines = [f"# 아마란스 메뉴 + Export 재크롤링 결과 (v2)", ""]
    lines.append(f"- 계정: `{result['gw_user']}`")
    lines.append(f"- 크롤링 시각: {result['crawled_at']}")
    lines.append(f"- 홈 모듈: {len(result['home_modules'])}개")
    lines.append(f"- 탐색 메뉴: {len(result['menus'])}개")
    if result["errors"]:
        lines.append(f"- 오류: {len(result['errors'])}건")
    lines.append("")

    lines.append("## 홈 모듈 아이콘")
    lines.append("| 코드 | 텍스트 |")
    lines.append("|---|---|")
    for mod in result["home_modules"]:
        lines.append(f"| {mod['code']} | {mod['text']} |")
    lines.append("")

    has_export = [m for m in result["menus"] if m["export_candidates"]]
    lines.append(f"## ★ Export 가능 메뉴 ({len(has_export)}개)")
    lines.append("| 모듈 | 메뉴코드 | 페이지 | 라벨 | Export 버튼 |")
    lines.append("|---|---|---|---|---|")
    for m in has_export:
        names = " / ".join(sorted({e["text"] for e in m["export_candidates"]}))
        lines.append(f"| {m.get('module') or m.get('parent_module')} | {m['menu_code']} | {m['page_code']} | {m['label']} | {names} |")
    lines.append("")

    lines.append("## 모듈별 전체 메뉴")
    by_mod = {}
    for m in result["menus"]:
        by_mod.setdefault(m.get("parent_module") or "?", []).append(m)
    for mod, items in sorted(by_mod.items()):
        lines.append(f"\n### [{mod}] {items[0].get('parent_module_text','')}")
        lines.append("| 메뉴코드 | 페이지 | 라벨 | URL | 버튼 수 | Export |")
        lines.append("|---|---|---|---|---|---|")
        for m in items:
            ex = "✅" if m["export_candidates"] else ""
            lines.append(
                f"| {m['menu_code']} | {m['page_code']} | {m['label']} | "
                f"`{m['url']}` | {m['buttons_count']} | {ex} |"
            )

    OUT_MD.parent.mkdir(exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Markdown 저장: {OUT_MD}")

    has_export_n = len(has_export)
    logger.info("=" * 60)
    logger.info(f"홈 모듈: {len(result['home_modules'])} / 메뉴: {len(result['menus'])} / Export: {has_export_n}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
