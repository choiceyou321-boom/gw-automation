"""
GW 메인 페이지(/#/) 의 실제 DOM 구조를 덤프해서
홈 화면 모듈 아이콘이 어떤 셀렉터로 잡히는지 진단한다.

저장 위치: data/gw_dom_diag.json
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from src.shared.auth.login import login_and_get_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("diag")

OUT = Path(__file__).resolve().parent.parent / "data" / "gw_dom_diag.json"


JS = r"""
() => {
    // 1) 모든 a, button, [role=link], [role=button] 의 visible 요소를 텍스트+위치+href와 함께 수집
    const items = [];
    const all = document.querySelectorAll('a, button, [role="link"], [role="button"], [onclick]');
    all.forEach(el => {
        const txt = (el.innerText || el.textContent || '').trim();
        if (!txt || txt.length > 30) return;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        items.push({
            tag: el.tagName,
            text: txt,
            href: el.getAttribute('href') || '',
            onclick: !!el.onclick || el.hasAttribute('onclick'),
            cls: (el.className || '').toString().slice(0, 100),
            id: el.id || '',
            x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height),
        });
    });

    // 2) onclick 기반으로 SPA 라우팅 호출하는 컨테이너 캡처
    //    더존 GW는 보통 div + onclick="moveMenu(...)" 형식을 쓰기도 함
    const divs = document.querySelectorAll('div, span, li');
    const onclickDivs = [];
    divs.forEach(el => {
        const oc = el.getAttribute('onclick') || '';
        if (!oc) return;
        const txt = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        onclickDivs.push({
            tag: el.tagName,
            text: txt.slice(0, 40),
            onclick: oc.slice(0, 200),
            cls: (el.className || '').toString().slice(0, 100),
            x: Math.round(r.x), y: Math.round(r.y),
        });
    });

    // 3) 모든 iframe 목록
    const iframes = Array.from(document.querySelectorAll('iframe')).map(f => ({
        id: f.id, name: f.name, src: f.src,
    }));

    return {
        url: location.href,
        title: document.title,
        item_count: items.length,
        items: items.slice(0, 200),  // 처음 200개만
        onclick_div_count: onclickDivs.length,
        onclick_divs: onclickDivs.slice(0, 80),
        iframe_count: iframes.length,
        iframes,
        body_class: document.body.className,
        html_outer_size: document.documentElement.outerHTML.length,
    };
}
"""


def main():
    with sync_playwright() as pw:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=False,
            user_id="tgjeon",
        )
        # 홈으로 이동
        import re
        m = re.match(r"(https://[^/]+)", page.url)
        base = m.group(1) if m else "https://gw.glowseoul.co.kr"
        page.goto(f"{base}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)

        result = page.evaluate(JS)
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"DOM 덤프 저장: {OUT}")
        logger.info(f"  - URL: {result['url']}")
        logger.info(f"  - 클릭 가능 요소: {result['item_count']}개")
        logger.info(f"  - onclick div: {result['onclick_div_count']}개")
        logger.info(f"  - iframe: {result['iframe_count']}개")

        # 스크린샷도 함께
        ss = Path(__file__).resolve().parent.parent / "data" / "gw_home_screenshot.png"
        page.screenshot(path=str(ss), full_page=True)
        logger.info(f"  - 스크린샷: {ss}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
