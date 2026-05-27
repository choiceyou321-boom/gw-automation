"""
GW 모듈 진입 후 좌측 메뉴(LNB) DOM 구조를 덤프한다.
- 알려진 모듈 URL 8종(HP/BN/UD/UK/UB/UA/UE/UF...)에 순차 진입
- 각 진입 후 가시 텍스트 노드 중 메뉴로 보이는 것들 + 클릭 가능한 li/a/div 수집
- 모듈코드/메뉴코드/페이지코드 패턴(href 안의 #/AA/BBB/CCC) 추출

저장: data/gw_lnb_diag.json
"""
from __future__ import annotations
import json, logging, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from src.shared.auth.login import login_and_get_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("lnb")

OUT = Path(__file__).resolve().parent.parent / "data" / "gw_lnb_diag.json"

# 알려진 모듈 진입 URL 후보 (모듈코드 + 첫 페이지로 추정되는 코드 조합)
ENTRY_URLS = [
    ("HP", "/#/HP/HPD0110/HPD0110"),   # 근태신청
    ("BN", "/#/BN/NCF0090/SYB0060"),   # 예산관리/프로젝트등록
    ("UD", "/#/UD/UDA/UDA0000"),       # 메일
    ("UK", "/#/UK/UKA/UKA0000"),       # 자원예약
    ("UB", "/#/UB/UBA/UBA0010"),       # 전자결재(추정)
    ("AC", "/#/AC/ACA/ACA0010"),       # 회계(추정)
    ("PR", "/#/PR/PRA/PRA0010"),       # 구매(추정)
    ("HR", "/#/HR/HRA/HRA0010"),       # 인사관리(추정)
]

JS = r"""
() => {
    const hrefs = new Set();
    const links = [];
    const divs = [];
    // 모든 a[href*='#/'] 수집
    document.querySelectorAll('a').forEach(a => {
        const href = a.getAttribute('href') || '';
        const txt = (a.innerText || '').trim();
        if (!href.includes('#/')) return;
        const r = a.getBoundingClientRect();
        const visible = r.width > 0 && r.height > 0;
        const m = href.match(/#\/([A-Z]{2,4})\/([A-Z0-9_]+)\/([A-Z0-9_]+)/);
        links.push({
            text: txt.slice(0, 60),
            href, visible,
            x: Math.round(r.x), y: Math.round(r.y),
            module: m ? m[1] : null, menu: m ? m[2] : null, page: m ? m[3] : null,
            cls: (a.className || '').toString().slice(0, 100),
        });
    });
    // li / div / span 중 onclick 또는 data-menucode 같은 속성 있는 것
    document.querySelectorAll('li, div, span').forEach(el => {
        const oc = el.getAttribute('onclick');
        const dc = el.getAttribute('data-menucode') || el.getAttribute('data-menuid') || el.getAttribute('data-id');
        if (!oc && !dc) return;
        const txt = (el.innerText || '').trim();
        if (!txt || txt.length > 40) return;
        const r = el.getBoundingClientRect();
        if (r.width === 0) return;
        divs.push({
            tag: el.tagName,
            text: txt.slice(0, 60),
            onclick: oc ? oc.slice(0, 150) : null,
            data: dc || null,
            cls: (el.className || '').toString().slice(0, 100),
            x: Math.round(r.x), y: Math.round(r.y),
        });
    });
    // 전역 변수 후보
    const globals = {};
    ['menuList', 'MENU_DATA', 'menuTree', 'gwMenu', 'userMenu', '__MENUS__', 'mainStore'].forEach(k => {
        try { if (window[k]) globals[k] = typeof window[k]; } catch(e){}
    });
    return {
        url: location.href,
        title: document.title,
        link_count: links.length,
        links: links,
        div_count: divs.length,
        divs: divs,
        globals,
    };
}
"""


def main():
    import time
    result = {"entries": []}
    with sync_playwright() as pw:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=False,
            user_id="tgjeon",
        )
        m = re.match(r"(https://[^/]+)", page.url)
        base = m.group(1) if m else "https://gw.glowseoul.co.kr"

        for mod_code, path in ENTRY_URLS:
            url = base + path
            logger.info(f"[{mod_code}] {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3500)
            except Exception as e:
                logger.warning(f"  goto 실패: {e}")
                continue
            try:
                info = page.evaluate(JS)
            except Exception as e:
                logger.warning(f"  evaluate 실패: {e}")
                continue
            # 모듈코드별 통계
            mods = {}
            for lk in info["links"]:
                k = lk.get("module") or "?"
                mods[k] = mods.get(k, 0) + 1
            logger.info(f"  → 링크 {info['link_count']}개, onclick-div {info['div_count']}개, 모듈코드 분포: {mods}")
            info["entry_module"] = mod_code
            info["entry_url"] = url
            # 스크린샷
            ss = Path(__file__).resolve().parent.parent / "data" / f"gw_lnb_{mod_code}.png"
            try:
                page.screenshot(path=str(ss))
            except Exception:
                pass
            result["entries"].append(info)

        context.close()
        browser.close()

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"저장: {OUT}")


if __name__ == "__main__":
    main()
