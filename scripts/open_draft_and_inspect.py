"""
임시보관문서 열기 + 결재상신 DOM 확인 테스트
- 임시보관문서함에서 문서 1건 클릭 → 팝업으로 열기
- 열린 문서의 DOM 구조 캡처 (스크린샷, HTML, 버튼 목록)
- 결재상신 버튼 selector 확인 (클릭하지 않음!)

⚠️ 주의: 실제 결재상신은 절대 실행하지 않음 — DOM 구조 확인만
"""

import json
import time
import sys
import logging
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from playwright.sync_api import sync_playwright
from src.auth.login import login_and_get_context, close_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = ROOT_DIR / "data" / "approval_drafts" / "open_test"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GW_URL = "https://gw.glowseoul.co.kr"
DRAFT_URL = f"{GW_URL}/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1020"


def save_screenshot(page, name):
    """스크린샷 저장"""
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    logger.info(f"스크린샷: {path}")


def dump_buttons(page, name):
    """보이는 버튼들 추출"""
    info = page.evaluate("""() => {
        const result = [];
        document.querySelectorAll('button, [role="button"], a.btn, input[type="button"], input[type="submit"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (el.offsetParent !== null && rect.width > 0 && rect.height > 0) {
                result.push({
                    text: el.textContent.trim().substring(0, 80),
                    tag: el.tagName.toLowerCase(),
                    id: el.id,
                    className: el.className.substring(0, 150),
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    disabled: el.disabled || false,
                });
            }
        });
        return result;
    }""")
    path = OUTPUT_DIR / f"{name}_buttons.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    logger.info(f"버튼 {len(info)}개 저장: {path}")
    for b in info:
        if b['text']:
            logger.info(f"  버튼: \"{b['text'][:50]}\" disabled={b.get('disabled')}")
    return info


def dump_inputs(page, name):
    """입력 필드 추출"""
    info = page.evaluate("""() => {
        const result = [];
        document.querySelectorAll('input, select, textarea').forEach(el => {
            const rect = el.getBoundingClientRect();
            result.push({
                tag: el.tagName.toLowerCase(),
                id: el.id,
                name: el.name,
                type: el.type || '',
                placeholder: el.placeholder || '',
                disabled: el.disabled,
                visible: el.offsetParent !== null && rect.width > 0 && rect.height > 0,
                value: el.value.substring(0, 100),
                className: el.className.substring(0, 120),
                rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
            });
        });
        return result;
    }""")
    path = OUTPUT_DIR / f"{name}_inputs.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    visible = [i for i in info if i.get("visible")]
    logger.info(f"필드 {len(info)}개 (visible {len(visible)}개) 저장: {path}")
    for v in visible:
        logger.info(f"  {v['tag']}[{v['type']}] id={v['id']} ph={v['placeholder']} val={v['value'][:30]}")
    return info


def dump_tables(page, name):
    """테이블 구조 분석"""
    info = page.evaluate("""() => {
        const tables = [];
        document.querySelectorAll('table').forEach((table, ti) => {
            if (table.offsetParent === null) return;
            const rows = [];
            table.querySelectorAll('tr').forEach((tr, ri) => {
                const cells = [];
                tr.querySelectorAll('td, th').forEach((cell, ci) => {
                    const inputs = [];
                    cell.querySelectorAll('input, select, textarea').forEach(inp => {
                        inputs.push({
                            tag: inp.tagName.toLowerCase(),
                            name: inp.name, id: inp.id,
                            type: inp.type || '', visible: inp.offsetParent !== null,
                            placeholder: inp.placeholder || '',
                            value: inp.value.substring(0, 50),
                        });
                    });
                    cells.push({
                        tag: cell.tagName.toLowerCase(),
                        text: cell.textContent.trim().substring(0, 80),
                        colspan: cell.colSpan, rowspan: cell.rowSpan,
                        inputs: inputs,
                    });
                });
                if (cells.length > 0) rows.push({ri: ri, cells: cells});
            });
            if (rows.length > 0) {
                tables.push({ti: ti, id: table.id, className: table.className.substring(0, 100), rows: rows.slice(0, 50)});
            }
        });
        return tables;
    }""")
    path = OUTPUT_DIR / f"{name}_tables.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    logger.info(f"테이블 {len(info)}개 저장: {path}")
    return info


