"""
전자결재 자동화 -- OBTDataGrid 그리드 조작 mixin
"""

import logging
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from src.approval.base import _GET_GRID_IFACE_JS, _save_debug, _js_str

logger = logging.getLogger("approval_automation")


class GridMixin:
    """OBTDataGrid 그리드 셀 입력/조작"""

    def _fill_grid_items(self, items: list[dict]):
        """
        지출내역 그리드에 항목 입력

        그리드는 RealGrid(realgridjs) 커스텀 컴포넌트:
        - 셀 클릭 -> 편집 모드 활성화 -> input 나타남 -> 값 입력 -> Tab/Enter로 확정
        - "추가" 버튼으로 새 행 추가 (DOM 기준 x=1808, y=373)
        - 첫 번째 행은 이미 존재 (빈 행)
        - RealGrid API 우선 시도, 실패 시 좌표 기반 폴백

        Args:
            items: [
                {"item": "항목명", "amount": 100000},  # 간단 형식 (agent.py 호환)
                {"content": "내용", "vendor": "거래처", "supply_amount": 50000, "tax_amount": 5000},  # 상세 형식
            ]
        """
        if not items:
            return

        logger.info(f"지출내역 그리드 입력 시작: {len(items)}개 항목")

        for row_idx, item_data in enumerate(items):
            # 첫 행은 이미 있음, 2번째부터 "추가" 버튼 클릭
            if row_idx > 0:
                self._click_grid_add_button()
                self.page.wait_for_timeout(1000)

            # 각 필드 입력
            filled_count = 0
            for key, value in item_data.items():
                if not value:
                    continue

                col_name = self.ITEM_KEY_TO_COL.get(key)
                if not col_name:
                    continue

                col_idx = self.GRID_COL_MAP.get(col_name)
                if col_idx is None:
                    continue

                success = self._fill_grid_cell(row_idx, col_idx, col_name, str(value))
                if success:
                    filled_count += 1

            logger.info(f"그리드 행 {row_idx}: {filled_count}개 필드 입력")

        logger.info("지출내역 그리드 입력 완료")

    def _click_grid_add_button(self):
        """그리드 "추가" 버튼 클릭하여 새 행 추가"""
        page = self.page

        # 지출내역 헤더 y 기준으로 동적 범위 계산 (fullscreen 호환)
        grid_y_min, grid_y_max = 300, 500  # 기본 범위
        try:
            header_el = page.locator("text='지출내역'").first
            if header_el.is_visible(timeout=1000):
                hbox = header_el.bounding_box()
                if hbox:
                    grid_y_min = hbox["y"] - 20
                    grid_y_max = hbox["y"] + 150
        except Exception:
            pass

        # 방법 1: 텍스트 기반 버튼 탐색 (y 범위 동적 적용)
        for selector in [
            "button:has-text('추가')",
            "button:has-text('행추가')",
            "[title='추가']",
            "[title='행추가']",
            "button.add-row",
            "text=추가",
        ]:
            try:
                btns = page.locator(selector).all()
                for btn in btns:
                    if btn.is_visible():
                        box = btn.bounding_box()
                        if box and grid_y_min < box["y"] < grid_y_max:
                            btn.click(force=True)
                            logger.info(f"그리드 '추가' 버튼 클릭 (sel='{selector}', y={box['y']:.0f})")
                            return True
            except Exception:
                continue

        # 방법 2: 지출내역 그리드 컨테이너 내 추가 버튼 탐색
        for container_sel in [
            "div.OBTDataGrid_grid__22Vfl",
            "div[class*='OBTDataGrid']",
            "div[class*='grid-container']",
            "div[class*='gridContainer']",
        ]:
            try:
                container = page.locator(container_sel).first
                if container.is_visible(timeout=1000):
                    add_btn = container.locator("button:has-text('추가'), button:has-text('행추가')").first
                    if add_btn.is_visible(timeout=1000):
                        add_btn.click(force=True)
                        logger.info(f"그리드 '추가' 버튼 클릭 (컨테이너 내부 '{container_sel}')")
                        return True
            except Exception:
                continue

        # 방법 3: OBTDataGrid 컨테이너 인접(외부) 버튼 탐색
        for adj_sel in [
            ".OBTDataGrid_grid__22Vfl + * button:has-text('추가')",
            ".OBTDataGrid_grid__22Vfl ~ * button:has-text('추가')",
            "* + .OBTDataGrid_grid__22Vfl button:has-text('추가')",
            "[class*='OBTDataGrid'] ~ button:has-text('추가')",
            "[class*='OBTDataGrid'] + button",
            "[title='행추가']",
            "[aria-label*='추가']",
            "button[class*='add']",
            "button[class*='row-add']",
        ]:
            try:
                el = page.locator(adj_sel).first
                if el.is_visible(timeout=1000):
                    el.click(force=True)
                    logger.info(f"그리드 '추가' 버튼 클릭 (인접 셀렉터 '{adj_sel}')")
                    return True
            except Exception:
                continue

        # 방법 4: JS로 그리드 인접 '추가' 버튼 동적 탐색 + 직접 클릭
        try:
            js_result = page.evaluate("""() => {
                const grid = document.querySelector('.OBTDataGrid_grid__22Vfl, [class*="OBTDataGrid"]');
                const gridRect = grid ? grid.getBoundingClientRect() : null;
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
                let best = null, bestDist = Infinity;
                for (const btn of buttons) {
                    const text = btn.textContent.trim();
                    if (!['추가', '행추가', '+'].includes(text)) continue;
                    const r = btn.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    const dist = gridRect ? Math.abs(r.top - gridRect.top) : 0;
                    if (dist < bestDist) {
                        bestDist = dist;
                        best = btn;
                    }
                }
                if (best) {
                    best.click();
                    return { clicked: true };
                }
                return null;
            }""")
            if js_result and js_result.get("clicked"):
                logger.info("그리드 '추가' 버튼 클릭 (JS직접클릭)")
                return True
        except Exception as e:
            logger.debug(f"그리드 '추가' JS 탐색 실패: {e}")

        # 폴백 5: Playwright locator로 '추가' 버튼 찾기 (y 범위 무시)
        try:
            add_btn = page.locator("button:has-text('추가')").first
            if add_btn.is_visible(timeout=2000):
                add_btn.click(force=True)
                logger.info("그리드 '추가' 버튼 클릭 (Playwright locator 폴백)")
                return True
        except Exception:
            pass

        # 최종 폴백: DOM 데이터 기준 하드코딩 좌표 (x=1808, y=373)
        try:
            logger.warning("그리드 '추가' 버튼 셀렉터 모두 실패, 좌표 폴백: (1808, 373)")
            page.mouse.click(1808, 373)
            logger.info("그리드 '추가' 버튼 클릭 (좌표 폴백 x=1808, y=373)")
            return True
        except Exception as e:
            logger.warning(f"그리드 '추가' 좌표 폴백도 실패: {e}")

        logger.warning("그리드 '추가' 버튼을 찾지 못했습니다")
        return False

    def _fill_grid_cell(self, row_idx: int, col_idx: int, col_name: str, value: str) -> bool:
        """
        그리드 셀에 값 입력

        RealGrid 동작:
        1. 셀 영역 클릭 -> 편집 모드 활성화
        2. 활성화된 input/textarea에 값 입력
        3. Tab 키로 다음 셀 이동 (값 확정)

        Args:
            row_idx: 행 인덱스 (0-based)
            col_idx: 열 인덱스 (0-based, 체크박스 제외)
            col_name: 열 이름 (로깅용)
            value: 입력할 값
        """
        page = self.page

        try:
            # 방법 1: RealGrid JavaScript API로 값 직접 설정
            # RealGrid는 canvas 기반으로 표준 DOM 접근이 불가하므로 JS API 우선
            if self._fill_grid_cell_via_realgrid_api(row_idx, col_idx, col_name, value):
                return True

            # 방법 2: div[role="row"] 기반 탐색 (일부 그리드)
            grid_rows = page.locator("div[role='row']").all()

            if not grid_rows or row_idx >= len(grid_rows):
                logger.debug(f"그리드 행 {row_idx} 찾기 실패 (총 {len(grid_rows)}행)")
                return self._fill_grid_cell_by_position(row_idx, col_idx, col_name, value)

            row = grid_rows[row_idx]
            # 체크박스 td 건너뛰기: col_idx + 1 (또는 +2 if 확장 아이콘)
            cells = row.locator("td, div[role='gridcell']").all()

            # 체크박스 + 확장아이콘 2개 건너뛰기
            actual_col = col_idx + 2
            if actual_col >= len(cells):
                actual_col = col_idx + 1

            if actual_col >= len(cells):
                logger.debug(f"셀 인덱스 초과: row={row_idx}, col={actual_col}, total={len(cells)}")
                return self._fill_grid_cell_by_position(row_idx, col_idx, col_name, value)

            cell = cells[actual_col]
            return self._activate_and_fill_cell(cell, col_name, value)

        except Exception as e:
            logger.debug(f"그리드 셀 입력 실패 (row={row_idx}, col={col_name}): {e}")
            return self._fill_grid_cell_by_position(row_idx, col_idx, col_name, value)

    def _fill_grid_cell_via_realgrid_api(
        self, row_idx: int, col_idx: int, col_name: str, value: str
    ) -> bool:
        """
        RealGrid JavaScript API를 통해 그리드 셀 값 직접 설정.

        RealGrid API 패턴:
        - window.gridView (또는 첫 번째 GridView 인스턴스)를 찾아서
        - gridView.setValue(itemIndex, fieldName, value) 또는
        - gridView.setValues(itemIndex, {fieldName: value}) 호출

        컬럼 필드명은 RealGrid 설정에 따라 달라질 수 있음:
        '내용', 'content', 'CONT', 'col_1' 등 다양
        """
        page = self.page

        # RealGrid 컬럼 인덱스 -> 필드명 매핑 (실제 그리드 설정에 따라 달라짐)
        # 좌표 클릭으로 셀을 활성화한 뒤 편집 input에 type하는 방식이 더 안전
        try:
            result = page.evaluate(f"""
            (function() {{
                // RealGrid 인스턴스 찾기
                const gridNames = ['gridView', 'grid', 'expenseGrid', 'detailGrid'];
                let gv = null;
                for (const name of gridNames) {{
                    if (window[name] && typeof window[name].setCurrent === 'function') {{
                        gv = window[name];
                        break;
                    }}
                }}
                if (!gv) return false;

                // 셀 포커스 이동 (itemIndex, columnIndex)
                try {{
                    gv.setCurrent({{ itemIndex: {row_idx}, column: {col_idx + 1} }});
                    return true;
                }} catch(e) {{
                    return false;
                }}
            }})()
            """)

            if result:
                # 편집 모드 input에 값 입력
                active_input = page.locator("input:focus, textarea:focus").first
                if active_input.is_visible(timeout=1000):
                    active_input.fill(str(value))
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (RealGrid API): {value}")
                    return True
        except Exception as e:
            logger.debug(f"RealGrid API 시도 실패 ({col_name}): {e}")

        return False

    def _activate_and_fill_cell(self, cell, col_name: str, value: str) -> bool:
        """셀 클릭하여 활성화 -> input에 값 입력"""
        page = self.page

        try:
            # 1. 셀 클릭 -> 편집 모드 활성화
            cell.click(force=True)
            self.page.wait_for_timeout(500)

            # 2. 활성화된 input 찾기 (셀 내부 또는 페이지 전체에서)
            # RealGrid는 활성 셀에 overlay input을 동적으로 생성
            inp = cell.locator("input:visible, textarea:visible").first
            try:
                if inp.is_visible(timeout=1000):
                    inp.fill("")
                    inp.fill(value)
                    # Tab으로 값 확정
                    inp.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력: {value}")
                    return True
            except Exception:
                pass

            # 3. 셀 내부에 input이 없으면 포커스된 input 찾기
            # OBTGrid가 overlay input을 사용하는 경우
            active_input = page.locator("input:focus, textarea:focus").first
            try:
                if active_input.is_visible(timeout=1000):
                    active_input.fill("")
                    active_input.fill(value)
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (focus): {value}")
                    return True
            except Exception:
                pass

            # 4. 더블클릭 시도 (일부 그리드는 더블클릭으로 편집)
            cell.dblclick(force=True)
            self.page.wait_for_timeout(500)

            inp = cell.locator("input:visible, textarea:visible").first
            try:
                if inp.is_visible(timeout=1000):
                    inp.fill("")
                    inp.fill(value)
                    inp.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (dblclick): {value}")
                    return True
            except Exception:
                pass

            logger.debug(f"그리드 '{col_name}' 셀 활성화 후 input 미발견")
            return False

        except Exception as e:
            logger.debug(f"그리드 셀 활성화 실패 ({col_name}): {e}")
            return False

    def _fill_grid_cell_by_position(self, row_idx: int, col_idx: int, col_name: str, value: str) -> bool:
        """
        그리드 셀 입력 (폴백 계층)

        방법 A-0: OBTDataGrid setValue() API -- 값을 직접 설정 (좌표/포커스 불필요)
        방법 A: OBTDataGrid React Fiber interface -- 헤더명/인덱스로 컬럼 찾아 포커스 후 키보드 입력
        방법 A-2: OBTDataGrid 컬럼 폭 기반 동적 좌표 계산 후 클릭
        방법 B: 하드코딩 좌표 단클릭 → input:focus → fill (폴백)
        방법 C: 하드코딩 좌표 더블클릭 → input:focus → fill (최종 폴백)

        DOM 탐색 기준 좌표 (방법 B/C 폴백용):
        - 그리드 첫 행 y ~ 345, 행 높이 ~ 28px
        - 컬럼 x: 용도~560, 내용~680, 거래처~850, 공급가액~960, 부가세~1070, 합계액~1140
        """
        page = self.page

        # ── 방법 A-0: OBTDataGrid setValue() API로 값 직접 설정 ──
        # 가장 안정적: 좌표/포커스 없이 API로 바로 값 입력
        try:
            # 지출내역 그리드는 보통 두 번째 OBTDataGrid (첫 번째는 헤더/상단 그리드)
            set_result = page.evaluate(f"""() => {{
                try {{
                    const grids = document.querySelectorAll('.OBTDataGrid_grid__22Vfl, [class*="OBTDataGrid"]');
                    // 지출내역 그리드 찾기: 여러 그리드 중 행이 있는 것 우선
                    let iface = null;
                    for (let gi = grids.length - 1; gi >= 0; gi--) {{
                        const el = grids[gi];
                        const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                        if (!fk) continue;
                        let f = el[fk];
                        for (let i = 0; i < 3 && f; i++) f = f.return;
                        if (!f || !f.stateNode || !f.stateNode.state || !f.stateNode.state.interface) continue;
                        const candidate = f.stateNode.state.interface;
                        if (typeof candidate.setValue === 'function' && typeof candidate.getColumns === 'function') {{
                            iface = candidate;
                            break;
                        }}
                    }}
                    if (!iface) return {{ success: false, reason: 'no_iface' }};

                    // 헤더명으로 컬럼 탐색
                    const cols = iface.getColumns();
                    let col = cols.find(c => c.header === {_js_str(col_name)} || c.name === {_js_str(col_name)});
                    if (!col && cols.length > {col_idx}) col = cols[{col_idx}];
                    if (!col) return {{ success: false, reason: 'no_col', available: cols.map(c => c.header || c.name) }};

                    iface.setValue({row_idx}, col.name, {_js_str(value)});
                    iface.commit();
                    return {{ success: true, usedCol: col.name, method: 'setValue' }};
                }} catch(e) {{
                    return {{ success: false, reason: 'exception', error: e.message }};
                }}
            }}""")

            if set_result and set_result.get("success"):
                logger.info(f"그리드 '{col_name}' 입력 (OBTDataGrid setValue API, col={set_result.get('usedCol')}): {value}")
                return True
            else:
                logger.debug(f"그리드 '{col_name}' 방법A-0(setValue) 미적용: {set_result}")
        except Exception as e:
            logger.debug(f"그리드 '{col_name}' 방법A-0(setValue) 예외: {e}")

        # ── 방법 A: OBTDataGrid interface -> setSelection + focus + 키보드 입력 ──
        try:
            obt_result = page.evaluate(f"""() => {{
                const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                if (!el) return {{ success: false, reason: 'no_el' }};
                const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                if (!fk) return {{ success: false, reason: 'no_fiber' }};
                let f = el[fk];
                for (let i = 0; i < 3; i++) f = f ? f.return : null;
                if (!f || !f.stateNode || !f.stateNode.state || !f.stateNode.state.interface)
                    return {{ success: false, reason: 'no_iface' }};
                const iface = f.stateNode.state.interface;
                if (typeof iface.getColumns !== 'function') return {{ success: false, reason: 'no_getCols' }};

                // 헤더명으로 컬럼 탐색, 없으면 col_idx 순서로 fallback
                const cols = iface.getColumns();
                let col = cols.find(c => c.header === {_js_str(col_name)} || c.name === {_js_str(col_name)});
                if (!col && cols.length > {col_idx}) col = cols[{col_idx}];
                if (!col) return {{ success: false, reason: 'no_col', available: cols.map(c => c.header) }};

                iface.setSelection({{ rowIndex: {row_idx}, columnName: col.name }});
                iface.focus();
                return {{ success: true, usedCol: col.name }};
            }}""")

            if obt_result and obt_result.get("success"):
                self.page.wait_for_timeout(300)
                page.keyboard.type(str(value), delay=20)
                self.page.wait_for_timeout(200)
                page.keyboard.press("Tab")
                logger.info(f"그리드 '{col_name}' 입력 (OBTDataGrid방법A, col={obt_result.get('usedCol')}): {value}")
                return True
            else:
                logger.debug(f"그리드 '{col_name}' 방법A 미적용: {obt_result}")
        except Exception as e:
            logger.debug(f"그리드 '{col_name}' 방법A 예외: {e}")

        # ── 방법 A-2: OBTDataGrid 컬럼 폭 기반 동적 좌표 계산 ──
        try:
            obt_coords = page.evaluate(f"""() => {{
                const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                if (!el) return null;
                const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                if (!fk) return null;
                let f = el[fk];
                for (let i = 0; i < 3; i++) f = f ? f.return : null;
                if (!f || !f.stateNode || !f.stateNode.state || !f.stateNode.state.interface)
                    return null;
                const iface = f.stateNode.state.interface;
                if (typeof iface.getColumns !== 'function') return null;
                const cols = iface.getColumns();
                let col = cols.find(c => c.header === {_js_str(col_name)} || c.name === {_js_str(col_name)});
                if (!col && cols.length > {col_idx}) col = cols[{col_idx}];
                if (!col) return null;

                const rect = el.getBoundingClientRect();
                let xOff = rect.left;
                for (let i = 0; i < cols.length; i++) {{
                    const w = cols[i].width || 100;
                    if (cols[i].name === col.name || cols[i].header === col.header) {{
                        xOff += w / 2;
                        break;
                    }}
                    xOff += w;
                }}
                const rowH = 28;
                const yOff = rect.top + rowH * {row_idx} + rowH / 2;
                return {{ x: xOff, y: yOff }};
            }}""")
            if obt_coords:
                # 먼저 setSelection + F2/Enter로 편집 모드 시도 (좌표 불필요)
                edit_mode = False
                try:
                    edit_mode = page.evaluate(f"""() => {{
                        const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                        if (!el) return false;
                        const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                        if (!fk) return false;
                        let f = el[fk];
                        for (let i = 0; i < 3; i++) f = f ? f.return : null;
                        if (!f || !f.stateNode || !f.stateNode.state || !f.stateNode.state.interface) return false;
                        const iface = f.stateNode.state.interface;
                        const cols = iface.getColumns();
                        let col = cols.find(c => c.header === {_js_str(col_name)} || c.name === {_js_str(col_name)});
                        if (!col && cols.length > {col_idx}) col = cols[{col_idx}];
                        if (!col) return false;
                        iface.setSelection({{ rowIndex: {row_idx}, columnName: col.name }});
                        iface.focus();
                        return true;
                    }}""")
                except Exception:
                    pass

                if edit_mode:
                    # F2로 편집 모드 진입 시도
                    page.keyboard.press("F2")
                    self.page.wait_for_timeout(300)
                    active_input = page.locator("input:focus, textarea:focus").first
                    try:
                        if active_input.is_visible(timeout=1000):
                            active_input.fill("")
                            active_input.fill(value)
                            active_input.press("Tab")
                            logger.info(f"그리드 '{col_name}' 입력 (setSelection+F2): {value}")
                            return True
                    except Exception:
                        pass

                # 폴백: 동적 좌표 클릭
                page.mouse.click(obt_coords["x"], obt_coords["y"])
                self.page.wait_for_timeout(500)
                active_input = page.locator("input:focus, textarea:focus").first
                try:
                    if active_input.is_visible(timeout=1000):
                        active_input.fill("")
                        active_input.fill(value)
                        active_input.press("Tab")
                        logger.info(f"그리드 '{col_name}' 입력 (OBTDataGrid동적좌표): {value}")
                        return True
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"그리드 '{col_name}' 방법A-2 예외: {e}")

        # ── 방법 B-0: setSelection + F2/Enter로 편집 모드 진입 (좌표 불필요) ──
        try:
            sel_ok = page.evaluate(f"""() => {{
                const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                if (!el) return false;
                const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                if (!fk) return false;
                let f = el[fk];
                for (let i = 0; i < 3; i++) f = f ? f.return : null;
                if (!f || !f.stateNode || !f.stateNode.state || !f.stateNode.state.interface) return false;
                const iface = f.stateNode.state.interface;
                const cols = iface.getColumns();
                let col = cols.find(c => c.header === {_js_str(col_name)} || c.name === {_js_str(col_name)});
                if (!col && cols.length > {col_idx}) col = cols[{col_idx}];
                if (!col) return false;
                iface.setSelection({{ rowIndex: {row_idx}, columnName: col.name }});
                iface.focus();
                return true;
            }}""")
            if sel_ok:
                for key in ["F2", "Enter"]:
                    page.keyboard.press(key)
                    self.page.wait_for_timeout(300)
                    active_input = page.locator("input:focus, textarea:focus").first
                    try:
                        if active_input.is_visible(timeout=800):
                            active_input.fill("")
                            active_input.fill(value)
                            active_input.press("Tab")
                            logger.info(f"그리드 '{col_name}' 입력 (setSelection+{key} 폴백): {value}")
                            return True
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"그리드 '{col_name}' 방법B-0(setSelection) 예외: {e}")

        # ── 방법 B/C: 하드코딩 좌표 폴백 (DOM 데이터 기준, fullscreen 기준값) ──
        col_x_map = {
            0: 560,   # 용도
            1: 680,   # 내용
            2: 850,   # 거래처
            3: 960,   # 공급가액
            4: 1070,  # 부가세
            5: 1140,  # 합계액
        }
        x = col_x_map.get(col_idx)
        if x is None:
            return False
        y = 345 + (row_idx * 28)

        try:
            # 방법 B: 좌표 단클릭 후 input:focus (폴백)
            logger.warning(f"그리드 '{col_name}' setSelection 실패, 좌표 폴백 시도: ({x}, {y})")
            page.mouse.click(x, y)
            self.page.wait_for_timeout(500)
            active_input = page.locator("input:focus, textarea:focus").first
            try:
                if active_input.is_visible(timeout=1000):
                    active_input.fill("")
                    active_input.fill(value)
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (좌표 클릭 폴백): {value}")
                    return True
            except Exception:
                pass

            # 방법 C: 좌표 더블클릭 후 input:focus (최종 폴백)
            page.mouse.dblclick(x, y)
            self.page.wait_for_timeout(500)
            active_input = page.locator("input:focus, textarea:focus").first
            try:
                if active_input.is_visible(timeout=1000):
                    active_input.fill("")
                    active_input.fill(value)
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (좌표 dblclick 폴백): {value}")
                    return True
            except Exception:
                pass

            logger.debug(f"그리드 '{col_name}' 모든 방법 실패")
            return False

        except Exception as e:
            logger.debug(f"그리드 좌표 입력 실패 ({col_name}): {e}")
            return False

