"""
RealGrid 그리드 instance 탐색 스크립트

더존 WEHAGO 지출결의서 양식의 RealGrid/OBTGrid 인스턴스를 찾기 위한 탐색.
- 모든 frame에서 RealGrid 관련 window 변수 검색
- DOM에서 canvas, RealGrid, OBTGrid 요소 탐색
- React fiber를 통한 그리드 컨테이너 탐색
- __realgrid__ 속성 보유 요소 탐색
- 프로젝트코드도움 모달 / 세금계산서 모달 / 증빙유형 버튼 구조 확인
"""

import json
import time
import logging
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Frame

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.auth.login import login_and_get_context, close_session, GW_URL

# 출력 경로
OUTPUT_DIR = PROJECT_ROOT / "data" / "gw_analysis"
OUTPUT_FILE = OUTPUT_DIR / "realgrid_discovery.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("explore_realgrid")


# ─────────────────────────────────────────
# JS 탐색 함수들 (frame.evaluate에 전달)
# ─────────────────────────────────────────

JS_FIND_GRID_WINDOW_VARS = """() => {
    // window 객체에서 grid/Grid/RealGrid/realgrid 관련 키 검색
    const results = [];
    const patterns = [/grid/i, /realgrid/i, /RealGrid/, /dataProvider/i, /GridView/i];
    for (const key of Object.keys(window)) {
        for (const pat of patterns) {
            if (pat.test(key)) {
                let valType = typeof window[key];
                let valPreview = '';
                try {
                    if (valType === 'object' && window[key] !== null) {
                        const keys = Object.keys(window[key]).slice(0, 20);
                        valPreview = keys.join(', ');
                    } else if (valType === 'function') {
                        valPreview = window[key].toString().slice(0, 100);
                    } else {
                        valPreview = String(window[key]).slice(0, 100);
                    }
                } catch(e) { valPreview = '[접근 불가]'; }
                results.push({key, type: valType, preview: valPreview});
                break;  // 한 키에 한 번만
            }
        }
    }
    return results;
}"""

JS_FIND_REALGRID_CONSTRUCTORS = """() => {
    // RealGrid 생성자나 전역 네임스페이스 탐색
    const results = [];
    // 1) window.RealGrid / window.realGrid 네임스페이스
    for (const ns of ['RealGrid', 'realGrid', 'realgrid', 'RealGridJS']) {
        if (window[ns]) {
            const keys = Object.keys(window[ns]).slice(0, 30);
            results.push({namespace: ns, keys: keys});
        }
    }
    // 2) GridView, TreeView, DataProvider 등 직접 접근
    for (const cls of ['GridView', 'TreeView', 'LocalDataProvider', 'LocalTreeDataProvider']) {
        if (window[cls]) {
            results.push({constructor: cls, type: typeof window[cls]});
        }
    }
    return results;
}"""

JS_FIND_GRID_DOM_ELEMENTS = """() => {
    // DOM에서 RealGrid/OBTGrid/canvas 관련 요소 탐색
    const results = {canvases: [], realgridClasses: [], obtGridClasses: [], rgClasses: []};

    // canvas 요소
    document.querySelectorAll('canvas').forEach(el => {
        const rect = el.getBoundingClientRect();
        results.canvases.push({
            id: el.id,
            className: el.className,
            width: el.width,
            height: el.height,
            rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
            parentClass: el.parentElement?.className?.slice(0, 100) || '',
            parentId: el.parentElement?.id || '',
        });
    });

    // class에 RealGrid 포함
    document.querySelectorAll('[class*="RealGrid"], [class*="realgrid"]').forEach(el => {
        const rect = el.getBoundingClientRect();
        results.realgridClasses.push({
            tag: el.tagName,
            id: el.id,
            className: el.className.slice(0, 200),
            rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
        });
    });

    // class에 OBTGrid 포함
    document.querySelectorAll('[class*="OBTGrid"], [class*="obtGrid"], [class*="obt-grid"]').forEach(el => {
        const rect = el.getBoundingClientRect();
        results.obtGridClasses.push({
            tag: el.tagName,
            id: el.id,
            className: el.className.slice(0, 200),
            rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
        });
    });

    // class에 rg- 포함 (RealGrid 내부 CSS 클래스)
    document.querySelectorAll('[class*="rg-"]').forEach(el => {
        const rect = el.getBoundingClientRect();
        results.rgClasses.push({
            tag: el.tagName,
            id: el.id,
            className: el.className.slice(0, 200),
            rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
        });
    });

    return results;
}"""