def dump_action_buttons(page, name):
    """결재 관련 액션 버튼만 추출"""
    info = page.evaluate("""() => {
        const result = [];
        const keywords = ['보관', '상신', '결재상신', '임시저장', '미리보기', '결재선', '취소', '닫기', '삭제', '수정', '반려'];
        document.querySelectorAll('button, [role="button"], a').forEach(el => {
            const text = el.textContent.trim();
            if (keywords.some(k => text.includes(k)) && el.offsetParent !== null) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    result.push({
                        text: text.substring(0, 60),
                        tag: el.tagName.toLowerCase(),
                        id: el.id,
                        className: el.className.substring(0, 150),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                        disabled: el.disabled || false,
                    });
                }
            }
        });
        return result;
    }""")
    path = OUTPUT_DIR / f"{name}_action_buttons.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    logger.info(f"액션 버튼 {len(info)}개: {path}")
    for a in info:
        logger.info(f"  액션: \"{a['text'][:40]}\" at ({a['rect']['x']},{a['rect']['y']})")
    return info


def run():
    pw = sync_playwright().start()
    browser, context, page = login_and_get_context(
        playwright_instance=pw, headless=False
    )
    page.set_viewport_size({"width": 1920, "height": 1080})

    # API 응답 캡처
    api_data = []
    def handle_response(response):
        url = response.url
        if any(kw in url.lower() for kw in ["eap", "apb", "uba", "draft", "document"]):
            try:
                body = response.json()
                api_data.append({"url": url, "status": response.status, "data": body})
                logger.info(f"API 캡쳐: {url[:120]}")
            except Exception:
                pass
    page.on("response", handle_response)

    try:
        # ============================================================
        # 1단계: 임시보관문서함 이동
        # ============================================================
        logger.info("="*60)
        logger.info("[1/5] 임시보관문서함 이동")
        logger.info("="*60)

        page.goto(DRAFT_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(8)

        # 팝업 닫기
        for p in context.pages:
            if "popup" in p.url and p != page:
                try:
                    p.close()
                except Exception:
                    pass

        save_screenshot(page, "01_draft_list")
        logger.info(f"현재 URL: {page.url}")

        # ============================================================
        # 2단계: 문서 목록에서 첫 번째 문서 클릭
        # ============================================================
        logger.info("="*60)
        logger.info("[2/5] 문서 클릭 (첫 번째 문서)")
        logger.info("="*60)

        # 문서 제목이 포함된 행을 찾아 클릭
        # 세션 V에서 확인한 문서 제목: "GS-25-0088. [종로] 메디빌더 음향공사..."
        doc_clicked = False

        # 방법 1: 그리드 셀에서 문서 제목 텍스트 찾기
        for keyword in ["GS-25-0088", "메디빌더", "지출결의서"]:
            try:
                links = page.locator(f"text={keyword}").all()
                for link in links:
                    if link.is_visible():
                        logger.info(f"문서 발견: '{keyword}' → 클릭")
                        link.click()
                        doc_clicked = True
                        break
                if doc_clicked:
                    break
            except Exception:
                continue

        # 방법 2: 그리드 행에서 첫 번째 문서 클릭
        if not doc_clicked:
            try:
                # OBT 그리드 행 클릭
                grid_rows = page.locator("[class*='OBTGrid'] [class*='row'], table tbody tr").all()
                logger.info(f"그리드 행 수: {len(grid_rows)}")
                for i, row in enumerate(grid_rows[:10]):
                    try:
                        text = row.inner_text(timeout=2000).strip()
                        if "GS-" in text or "메디빌더" in text or len(text) > 20:
                            logger.info(f"행[{i}] 클릭: {text[:60]}")
                            row.click()
                            doc_clicked = True
                            break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"그리드 행 탐색 실패: {e}")

        # 방법 3: 더블클릭 시도 (일부 그리드는 더블클릭으로 열림)
        if not doc_clicked:
            try:
                first_cell = page.locator("[class*='OBTGrid'] [class*='cell']").first
                if first_cell.is_visible():
                    first_cell.dblclick()
                    doc_clicked = True
                    logger.info("그리드 첫 셀 더블클릭")
            except Exception:
                pass

        if not doc_clicked:
            logger.error("문서를 클릭할 수 없습니다!")
            save_screenshot(page, "02_click_failed")
            return

        time.sleep(5)
        save_screenshot(page, "02_after_click")

        # ============================================================
        # 3단계: 팝업 문서 감지 및 전환
        # ============================================================
        logger.info("="*60)
        logger.info("[3/5] 팝업 문서 감지")
        logger.info("="*60)

        # 새 페이지(팝업) 열림 감지
        all_pages = context.pages
        logger.info(f"열린 페이지 수: {len(all_pages)}")
        for i, p in enumerate(all_pages):
            logger.info(f"  page[{i}]: {p.url[:120]}")

        # 결재 문서 팝업 찾기
        doc_page = None
        for p in all_pages:
            url_lower = p.url.lower()
            # APB: 결재작성, eap: 전자결재 관련
            if any(kw in url_lower for kw in ["apb", "eap1", "eap0", "document", "view"]):
                if p != page:
                    doc_page = p
                    break

        # 팝업이 없으면 원래 페이지에서 문서가 열렸을 수 있음
        if doc_page:
            logger.info(f"문서 팝업 발견! URL: {doc_page.url[:120]}")
            doc_page.set_viewport_size({"width": 1920, "height": 1080})
            doc_page.bring_to_front()
            time.sleep(3)
        else:
            logger.info("별도 팝업 없음 — 원래 페이지에서 문서 열림 (인라인)")
            doc_page = page
            time.sleep(3)

        save_screenshot(doc_page, "03_document_opened")

        # ============================================================
        # 4단계: 열린 문서 DOM 캡처
        # ============================================================
        logger.info("="*60)
        logger.info("[4/5] 문서 DOM 캡처")
        logger.info("="*60)

        # 입력 필드
        dump_inputs(doc_page, "document")
        # 버튼
        dump_buttons(doc_page, "document")
        # 테이블 구조
        dump_tables(doc_page, "document")
        # 액션 버튼 (결재상신, 보관 등)
        dump_action_buttons(doc_page, "document")

        # HTML 저장
        try:
            html = doc_page.content()
            if len(html) < 5_000_000:
                (OUTPUT_DIR / "document.html").write_text(html, encoding="utf-8")
                logger.info(f"HTML 저장 ({len(html):,} bytes)")
            else:
                logger.info(f"HTML 너무 큼 ({len(html):,} bytes), 스킵")
        except Exception as e:
            logger.warning(f"HTML 저장 실패: {e}")

        # 페이지 텍스트
        try:
            text = doc_page.inner_text("body")
            (OUTPUT_DIR / "document_text.txt").write_text(text, encoding="utf-8")
            logger.info("페이지 텍스트 저장")
        except Exception as e:
            logger.warning(f"텍스트 저장 실패: {e}")

        # ============================================================
        # 5단계: 결재상신 버튼 확인 (클릭하지 않음!)
        # ============================================================
        logger.info("="*60)
        logger.info("[5/5] 결재상신 버튼 확인 (클릭 안 함!)")
        logger.info("="*60)

        # 결재상신 버튼 존재 확인
        submit_selectors = [
            "button:has-text('결재상신')",
            "text=결재상신",
            "[class*='submit']",
            "button:has-text('상신')",
        ]
        for sel in submit_selectors:
            try:
                btn = doc_page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    box = btn.bounding_box()
                    text = btn.text_content()
                    logger.info(f"결재상신 버튼 발견! selector='{sel}' text='{text}' box={box}")
                else:
                    logger.info(f"  selector '{sel}' → 미발견 (hidden)")
            except Exception:
                logger.info(f"  selector '{sel}' → 미발견")

        # 최종 스크린샷
        save_screenshot(doc_page, "04_final")

        # API 데이터 저장
        if api_data:
            (OUTPUT_DIR / "api_responses.json").write_text(
                json.dumps(api_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(f"API 응답 {len(api_data)}개 저장")

        logger.info("="*60)
        logger.info(f"탐색 완료! 결과: {OUTPUT_DIR}")
        logger.info("="*60)

    except Exception as e:
        logger.error(f"오류: {e}", exc_info=True)
        save_screenshot(page, "error")
    finally:
        close_session(browser)
        pw.stop()


if __name__ == "__main__":
    run()
