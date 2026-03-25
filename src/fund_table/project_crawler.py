"""
GW 프로젝트 등록정보 크롤러
- Playwright로 GW 접속 → 프로젝트 등록 페이지 → 데이터 추출
- 프로젝트 코드, 시작일, 기간, 담당자 등 기본정보 크롤링
"""

import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("project_crawler")

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "approval_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# 프로젝트 등록정보 추출 JS — 페이지의 입력 필드에서 데이터 추출
_EXTRACT_PROJECT_INFO_JS = """
(() => {
    const result = {};

    // 1. OBTConditionPanel / form 내 입력 필드에서 데이터 추출
    const inputs = document.querySelectorAll('input[type="text"], input[type="date"]');
    inputs.forEach(inp => {
        const ph = inp.placeholder || '';
        const id = inp.id || '';
        const name = inp.name || '';
        const val = inp.value || '';
        if (!val) return;

        // 필드 매핑 (placeholder, id, name 기반)
        const key = (ph + ' ' + id + ' ' + name).toLowerCase();
        if (key.includes('사업코드') || key.includes('프로젝트코드') || key.includes('pjtcd') || key.includes('mgtcd')) {
            result.project_code = val;
        }
        if (key.includes('사업명') || key.includes('프로젝트명') || key.includes('pjtnm')) {
            result.project_name = val;
        }
        if (key.includes('시작일') || key.includes('착수일') || key.includes('startdt') || key.includes('fromdt')) {
            result.start_date = val;
        }
        if (key.includes('종료일') || key.includes('완료일') || key.includes('enddt') || key.includes('todt')) {
            result.end_date = val;
        }
        if (key.includes('기간') || key.includes('duration')) {
            result.duration = val;
        }
        if (key.includes('담당자') || key.includes('책임자') || key.includes('manager')) {
            result.manager = val;
        }
        if (key.includes('발주처') || key.includes('고객사') || key.includes('client')) {
            result.client = val;
        }
    });

    // 2. OBTTextField, OBTDatePicker 등 더존 컴포넌트에서 추출
    const obtFields = document.querySelectorAll('[class*="OBTTextField"], [class*="OBTDatePicker"], [class*="OBTCalendar"]');
    obtFields.forEach(el => {
        const inp = el.querySelector('input');
        if (!inp || !inp.value) return;

        // 라벨 텍스트 찾기 (이전 형제 또는 부모의 label)
        let label = '';
        const prevSibling = el.previousElementSibling;
        if (prevSibling) label = prevSibling.textContent.trim();
        if (!label) {
            const parent = el.closest('tr, .form-group, [class*="row"]');
            if (parent) {
                const th = parent.querySelector('th, label, [class*="label"]');
                if (th) label = th.textContent.trim();
            }
        }

        if (label.includes('사업코드') || label.includes('프로젝트코드')) result.project_code = inp.value;
        if (label.includes('사업명') || label.includes('프로젝트명')) result.project_name = inp.value;
        if (label.includes('시작일') || label.includes('착수일') || label.includes('시작')) result.start_date = inp.value;
        if (label.includes('종료일') || label.includes('완료일') || label.includes('종료')) result.end_date = inp.value;
        if (label.includes('기간')) result.duration = inp.value;
        if (label.includes('담당') || label.includes('책임')) result.manager = inp.value;
        if (label.includes('발주처') || label.includes('고객')) result.client = inp.value;
    });

    // 3. React fiber에서 form state 직접 추출 (가장 신뢰할 수 있음)
    const formContainers = document.querySelectorAll(
        '[class*="OBTDataGrid"], [class*="formContent"], [class*="detail-content"]'
    );
    for (const el of formContainers) {
        const fk = Object.keys(el).find(k =>
            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
        );
        if (!fk) continue;

        let f = el[fk];
        // depth 5~15 탐색하여 form state 찾기
        for (let i = 0; i < 15 && f; i++) {
            f = f.return;
            if (!f?.stateNode?.state) continue;
            const state = f.stateNode.state;

            // head 데이터 (마스터 레코드)
            if (state.head && typeof state.head === 'object') {
                const h = state.head;
                result._react_head = {};
                for (const [k, v] of Object.entries(h)) {
                    if (v && typeof v !== 'object') result._react_head[k] = v;
                }
                // 알려진 필드 매핑
                if (h.pjtCd) result.project_code = h.pjtCd;
                if (h.pjtNm) result.project_name = h.pjtNm;
                if (h.mgtCd) result.project_code = result.project_code || h.mgtCd;
                if (h.mgtNm) result.project_name = result.project_name || h.mgtNm;
                if (h.strtDt || h.startDt || h.fromDt) result.start_date = h.strtDt || h.startDt || h.fromDt;
                if (h.endDt || h.toDt || h.fnshDt) result.end_date = h.endDt || h.toDt || h.fnshDt;
                if (h.pjtPrd || h.duration) result.duration = h.pjtPrd || h.duration;
                if (h.mgrEmpNm || h.charger) result.manager = h.mgrEmpNm || h.charger;
                if (h.clientNm || h.custNm) result.client = h.clientNm || h.custNm;
                if (h.pjtStCd) result.status_code = h.pjtStCd;
                if (h.pjtStNm) result.status = h.pjtStNm;
                if (h.remark || h.rmk) result.remark = h.remark || h.rmk;
                break;
            }

            // form 데이터
            if (state.form && typeof state.form === 'object') {
                result._react_form = {};
                for (const [k, v] of Object.entries(state.form)) {
                    if (v && typeof v !== 'object') result._react_form[k] = v;
                }
            }
        }
    }

    // 4. 테이블 기반 폼에서 추출 (th: label, td: value 패턴)
    const rows = document.querySelectorAll('table tr, [class*="formTable"] tr');
    rows.forEach(tr => {
        const th = tr.querySelector('th, [class*="label"]');
        const td = tr.querySelector('td, [class*="value"]');
        if (!th || !td) return;

        const label = th.textContent.trim();
        // td 내 input 값 또는 텍스트
        const inp = td.querySelector('input');
        const val = inp ? inp.value : td.textContent.trim();
        if (!val) return;

        if (label.includes('사업코드') || label.includes('프로젝트코드')) result.project_code = result.project_code || val;
        if (label.includes('사업명') || label.includes('프로젝트명')) result.project_name = result.project_name || val;
        if (label.includes('시작') || label.includes('착수')) result.start_date = result.start_date || val;
        if (label.includes('종료') || label.includes('완료')) result.end_date = result.end_date || val;
        if (label.includes('기간')) result.duration = result.duration || val;
        if (label.includes('담당') || label.includes('책임')) result.manager = result.manager || val;
        if (label.includes('발주처') || label.includes('고객')) result.client = result.client || val;
        if (label.includes('상태') || label.includes('진행')) result.status = result.status || val;
    });

    return result;
})()
"""

