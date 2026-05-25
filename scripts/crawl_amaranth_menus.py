"""
아마란스(Amaranth10) 전체 메뉴 + export 버튼 재크롤링 스크립트
- 권한이 해금된 후 새로 보이는 메뉴를 모두 탐지한다.
- 홈 12개 모듈 아이콘 → 좌측 메뉴 트리(서브메뉴) → 각 페이지 진입 →
  엑셀/CSV/PDF/다운로드 버튼 유무 + URL + 상단 액션 버튼 목록을 수집한다.
- 결과는 data/amaranth_menus_v2.json 및 docs/AMARANTH_MENUS_v2.md 로 저장.

실행:
    .venv/bin/python scripts/crawl_amaranth_menus.py [--headless] [--limit N]
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

from playwright.sync_api import sync_playwright, Page

from src.shared.auth.login import login_and_get_context

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("crawl_amaranth_menus")

GW_USER_ID = "tgjeon"

# 홈 화면 메인 모듈 아이콘 후보(레이블 기반).
# 권한 해금으로 더 많이 보일 수 있으므로 사전 정의 외에도 동적으로 수집한다.
KNOWN_HOME_MODULES = [
    "마이페이지", "메일", "전자결재", "회의실예약", "근태관리",
    "인사관리", "급여관리", "경비청구", "지출결의/계산서",
    "개인지출결의서", "예산관리", "프로세스갤러리",
    # 권한 해금 후 가능성 있는 메뉴
    "회계관리", "자금관리", "구매관리", "자산관리", "프로젝트관리",
    "고객관리", "영업관리", "총무관리", "전자세금계산서",
]

# export 후보 텍스트 (한국어 + 영문 + 아이콘 title 속성)
EXPORT_KEYWORDS = [
    "엑셀", "엑셀다운", "엑셀저장", "엑셀출력", "엑셀변환",
    "CSV", "PDF", "다운로드", "내보내기", "Excel", "Export", "Download",
    "출력", "인쇄", "프린트", "Print",
]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
OUT_JSON = DATA_DIR / "amaranth_menus_v2.json"
OUT_MD = DOCS_DIR / "AMARANTH_MENUS_v2.md"


def js_collect_home_modules() -> str:
    """홈 화면 모듈 아이콘들을 텍스트+href로 수집하는 JS"""
    return r"""
    () => {
        // 홈 화면의 큰 아이콘들은 보통 a 또는 button 요소에 텍스트 라벨로 표시됨.
        // 여러 후보 셀렉터를 시도한다.
        const candidates = [
            'a[href*="#/"]',
            'button',
            '[role="link"]',
            '[class*="ModuleIcon"] *',
            '[class*="moduleIcon"] *',
            '[class*="HomeModule"] *',
        ];
        const collected = new Map();
        for (const sel of candidates) {
            document.querySelectorAll(sel).forEach(el => {
                const text = (el.innerText || el.textContent || '').trim();
                if (!text || text.length > 20) return;
                const href = el.getAttribute('href') || '';
                // 모듈코드는 보통 영문 2자
                const m = href.match(/#\/([A-Z]{2})\//);
                if (m || text.match(/관리|결재|메일|예약|결의|계산서|페이지|갤러리|청구|급여|인사/)) {
                    const key = text;
                    if (!collected.has(key)) {
                        collected.set(key, {
                            text,
                            href,
                            module: m ? m[1] : null,
                            tag: el.tagName,
                        });
                    }
                }
            });
        }
        return Array.from(collected.values());
    }
    """


def js_collect_left_menu() -> str:
    """현재 페이지의 좌측 메뉴(서브메뉴 트리)를 수집하는 JS"""
    return r"""
    () => {
        // GW의 좌측 메뉴는 보통 <li>, <a> 또는 트리 구조로 표현됨
        const items = [];
        const sels = [
            'aside a',
            '.lnb a',
            '.gnb a',
            '[class*="menu"] a',
            '[class*="Menu"] a',
            '[class*="Tree"] a',
            'nav a',
        ];
        const seen = new Set();
        for (const sel of sels) {
            document.querySelectorAll(sel).forEach(a => {
                const txt = (a.innerText || a.textContent || '').trim();
                const href = a.getAttribute('href') || '';
                if (!txt || txt.length > 50) return;
                if (!href.includes('#/')) return;
                const key = txt + '|' + href;
                if (seen.has(key)) return;
                seen.add(key);
                const m = href.match(/#\/([A-Z]{2})\/([A-Z0-9_]+)\/([A-Z0-9_]+)/);
                items.push({
                    text: txt,
                    href,
                    module: m ? m[1] : null,
                    menu: m ? m[2] : null,
                    page: m ? m[3] : null,
                });
            });
        }
        return items;
    }
    """


def js_collect_buttons_and_export() -> str:
    """현재 활성 컨텐츠 영역의 액션 버튼 + export 버튼 후보 수집"""
    return r"""
    (keywords) => {
        const result = { buttons: [], export_candidates: [], title: '' };
        // 페이지 타이틀 후보
        const titleEl = document.querySelector('[class*="PageTitle"]') ||
                        document.querySelector('[class*="pageTitle"]') ||
                        document.querySelector('h1, h2');
        result.title = titleEl ? (titleEl.innerText || '').trim() : '';

        const all = document.querySelectorAll('button, a[role="button"], [class*="Button"]');
        const seen = new Set();
        all.forEach(el => {
            const txt = (el.innerText || el.textContent || el.title || el.getAttribute('aria-label') || '').trim();
            if (!txt || txt.length > 30) return;
            // 보이지 않는 버튼 제외
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) return;
            const key = txt;
            if (seen.has(key)) return;
            seen.add(key);
            const btn = {
                text: txt,
                title: el.title || '',
                aria: el.getAttribute('aria-label') || '',
                cls: el.className.toString().slice(0, 80),
            };
            result.buttons.push(btn);
            for (const kw of keywords) {
                if (txt.includes(kw) || btn.title.includes(kw) || btn.aria.includes(kw)) {
                    result.export_candidates.push({ ...btn, matched: kw });
                    break;
                }
            }
        });
        return result;
    }
    """


def safe_goto(page: Page, url: str, wait_ms: int = 2500) -> bool:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(wait_ms)
        return True
    except Exception as e:
        logger.warning(f"goto 실패 {url}: {e}")
        return False


def crawl(headless: bool, limit_pages: int) -> dict:
    """전체 메뉴 + export 버튼 크롤링"""
    result = {
        "gw_user": GW_USER_ID,
        "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "home_modules": [],
        "menus": [],  # {module, menu, page, href, title, export_candidates, buttons}
        "errors": [],
    }

    with sync_playwright() as pw:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=headless,
            user_id=GW_USER_ID,
        )

        # 1단계: 홈 진입 + 모듈 아이콘 수집
        gw_url = page.context.pages[0].url
        m = re.match(r"(https://[^/]+)", gw_url)
        base_url = m.group(1) if m else "https://gw.glowseoul.co.kr"
        safe_goto(page, f"{base_url}/#/", wait_ms=4000)

        home_modules = page.evaluate(js_collect_home_modules())
        result["home_modules"] = home_modules
        logger.info(f"홈 모듈 후보 {len(home_modules)}개 수집")
        for hm in home_modules:
            logger.info(f"  • {hm.get('text')} (module={hm.get('module')})")

        # 2단계: 각 모듈 진입 → 좌측 메뉴 트리 수집 → 메뉴별 페이지 진입
        # 모듈 아이콘 href가 있으면 우선 사용. 없으면 알려진 12 + 후보 텍스트로 텍스트 클릭
        visited_modules = set()
        all_menu_items = []

        for hm in home_modules:
            mod_code = hm.get("module")
            href = hm.get("href") or ""
            text = hm.get("text") or ""
            if mod_code and mod_code in visited_modules:
                continue
            if not href or "#/" not in href:
                continue

            target_url = href if href.startswith("http") else f"{base_url}/{href.lstrip('/')}"
            if not safe_goto(page, target_url, wait_ms=3000):
                result["errors"].append({"module": text, "error": "goto_failed", "url": target_url})
                continue

            # 좌측 메뉴 트리 수집
            menu_items = page.evaluate(js_collect_left_menu())
            logger.info(f"[{text}] 좌측 메뉴 {len(menu_items)}개")
            if mod_code:
                visited_modules.add(mod_code)
            for mi in menu_items:
                mi["parent_module_text"] = text
                all_menu_items.append(mi)

        # 3단계: 메뉴별 페이지 순회 → export/버튼 수집
        # 중복 제거
        dedup = {}
        for mi in all_menu_items:
            key = mi.get("href")
            if key and key not in dedup:
                dedup[key] = mi
        unique_menus = list(dedup.values())
        logger.info(f"고유 메뉴 페이지 {len(unique_menus)}개 (limit={limit_pages})")

        for idx, mi in enumerate(unique_menus[:limit_pages]):
            href = mi.get("href") or ""
            full = href if href.startswith("http") else f"{base_url}/{href.lstrip('/')}"
            logger.info(f"[{idx+1}/{min(len(unique_menus), limit_pages)}] {mi.get('text')} → {href}")
            ok = safe_goto(page, full, wait_ms=2500)
            if not ok:
                result["errors"].append({"menu": mi, "error": "goto_failed"})
                continue
            try:
                page_info = page.evaluate(js_collect_buttons_and_export(), EXPORT_KEYWORDS)
            except Exception as e:
                logger.warning(f"  버튼 수집 실패: {e}")
                page_info = {"buttons": [], "export_candidates": [], "title": ""}

            entry = {
                "module": mi.get("module"),
                "menu_code": mi.get("menu"),
                "page_code": mi.get("page"),
                "label": mi.get("text"),
                "url": href,
                "page_title": page_info.get("title", ""),
                "parent_module_text": mi.get("parent_module_text"),
                "buttons_count": len(page_info.get("buttons", [])),
                "buttons": page_info.get("buttons", [])[:30],
                "export_candidates": page_info.get("export_candidates", []),
            }
            result["menus"].append(entry)
            if entry["export_candidates"]:
                names = [e["text"] for e in entry["export_candidates"]]
                logger.info(f"  ★ EXPORT 발견: {names}")

        context.close()
        browser.close()

    return result


def write_outputs(result: dict):
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"JSON 저장: {OUT_JSON}")

    # Markdown 요약
    lines = []
    lines.append(f"# 아마란스 메뉴 + Export 버튼 재크롤링 결과")
    lines.append("")
    lines.append(f"- 계정: `{result['gw_user']}`")
    lines.append(f"- 크롤링 시각: {result['crawled_at']}")
    lines.append(f"- 홈 모듈 후보: {len(result['home_modules'])}개")
    lines.append(f"- 탐색한 메뉴 페이지: {len(result['menus'])}개")
    err = len(result.get("errors", []))
    if err:
        lines.append(f"- 오류: {err}건")
    lines.append("")

    # Export 가능 메뉴
    has_export = [m for m in result["menus"] if m["export_candidates"]]
    lines.append(f"## ★ Export 가능 메뉴 ({len(has_export)}개)")
    lines.append("")
    lines.append("| 모듈 | 메뉴코드 | 페이지 | 라벨 | Export 버튼 |")
    lines.append("|---|---|---|---|---|")
    for m in has_export:
        names = " / ".join(sorted({e["text"] for e in m["export_candidates"]}))
        lines.append(f"| {m['module']} | {m['menu_code']} | {m['page_code']} | {m['label']} | {names} |")
    lines.append("")

    # 모듈별 전체 메뉴
    lines.append("## 모듈별 전체 메뉴")
    by_mod: dict[str, list] = {}
    for m in result["menus"]:
        by_mod.setdefault(m.get("module") or "?", []).append(m)
    for mod, items in sorted(by_mod.items()):
        lines.append(f"\n### [{mod}] {items[0].get('parent_module_text','')}")
        lines.append("")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true", help="브라우저 숨김 (기본: headed)")
    ap.add_argument("--limit", type=int, default=200, help="탐색할 최대 메뉴 페이지 수")
    args = ap.parse_args()

    result = crawl(headless=args.headless, limit_pages=args.limit)
    write_outputs(result)

    has_export = sum(1 for m in result["menus"] if m["export_candidates"])
    logger.info("=" * 60)
    logger.info(f"총 메뉴: {len(result['menus'])} / Export 가능: {has_export}")
    logger.info(f"결과: {OUT_JSON}")
    logger.info(f"요약: {OUT_MD}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