JS_FIND_REACT_FIBER_GRIDS = """() => {
    // React fiber 속성을 가진 그리드 관련 컨테이너 탐색
    const results = [];
    const allEls = document.querySelectorAll('*');
    for (const el of allEls) {
        // React fiber 키 탐색
        const fiberKey = Object.keys(el).find(k =>
            k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$')
        );
        if (!fiberKey) continue;

        // 그리드 관련 클래스/속성 확인
        const cls = el.className || '';
        const isGridRelated = /grid|Grid|OBT|canvas|realgrid/i.test(cls)
            || el.tagName === 'CANVAS'
            || el.querySelector('canvas');

        if (!isGridRelated) continue;

        let fiberInfo = {};
        try {
            const fiber = el[fiberKey];
            fiberInfo.type = fiber?.type?.name || fiber?.type?.displayName || String(fiber?.type).slice(0, 50);
            fiberInfo.pendingProps = fiber?.pendingProps
                ? Object.keys(fiber.pendingProps).slice(0, 15)
                : [];
        } catch(e) { fiberInfo.error = e.message; }

        const rect = el.getBoundingClientRect();
        results.push({
            tag: el.tagName,
            id: el.id,
            className: cls.slice(0, 200),
            fiberKey: fiberKey,
            fiberInfo: fiberInfo,
            rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
        });

        if (results.length >= 30) break;  // 너무 많으면 제한
    }
    return results;
}"""

JS_FIND_REALGRID_INSTANCES = """() => {
    // __realgrid__ 속성이 있는 요소 탐색
    const results = [];
    const allEls = document.querySelectorAll('*');
    for (const el of allEls) {
        // __realgrid__ 직접 속성
        if (el.__realgrid__ || el._grid || el._gridView) {
            const rect = el.getBoundingClientRect();
            let gridKeys = [];
            try {
                const gridObj = el.__realgrid__ || el._grid || el._gridView;
                gridKeys = Object.keys(gridObj).slice(0, 20);
            } catch(e) {}
            results.push({
                tag: el.tagName,
                id: el.id,
                className: (el.className || '').slice(0, 200),
                propName: el.__realgrid__ ? '__realgrid__' : (el._grid ? '_grid' : '_gridView'),
                gridKeys: gridKeys,
                rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
            });
        }

        // data-* 속성 중 grid 관련
        for (const attr of el.attributes || []) {
            if (/grid|realgrid/i.test(attr.name)) {
                const rect = el.getBoundingClientRect();
                results.push({
                    tag: el.tagName,
                    id: el.id,
                    className: (el.className || '').slice(0, 200),
                    attrName: attr.name,
                    attrValue: attr.value.slice(0, 100),
                    rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
                });
            }
        }
        if (results.length >= 30) break;
    }
    return results;
}"""

JS_DEEP_GRID_SEARCH = """() => {
    // 더 깊은 탐색: window의 모든 1-depth 객체에서 grid instance 검색
    const results = [];
    const checked = new Set();
    for (const key of Object.keys(window)) {
        try {
            const val = window[key];
            if (!val || typeof val !== 'object' || checked.has(val)) continue;
            checked.add(val);

            // GridView / DataProvider 메서드 보유 여부 확인
            const hasGetRowCount = typeof val.getRowCount === 'function';
            const hasSetCurrent = typeof val.setCurrent === 'function';
            const hasGetValues = typeof val.getValues === 'function';
            const hasGetDataSource = typeof val.getDataSource === 'function';
            const hasCommit = typeof val.commit === 'function';

            if (hasGetRowCount || hasSetCurrent || hasGetDataSource) {
                const methods = Object.getOwnPropertyNames(Object.getPrototypeOf(val) || {})
                    .filter(m => typeof val[m] === 'function').slice(0, 30);
                results.push({
                    windowKey: key,
                    constructorName: val.constructor?.name || 'unknown',
                    hasGetRowCount, hasSetCurrent, hasGetValues, hasGetDataSource, hasCommit,
                    methods: methods,
                });
            }
        } catch(e) { /* 접근 불가 객체 무시 */ }
    }
    return results;
}"""