# 1단계: "프로젝트 NNN건" 앵커에서 React 컴포넌트의 전체 프로젝트 배열 추출
_EXTRACT_REACT_PROJECT_DATA_JS = """
(() => {
    // "프로젝트 NNN건" 텍스트를 포함하는 요소를 앵커로 사용
    const allSpans = document.querySelectorAll('span, div, strong, b');
    let anchorEl = null;
    let expectedCount = 0;
    for (const el of allSpans) {
        const t = el.textContent.trim();
        const m = t.match(/프로젝트\\s*(\\d+)건/);
        if (m) {
            anchorEl = el;
            expectedCount = parseInt(m[1]);
            break;
        }
    }
    if (!anchorEl) return { error: 'anchor_not_found', hint: '프로젝트 NNN건 텍스트를 찾을 수 없음' };

    // 앵커에서 상위로 올라가며 스크롤 가능한 카드 리스트 컨테이너 찾기
    let container = anchorEl.parentElement;
    let listContainer = null;
    for (let i = 0; i < 10 && container; i++) {
        // 스크롤 가능하고 체크박스가 있는 자식 div 찾기
        const scrollDivs = container.querySelectorAll('div');
        for (const div of scrollDivs) {
            if (div.scrollHeight > div.clientHeight + 30 &&
                div.clientHeight > 100 &&
                div.querySelectorAll('input[type="checkbox"]').length > 1) {
                listContainer = div;
                break;
            }
        }
        if (listContainer) break;
        container = container.parentElement;
    }

    // 앵커 요소의 React fiber에서 프로젝트 데이터 배열 탐색
    // 페이지 컴포넌트 트리 상위에 전체 프로젝트 목록이 있을 것
    const fiberKey = Object.keys(anchorEl).find(k =>
        k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
    );

    if (fiberKey) {
        let fiber = anchorEl[fiberKey];
        for (let depth = 0; depth < 40 && fiber; depth++) {
            // props와 state 모두 탐색
            const sources = [];
            if (fiber.memoizedProps) sources.push(fiber.memoizedProps);
            if (fiber.memoizedState) {
                // memoizedState는 연결 리스트일 수 있음
                let ms = fiber.memoizedState;
                for (let si = 0; si < 10 && ms; si++) {
                    if (ms.memoizedState) sources.push(
                        typeof ms.memoizedState === 'object' ? ms.memoizedState : {}
                    );
                    if (ms.queue?.lastRenderedState) sources.push(
                        typeof ms.queue.lastRenderedState === 'object' ? ms.queue.lastRenderedState : {}
                    );
                    ms = ms.next;
                }
            }
            if (fiber.stateNode?.state) sources.push(fiber.stateNode.state);
            if (fiber.stateNode?.props) sources.push(fiber.stateNode.props);

            for (const src of sources) {
                if (!src || typeof src !== 'object') continue;
                // 재귀적으로 배열 탐색 (depth 2까지)
                const arrays = [];
                for (const [k, v] of Object.entries(src)) {
                    if (Array.isArray(v) && v.length >= expectedCount * 0.8) arrays.push({ key: k, arr: v });
                    else if (v && typeof v === 'object' && !Array.isArray(v)) {
                        for (const [k2, v2] of Object.entries(v)) {
                            if (Array.isArray(v2) && v2.length >= expectedCount * 0.8) arrays.push({ key: k+'.'+k2, arr: v2 });
                        }
                    }
                }

                for (const { key, arr } of arrays) {
                    const sample = arr[0];
                    if (!sample || typeof sample !== 'object') continue;
                    const sampleKeys = Object.keys(sample);
                    // 프로젝트 등록 데이터에는 코드+이름+날짜가 있어야 함
                    const hasCode = sampleKeys.some(k => /pjtcd|mgtcd|projcd/i.test(k));
                    const hasName = sampleKeys.some(k => /pjtnm|mgtnm|projnm/i.test(k));
                    const hasDate = sampleKeys.some(k => /strtdt|startdt|fromdt|enddt|todt/i.test(k));
                    if (hasCode && hasName && hasDate) {
                        const results = [];
                        for (const item of arr) {
                            const code = item.pjtCd || item.mgtCd || item.projCd || '';
                            const name = item.pjtNm || item.mgtNm || item.projNm || '';
                            if (code || name) {
                                results.push({
                                    code: String(code).trim(),
                                    name: String(name).trim(),
                                    start_date: item.strtDt || item.startDt || item.fromDt || '',
                                    end_date: item.endDt || item.toDt || item.fnshDt || '',
                                    status: item.pjtStNm || item.statusNm || item.stCdNm || ''
                                });
                            }
                        }
                        if (results.length >= expectedCount * 0.8) {
                            return {
                                projects: results,
                                method: 'react_anchor_' + key,
                                total: results.length,
                                expected: expectedCount
                            };
                        }
                    }
                }
            }
            fiber = fiber.return;
        }
    }

    return {
        error: 'react_data_not_found',
        expected: expectedCount,
        hasListContainer: !!listContainer,
        listScrollHeight: listContainer ? listContainer.scrollHeight : 0,
        listClientHeight: listContainer ? listContainer.clientHeight : 0
    };
})()
"""

