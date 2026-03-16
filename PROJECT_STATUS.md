# 프로젝트 현황 (Project Status)

> 글로우서울 그룹웨어(더존 Amaranth10/WEHAGO) 자동화 프로젝트
> 최종 업데이트: 2026-03-08 (세션 XI — OBTDataGrid API 발견 + 결재선 동적화 + 좌표 코드 교체)

---

## 현재 상태 요약

| 항목 | 내용 |
|------|------|
| 전체 진행률 | 세션 XI — **OBTDataGrid React fiber API 발견 + 사용자별 결재선 동적화** |
| 진행 중 | T6 양식 로드 안정화, T13 임시보관 문서 클릭 개선, 나머지 좌표 의존 코드 제거 |
| 완료된 핵심 기능 | 회의실 예약(생성/취소/조회), 전자결재(지출결의서 22단계+거래처등록 E2E+대화형 플로우), 결재선 동적 설정(/setline, /myline), 메일 요약, 텔레그램 봇, 파일 첨부, 6개 양식 DOM 탐색, E2E 통합 테스트(T1~T13), MD 통폐합 |

---

## 세션별 작업 이력 (요약)

| 세션 | 날짜 | 주요 완료 사항 |
|------|------|--------------|
| A~E | ~2026-03-01 | 환경 구성, GW 분석(89+ API), 로그인 모듈, wehago-sign 해독, 회의실 예약 API 확정 |
| F~I | 2026-03-01~02 | 예약 생성/취소 E2E 완료, 다중 사용자 DB, JWT 인증, 대화 히스토리 DB, 전자결재 기초 |
| IV~V | 2026-03-02 | 텔레그램 봇, 양식 8개 확장, Phase 0 DOM 탐색, eap API 16종 캡처 |
| VI | 2026-03-02 | Task #1~#10, #15~#22 전체 완료 (아래 세부 참고) |
| VII | 2026-03-03 | T6 지출결의서 인라인 폼 수정, Enter→Tab, 탐색 스크립트 정리 |
| VIII | 2026-03-03 | 지출결의서 22단계 자동화 확장 (용도코드, 예산과목 팝업, 날짜필드, 검증결과) |
| IX | 2026-03-03 | scripts 통폐합 (54→1+archive), 데드코드 정리 (reservation.py 삭제, history.py 이동) |
| X | 2026-03-04 | T6 풀스크린 호환, OBT canvas 그리드 좌표 대응, 세금계산서 1건 선택 |
| XI | 2026-03-08 | OBTDataGrid React fiber API 발견, 결재선 동적화 (/setline, /myline), 용도코드/지급요청일 코드 교체 |

---

## 세션 XI 작업 내역 (2026-03-08)

### 완료된 작업

| 항목 | 내용 | 상태 |
|------|------|------|
| OBTDataGrid API 발견 | React fiber (`__reactFiber`) → depth 3 → `stateNode.state.interface` 경로로 그리드 API 접근 성공 | **완료** |
| 그리드 API 교체 (step 10) | 용도코드 입력: `window.gridView` (null 실패) → OBTDataGrid interface `setSelection()` + `focus()` | **완료** |
| 그리드 API 교체 (step 10-1) | 지급요청일 입력: 동일 교체, 좌표 폴백 제거 | **완료** |
| 결재선 동적화 (DB) | `user_db.py`에 `approval_config` 컬럼 + `get/set_approval_config()` | **완료** |
| 결재선 resolve 개선 | `form_templates.py` 4단계 우선순위: 대화직접 > DB양식별 > DB기본 > 내장기본 | **완료** |
| 텔레그램 /setline, /myline | 사용자별 결재선 설정/조회 명령어 | **완료** |
| agent.py 결재선 주입 | `handle_submit_expense_approval()` 등에서 user_context 기반 결재선 자동 적용 | **완료** |
| USER_MANUAL.md 갱신 | 결재선 설정 사용 예시 추가, 메일 요약 섹션 삭제 (내부 전용) | **완료** |
| T10 22단계 테스트 PASS | OBTDataGrid API 교체 후 전체 필드 테스트 통과 (85s) | **완료** |