JS_EXPLORE_MODAL_STRUCTURE = """(modalTitle) => {
    // 모달의 내부 구조 탐색 (프로젝트코드도움, 세금계산서 등)
    const results = {
        title: modalTitle,
        found: false,
        structure: null,
    };

    // 모달 컨테이너 찾기
    const allEls = document.querySelectorAll('[class*="OBTDialog"], [class*="modal"], [role="dialog"], [class*="popup"]');
    for (const container of allEls) {
        if (!container.textContent.includes(modalTitle)) continue;

        results.found = true;

        // 내부 canvas 확인
        const canvases = container.querySelectorAll('canvas');
        const tables = container.querySelectorAll('table');
        const inputs = container.querySelectorAll('input');
        const buttons = container.querySelectorAll('button');

        results.structure = {
            containerTag: container.tagName,
            containerClass: container.className.slice(0, 200),
            canvasCount: canvases.length,
            tableCount: tables.length,
            inputCount: inputs.length,
            buttonCount: buttons.length,
            canvases: Array.from(canvases).map(c => ({
                id: c.id, width: c.width, height: c.height,
                rect: (() => { const r = c.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; })()
            })),
            tables: Array.from(tables).map(t => ({
                id: t.id, className: t.className.slice(0, 100),
                rows: t.rows?.length || 0,
                rect: (() => { const r = t.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; })()
            })),
            buttons: Array.from(buttons).map(b => ({
                text: b.textContent.trim().slice(0, 50),
                className: b.className.slice(0, 100),
                rect: (() => { const r = b.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; })()
            })),
        };
        break;
    }
    return results;
}"""

JS_EVIDENCE_TYPE_BUTTONS = """() => {
    // 증빙유형 관련 버튼/탭 탐색
    const keywords = ['세금계산서', '계산서내역', '카드사용내역', '현금영수증', '증빙유형'];
    const results = [];

    for (const kw of keywords) {
        // 텍스트가 포함된 모든 요소
        const xpath = `//*/text()[contains(., '${kw}')]/parent::*`;
        const xresult = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
        for (let i = 0; i < Math.min(xresult.snapshotLength, 5); i++) {
            const el = xresult.snapshotItem(i);
            const rect = el.getBoundingClientRect();
            // 크기가 너무 큰 컨테이너 제외 (텍스트를 직접 포함하는 요소만)
            if (rect.width > 500 || rect.height > 200) continue;
            results.push({
                keyword: kw,
                tag: el.tagName,
                id: el.id,
                className: (el.className || '').slice(0, 150),
                text: el.textContent.trim().slice(0, 80),
                rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
                clickable: el.tagName === 'BUTTON' || el.tagName === 'A'
                    || el.getAttribute('role') === 'button'
                    || /btn|button|tab|click/i.test(el.className),
            });
        }
    }
    return results;
}"""


# ─────────────────────────────────────────
# 메인 탐색 로직
# ─────────────────────────────────────────

