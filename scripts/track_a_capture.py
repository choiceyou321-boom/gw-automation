"""
GW Track A 셀렉터 캡처 헬퍼.

사용 방법:
    .venv/bin/python scripts/track_a_capture.py

흐름:
    1. Chromium(headed)으로 GW 로그인 → 사용자가 직접 페이지 탐색
    2. 사용자가 각 페이지에서 "조회 클릭 전/후/엑셀 클릭 후 모달" 시점에
       콘솔의 Enter 입력으로 캡처 트리거
    3. 각 시점의 DOM(버튼·모달)을 자동 분석해
       data/track_a_captures.json에 누적 저장
    4. 종료 시 selectors.py에 자동 머지할 수 있는 형식으로 출력

자세한 절차는 docs/GW_TRACK_A_PLAYBOOK.md 참고.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "config" / ".env", override=True)

from playwright.sync_api import sync_playwright, Page

from src.shared.auth.login import login_and_get_context

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("track_a_capture")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "track_a_captures.json"


JS_DETECT_BUTTONS = r"""
() => {
    /**
     * 화면에 보이는 모든 클릭 가능한 버튼/링크의 셀렉터 후보 추출.
     * 우선순위:
     *  1) text 일치 (button:has-text('조회'))
     *  2) title 속성
     *  3) class 조합
     *  4) 좌표
     */
    const items = [];
    document.querySelectorAll('button, a[role="button"], [class*="OBTButton"]').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        const text = (el.innerText || el.textContent || '').trim();
        if (text.length > 30) return;
        const cls = (el.className || '').toString();
        const id = el.id || '';
        const title = el.title || '';
        const aria = el.getAttribute('aria-label') || '';
        const selectors = [];
        if (text) selectors.push(`button:has-text('${text}')`);
        if (id) selectors.push(`#${CSS.escape(id)}`);
        if (title) selectors.push(`[title='${title.replace(/'/g, "\\'")}']`);
        if (aria) selectors.push(`[aria-label='${aria.replace(/'/g, "\\'")}']`);
        // OBT 클래스 패턴
        const obtCls = cls.match(/OBTButton_(?:typedefault|typeicon|typeprimary)[^\s]*/);
        if (obtCls) selectors.push(`button.${obtCls[0].split(' ')[0].replace(/__/g, '__')}`);
        items.push({
            text,
            title,
            aria,
            id,
            cls: cls.slice(0, 100),
            selectors,
            x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height),
        });
    });
    return items;
}
"""


JS_DETECT_MODAL = r"""
() => {
    /**
     * 화면에 표시 중인 모달/다이얼로그 + 버튼들 캡처.
     */
    const modals = [];
    document.querySelectorAll('[role="dialog"], [class*="OBTDialog"], [class*="Modal"], [class*="modal"]').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        const cls = (el.className || '').toString();
        // 내부 버튼 텍스트
        const buttons = [];
        el.querySelectorAll('button').forEach(b => {
            const bt = (b.innerText || '').trim();
            const br = b.getBoundingClientRect();
            if (bt && br.width > 0) buttons.push(bt);
        });
        // 모달 텍스트 일부
        const innerText = (el.innerText || '').trim().slice(0, 200);
        modals.push({
            cls: cls.slice(0, 120),
            x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height),
            buttons,
            text_sample: innerText,
        });
    });
    return modals;
}
"""


def collect_buttons(page: Page) -> list[dict]:
    out = []
    for fr in [page.main_frame] + [f for f in page.frames if f != page.main_frame]:
        try:
            r = fr.evaluate(JS_DETECT_BUTTONS)
            if isinstance(r, list):
                out.extend(r)
        except Exception:
            continue
    return out


def collect_modals(page: Page) -> list[dict]:
    out = []
    for fr in [page.main_frame] + [f for f in page.frames if f != page.main_frame]:
        try:
            r = fr.evaluate(JS_DETECT_MODAL)
            if isinstance(r, list):
                out.extend(r)
        except Exception:
            continue
    return out


def pick_inquiry_selectors(buttons: list[dict]) -> list[str]:
    """버튼 목록에서 '조회'/'검색'으로 보이는 후보의 셀렉터만 추출."""
    candidates = []
    for b in buttons:
        if b["text"] in ("조회", "검색", "Search", "조회하기"):
            for sel in b.get("selectors", []):
                if sel not in candidates:
                    candidates.append(sel)
    return candidates


def current_url(page: Page) -> str:
    candidates = [fr.url for fr in page.frames if fr.url and "#/" in fr.url]
    return max(candidates, key=len) if candidates else page.url


def prompt(message: str) -> str:
    """blocking input — 사용자 시연 흐름 제어."""
    try:
        return input(f"\n[track_a] {message}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def load_existing() -> dict:
    if OUT.exists():
        try:
            return json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(captures: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(captures, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("저장: %s (%d 페이지)", OUT, len(captures))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="tgjeon")
    ap.add_argument("--headless", action="store_true", help="(테스트 용) 비대화 모드")
    args = ap.parse_args()

    captures = load_existing()
    logger.info("기존 캡처: %d 페이지", len(captures))
    logger.info("결과는 자동으로 %s 에 저장됨 (이어쓰기)", OUT)

    with sync_playwright() as pw:
        browser, context, page = login_and_get_context(
            playwright_instance=pw, headless=args.headless, user_id=args.user,
        )
        try:
            page.set_viewport_size({"width": 1920, "height": 1080})
        except Exception:
            pass

        if args.headless:
            logger.info("headless 모드 — 대화 없이 종료(헬스 체크)")
            context.close()
            browser.close()
            return

        print("\n" + "=" * 70)
        print("✋  GW가 열렸습니다. 이제 페이지를 탐색하며 다음 절차를 반복하세요.")
        print("=" * 70)

        while True:
            print("\n────────────────────────────────────────")
            label = prompt(
                "캡처할 페이지 라벨 입력 (예: 예실대비현황_상세 / 'q'=종료)"
            )
            if not label or label.lower() in ("q", "quit", "exit"):
                break

            current = captures.get(label, {})
            current["url_path"] = current_url(page).split(".co.kr", 1)[-1]
            current["captured_at"] = datetime.now(timezone.utc).isoformat()

            # 1) 조회 직전 DOM
            prompt("'조회' 버튼을 클릭하기 직전 상태에서 Enter")
            before_buttons = collect_buttons(page)
            current["before_inquiry"] = {
                "button_count": len(before_buttons),
                "buttons": before_buttons[:50],
                "inquiry_selector_candidates": pick_inquiry_selectors(before_buttons),
            }
            logger.info(
                "before_inquiry — 버튼 %d, 조회 셀렉터 후보 %d",
                len(before_buttons),
                len(current["before_inquiry"]["inquiry_selector_candidates"]),
            )

            # 2) 사용자 조회 클릭
            prompt("이제 직접 '조회' 버튼을 누른 뒤 데이터 로드 확인하고 Enter")
            after_buttons = collect_buttons(page)
            current["after_inquiry"] = {
                "button_count": len(after_buttons),
                "buttons": after_buttons[:50],
                "inquiry_selector_candidates": pick_inquiry_selectors(after_buttons),
                "has_excel_icon": any(
                    "cel_save" in (b.get("cls") or "")
                    or "엑셀" in (b.get("text") or "")
                    or "엑셀" in (b.get("title") or "")
                    for b in after_buttons
                ),
            }
            logger.info(
                "after_inquiry — 버튼 %d, 엑셀 아이콘=%s",
                len(after_buttons),
                current["after_inquiry"]["has_excel_icon"],
            )

            # 3) 엑셀 클릭 후 모달 (선택)
            ans = prompt("엑셀 다운로드 클릭 후 모달이 떴다면 y, 모달 없이 즉시 다운로드면 n").lower()
            if ans == "y":
                prompt("모달이 떠 있는 상태에서 Enter (자동 dismiss하지 마세요)")
                modals = collect_modals(page)
                current["download_modal"] = {
                    "modal_count": len(modals),
                    "modals": modals,
                    "confirm_buttons": list({
                        bt for m in modals for bt in (m.get("buttons") or [])
                    }),
                }
                logger.info("modal — %d개, 버튼 텍스트: %s",
                            len(modals), current["download_modal"]["confirm_buttons"])
            else:
                current["download_modal"] = {"modal_count": 0, "modals": [], "confirm_buttons": []}

            captures[label] = current
            save(captures)

            if prompt("다음 페이지 계속? (y/n)").lower() != "y":
                break

        context.close()
        browser.close()

    print("\n" + "=" * 70)
    print(f"✅ 캡처 완료 — 총 {len(captures)} 페이지")
    print(f"   결과: {OUT}")
    print("   다음 단계: data/track_a_captures.json → src/shared/gw_session/selectors.py 머지")
    print("=" * 70)


if __name__ == "__main__":
    main()