### 핵심 발견 사항 (★)

1. **OBTDataGrid = 더존 자체 canvas 그리드** (내부 RealGrid 래핑). `window.gridView` 등 전역 변수 없음
2. **접근 경로**: `.OBTDataGrid_grid__22Vfl` → React fiber → depth 3 → `stateNode.state.interface`
3. **interface 주요 메서드**: `setValue()`, `getValue()`, `getRowCount()`, `getColumns()`, `setSelection()`, `focus()`, `commit()`
4. **depth 12**: 폼 컴포넌트 (`state.grid` = 지출내역 데이터, `state.head` = 상단 필드)
5. **Playwright `page.evaluate()`에서 동일 경로로 접근 가능** → 좌표 클릭 없이 셀 값 제어

### 미해결 / 다음 세션 작업

| 항목 | 내용 | 상태 |
|------|------|------|
| T6 양식 로드 안정화 | 결재작성 → 양식 클릭 후 폼 로드 타임아웃 | **수정 중** |
| T13 임시보관 문서 클릭 | 좌표 기반 (600,215) → DOM/API 기반으로 교체 | **수정 중** |
| 나머지 좌표 의존 코드 | 증빙유형, 프로젝트 더블클릭, 세금계산서 등 9개 mouse.click 잔존 | **미해결** |
| headless 1920x1080 E2E | 챗봇 배포 전 필수 테스트 | **미테스트** |
| 다중 사용자 결재선 테스트 | 실 계정 2개 이상으로 /setline 검증 | **미테스트** |

---

## 세션 X 작업 내역 (2026-03-04)

### 완료된 수정 사항

| 항목 | 내용 | 상태 |
|------|------|------|
| 돋보기(조회) 버튼 셀렉터 | `[title='조회']` → `button[class*='searchButton']` (OBTConditionPanel_searchButton) | **완료** |
| 모달 검색 input | 일반 `input:not([disabled])` → JS로 OBTDialog 컨테이너 내부 input 탐색 | **완료** |
| 증빙유형 버튼 y 범위 | 하드코딩 340~430 → "지출내역" 헤더 기준 동적 범위 (풀스크린 호환) | **완료** |
| 프로젝트 행 선택 | `row.click()` → 좌표 기반 `page.mouse.dblclick()` (canvas 그리드 대응) | **완료** |
| 세금계산서 1건 선택 | `modal_top + 185` (전체 선택) → `modal_top + 215` (첫 데이터 행) | **완료** |
| 부적합 에러 모달 감지 | "검증결과가 부적합인" 모달 텍스트 추출 + 닫기 버튼 클릭 | **완료** |

### 미해결 / 다음 세션 작업

| 항목 | 내용 | 상태 |
|------|------|------|
| 프로젝트 좌표 더블클릭 검증 | 코딩 완료 (title_box.y + 95), 실 테스트 필요 | **미테스트** |
| 세금계산서 1건 좌표 검증 | modal_top + 215 → 실 테스트 필요 | **미테스트** |
| 용도코드 전체 행 입력 | RealGrid API `window.gridView` null → grid instance 이름 탐색 필요 | **미해결** |
| 지급요청일 전체 행 입력 | 동일 RealGrid API null 문제 | **미해결** |
| 예산과목 선택 | budget_helpers "필드를 찾을 수 없음" → 재조사 필요 | **미해결** |

### 핵심 발견 사항 (★)

1. **OBTGrid = canvas 기반**: 프로젝트코드도움 모달의 그리드는 DOM 행 요소 없음 → `tr`, `div[class*='row']` 셀렉터 불가. 좌표 기반 더블클릭만 유효
2. **RealGrid API 미발견**: `window.gridView`, `window.grid`, `window.expenseGrid` 등 0개 → 지출내역 그리드 instance 이름을 별도로 찾아야 함
3. **풀스크린 좌표 변화**: `--start-maximized` + `no_viewport=True` 시 모든 하드코딩 좌표가 무효화됨 → 반드시 동적 기준점(헤더, 모달 제목) 사용
4. **OBTDialog2 overlay**: 모달이 열리면 `OBTDialog2__dimClicker__iUp5m` 레이어가 뒤쪽 input을 가림 → `force=True` 대신 모달 컨테이너 내부에서 요소 찾기
5. **더블클릭 = 선택+닫기**: 프로젝트코드도움 모달에서 더블클릭하면 행 선택 + 모달 자동 닫힘