def explore_frame(frame: Frame, frame_name: str) -> dict:
    """단일 frame에서 RealGrid 관련 정보 수집"""
    result = {"frame_name": frame_name, "url": ""}
    try:
        result["url"] = frame.url
    except Exception:
        pass

    # 1. window 변수 중 grid 관련
    try:
        result["window_grid_vars"] = frame.evaluate(JS_FIND_GRID_WINDOW_VARS)
    except Exception as e:
        result["window_grid_vars"] = f"ERROR: {e}"

    # 2. RealGrid 네임스페이스/생성자
    try:
        result["realgrid_constructors"] = frame.evaluate(JS_FIND_REALGRID_CONSTRUCTORS)
    except Exception as e:
        result["realgrid_constructors"] = f"ERROR: {e}"

    # 3. DOM 요소 탐색
    try:
        result["dom_elements"] = frame.evaluate(JS_FIND_GRID_DOM_ELEMENTS)
    except Exception as e:
        result["dom_elements"] = f"ERROR: {e}"

    # 4. React fiber 그리드 컨테이너
    try:
        result["react_fiber_grids"] = frame.evaluate(JS_FIND_REACT_FIBER_GRIDS)
    except Exception as e:
        result["react_fiber_grids"] = f"ERROR: {e}"

    # 5. __realgrid__ 속성 요소
    try:
        result["realgrid_instances"] = frame.evaluate(JS_FIND_REALGRID_INSTANCES)
    except Exception as e:
        result["realgrid_instances"] = f"ERROR: {e}"

    # 6. 깊은 탐색: window 1-depth 객체에서 GridView/DataProvider 메서드 보유 객체
    try:
        result["deep_grid_objects"] = frame.evaluate(JS_DEEP_GRID_SEARCH)
    except Exception as e:
        result["deep_grid_objects"] = f"ERROR: {e}"

    return result


def navigate_to_expense_form(page: Page):
    """결재 메뉴 진입 → 결재작성 → 지출결의서 양식 선택"""
    # 1. 결재 메뉴 진입
    logger.info("결재 메뉴 진입 중...")
    page.goto(f"{GW_URL}/#/eap", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    logger.info(f"현재 URL: {page.url}")

    # 2. 결재작성 버튼 클릭
    logger.info("결재작성 버튼 클릭 중...")
    for selector in [
        "button:has-text('결재작성')",
        "a:has-text('결재작성')",
        "div:has-text('결재작성') >> visible=true",
        "text=결재작성",
    ]:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=3000):
                btn.click(force=True)
                logger.info(f"결재작성 버튼 클릭 (selector: {selector})")
                break
        except Exception:
            continue

    page.wait_for_timeout(2000)

    # 3. 지출결의서 양식 선택
    logger.info("지출결의서 양식 선택 중...")
    for keyword in ["[프로젝트]지출결의서", "프로젝트]지출", "지출결의서"]:
        try:
            links = page.locator(f"text={keyword}").all()
            for link in links:
                if link.is_visible():
                    link.click(force=True)
                    logger.info(f"양식 클릭: '{keyword}'")
                    page.wait_for_timeout(5000)  # 양식 로드 대기 (그리드 포함)
                    return True
        except Exception:
            continue

    logger.warning("지출결의서 양식을 찾을 수 없음")
    return False


def wait_for_grid_area(page: Page):
    """지출내역 그리드 영역이 로드될 때까지 대기"""
    logger.info("양식 + 그리드 로드 대기 중...")

    # 제목 필드 대기
    try:
        page.locator("th:has-text('제목')").first.wait_for(state="visible", timeout=15000)
        logger.info("양식 제목 필드 로드 확인")
    except Exception:
        logger.warning("제목 필드 미발견 — 그래도 계속 진행")

    # 추가 대기 (그리드 렌더링 완료용)
    page.wait_for_timeout(3000)

    # 지출내역 영역 확인
    try:
        el = page.locator("text=지출내역").first
        if el.is_visible(timeout=5000):
            logger.info("지출내역 영역 확인됨")
    except Exception:
        logger.warning("지출내역 텍스트 미발견")