# DOM에서 현재 화면에 보이는 카드 텍스트 수집
# 체크박스에 의존하지 않고, "코드. 이름" 패턴을 직접 탐색
_EXTRACT_VISIBLE_CARDS_JS = """
(() => {
    const seen = new Set();
    const results = [];
    // 코드 패턴: "GS-24-0001" 또는 "**임시"
    const codeRe = /^((?:[A-Z*]{2,}-?\\d{2}-?\\d{3,4})|(?:\\*{2}임시))\\.\\s*(.+)$/;
    const dateRe = /(\\d{8})\\s*~\\s*(\\d{8})\\s*\\/\\s*(\\S+)/;

    // 방법A: 모든 div/span에서 코드.이름 패턴 매칭
    const textEls = document.querySelectorAll('div, span');
    for (const el of textEls) {
        // 자식 요소가 3개 이하인 리프 노드급 요소만
        if (el.childElementCount > 3) continue;

        const text = el.textContent.trim();
        if (text.length < 5 || text.length > 200) continue;

        const cm = text.match(codeRe);
        if (!cm) continue;
        const code = cm[1].trim();
        if (seen.has(code)) continue;

        // 같은 카드 컨테이너에서 날짜 찾기
        let startDate = '', endDate = '', status = '';
        const parent = el.parentElement;
        if (parent) {
            const parentText = parent.textContent.trim();
            const dm = parentText.match(dateRe);
            if (dm) {
                startDate = dm[1];
                endDate = dm[2];
                status = dm[3].trim();
            }
        }

        seen.add(code);
        results.push({
            code: code,
            name: cm[2].trim(),
            start_date: startDate,
            end_date: endDate,
            status: status
        });
    }

    // 방법B: 전체 텍스트에서 정규식 매칭 (방법A가 부족할 때)
    if (results.length < 10) {
        const fullRe = /((?:[A-Z*]{2,}-?\\d{2}-?\\d{3,4})|(?:\\*{2}임시))\\.\\s*([^\\n\\d]+?)\\s*(\\d{8})\\s*~\\s*(\\d{8})\\s*\\/\\s*(\\S+)/g;
        const body = document.body?.innerText || '';
        let match;
        while ((match = fullRe.exec(body)) !== null) {
            const code = match[1].trim();
            if (!seen.has(code)) {
                seen.add(code);
                results.push({
                    code: code,
                    name: match[2].trim(),
                    start_date: match[3],
                    end_date: match[4],
                    status: match[5].trim()
                });
            }
        }
    }

    return results;
})()
"""