---

## 세션 IX 완료 작업 (2026-03-03)

| 항목 | 내용 | 상태 |
|------|------|------|
| scripts 중복 삭제 | test_vendor_form{1~4,6~8}, analyze_vendor_body{2,3}, explore_approval_dom v1, test_vendor_api{1,2}, scripts/이전/ (19파일) | **완료** |
| 테스트 통합 | T11 챗봇 취소, T12 다중 턴 대화, T13 임시보관 상신 E2E → `full_test.py`에 추가 | **완료** |
| archive 이동 | 일회성 explore/analyze/capture + 독립 테스트 41개 → `scripts/archive/` | **완료** |
| 데드코드 삭제 | `src/meeting/reservation.py` (938줄) — `reservation_api.py`로 완전 대체 | **완료** |
| 모듈 이동 | `src/approval/history.py` → `scripts/archive/` (일회성 탐색 스크립트) | **완료** |
| 빈 패키지 삭제 | `src/utils/` (빈 디렉토리) | **완료** |

### 정리 결과
- **scripts/**: 54파일 → `full_test.py` 1개 + `archive/` 42개
- **src/**: 데드코드 938줄 삭제, 빈 패키지 제거
- **full_test.py**: T1~T10 → T1~T13 (13개 테스트)

---

## 세션 VIII 완료 작업 (2026-03-03)

| 항목 | 내용 | 상태 |
|------|------|------|
| 예산과목 팝업 헬퍼 | `src/approval/budget_helpers.py` 신규 — `select_budget_code(page, project_keyword, budget_keyword)` | **완료** |
| 용도코드 입력 | `_fill_expense_fields()` step 10~11 — RealGrid 용도 셀 코드 입력 + 자동완성 + Tab 확정 | **완료** |
| 예산과목 선택 연동 | `_fill_expense_fields()` step 12~17 — `budget_helpers.select_budget_code()` 호출, 2xxx 코드 자동 선택 | **완료** |
| 지급요청일 | `_fill_expense_fields()` step 18~19 — OBTDatePicker (y>800, x>750) + 캘린더 폴백 | **완료** |
| 회계처리일자 | `_fill_expense_fields()` step 20~21 — 상단(y<200) 날짜 input + 라벨 폴백 | **완료** |
| 검증결과 확인 | `_fill_expense_fields()` step 22 — 적합/부적합 감지, 부적합 시 hover 툴팁 추출 | **완료** |
| agent.py 연동 | `submit_expense_approval` 파라미터 확장: `usage_code`, `budget_keyword`, `payment_request_date`, `accounting_date` | **완료** |
| 테스트 통합 | `test_expense_22step.py` 삭제 → `full_test.py` T10으로 통합 (테스트 라이브러리 일원화) | **완료** |
| 문서 업데이트 | PROJECT_STATUS, DEVELOPER_GUIDE, MEMORY.md 갱신 | **완료** |

### 핵심 변경 사항
- **`_fill_expense_fields()` 22단계 통합**: 기존 step 1~9에 step 10~22 추가 — 하나의 메서드로 지출결의서 전체 플로우 완성
- **`budget_helpers.py` 신규 파일**: 공통 예산잔액 조회 모달 → 프로젝트 자동완성 → 예산과목코드도움 서브 팝업 → 2xxx 코드 선택
- **검증결과 부적합 시 툴팁**: hover → title/tooltip div 텍스트 추출 → 로그 경고

---

## 세션 VII 완료 작업 (2026-03-03)

| 항목 | 내용 | 상태 |
|------|------|------|
| T6 수정 | 지출결의서 인라인 폼: Enter→Tab 변경, `_verify_expense_fields()` 추가, `_submit_inline_form()` 추가 | **완료** |
| 발견사항 | GW 폼 2종: 인라인(지출결의서, 보관 없음) vs 팝업(거래처등록, 보관 있음) | 확인 |
| 테스트 | T1/T5/T6/T7/T9 모두 PASS (5/9 PASS, 4 SKIP) | **완료** |
| 정리 | 임시 탐색 스크립트 10개 삭제 | **완료** |

### T6 수정 상세
- **근본 원인**: `_fill_project_code()`에서 Enter 키가 GW의 "예산관리 > 프로세스갤러리"로 지연 네비게이션 트리거
- **수정**: `proj_input.press("Enter")` → `proj_input.press("Tab")` (4곳 변경)
- **추가 발견**: 인라인 폼에는 보관 버튼이 없음 → `save_mode="verify"` 모드 추가

---

## 세션 VI 완료 작업 (2026-03-02)

| Task | 내용 | 상태 |
|------|------|------|
| #1 | 임시보관문서 열기 및 결재상신 E2E — `open_draft_and_submit()`, `_click_draft_document()`, `_find_submit_button()` 구현, dry_run 안전장치 | **완료** |
| #2 | 지출내역 그리드 및 첨부파일 자동 입력 고도화 | **완료** |
| #3 | 거래처등록 양식 DOM 탐색 | **완료** |
| #3-1 | 지출결의서 내역상세 및 증빙 고도화 (`evidence_type`, 프로젝트코드, 예산 스크린샷) | **완료** |
| #4 | 결재 모듈/로그인 동작 보완 테스트 | **완료** |
| #5~#6 | 필수 필드 누락 방지 및 에러 핸들링 고도화 | **완료** |
| #7 | 결재선 자동 설정 확장 (APPROVAL_PRESETS/CC_PRESETS, 자연어 지원) | **완료** |
| #8 | 메일 요약 + Notion/Telegram 연동 — Gemini 3줄 요약, `/mail`+`/mailcheck`, `run_mail_push_for_user()` async 파이프라인, Notion 저장, To 필터링 | **완료** |
| #9 | 파일 첨부 Gemini 통합 연동 | **완료** |
| #10 | wehago-sign HMAC 예외처리 고도화 | **완료** |
| #15 | P0/P1 sleep 최적화 | **완료** |
| #16 | 전자결재 대화형 질문 플로우 (단계별 흐름, function calling, 프로젝트 자동완성) | **완료** |
| #17 | 세금계산서 팝업 검색 — `_select_invoice_from_popup()` 구현, 기간 확장 + 거래처/금액 매칭 | **완료** |
| #18 | 프로젝트 자동완성 확인 플로우 — `search_project_codes()` + `search_project_code` 도구 구현 | **완료** |
| #19 | 결재 제목 자동 제안 플로우 — 프로젝트 확정 후 자동 제목 생성 및 사용자 확인 | **완료** |
| #20 | MD 파일 통폐합 — PROJECT_STATUS 세션 이력 압축, DEVELOPER_GUIDE 중복 제거 | **완료** |
| #21 | 6개 양식 DOM 탐색 — 선급금요청(formId=181), 연장근무(43), 외근(41), 근태관리 모듈 분리 확인 | **완료** |
| #22 | E2E 통합 테스트 — 5개 플로우 정적 분석 통과, invoice 데이터 전달 버그 1건 수정 | **완료** |

---

## 다음 할 일

| 우선순위 | 작업 | 비고 |
|---------|------|------|
| **1순위** | T6/T13 안정화 | 양식 로드 타이밍 + 임시보관 문서 클릭 방식 개선 (수정 중) |
| **1순위** | 나머지 좌표 코드 제거 | 증빙유형, 프로젝트 더블클릭, 세금계산서 등 9개 mouse.click → OBTDataGrid API 교체 |
| 2순위 | headless E2E 테스트 | 챗봇 배포용 1920x1080 환경 검증 |
| 2순위 | 다중 사용자 결재선 테스트 | /setline 실 계정 검증 |
| 3순위 | 클라우드 배포 | HTTPS 적용 필요 |

---

*마지막 업데이트: 2026-03-08 (세션 XI — OBTDataGrid API 발견 + 결재선 동적화)*