def explore_additional_ui(page: Page) -> dict:
    """추가 탐색: 프로젝트코드도움 모달, 세금계산서 모달, 증빙유형 버튼"""
    results = {}

    # 1. 증빙유형 버튼 탐색 (모달 열지 않고 현재 페이지에서)
    logger.info("증빙유형 버튼 탐색...")
    try:
        results["evidence_type_buttons"] = page.evaluate(JS_EVIDENCE_TYPE_BUTTONS)
    except Exception as e:
        results["evidence_type_buttons"] = f"ERROR: {e}"

    # 2. 프로젝트코드도움 모달 열기 시도
    logger.info("프로젝트코드도움 모달 탐색 시도...")
    try:
        proj_input = page.locator("input[placeholder='프로젝트코드도움']").first
        if proj_input.is_visible(timeout=3000):
            proj_input.click()
            page.wait_for_timeout(1500)

            # 모달이 열렸으면 구조 탐색
            results["project_modal"] = page.evaluate(JS_EXPLORE_MODAL_STRUCTURE, "프로젝트코드도움")

            # 모달 닫기 (ESC)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        else:
            results["project_modal"] = {"found": False, "note": "프로젝트코드도움 input 미발견"}
    except Exception as e:
        results["project_modal"] = {"found": False, "error": str(e)}

    # 3. 세금계산서 모달 (계산서내역 버튼 클릭 시도)
    logger.info("세금계산서 모달 탐색 시도...")
    try:
        # 증빙유형 탭에서 "계산서내역" 클릭
        invoice_clicked = False
        for sel in ["text='계산서내역'", "button:has-text('계산서내역')", "span:has-text('계산서내역')"]:
            try:
                els = page.locator(sel).all()
                for el in els:
                    if el.is_visible():
                        box = el.bounding_box()
                        # 지출내역 영역 근처만 (너무 큰 컨테이너 제외)
                        if box and box["width"] < 200:
                            el.click()
                            invoice_clicked = True
                            logger.info("계산서내역 버튼 클릭")
                            break
                if invoice_clicked:
                    break
            except Exception:
                continue

        if invoice_clicked:
            page.wait_for_timeout(2000)

            # 세금계산서 모달 구조 탐색
            for title in ["세금계산서", "계산서", "매입계산서"]:
                modal_result = page.evaluate(JS_EXPLORE_MODAL_STRUCTURE, title)
                if modal_result.get("found"):
                    results["invoice_modal"] = modal_result
                    break
            else:
                results["invoice_modal"] = {"found": False, "note": "세금계산서 모달 미열림"}

            # 모달 닫기 (ESC)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        else:
            results["invoice_modal"] = {"found": False, "note": "계산서내역 버튼 미발견"}
    except Exception as e:
        results["invoice_modal"] = {"found": False, "error": str(e)}

    return results