def _try_full_data_view(page) -> list:
    """
    "전체데이터보기" 버튼을 클릭하여 OBTDataGrid에서 전체 프로젝트 추출.
    프로젝트등록 페이지 우측 상단에 있는 버튼.
    """
    try:
        # "전체데이터보기" 버튼 클릭
        clicked = page.evaluate("""
            () => {
                const btns = document.querySelectorAll('button, [class*="OBTButton"], span, a');
                for (const el of btns) {
                    const txt = el.textContent.trim();
                    if (txt === '전체데이터보기' || txt === '전체 데이터보기' || txt === '전체데이터 보기') {
                        el.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        if not clicked:
            logger.info("'전체데이터보기' 버튼 미발견")
            return []

        page.wait_for_timeout(5000)
        _dismiss_alerts(page)
        _save_screenshot(page, "full_data_view")

        # OBTDataGrid가 나타났는지 확인 → 데이터 추출
        # 그룹 컬럼이 있는 그리드이므로 컬럼 헤더 텍스트로 매핑
        grid_result = page.evaluate("""
            () => {
                const grids = document.querySelectorAll('.OBTDataGrid_grid__22Vfl, [class*="OBTDataGrid"]');
                for (const el of grids) {
                    const fk = Object.keys(el).find(k =>
                        k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                    );
                    if (!fk) continue;

                    for (const maxD of [3, 5, 7]) {
                        let f = el[fk];
                        for (let i = 0; i < maxD && f; i++) f = f.return;
                        if (!f?.stateNode?.state?.interface) continue;

                        const iface = f.stateNode.state.interface;
                        try {
                            const rowCount = iface.getRowCount();
                            if (rowCount < 5) continue;

                            // 모든 컬럼 정보 수집 (그룹 컬럼 포함)
                            const colInfo = [];
                            try {
                                const cols = iface.getColumns();
                                const collectCols = (arr) => {
                                    for (const c of arr) {
                                        if (c.columns) collectCols(c.columns);
                                        else {
                                            const hdr = c.header ? (c.header.text || c.header) : '';
                                            colInfo.push({ name: c.name, header: hdr });
                                        }
                                    }
                                };
                                collectCols(cols);
                            } catch(e) {}

                            // 컬럼 정보가 없으면 DataSource 필드 사용
                            if (!colInfo.length) {
                                try {
                                    const ds = iface.getDataSource();
                                    const fns = ds.getFieldNames ? ds.getFieldNames() : [];
                                    fns.forEach(fn => colInfo.push({ name: fn, header: fn }));
                                } catch(e) {}
                            }

                            // 첫 번째 행의 값을 샘플로 읽어서 프로젝트코드 컬럼 식별
                            // (헤더 매핑 + 값 패턴 매핑 병행)
                            const headerMap = {};  // header text → field name
                            const codeColCandidates = [];
                            for (const ci of colInfo) {
                                headerMap[ci.header] = ci.name;
                                // 첫 행(row 0) 값 샘플
                                try {
                                    const val = String(iface.getValue(0, ci.name) || '');
                                    if (/^GS-\\d{2}-\\d{3,4}$/.test(val) || val === '**임시') {
                                        codeColCandidates.push(ci.name);
                                    }
                                } catch(e) {}
                            }

                            // 프로젝트코드/프로젝트명 컬럼 결정
                            // 헤더 부분 매칭 (포함 검색) — GW 헤더가 정확히 일치하지 않을 수 있음
                            const findCol = (keywords) => {
                                for (const kw of keywords) {
                                    // 정확 매칭 먼저
                                    if (headerMap[kw]) return headerMap[kw];
                                }
                                for (const kw of keywords) {
                                    // 부분 매칭
                                    for (const ci of colInfo) {
                                        if (ci.header && ci.header.includes(kw)) return ci.name;
                                    }
                                }
                                return '';
                            };
                            let codeCol = findCol(['프로젝트코드', '사업코드', '프로젝트 코드']) || codeColCandidates[0] || '';
                            let nameCol = findCol(['프로젝트명', '사업명', '프로젝트 명']);
                            let statusCol = findCol(['프로젝트구분', '상태', '구분']);
                            let abbrCol = findCol(['프로젝트약칭', '약칭']);
                            let startCol = findCol(['프로젝트기간일', '시작일', '기간일']);

                            // nameCol이 없으면 값으로 추정 (한글이 많은 컬럼)
                            if (!nameCol) {
                                for (const ci of colInfo) {
                                    if (ci.name === codeCol) continue;
                                    try {
                                        const val = String(iface.getValue(0, ci.name) || '');
                                        if (val.length > 2 && /[가-힣]/.test(val)) {
                                            nameCol = ci.name;
                                            break;
                                        }
                                    } catch(e) {}
                                }
                            }

                            // codeCol/nameCol 둘 다 없으면 모든 컬럼 값 샘플링하여 추정
                            if (!codeCol && !nameCol) {
                                // 모든 컬럼에서 첫 3행 값을 읽어 프로젝트코드/명 추정
                                for (const ci of colInfo) {
                                    const vals = [];
                                    for (let r = 0; r < Math.min(3, rowCount); r++) {
                                        try { vals.push(String(iface.getValue(r, ci.name) || '')); }
                                        catch(e) { vals.push(''); }
                                    }
                                    // GS-XX-XXXX 패턴이면 코드 컬럼
                                    if (!codeCol && vals.some(v => /^(GS|[A-Z]{2})-\\d{2}-\\d{3,4}$/.test(v))) {
                                        codeCol = ci.name;
                                    }
                                    // 한글 포함 + 길이 3이상 → 이름 후보
                                    if (!nameCol && ci.name !== codeCol && vals.some(v => v.length > 2 && /[가-힣]/.test(v))) {
                                        nameCol = ci.name;
                                    }
                                }
                            }

                            if (!codeCol && !nameCol) {
                                // 정말 매핑 실패 — 디버그용으로 모든 컬럼+첫 행 값 반환
                                const sample = {};
                                for (const ci of colInfo) {
                                    try { sample[ci.header || ci.name] = String(iface.getValue(0, ci.name) || ''); }
                                    catch(e) {}
                                }
                                return {
                                    error: 'column_mapping_failed',
                                    columns: colInfo.map(c => c.header + '=' + c.name),
                                    sample,
                                    rowCount
                                };
                            }

                            const rows = [];
                            for (let r = 0; r < rowCount; r++) {
                                const row = {};
                                if (codeCol) try { row.code = iface.getValue(r, codeCol) || ''; } catch(e) {}
                                if (nameCol) try { row.name = iface.getValue(r, nameCol) || ''; } catch(e) {}
                                if (statusCol) try { row.status = iface.getValue(r, statusCol) || ''; } catch(e) {}
                                if (abbrCol) try { row.abbr = iface.getValue(r, abbrCol) || ''; } catch(e) {}
                                if (startCol) try { row.start_date = iface.getValue(r, startCol) || ''; } catch(e) {}
                                rows.push(row);
                            }
                            return {
                                rows, rowCount,
                                mapping: { codeCol, nameCol, statusCol, abbrCol, startCol },
                                colHeaders: colInfo.map(c => c.header + '=' + c.name)
                            };
                        } catch(e) {
                            return { error: e.message };
                        }
                    }
                }
                return { error: 'no_grid' };
            }
        """)

        if not isinstance(grid_result, dict):
            logger.warning(f"전체데이터보기 그리드 evaluate 결과가 dict가 아님: {type(grid_result)}")
            _close_full_data_popup(page)
            return []

        if grid_result.get("error"):
            logger.info(f"전체데이터보기 그리드 추출 실패: {grid_result['error']}")
            if grid_result.get("columns"):
                logger.info(f"컬럼 목록: {grid_result['columns']}")
            if grid_result.get("sample"):
                logger.info(f"첫 행 샘플: {grid_result['sample']}")
            if grid_result.get("rowCount"):
                logger.info(f"행 수: {grid_result['rowCount']}")
            # 닫기 버튼 클릭
            _close_full_data_popup(page)
            return []

        logger.info(f"전체데이터보기 성공: {grid_result.get('rowCount')}행, "
                     f"매핑: {grid_result.get('mapping')}, "
                     f"컬럼: {grid_result.get('colHeaders', [])}")
        # 첫 3행 샘플 로깅
        sample_rows = grid_result.get("rows", [])[:3]
        for i, row in enumerate(sample_rows):
            logger.info(f"  row[{i}]: {row}")

        projects = []
        for row in grid_result.get("rows", []):
            code = str(row.get("code", "")).strip()
            name = str(row.get("name", "")).strip()
            if code or name:
                entry = {"code": code, "name": name}
                if row.get("status"):
                    entry["status"] = str(row["status"]).strip()
                if row.get("abbr"):
                    entry["abbr"] = str(row["abbr"]).strip()
                if row.get("start_date"):
                    entry["start_date"] = str(row["start_date"]).strip()
                projects.append(entry)

        logger.info(f"전체데이터보기 추출: {len(projects)}개 프로젝트")

        # 팝업 닫기
        _close_full_data_popup(page)

        return projects

    except Exception as e:
        logger.error(f"전체데이터보기 오류: {e}")
        return []


def _parse_project_list(raw_projects: list) -> list:
    """React/기타 소스에서 추출된 raw 프로젝트 데이터를 정리"""
    projects = []
    for p in raw_projects:
        code = str(p.get("code", "")).strip()
        name = str(p.get("name", "")).strip()
        if code or name:
            entry = {"code": code, "name": name}
            if p.get("start_date"):
                entry["start_date"] = str(p["start_date"]).strip()
            if p.get("end_date"):
                entry["end_date"] = str(p["end_date"]).strip()
            if p.get("status"):
                entry["status"] = str(p["status"]).strip()
            projects.append(entry)
    return projects


def _progressive_scroll_collect(page, max_scrolls=30) -> list:
    """
    카드 리스트를 스크롤하면서 현재 보이는 카드를 수집.
    가상 리스트(화면에 보이는 항목만 렌더링)에 대응.
    """
    all_projects = {}  # code → project dict (중복 제거용)

    try:
        for scroll_idx in range(max_scrolls):
            # 현재 화면에 보이는 카드 수집
            visible = page.evaluate(_EXTRACT_VISIBLE_CARDS_JS)
            for p in (visible or []):
                code = p.get("code", "")
                if code and code not in all_projects:
                    all_projects[code] = p

            # 스크롤 한 페이지 아래로
            done = page.evaluate("""
                () => {
                    // "프로젝트 NNN건" 근처의 스크롤 컨테이너 찾기
                    const allEls = document.querySelectorAll('span, div, strong, b');
                    let anchorEl = null;
                    for (const el of allEls) {
                        if (/프로젝트\\s*\\d+건/.test(el.textContent.trim())) {
                            anchorEl = el; break;
                        }
                    }
                    if (!anchorEl) return { done: true, reason: 'no_anchor' };

                    // 앵커 근처에서 스크롤 가능한 컨테이너 찾기
                    let container = anchorEl.parentElement;
                    for (let i = 0; i < 15 && container; i++) {
                        // 자식 div 중 스크롤 가능한 것
                        const allDivs = container.querySelectorAll('div');
                        for (const div of allDivs) {
                            if (div.scrollHeight > div.clientHeight + 50 &&
                                div.clientHeight > 100 &&
                                div.clientHeight < 900) {
                                // GS- 패턴이 있는 스크롤 영역인지 확인
                                if (div.textContent.includes('GS-') || div.textContent.includes('임시')) {
                                    const prevTop = div.scrollTop;
                                    div.scrollBy(0, div.clientHeight * 0.8);
                                    return {
                                        done: div.scrollTop === prevTop,
                                        scrollTop: div.scrollTop,
                                        scrollHeight: div.scrollHeight
                                    };
                                }
                            }
                        }
                        container = container.parentElement;
                    }
                    return { done: true, reason: 'no_scroll_container' };
                }
            """)

            if done.get("done"):
                # 마지막 위치에서 한번 더 수집
                visible = page.evaluate(_EXTRACT_VISIBLE_CARDS_JS)
                for p in (visible or []):
                    code = p.get("code", "")
                    if code and code not in all_projects:
                        all_projects[code] = p
                break

            page.wait_for_timeout(300)  # 렌더링 대기

        logger.info(f"프로그레시브 스크롤 수집: {len(all_projects)}개")

    except Exception as e:
        logger.error(f"프로그레시브 스크롤 오류: {e}")

    return list(all_projects.values())


def _save_screenshot(page, name: str):
    """디버그 스크린샷"""
    try:
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path))
        logger.info(f"스크린샷: {path}")
    except Exception as e:
        logger.warning(f"스크린샷 실패: {e}")


def _dismiss_alerts(page, max_tries=3):
    """OBTAlert 팝업 닫기"""
    for _ in range(max_tries):
        try:
            btn = page.locator(
                ".OBTAlert_alertBoxStyle__WdE7R button, "
                ".OBTButton_labelText__1s2qO:has-text('확인')"
            )
            if btn.count() > 0:
                btn.first.click(timeout=2000)
                page.wait_for_timeout(500)
            else:
                break
        except Exception:
            break


def _close_full_data_popup(page):
    """전체데이터보기 팝업 닫기 — 최상위 다이얼로그를 대상으로 닫기"""
    try:
        closed = page.evaluate("""
            () => {
                // OBTDialog2 다이얼로그를 찾아서 그 안의 버튼만 탐색 (다른 팝업 닫기 방지)
                const dialogs = document.querySelectorAll(
                    '[class*="OBTDialog2"], [class*="OBTFullDataViewDialog"], ' +
                    '[class*="dialog"][role="dialog"], [class*="Dialog"]'
                );
                // 가장 마지막(최상위) 다이얼로그부터 시도
                for (let i = dialogs.length - 1; i >= 0; i--) {
                    const dlg = dialogs[i];
                    // X 닫기 버튼 우선
                    const closeX = dlg.querySelector(
                        '[class*="closeButton"], [class*="close_button"], ' +
                        '[class*="OBTDialog2_closeButton"]'
                    );
                    if (closeX) {
                        closeX.click();
                        return 'close_x';
                    }
                    // "확인" / "닫기" 버튼
                    const btns = dlg.querySelectorAll('button');
                    for (const btn of btns) {
                        const txt = btn.textContent.trim();
                        if (txt === '확인' || txt === '닫기' || txt === '취소') {
                            btn.click();
                            return 'button:' + txt;
                        }
                    }
                }
                // 다이얼로그를 못 찾으면 전역 폴백 (이전 로직)
                const fallbackBtns = document.querySelectorAll(
                    '.OBTDialog2_buttonWrap__24xJY button'
                );
                for (const btn of fallbackBtns) {
                    const txt = btn.textContent.trim();
                    if (txt === '확인' || txt === '닫기') {
                        btn.click();
                        return 'fallback:' + txt;
                    }
                }
                return false;
            }
        """)
        if closed:
            logger.info(f"전체데이터보기 팝업 닫기: {closed}")
        else:
            logger.warning("전체데이터보기 팝업 닫기 버튼 미발견")
        page.wait_for_timeout(1000)
    except Exception as e:
        logger.warning(f"팝업 닫기 실패: {e}")


def _close_sidebar(page):
    """좌측 사이드바 닫기"""
    try:
        page.evaluate("""
            () => {
                const sw = document.getElementById('sideWrap');
                if (sw && sw.classList.contains('on')) sw.classList.remove('on');
            }
        """)
    except Exception:
        pass


def search_gw_projects(gw_id: str, search_name: str = "") -> dict:
    """
    GW 사업등록 페이지에서 프로젝트 목록을 조회하여 사업코드 목록 반환.
    search_name이 주어지면 해당 이름으로 필터링.

    Returns:
        { success, projects: [{code, name}, ...], error? }
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return {"success": False, "error": f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다."}

    pw = sync_playwright().start()
    browser = None
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        # BM 모듈 → 프로젝트 등록 페이지 이동
        page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        _dismiss_alerts(page)

        page_loaded = False

        # BM 모듈 클릭
        bm_link = page.locator("span.module-link.BM")
        if bm_link.count() > 0:
            bm_link.first.click()
            page.wait_for_timeout(4000)
            _dismiss_alerts(page)
            _close_sidebar(page)
            page.wait_for_timeout(1000)

            # 예산기초정보설정 → 프로젝트 등록
            page.evaluate("""
                () => {
                    const items = document.querySelectorAll('.nav-text, [class*="menu-text"], a, span');
                    for (const el of items) {
                        if (el.textContent.trim() === '예산기초정보설정' || el.textContent.trim() === '예산기초정보') {
                            el.click(); return true;
                        }
                    }
                    return false;
                }
            """)
            page.wait_for_timeout(2000)

            clicked = page.evaluate("""
                () => {
                    const items = document.querySelectorAll('.nav-text, [class*="menu-text"], a, span');
                    for (const el of items) {
                        const txt = el.textContent.trim();
                        if (txt === '프로젝트 등록' || txt === '프로젝트등록' || txt === '사업등록') {
                            el.click(); return true;
                        }
                    }
                    return false;
                }
            """)
            if clicked:
                page.wait_for_timeout(4000)
                _dismiss_alerts(page)
                page_loaded = True

        if not page_loaded:
            # 직접 URL 이동
            for url in [f"{GW_URL}/#/BN/NCB0100/NCB0100", f"{GW_URL}/#/BN/NCA0100/NCA0100"]:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                _dismiss_alerts(page)
                has_content = page.evaluate("""
                    () => {
                        // 카드 리스트 또는 그리드가 있는지 확인
                        const grid = document.querySelector('[class*="OBTDataGrid"]');
                        const checkboxes = document.querySelectorAll('input[type="checkbox"]');
                        return !!(grid || checkboxes.length > 3);
                    }
                """)
                if has_content:
                    page_loaded = True
                    break

        if not page_loaded:
            close_session(browser)
            return {"success": False, "error": "프로젝트 등록 페이지를 찾을 수 없습니다."}

        # 카드 리스트 로드 대기
        page.wait_for_timeout(3000)

        projects = []

        # === 1단계: "전체데이터보기" 버튼 → OBTDataGrid 추출 ===
        projects = _try_full_data_view(page)

        # === 2단계: React fiber에서 프로젝트 배열 추출 ===
        if len(projects) < 20:
            react_data = page.evaluate(_EXTRACT_REACT_PROJECT_DATA_JS)
            logger.info(f"React 추출: {react_data.get('method', react_data.get('error'))}, "
                         f"total={react_data.get('total', 0)}")
            if react_data.get("projects"):
                projects = _parse_project_list(react_data["projects"])

        # === 3단계: DOM 텍스트 파싱 + 프로그레시브 스크롤 ===
        if len(projects) < 20:
            logger.info("React 추출 부족, 프로그레시브 스크롤 수집 시작")
            scroll_projects = _progressive_scroll_collect(page)
            if len(scroll_projects) > len(projects):
                projects = scroll_projects

        # === 지출결의서/상신 문서 필터링 ===
        before = len(projects)
        projects = [p for p in projects
                    if not any(kw in p.get("name", "")
                               for kw in ["결의서", "상신의 건", "지급의 건", "요청의 건"])]
        if len(projects) < before:
            logger.info(f"문서 항목 {before - len(projects)}개 필터링 → {len(projects)}개")

        _save_screenshot(page, "gw_project_search")
        close_session(browser)

        return {
            "success": True,
            "projects": projects,
            "total": len(projects),
        }

    except Exception as e:
        logger.error(f"GW 프로젝트 검색 실패: {e}", exc_info=True)
        # 브라우저 세션 정리 (login 실패 시 browser가 None일 수 있음)
        if browser:
            try:
                close_session(browser)
            except Exception:
                pass
        return {"success": False, "error": str(e)}
    finally:
        pw.stop()


def crawl_project_info(gw_id: str, project_code: str, project_id: int = None):
    """
    단일 프로젝트의 GW 등록정보 크롤링.

    Args:
        gw_id: GW 로그인 ID
        project_code: GW 사업코드 (예: GS-25-0088)
        project_id: fund_management.db 프로젝트 ID (저장용)

    Returns:
        dict: { success, data?, error? }
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password

    if not project_code:
        return {"success": False, "error": "project_code가 필요합니다."}

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return {"success": False, "error": f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다."}

    pw = sync_playwright().start()
    browser = None
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        result = _navigate_to_project_detail(page, project_code)

        if result.get("success") and result.get("data"):
            # DB에 저장
            if project_id:
                _save_to_db(project_id, result["data"])
                result["saved"] = True

        close_session(browser)
        return result

    except Exception as e:
        logger.error(f"프로젝트 정보 크롤링 실패: {e}", exc_info=True)
        if browser:
            try:
                close_session(browser)
            except Exception:
                pass
        return {"success": False, "error": str(e)}
    finally:
        pw.stop()


def crawl_all_project_info(gw_id: str):
    """
    등록된 모든 프로젝트의 GW 정보 일괄 크롤링.
    project_code가 설정된 프로젝트만 대상.
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password
    from src.fund_table import db

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return {"success": False, "error": f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다."}

    projects = db.list_projects()
    targets = [p for p in projects if p.get("project_code")]

    if not targets:
        return {"success": False, "error": "project_code가 설정된 프로젝트가 없습니다."}

    pw = sync_playwright().start()
    results = []
    browser = None
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        for proj in targets:
            pid = proj["id"]
            pcode = proj["project_code"]
            pname = proj.get("name", "")
            logger.info(f"프로젝트 정보 크롤링: {pname} ({pcode})")

            try:
                result = _navigate_to_project_detail(page, pcode)
                if result.get("success") and result.get("data"):
                    _save_to_db(pid, result["data"])
                    results.append({
                        "project_id": pid, "project_name": pname,
                        "status": "success", "data": result["data"],
                    })
                else:
                    results.append({
                        "project_id": pid, "project_name": pname,
                        "status": "fail", "message": result.get("error", "추출 실패"),
                    })
            except Exception as e:
                logger.error(f"프로젝트 {pname} 크롤링 오류: {e}")
                results.append({
                    "project_id": pid, "project_name": pname,
                    "status": "error", "message": str(e),
                })

        close_session(browser)
    except Exception as e:
        logger.error(f"일괄 크롤링 실패: {e}", exc_info=True)
        if browser:
            try:
                close_session(browser)
            except Exception:
                pass
        return {"success": False, "error": str(e), "results": results}
    finally:
        pw.stop()

    success_count = sum(1 for r in results if r["status"] == "success")
    return {
        "success": True,
        "message": f"{success_count}/{len(targets)} 프로젝트 정보 크롤링 완료",
        "results": results,
    }


def _navigate_to_project_detail(page, project_code: str) -> dict:
    """
    GW 프로젝트 등록정보 페이지로 이동 + 데이터 추출.

    탐색 전략:
    1. 예산관리(BM) → 사업등록 메뉴
    2. 사업코드 검색 → 상세 페이지 접근
    3. React state에서 프로젝트 정보 추출
    """
    try:
        # GW 메인으로 이동
        page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        _dismiss_alerts(page)

        page_loaded = False

        # === 방법 A: 예산관리(BM) → 예산기초정보설정 → 프로젝트 등록 ===
        bm_link = page.locator("span.module-link.BM")
        if bm_link.count() > 0:
            bm_link.first.click()
            page.wait_for_timeout(4000)
            _dismiss_alerts(page)
            _close_sidebar(page)
            page.wait_for_timeout(1000)
            logger.info(f"BM 모듈 클릭 후 URL: {page.url}")

            # 1단계: "예산기초정보설정" 메뉴 클릭 (펼치기)
            step1 = page.evaluate("""
                () => {
                    const items = document.querySelectorAll(
                        '.nav-text, [class*="menu-text"], [class*="menuText"], a, span'
                    );
                    for (const el of items) {
                        const txt = el.textContent.trim();
                        if (txt === '예산기초정보설정' || txt === '예산기초정보') {
                            el.click();
                            return { found: txt, clicked: true };
                        }
                    }
                    return {
                        found: null,
                        menus: Array.from(items)
                            .map(el => el.textContent.trim())
                            .filter(t => t.length > 0 && t.length < 30)
                            .slice(0, 50)
                    };
                }
            """)
            logger.info(f"예산기초정보설정 메뉴: {step1}")
            page.wait_for_timeout(2000)

            # 2단계: "프로젝트 등록" 또는 "프로젝트등록" 클릭
            step2 = page.evaluate("""
                () => {
                    const items = document.querySelectorAll(
                        '.nav-text, [class*="menu-text"], [class*="menuText"], a, span'
                    );
                    for (const el of items) {
                        const txt = el.textContent.trim();
                        if (txt === '프로젝트 등록' || txt === '프로젝트등록'
                            || txt === '사업등록' || txt === '프로젝트관리') {
                            el.click();
                            return { found: txt, clicked: true };
                        }
                    }
                    return {
                        found: null,
                        subMenus: Array.from(items)
                            .map(el => el.textContent.trim())
                            .filter(t => t.length > 0 && t.length < 30)
                            .slice(0, 50)
                    };
                }
            """)
            logger.info(f"프로젝트 등록 메뉴: {step2}")
            page.wait_for_timeout(4000)
            _dismiss_alerts(page)

            if step2.get("clicked"):
                page_loaded = True
                _save_screenshot(page, "project_reg_page")
            else:
                logger.warning(f"프로젝트 등록 메뉴 미발견. 하위 메뉴: {step2}")
                _save_screenshot(page, "project_reg_menu_not_found")

        if not page_loaded:
            # === 방법 B: 직접 URL 이동 (메뉴코드 추정) ===
            possible_urls = [
                f"{GW_URL}/#/BN/NCB0100/NCB0100",  # 사업등록 추정
                f"{GW_URL}/#/BN/NCB0110/NCB0110",  # 사업현황 추정
                f"{GW_URL}/#/BN/NCA0100/NCA0100",  # 예산기초 사업등록
            ]
            for url in possible_urls:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                _dismiss_alerts(page)

                # 페이지 로드 확인 (그리드 또는 폼 필드 존재)
                has_content = page.evaluate("""
                    () => {
                        const grid = document.querySelector('[class*="OBTDataGrid"]');
                        const form = document.querySelector(
                            'input[placeholder*="사업코드"], input[placeholder*="프로젝트"]'
                        );
                        return !!(grid || form);
                    }
                """)
                if has_content:
                    logger.info(f"URL 직접 이동 성공: {url}")
                    page_loaded = True
                    _save_screenshot(page, "project_reg_direct_url")
                    break

        if not page_loaded:
            # 디버깅 정보 수집
            _save_screenshot(page, "project_page_not_found")
            page_info = page.evaluate("""
                () => ({
                    url: location.href,
                    title: document.title,
                    modules: Array.from(document.querySelectorAll('.module-link'))
                        .map(m => m.className + ':' + m.textContent.trim()),
                    allMenus: Array.from(document.querySelectorAll(
                        '.nav-text, [class*="menu-text"], [class*="menuText"]'
                    )).map(el => el.textContent.trim()).filter(t => t.length > 0).slice(0, 80)
                })
            """)
            logger.warning(f"프로젝트 등록 페이지 미발견. 페이지 정보: {page_info}")
            return {
                "success": False,
                "error": "프로젝트 등록 페이지를 찾을 수 없습니다.",
                "page_info": page_info,
            }

        # === 프로젝트 코드로 검색 ===
        search_result = _search_and_select_project(page, project_code)
        if not search_result.get("success"):
            return search_result

        page.wait_for_timeout(3000)
        _save_screenshot(page, f"project_detail_{project_code}")

        # === 데이터 추출 ===
        data = page.evaluate(_EXTRACT_PROJECT_INFO_JS)
        logger.info(f"추출된 프로젝트 정보: {data}")

        if not data or (not data.get("project_code") and not data.get("project_name")
                        and not data.get("_react_head")):
            # 카드 리스트에서 추출 시도
            card_data = page.evaluate(_EXTRACT_REACT_PROJECT_DATA_JS)
            if card_data.get("projects"):
                for p in card_data["projects"]:
                    code_val = p.get("code", "")
                    if project_code in str(code_val):
                        data = {
                            "project_code": p.get("code", ""),
                            "project_name": p.get("name", ""),
                            "start_date": p.get("start_date", ""),
                            "end_date": p.get("end_date", ""),
                            "status": p.get("status", ""),
                        }
                        break
                if not data:
                    data = {"_card_data": card_data, "_note": "코드 매칭 실패"}

        if not data or not any(data.get(k) for k in
                               ["project_code", "project_name", "start_date", "end_date"]):
            _save_screenshot(page, f"project_no_data_{project_code}")
            return {
                "success": False,
                "error": "프로젝트 정보를 추출할 수 없습니다.",
                "raw_data": data,
            }

        return {"success": True, "data": data, "project_code": project_code}

    except Exception as e:
        _save_screenshot(page, "project_crawl_exception")
        logger.error(f"프로젝트 정보 추출 오류: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _search_and_select_project(page, project_code: str) -> dict:
    """사업코드로 프로젝트 검색 + 선택"""
    try:
        _dismiss_alerts(page)

        # 사업코드 입력 필드 탐색
        search_input = page.locator(
            "input[placeholder*='사업코드']:not(#search_input):not(#searchInput)"
        )
        if search_input.count() == 0:
            search_input = page.locator("input[placeholder*='프로젝트']:not(#search_input)")
        if search_input.count() == 0:
            search_input = page.locator("[class*='OBTSearchHelp'] input[type='text']")
        if search_input.count() == 0:
            search_input = page.locator(
                "[class*='OBTConditionPanel'] input[type='text']"
            )

        if search_input.count() == 0:
            # 조회 조건 없이 그리드가 이미 있으면 성공으로 처리
            grid = page.locator("[class*='OBTDataGrid']")
            if grid.count() > 0:
                logger.info("검색 필드 없지만 그리드 발견 — 그리드에서 직접 검색")
                return {"success": True}
            return {"success": False, "error": "사업코드 입력 필드를 찾을 수 없습니다."}

        # 코드 입력 + 엔터
        search_input.first.click(timeout=5000)
        search_input.first.fill("")
        page.wait_for_timeout(300)
        search_input.first.fill(project_code)
        page.wait_for_timeout(500)
        search_input.first.press("Enter")
        page.wait_for_timeout(2000)
        _dismiss_alerts(page)

        # 팝업에서 선택
        _select_popup_item(page, project_code)

        # 조회 버튼 클릭
        _click_search_button(page)
        page.wait_for_timeout(3000)

        return {"success": True}

    except Exception as e:
        return {"success": False, "error": f"프로젝트 검색 오류: {e}"}


def _select_popup_item(page, project_code: str):
    """검색 도움 팝업에서 항목 선택"""
    try:
        portal = page.locator(
            ".OBTPortal_orbitPortalRoot__3FIEo, [class*='OBTDialog'], [class*='OBTPopup']"
        )
        if portal.count() == 0:
            return

        page.evaluate("""
            (code) => {
                const portals = document.querySelectorAll('.OBTPortal_orbitPortalRoot__3FIEo');
                for (const portal of portals) {
                    const grids = portal.querySelectorAll('[class*="OBTDataGrid"]');
                    for (const el of grids) {
                        const fk = Object.keys(el).find(k =>
                            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                        );
                        if (!fk) continue;

                        let f = el[fk];
                        for (let i = 0; i < 5 && f; i++) f = f.return;
                        if (!f?.stateNode?.state?.interface) {
                            f = el[fk];
                            for (let i = 0; i < 3 && f; i++) f = f.return;
                        }
                        if (!f?.stateNode?.state?.interface) continue;

                        const iface = f.stateNode.state.interface;
                        const rowCount = iface.getRowCount();

                        for (let r = 0; r < rowCount; r++) {
                            let val = '';
                            try { val = iface.getValue(r, 'mgtCd'); } catch(e) {}
                            if (!val) try { val = iface.getValue(r, 'pjtCd'); } catch(e) {}

                            if (val === code) {
                                try {
                                    iface.setSelection({
                                        startRow: r, endRow: r, startColumn: 0, endColumn: 0
                                    });
                                    iface.focus();
                                } catch(e) {}

                                const canvas = el.querySelector('canvas');
                                if (canvas) {
                                    const y = 30 + r * 30 + 15;
                                    canvas.dispatchEvent(new MouseEvent('dblclick', {
                                        bubbles: true,
                                        clientX: 50,
                                        clientY: canvas.getBoundingClientRect().top + y
                                    }));
                                }
                                return true;
                            }
                        }
                    }
                }
                return false;
            }
        """, project_code)
        page.wait_for_timeout(1000)
    except Exception as e:
        logger.debug(f"팝업 선택 오류: {e}")


def _click_search_button(page):
    """조회 버튼 클릭"""
    try:
        page.evaluate("""
            () => {
                const btns = document.querySelectorAll(
                    'button, [class*="OBTButton"]'
                );
                for (const btn of btns) {
                    const text = btn.textContent.trim();
                    if (text === '조회' || text === '검색') {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }
        """)
    except Exception:
        pass


def _map_grid_row(row: dict) -> dict:
    """그리드 행 데이터를 프로젝트 정보로 매핑"""
    return {
        "project_code": row.get("mgtCd") or row.get("pjtCd") or "",
        "project_name": row.get("mgtNm") or row.get("pjtNm") or "",
        "start_date": row.get("strtDt") or row.get("startDt") or row.get("fromDt") or "",
        "end_date": row.get("endDt") or row.get("toDt") or row.get("fnshDt") or "",
        "duration": row.get("pjtPrd") or row.get("duration") or "",
        "manager": row.get("mgrEmpNm") or row.get("charger") or "",
        "client": row.get("clientNm") or row.get("custNm") or "",
        "status": row.get("pjtStNm") or row.get("statusNm") or "",
    }


def _save_to_db(project_id: int, data: dict):
    """크롤링 데이터를 fund_management DB 개요에 저장"""
    from src.fund_table import db

    overview_updates = {}

    # 날짜 필드 매핑
    if data.get("start_date"):
        # 형식 통일: YYYY-MM-DD
        date_str = _normalize_date(data["start_date"])
        if date_str:
            overview_updates["construction_start"] = date_str
    if data.get("end_date"):
        date_str = _normalize_date(data["end_date"])
        if date_str:
            overview_updates["construction_end"] = date_str

    # 발주처/고객사
    if data.get("client"):
        overview_updates["client"] = data["client"]

    # 담당자
    if data.get("manager"):
        overview_updates["manager"] = data["manager"]

    # 프로젝트 코드 업데이트
    if data.get("project_code"):
        db.update_project(project_id, project_code=data["project_code"])

    # 개요 저장
    if overview_updates:
        # 기존 개요 가져와서 병합
        existing = db.get_project_overview(project_id) or {}
        existing.update(overview_updates)
        db.save_project_overview(project_id, existing)
        logger.info(f"프로젝트 {project_id} 개요 업데이트: {list(overview_updates.keys())}")


def _normalize_date(date_str: str) -> str | None:
    """다양한 날짜 형식을 YYYY-MM-DD로 변환"""
    if not date_str:
        return None
    date_str = date_str.strip()

    # YYYYMMDD → YYYY-MM-DD
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    # YYYY-MM-DD 이미 올바른 형식
    if len(date_str) == 10 and date_str[4] == '-' and date_str[7] == '-':
        return date_str
    # YYYY.MM.DD → YYYY-MM-DD
    if '.' in date_str:
        return date_str.replace('.', '-')
    # YYYY/MM/DD → YYYY-MM-DD
    if '/' in date_str:
        return date_str.replace('/', '-')

    return date_str