def main():
    logger.info("=" * 60)
    logger.info("RealGrid 그리드 인스턴스 탐색 시작")
    logger.info("=" * 60)

    pw = sync_playwright().start()
    browser = None

    try:
        # 1. 로그인
        browser, context, page = login_and_get_context(pw, headless=False)
        logger.info(f"로그인 완료, URL: {page.url}")

        # 2. 지출결의서 양식 진입
        if not navigate_to_expense_form(page):
            logger.error("지출결의서 양식 진입 실패")
            return

        # 3. 그리드 로드 대기
        wait_for_grid_area(page)

        # 스크린샷 저장
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUTPUT_DIR / "realgrid_explore_page.png"))

        # ─────────────────────────────────────────
        # 4. 전체 frame 순회하며 탐색
        # ─────────────────────────────────────────
        discovery = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "page_url": page.url,
            "frames": [],
            "additional_ui": {},
        }

        # 메인 페이지 (frame이 아닌 최상위)
        logger.info("메인 페이지 탐색 중...")
        main_result = explore_frame(page.main_frame, "main_page")
        discovery["frames"].append(main_result)

        # 모든 하위 frame 순회
        all_frames = page.frames
        logger.info(f"총 frame 수: {len(all_frames)}")
        for idx, frame in enumerate(all_frames):
            if frame == page.main_frame:
                continue  # 이미 처리함
            frame_name = frame.name or f"frame_{idx}"
            logger.info(f"  Frame [{idx}] '{frame_name}': {frame.url[:80] if frame.url else '(empty)'}")
            try:
                frame_result = explore_frame(frame, frame_name)
                discovery["frames"].append(frame_result)
            except Exception as e:
                logger.warning(f"  Frame [{idx}] 탐색 실패: {e}")
                discovery["frames"].append({
                    "frame_name": frame_name,
                    "url": frame.url if frame.url else "",
                    "error": str(e),
                })

        # ─────────────────────────────────────────
        # 5. 추가 UI 탐색 (모달, 버튼)
        # ─────────────────────────────────────────
        logger.info("추가 UI 탐색 중 (프로젝트코드도움, 세금계산서, 증빙유형)...")
        discovery["additional_ui"] = explore_additional_ui(page)

        # ─────────────────────────────────────────
        # 6. 결과 요약
        # ─────────────────────────────────────────
        summary = {
            "total_frames": len(all_frames),
            "frames_with_grid_vars": 0,
            "frames_with_canvases": 0,
            "frames_with_realgrid_instances": 0,
            "frames_with_deep_grid_objects": 0,
            "key_findings": [],
        }

        for fr in discovery["frames"]:
            # window 변수 중 grid 관련 발견
            gv = fr.get("window_grid_vars", [])
            if isinstance(gv, list) and len(gv) > 0:
                summary["frames_with_grid_vars"] += 1
                summary["key_findings"].append(
                    f"[{fr['frame_name']}] window grid 변수 {len(gv)}개: {[v['key'] for v in gv[:5]]}"
                )

            # canvas 발견
            dom = fr.get("dom_elements", {})
            if isinstance(dom, dict):
                canvases = dom.get("canvases", [])
                if canvases:
                    summary["frames_with_canvases"] += 1
                    summary["key_findings"].append(
                        f"[{fr['frame_name']}] canvas {len(canvases)}개 발견"
                    )

            # __realgrid__ 인스턴스
            ri = fr.get("realgrid_instances", [])
            if isinstance(ri, list) and len(ri) > 0:
                summary["frames_with_realgrid_instances"] += 1
                summary["key_findings"].append(
                    f"[{fr['frame_name']}] __realgrid__ 인스턴스 {len(ri)}개"
                )

            # deep grid objects
            dg = fr.get("deep_grid_objects", [])
            if isinstance(dg, list) and len(dg) > 0:
                summary["frames_with_deep_grid_objects"] += 1
                for obj in dg:
                    summary["key_findings"].append(
                        f"[{fr['frame_name']}] GridView-like 객체 발견: window.{obj['windowKey']} "
                        f"(constructor: {obj['constructorName']}, methods: {obj['methods'][:10]})"
                    )

        discovery["summary"] = summary

        # 7. 결과 저장
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(discovery, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"\n{'=' * 60}")
        logger.info(f"탐색 결과 저장: {OUTPUT_FILE}")
        logger.info(f"{'=' * 60}")
        logger.info(f"총 frame: {summary['total_frames']}")
        logger.info(f"grid 변수 발견: {summary['frames_with_grid_vars']}개 frame")
        logger.info(f"canvas 발견: {summary['frames_with_canvases']}개 frame")
        logger.info(f"__realgrid__ 인스턴스: {summary['frames_with_realgrid_instances']}개 frame")
        logger.info(f"deep grid 객체: {summary['frames_with_deep_grid_objects']}개 frame")
        logger.info(f"\n주요 발견:")
        for finding in summary["key_findings"]:
            logger.info(f"  → {finding}")

        # 사용자 확인용 대기 (headless=False이므로)
        logger.info("\n브라우저를 유지합니다. Ctrl+C로 종료하세요.")
        try:
            input("Enter를 누르면 브라우저를 닫습니다...")
        except (KeyboardInterrupt, EOFError):
            pass

    except Exception as e:
        logger.error(f"탐색 중 오류: {e}", exc_info=True)
    finally:
        if browser:
            close_session(browser)
        pw.stop()


if __name__ == "__main__":
    main()
