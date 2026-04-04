# GW 자동화 프로젝트 — 작업 목록

> 마지막 업데이트: 2026-04-04 (세션 XL 텔레그램 봇 통합 + YouTube Gemini 분석 + 프로젝트 일정표 + 노션 GS 업무 관리 페이지)
> 프로젝트: 글로우서울 그룹웨어(더존 Amaranth10/WEHAGO) 업무 자동화

---

## 범례

| 표시 | 의미 |
|------|------|
| :white_check_mark: | 완료 |
| :construction: | 진행 중 |
| :hourglass_flowing_sand: | 대기 (선행 작업 필요) |
| :clipboard: | 미착수 (새 작업) |

---

## 1. 핵심 기능 구현

### 1-1. 회의실 예약 :white_check_mark:

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | WEHAGO 회의실 API 분석 (rs121A 시리즈) | :white_check_mark: | 03-02 | HMAC 서명 인증 |
| 2 | 회의실 예약 생성 | :white_check_mark: | 03-02 | rs121A06 |
| 3 | 예약 현황 조회 | :white_check_mark: | 03-02 | rs121A05 |
| 4 | 예약 취소 | :white_check_mark: | 03-02 | seqNum 방식 발견 |
| 5 | 빈 회의실 검색 | :white_check_mark: | 03-02 | 시간대별 자동 검색 |
| 6 | 본인 예약 목록 (향후 N일) | :white_check_mark: | 03-09 | empSeq 필터 |
| 7 | 테스트 예약 일괄 취소 | :white_check_mark: | 03-09 | [TEST_] 접두사 필터 |
| 8 | 자동 재인증 (세션 만료 대응) | :white_check_mark: | 03-02 | 401/403 감지 → 자동 로그인 |

### 1-2. 전자결재 자동화 :white_check_mark:

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | GW 로그인 자동화 (Playwright) | :white_check_mark: | 03-01 | 2단계 로그인 + 팝업 처리 |
| 2 | 지출결의서 양식 자동 작성 (22단계) | :white_check_mark: | 03-02 | formId 255, 그리드 입력 포함 |
| 3 | 거래처등록 양식 자동 작성 | :white_check_mark: | 03-09 | formId 196, dzEditor API |
| 4 | 임시보관 → 상신 (E2E) | :white_check_mark: | 03-09 | 문서 목록 검색 → 상신 |
| 5 | 결재선/수신참조 자동 설정 | :white_check_mark: | 03-02 | 사용자별 `/setline` 커스텀 |
| 6 | OBTDataGrid API 발견 및 적용 | :white_check_mark: | 03-08 | 용도코드, 지급요청일 교체 완료 |
| 7 | 예산과목 모달 플로우 | :white_check_mark: | 03-09 | 팝업 → 검색 → 선택 전체 재구현 |
| 13 | **용도코드 자동팝업 처리 순서 수정** | :white_check_mark: | 03-25 | step 10-A 신규: Enter 후 즉시 팝업 처리 → step 10-1(지급요청일) 순서 확립 |
| 14 | **기결재 문서 수신참조 추가 자동화** | :white_check_mark: | 03-26 | `cc_manager.py` 신규: `add_cc_to_document()` / `batch_add_cc()` / `add_cc_by_title()` — docID 또는 제목 키워드 검색 양방향 지원 · RealGrid canvas checkRow + React fiber onClick 패턴 확립 |
| 8 | 전자결재 위저드 (챗봇 단계별 질문) | :white_check_mark: | 03-09 | approval_wizard.py |
| 9 | 선급금요청 양식 (code_ready) | :construction: | — | formId 181, 코드 작성 완료 → GW DOM 검증 필요 |
| 10 | 연장근무 양식 (code_ready) | :construction: | — | formId 43, `_save_overtime_draft()` 구현 완료 → GW DOM 검증 필요 |
| 11 | 외근신청 양식 (code_ready) | :construction: | — | formId 41, `_save_outside_work_draft()` 구현 완료 → GW DOM 검증 필요 |
| 12 | **좌표 의존 코드 제거 (13건→폴백 유지)** | :white_check_mark: | 03-22 | JS click/OBTDataGrid API 우선 → 좌표 폴백 유지 (expense 7건, grid 5건, budget 1건) |

### 1-3. 메일 요약 :white_check_mark:

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | GW 메일 수집 + 요약 | :white_check_mark: | 03-02 | 수신인(To) 본인만, 참조(CC) 제외 |

### 1-4. 계약서 자동 생성 :white_check_mark:

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | 자재납품 계약서 템플릿 | :white_check_mark: | 03-10 | DOCX 템플릿 치환 |
| 2 | 공사 하도급 계약서 템플릿 | :white_check_mark: | 03-10 | DOCX 템플릿 치환 |
| 3 | 챗봇 단건 작성 위저드 | :white_check_mark: | 03-10 | 대화형 정보 수집 |
| 4 | XLSX 다건 일괄 생성 | :white_check_mark: | 03-10 | 엑셀 드래그앤드롭 |
| 5 | 다운로드 엔드포인트 | :white_check_mark: | 03-10 | `/download/` |

### 1-5. 프로젝트 관리 시스템 :white_check_mark:

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | 프로젝트 관리표 양식 설계 (스프레드시트) | :white_check_mark: | 03-09 | 3시트: 프로젝트 관리/지출내역/발주현황 |
| 2 | SQLite DB 설계 (7+3 테이블) | :white_check_mark: | 03-17 | fund_management.db |
| 3 | REST API (21개 엔드포인트) | :white_check_mark: | 03-17 | `/api/fund/*` |
| 4 | 웹 프론트엔드 (프로젝트 관리 UI) | :white_check_mark: | 03-17 | `/fund` 페이지 |
| 5 | 프로젝트 등급/카테고리 시스템 | :white_check_mark: | 03-17 | 1~4등급, 7개 카테고리 |
| 6 | 드래그 정렬 | :white_check_mark: | 03-17 | 프로젝트 순서 변경 |
| 7 | Google Sheets 임포트 | :white_check_mark: | 03-17 | 하도급/연락처/이체내역/수금 |
| 8 | 챗봇 자금현황 요약 도구 | :white_check_mark: | 03-17 | `get_fund_summary` |
| 9 | **GW 프로젝트 목록 크롤링 + 검색 모달** | :white_check_mark: | 03-27 | 197개 프로젝트 목록 확인, XHR 인터셉터로 API 파라미터 확인 |
| 10 | **DB 스키마 확장 (세션 XXVIII)** | :white_check_mark: | 03-27 | gw_projects_cache +7컬럼, project_overview +9컬럼, payment_history +4컬럼, 신규 테이블 6개 (gw_tax_invoices, gw_budget_changes, gw_collection_schedule, gw_payment_approvals, project_risk_log, gw_contracts) |
| 11 | **project_crawler.py 확장 필드 수집** | :white_check_mark: | 03-27 | PM/소장/팀장/부서/계약금액/발주처연락처/진행률 — JS 추출 + React fiber 매핑 확장 |

### 1-6. STT 음성 인식 :white_check_mark:

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | Google Cloud STT API 연동 | :white_check_mark: | 03-16 | `stt.py` |
| 2 | 웹 챗봇 음성 파일 업로드 | :white_check_mark: | 03-16 | audio/* MIME 허용 |
| 3 | 텔레그램 음성 메시지 자동 인식 | :white_check_mark: | 03-16 | voice/audio 핸들러 |
| 4 | 시스템 프롬프트에 STT 안내 추가 | :white_check_mark: | 03-22 | prompts.py에 능동적 안내 규칙 3줄 추가 |

### 1-7. 예실대비 (GW 예산관리) 분석 :construction:

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | **GW 화면 직접 탐색 + RealGrid API 확인** | :white_check_mark: | 03-27 | `window.Grids.getActiveGrid().getDataProvider()` — 15개 필드 확인 |
| 2 | **budget_actual DB 스키마 확장** | :white_check_mark: | 03-27 | gw_project_code, gisu, def_nm, div_fg, is_leaf 컬럼 추가 |
| 3 | **budget_crawler.py 시도 0 추가** | :white_check_mark: | 03-27 | window.Grids DataProvider 방식 최우선 적용 |
| 4 | **routes.py 5개 신규 API** | :white_check_mark: | 03-27 | budget/detail, budget/sync-actuals, gw/sync-all-budget-actuals, gw/project-list, budget/cross-project |
| 5 | **fund.js 계층 구조 렌더링** | :white_check_mark: | 03-27 | 장/관/항/목 배지, 들여쓰기, Top5 미니차트 |
| 6 | **fund.html + fund.css UI 업데이트** | :white_check_mark: | 03-27 | budgetTopChart 컨테이너, budget-level-badge CSS |
| 7 | 예산과목원장(NCC0640) 크롤러 | :clipboard: | — | 트랜잭션 레벨 데이터 (승인일자/번호/거래처/수지출) |
| 8 | 임직원업무관리 이체완료내역 크롤러 | :clipboard: | — | 자금집행 승인 현황 |
| 9 | budget_crawler.py GW 실제 테스트 | :clipboard: | — | 로컬 서버 실행 후 크롤링 E2E 검증 |



---

## 2. 챗봇 & 인프라

### 2-1. 웹 챗봇 :white_check_mark:

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | FastAPI 서버 + 다크 테마 UI | :white_check_mark: | 03-01 | `app.py` + `static/` |
| 2 | JWT 쿠키 인증 | :white_check_mark: | 03-01 | httpOnly, 24시간 만료 |
| 3 | 대화 히스토리 (SQLite) | :white_check_mark: | 03-01 | 세션 목록/전환/삭제 |
| 4 | 파일 첨부 → Gemini 분석 | :white_check_mark: | 03-09 | base64 → Gemini 전달 |
| 5 | 관리자 페이지 | :white_check_mark: | 03-17 | `admin.html` |

### 2-2. 텔레그램 봇 :white_check_mark:

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | 기본 텔레그램 봇 연동 | :white_check_mark: | 03-02 | python-telegram-bot |
| 2 | `/setline`, `/myline` 결재선 명령어 | :white_check_mark: | 03-02 | DB 저장 |
| 3 | 2-step 인증 (비밀번호 별도 입력) | :white_check_mark: | 03-19 | 비밀번호 메시지 즉시 삭제 |
| 4 | 음성 메시지 핸들러 | :white_check_mark: | 03-16 | OGG → STT → 텍스트 |

### 2-3. AI 에이전트 (Gemini) :white_check_mark:

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | Gemini Function Calling 라우팅 | :white_check_mark: | 03-02 | 16개 도구 |
| 2 | 시스템 프롬프트 설계 | :white_check_mark: | 03-02 | 한국어 자연어 지시 |
| 3 | Gemini API 비동기화 | :white_check_mark: | 03-19 | `asyncio.to_thread()` |

---

## 3. 코드 품질 & 인프라 (세션 XVIII)

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | pytest 테스트 인프라 구축 (94개) | :white_check_mark: | 03-19 | 0.72초, 전체 PASS |
| 2 | agent.py 모듈 분할 (2103줄 → 4개) | :white_check_mark: | 03-19 | agent/tools_schema/prompts/handlers |
| 3 | approval_automation.py 분해 (5831줄 → 7 mixin) | :white_check_mark: | 03-19 | 기존 인터페이스 100% 유지 |
| 4 | Playwright sleep 최적화 (93개) | :white_check_mark: | 03-19 | `time.sleep` → `wait_for_timeout` |
| 5 | 순환 의존 없음 확인 | :white_check_mark: | 03-19 | import 그래프 분석 |
| 6 | 불필요 파일 정리 (~290MB 삭제) | :white_check_mark: | 03-19 | DOM 데이터, 디버그, 아카이브 등 |
| 7 | 문서 최신화 (DEVELOPER_GUIDE, README) | :white_check_mark: | 03-19 | PROJECT_STATUS.md 참조 정리 |
| 8 | Docker 배포 설정 | :white_check_mark: | 03-04 | Dockerfile + docker-compose + nginx |
| 9 | **전체 코드 리뷰 + 보안/품질 수정 (26건)** | :white_check_mark: | 03-30 | JS 인젝션 방지, XSS 방어, 스레드 안전, Playwright 정리, CSP 강화 |

---

## 4. 기타 완료 작업

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | 프로젝트 프로젝트 관리표 양식 (엑셀) | :white_check_mark: | 03-09 | `data/프로젝트_프로젝트 관리표_양식.xlsx` |
| 2 | 기능 생성기 CLI | :white_check_mark: | 03-09 | `scripts/feature_generator.py` |
| 3 | 스프레드시트 조건부 서식 (하도급) | :white_check_mark: | 03-16 | 체크박스 → 연파랑색 |
| 4 | KSHIA PDF 영문 변환 | :white_check_mark: | 03-16 | 디자인 유지 번역 |
| 5 | 사용자 DB 암호화 (Fernet) | :white_check_mark: | 03-01 | 비밀번호 대칭 암호화 |
| 6 | GW 세션 캐시 (TTL 2시간) | :white_check_mark: | 03-02 | 스레드 안전 |
| 7 | GW 데이터 자동 동기화 (APScheduler) | :white_check_mark: | 03-22 | 매일 08:00 3단계 크롤링, scheduler.py |
| 8 | 멀티유저 동시 사용 Lock | :white_check_mark: | 03-22 | handlers.py 4개 핸들러 per-user Lock |
| 9 | 수금현황 Sheets 임포트 | :white_check_mark: | 03-22 | sheets_import.py 매트릭스+테이블 이중 레이아웃 |

---

## 5. 남은 작업 (TODO)

### 높은 우선순위

| # | 작업 | 상태 | 선행 작업 | 설명 |
|---|------|------|-----------|------|
| 1 | **프로젝트 관리표 초기 정보 자동 기입** | :white_check_mark: | 03-22 | PM Official 시트 → DB 자동 반영 + API + 웹 버튼 |
| 2 | **GW 프로젝트 목록 크롤링 실제 테스트** | :construction: | — | 코드 버그 7건 수정 완료, 실제 GW 접속 확인 필요 |
| 3 | **지출결의서 invoice modal + project picker 완전 수정** | :construction: | — | 세션 XXXVI 디버깅 완료. 수정 사항: (1) _dismiss_obt_alert 버튼우선순위 취소>확인 (2) project input fill+Tab blur (3) cascade OBTAlert loop 10회. 미해결: invoice modal dataProvider 가 잘못된 grid 읽음 → 탑조명 invoice 미발견. invoice 선택 후 OBTAlert 처리 시 invoice modal이 닫히지 않아 project input 차단. |

### 보통 우선순위

| # | 작업 | 상태 | 선행 작업 | 설명 |
|---|------|------|-----------|------|
| 3 | 선급금요청 양식 자동화 | :construction: | — | formId 181. 코드 작성 완료, GW DOM 검증 필요 |
| 4 | 연장근무 양식 자동화 | :clipboard: | — | formId 43. 근태관리 모듈, Phase 0 DOM 탐색 필수 |
| 5 | 외근신청 양식 자동화 | :clipboard: | 연장근무 | formId 41. 연장근무 패턴 재사용 가능 |

### 낮은 우선순위 / 개선사항

| # | 작업 | 상태 | 설명 |
|---|------|------|------|
| 6 | 전자결재 API payload 확보 | :clipboard: | 현재 Playwright 폼 자동화 → API 직접 호출로 전환 시 속도 대폭 향상 |
| 7 | E2E 테스트 추가 (GW 서버 연동) | :clipboard: | 현재 133개 단위/통합 테스트만 — 실제 GW 연동 테스트 없음 |
| 8 | 첨부파일 드래그앤드랍 자동화 | :clipboard: | 실제 GW DOM 관찰 필요 — 파일 업로드 셀렉터 미확인 |
| 9 | 참조문서 연결 자동화 | :clipboard: | 전자결재 참조문서 연결 플로우 DOM 관찰 필요 |
| 10 | 예실대비현황(상세) 스크린샷 첨부 | :clipboard: | 상세 화면 캡처 후 첨부파일 자동화 플로우 미확인 |
| 11 | **지출결의서 프로젝트 키워드 자동검색** | :clipboard: | 지출결의서 작성 시 키워드(예: "오블리브") 입력 → gw_projects_cache 로컬 DB에서 유사 프로젝트명 자동 검색 후 제안 — GW Playwright 검색 실패 시 폴백으로 활용 |

---

## 6. 진행 타임라인

| 세션 | 날짜 | 주요 작업 |
|------|------|-----------|
| I~III | 03-01~02 | 프로젝트 초기 구현 (로그인, 챗봇, Gemini) |
| IV~VI | 03-02 | Gemini 에이전트 + 전자결재 + 메일 요약 |
| VII~VIII | 03-02 | 회의실 API 고도화 |
| IX | 03-04 | scripts 통폐합 + 데드코드 정리 |
| X | 03-04 | T6 풀스크린 호환 + OBT canvas 대응 |
| XI | 03-08 | OBTDataGrid API 발견 |
| XII | 03-09 | 코드 리뷰 + 보안 수정 |
| XIII | 03-09 | 챗봇 첨부파일 + 6개 양식 구현 |
| XIV | 03-09 | 예산과목 모달 플로우 전면 수정 |
| XV | 03-10 | 계약서 자동화 완료 |
| XVI | 03-16 | STT 음성인식 + 스프레드시트 서식 + PDF 번역 |
| XVII | 03-17 | 프로젝트 관리 시스템 구축 |
| XVIII | 03-19 | 코드 리뷰 리팩토링 + 테스트 94개 + 모듈 분할 + 파일 정리 |
| XIX~XXII | 03-19~20 | GW 크롤러 3종 구축 + 자금관리 확장 + gw-finance 스킬 |
| XXIII | 03-20 | GW 프로젝트 목록 크롤링 개선 (그룹컬럼 해결, 검색 모달 UI) |
| XXIV | 03-22 | 좌표 코드 제거 13건 + STT 프롬프트 + GW 자동동기화 + 멀티유저 Lock + 수금 임포트 |
| XXV | 03-25 | 용도코드 자동팝업 처리 순서 수정 (step 10-A 신규) + handle_auto_triggered_popup() 구현 |
| XXVI | 03-26 | 기결재 문서 수신참조 추가 자동화 (`cc_manager.py`) + RealGrid canvas 체크 패턴 확립 + 챗봇 도구 `add_cc_to_approval_doc` 추가 + 제목 키워드 검색 기능 (`add_cc_by_title`) + `tools_schema`/`handlers` doc_title 파라미터 분기 완성 |
| XXVII | 03-27 | Google Sheets 협력사 리스트 정리 (WORKING LIST + 자재 LIST 빈 행 삭제 + 참여 프로젝트/평가 컬럼 추가, `cleanZajaeRows` A/B열 기준 64개 삭제) + `/fund` 프로젝트 관리 페이지 전체 분석 (42개 개선 항목 도출, 5축 평가 기준 수립) |
| XXVIII | 03-27 | GW 크롤링 심층 분석 (8개 파일 ~500KB) → 미수집 데이터 식별 + DB 스키마 확장 (기존 3개 테이블 컬럼 추가, 신규 6개 테이블) + project_crawler.py JS 확장 + 프로젝트 관리 페이지 개선점 30개 추가 도출 |
| XXX | 03-28 | 챗봇 전체 기능 테스트 (Gemini parts=None 수정, 핸들러 시그니처 수정, getActionLabel 완성) |
| XXXI | 03-28 | /fund UI 개선: 수금 예정일 컬럼 (HTML+JS+API+DB), 예실대비 top chart fallback, 사이드바 검색 빈 상태, D-3 수금 예정일 강조 (주황/빨강). pytest 133/133 |
| XXXII | 03-28~29 | /fund 이체내역 엑셀 업로드 기능 (openpyxl 헤더 자동감지, 합계행 제외, 중복제거 5필드 기준), 지급총액 카드, 대시보드 인쇄 보고서(A4 가로 전용 HTML), 예실대비 장 그룹 필터링 + 상위차트 숨김 |
| XXXIII | 03-29 | 지출결의서 세금계산서 모달 리팩토링: Computer Use로 GW 실제 플로우 12단계 관찰 → _select_invoice_in_modal 전면 재작성 (날짜 input 감지 w:62px, 로딩 대기, 상세검색 토글, 거래처 keyboard.type, OBTDataGrid fiber API), 모달 canvas 그리드 gridAPI 발견 (rowCount=171), 체크박스 좌표 클릭 → 확인 → 그리드 반영 성공. 검증부적합 감지 + 모달 자동닫기 + 결재상신 JS 직접클릭 구현. pytest 133/133 |
| XXXIV | 03-30 | **전체 코드 리뷰 (56파일 31,936줄)** → 102건 발견 (19 Critical, 44 Medium, 39 Low) → **26건 수정 완료**: ① page.evaluate JS 인젝션 방지 (`_js_str` 헬퍼 + Playwright 인자전달, 19개소) ② XSS 방어 (fund.js `escapeHtml()` 14개소 + `printDashboard`) ③ 스레드 안전 (user_db double-check locking, session_manager per-user login Lock) ④ scheduler.py sync_running finally 데드락 수정 ⑤ middleware.py JWT KeyError 수정 ⑥ Playwright 정리 (`_playwright_session` 컨텍스트 매니저 2핸들러 적용) ⑦ CSP 강화 (script-src unsafe-inline 제거) ⑧ 업로드 토큰 TTL 1시간 + 임시파일 자동정리 ⑨ 데드코드/중복코드 제거 (login.py, style.css, approval_wizard.py, handlers.py). pytest 133/133 |
| XXXV | 03-30 | **병렬 에이전트 4개 동시 실행** — ① 크롤러 5종 신규 (tax_invoice/collection_schedule/payment_approval/contract/budget_changes) ② /fund UI 개선 8항목 (사이드바 뱃지, 수금 빈상태, 예산 def_nm 버그픽스, showToast 등) ③ project_crawler→project_overview 저장 연결 + payment_history gw_project_code 3단계 매칭 ④ routes.py 신규 엔드포인트 + fund.js 연도별 예산 탭 (2025/2026 캐시 전환). pytest 133/133 |
| XXXVII | 03-31 | 일정표 탭 신규(공정 일정 + 마일스톤 통합) + PDF 스타일 타임라인 UI + 이전 프로젝트 폴더 + PM 시트 수금/일정 가져오기 |
| XXXVIII | 04-02 | 타임라인 월 저장(DB+JS) + 이전 프로젝트 폴더 CSP 수정 + 대시보드 경고 카드 2종 + 수금률 진행바 + 연장근무/외근신청 양식 (code_ready) + 포트폴리오 수익성 그래프 + 계약/리스크 탭 신규 + 크롤링 버튼 + GW 신선도 배지 + 예산 변경이력 + 이체내역 공급가/세액 컬럼 + gw_projects_cache v2 연동. pytest 133/133 |
| XL | 04-04 | Telegram 봇+챗봇 서버 통합(lifespan) + 프로젝트 공정 일정표 조회 + GW 개인일정 조회 + YouTube Gemini 분석(yt-dlp+Gemini) + CLAUDE.md 최신화 + 노션 GS 업무 관리 페이지 신규 + 일과나 2 활용가이드/루틴 추가 |
| XXXVI | 03-30 | 지출결의서 OBTAlert 디버깅: JS dismiss 작동 확인, 버튼 우선순위 취소>확인 변경, project input fill+Tab blur 구현, cascade OBTAlert loop 10회. 발견: invoice modal 내 "매칭된 없음" OBTAlert가 project input 차단, dataProvider가 invoice modal grid 대신 expense form grid 읽음. base.py: wait_for_selector(detached) 추가, 버튼 우선순위 변경. expense.py: OBTAlert 대기 최대 3초, cascade loop 10회, fill+Tab blur. |

---

## 8. 프로젝트 관리 페이지 UI 개선

> 분석일: 2026-03-27 | 총 42개 항목 | 평가 기준: 정보 밀도(25%) / 작업 효율(25%) / 상태 가시성(20%) / 빈 상태 처리(15%) / 일관성(15%)

### 🔴 높음 (18개) — 즉시 개선 권장

| # | 위치 | 항목 | 설명 |
|---|------|------|------|
| 1 | 사이드바 | ~~숫자 뱃지 의미 명확화~~ | :white_check_mark: 03-30 완료 — 미완료 TODO 파란 원형 뱃지 추가 |
| 2 | 사이드바 | ~~상태별 그룹핑~~ | :white_check_mark: 기존에 구현됨 (03-30 확인) |
| 3 | 사이드바 | ~~검색 결과 없음 처리~~ | :white_check_mark: 03-28 완료 — 빈 상태 메시지 표시 |
| 4 | 대시보드 | ~~상단 요약 카드~~ | :white_check_mark: 03-30 완료 — 수금/미수금/하도급/TODO 4개 카드 |
| 5 | 대시보드 | ~~TODO 완료 피드백~~ | :white_check_mark: 이전 세션 완료 — 취소선 + 페이드아웃 애니메이션 |
| 6 | 대시보드 | ~~AI/사용자 TODO 구분~~ | :white_check_mark: 03-30 확인 — `.todo-ai` 기존 구현 |
| 7 | 수금 탭 | ~~D-3 수금 예정일 강조~~ | :white_check_mark: 03-28 완료 — D-3 주황, 기한초과 빨강 강조 |
| 8 | 수금 탭 | ~~수금 예정일 컬럼~~ | :white_check_mark: 03-28 완료 — 예정일 date input 추가 (전체 스택) |
| 9 | 수금 탭 | ~~빈 상태 템플릿 유도~~ | :white_check_mark: 03-30 완료 — "기본 단계 추가" 버튼 (계약금/중도금/잔금 자동생성) |
| 10 | 수금 탭 | ~~미수금 합계 배너~~ | :white_check_mark: 03-30 확인 — `uncollectedBanner` 기존 구현 |
| 11 | 예산 탭 | 손익 요약 카드 | 총 예산 / 집행액 / 잔액 / 손익률 카드형 표시 |
| 12 | 예산 탭 | ~~item_name 표시~~ | :white_check_mark: 03-30 완료 — `def_nm` 컬럼 추가 (헤더-컬럼 불일치 버그 픽스) |
| 13 | 하도급 탭 | ~~unsaved 경고~~ | :white_check_mark: 04-02 완료 — `_subcontractUnsaved` 플래그 + selectProject() 경고 |
| 14 | 하도급 탭 | 공종별 합계 헤더 | 공종 그룹 헤더 행에 소계 표시 |
| 15 | 하도급 탭 | 계약금액 합계 고정 | 테이블 하단 sticky 합계 행 |
| 16 | 공통 | ~~탭명 명확화~~ | :white_check_mark: 03-30 확인 — 탭명 이미 적절 |
| 17 | 공통 | ~~에러 토스트~~ | :white_check_mark: 03-30 확인 — `showToast()` 기존 구현 |
| 18 | 공통 | ~~로딩 스피너 일관성~~ | :white_check_mark: 03-30 확인 — `showLoading()`/`hideLoading()` 기존 구현 |

### 🟡 중간 (17개) — 다음 스프린트

| # | 위치 | 항목 | 설명 |
|---|------|------|------|
| 1 | 사이드바 | 최근 접근 프로젝트 | 사이드바 상단에 "최근 3개" 고정 |
| 2 | 사이드바 | 즐겨찾기 핀 | 별표 아이콘 → 상단 고정 기능 |
| 3 | 대시보드 | 마일스톤 타임라인 | 수평 간트차트 미니 버전 (주요 날짜 표시) |
| 4 | 대시보드 | 팀원별 TODO 현황 | 담당자별 완료율 미니 차트 |
| 5 | 대시보드 | 이슈 이력 패널 | 최근 변경 이력 타임라인 (우측 사이드) |
| 6 | 수금 탭 | 수금률 진행바 | 목표 대비 수금률 % 시각화 |
| 7 | 수금 탭 | 수금 예정 알림 | D-7 수금 예정 시 대시보드 뱃지 |
| 8 | 예산 탭 | 카테고리별 지출 파이차트 | 공종/항목별 비중 시각화 |
| 9 | 예산 탭 | 예산 초과 경고 | 항목별 예산 초과 시 빨간 강조 + 경고 아이콘 |
| 10 | 하도급 탭 | 지급률 진행바 | 계약 대비 지급 완료율 컬럼 |
| 11 | 하도급 탭 | 업체별 필터 | 업체명으로 빠른 필터링 |
| 12 | 지급 탭 | 지급 승인 플로우 | 대기/승인/완료 상태 워크플로 |
| 13 | 지급 탭 | 계좌 정보 연동 | 협력업체 DB에서 계좌 자동 조회 |
| 14 | 개요 탭 | 정렬 드롭다운 | 마감일/금액/상태별 정렬 옵션 |
| 15 | 개요 탭 | 프로젝트 복사 | 기존 구조 복사 → 새 프로젝트 빠른 생성 |
| 16 | 포트폴리오 | ~~수익성 분석 그래프~~ | :white_check_mark: 04-02 완료 — `_renderProfitChart()` 이익률 색상 분기 막대차트 |
| 17 | 공통 | 키보드 단축키 | Tab 이동, Esc 취소, Ctrl+S 저장 |

### 🟢 낮음 (7개) — 여유 시 개선

| # | 위치 | 항목 | 설명 |
|---|------|------|------|
| 1 | 사이드바 | 즐겨찾기 섹션 | 즐겨찾기 항목만 모아보기 뷰 |
| 2 | 대시보드 | 이슈 상세 이력 | 이슈 클릭 → 변경 이력 슬라이드 패널 |
| 3 | 하도급 탭 | 공종 드래그 정렬 | 공종 행 순서를 드래그로 변경 |
| 4 | 포트폴리오 | 기간별 필터 | 연도/분기별 포트폴리오 필터링 |
| 5 | 포트폴리오 | PDF 내보내기 | 포트폴리오 요약 PDF 출력 |
| 6 | 공통 | 다크/라이트 테마 전환 | 현재 다크 고정 → 테마 선택 옵션 |
| 7 | 공통 | 반응형 모바일 최적화 | 태블릿/모바일 레이아웃 개선 |

---

## 9. GW 크롤링 확장 + 프로젝트 관리 연동 (30개 항목)

> 분석일: 2026-03-27 | 평가 기준: 데이터 완결성(30%) / 신선도(20%) / 정보밀도(20%) / 작업효율(15%) / 상태가시성(15%)
> 현재 점수: 완결성 35% / 신선도 50% / 정보밀도 45% / 작업효율 55% / 상태가시성 40%

### 완료된 DB 작업

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 1 | gw_projects_cache 컬럼 7개 추가 | :white_check_mark: | manager, client, department, project_type, status, contract_amount, progress_rate |
| 2 | project_overview 컬럼 9개 추가 | :white_check_mark: | client, client_contact, client_phone, pm_name, site_manager, design_manager, gw_status, gw_project_type, gw_last_synced |
| 3 | payment_history 컬럼 4개 추가 | :white_check_mark: | supply_amount, tax_amount, payment_type, trade_id |
| 4 | 신규 테이블 6개 생성 | :white_check_mark: | gw_tax_invoices, gw_budget_changes, gw_collection_schedule, gw_payment_approvals, project_risk_log, gw_contracts |
| 5 | CRUD 함수 11종 추가 | :white_check_mark: | save/list 각 테이블, add/list/update_risk, save_gw_projects_cache_v2 |
| 6 | project_crawler.py JS 확장 | :white_check_mark: | PM/소장/팀장/부서/계약금액/발주처연락처/진행률 필드 추가 |

### 🔴 높음 — 신규 크롤러 구현 (미착수)

| # | 항목 | 상태 | 설명 |
|---|------|------|------|
| 7 | tax_invoice_crawler.py | :white_check_mark: 03-30 | GW 수금 모듈 → 세금계산서 발행 내역 → gw_tax_invoices (GW DOM 검증 필요) |
| 8 | collection_schedule_crawler.py | :white_check_mark: 03-30 | GW 수금 모듈 → 수금 예정 내역 → gw_collection_schedule (GW DOM 검증 필요) |
| 9 | payment_approval_crawler.py | :white_check_mark: 03-30 | GW 자금 모듈 → 집행승인 현황 → gw_payment_approvals (GW DOM 검증 필요) |
| 10 | budget_changes 크롤러 추가 | :white_check_mark: 03-30 | budget_crawler.py에 crawl_budget_changes() 추가 완료 |
| 11 | 계약 크롤러 (contract_crawler.py) | :white_check_mark: 03-30 | GW 계약관리 모듈 → gw_contracts (GW DOM 검증 필요) |
| 12 | project_crawler 저장 경로 연결 | :white_check_mark: 03-30 | upsert_project_overview_gw_fields() — pm_name/client/site_manager 등 자동 저장 |
| 13 | payment_history project_id 정확도 개선 | :white_check_mark: 03-30 | gw_project_code 3단계 매칭 (코드→캐시→정규화명) |

### 🔴 높음 — 페이지 연동 (미착수)

| # | 항목 | 상태 | 설명 |
|---|------|------|------|
| 14 | ~~발주처 정보 자동 채우기~~ | :white_check_mark: 04-02 | 이미 구현 — `upsert_project_overview_gw_fields()` GW 크롤 후 자동 저장 |
| 15 | ~~팀 구성 자동 채우기~~ | :white_check_mark: 04-02 | 이미 구현 — pm_name/site_manager/design_manager project_overview 저장 |
| 16 | ~~계약금액 자동 동기화~~ | :white_check_mark: 04-02 | 이미 구현 — crawl-gw 엔드포인트에서 자동 연결 |
| 17 | ~~미수금 D-Day 대시보드 카드~~ | :white_check_mark: 04-02 | `renderDashCollectionAlert()` — D-7 이내 경고 카드 (collections 기반) |
| 18 | ~~예산 초과 경보~~ | :white_check_mark: 04-02 | `renderDashBudgetAlert()` — 집행률 95% 초과 대시보드 카드 |
| 19 | ~~예산 변경 이력 탭/토글~~ | :white_check_mark: 04-02 | 예산 탭 하단 `<details>` 아코디언 — budget-changes API |
| 20 | 수금 예정일 배지 | :clipboard: | gw_collection_schedule D-7 이내 배지 (GW 크롤러 검증 후) |
| 21 | 세금계산서 연결 표시 | :clipboard: | 수금 행 세금계산서 발행 여부 아이콘 (GW 크롤러 검증 후) |
| 22 | 자금집행 승인 현황 | :clipboard: | gw_payment_approvals → 지급 탭 승인 대기 목록 (GW 크롤러 검증 후) |
| 23 | ~~신규 계약 탭~~ | :white_check_mark: 04-02 | `contracts` 탭 신규 — gw-contracts API 테이블 |
| 24 | ~~신규 리스크 관리 탭~~ | :white_check_mark: 04-02 | `risks` 탭 신규 — 카드 형식 + 추가/해결/재오픈 |
| 25 | ~~GW 데이터 신선도 배지~~ | :white_check_mark: 04-02 | `gwSyncBadge` — gw_last_synced 기반 "N일 전" 표시 |

### 🟡 중간 (미착수)

| # | 항목 | 상태 | 설명 |
|---|------|------|------|
| 26 | ~~routes.py 신규 6개 엔드포인트~~ | :white_check_mark: 04-02 | 이미 구현됨 확인 (Agent A) |
| 27 | ~~공급가/부가세 분리 표시~~ | :white_check_mark: 04-02 | 이체내역 탭 supply_amount/tax_amount 컬럼 추가 |
| 28 | ~~연도별 예산 탭 전환~~ | :white_check_mark: 04-02 | 이미 구현됨 확인 (`_renderBudgetYearTabs`) |
| 29 | ~~크롤링 일괄 실행 버튼~~ | :white_check_mark: 04-02 | `crawlAllExtendedBtn` 포트폴리오 뷰 추가 |
| 30 | ~~gw_projects_cache v2 연동~~ | :white_check_mark: 04-02 | `save_gw_projects_cache_v2()` 호출 경로 연결 (routes.py + project_crawler.py) |

---

## 7. 요약 통계

| 항목 | 수치 |
|------|------|
| 총 완료 작업 | **95개** (+21 세션 XXXVIII) |
| 진행 중 | **3개** (GW 프로젝트 목록 크롤링, 선급금요청 DOM 검증, 연장근무/외근신청 DOM 검증) |
| 미착수 | **3개** (수금예정일 배지, 세금계산서 연결, 자금집행 승인 현황 — GW 크롤러 검증 후) |
| 세션 수 | **34회** (03-01 ~ 04-02) |
| 테스트 | **133개** (전체 PASS) |
| 챗봇 도구 | **22개** |
| 전자결재 양식 | verified 2개 / code_ready 3개 |
| 코드 리뷰 수정 | **26건** (보안 19 + 품질 7) |
| 크롤러 | **8종** (기존 3 + 세션 XXXV 5 신규) |
| /fund 탭 | **9개** (대시보드/개요/수금/하도급/예산&지급/이체내역/일정표/계약/리스크) |

---

## 10. 일정표 시스템 (세션 XXXVII, 2026-03-31)

| # | 항목 | 상태 | 설명 |
|---|------|------|------|
| 1 | 일정표 탭 신규 추가 | :white_check_mark: 03-31 | fund.html 7번째 탭, 개요 탭 마일스톤 → 일정표로 이동 |
| 2 | 공정 일정 DB 테이블 | :white_check_mark: 03-31 | `project_schedule_items` (group_name, subtitle, item_type, bar_color 포함) |
| 3 | 일정 API 엔드포인트 | :white_check_mark: 03-31 | GET/POST `/api/fund/projects/{id}/schedule` |
| 4 | 마일스톤 D-Day 배지 | :white_check_mark: 03-31 | `calcDday()`, `ddayHtml()` — D-3 이내 주황 펄스, D-Day 빨강, 완료 초록 |
| 5 | 개요 탭 마일스톤 요약 | :white_check_mark: 03-31 | 마일스톤 → 일정표 링크 + `updateOvMilestoneSummary()` |
| 6 | PM 시트 → 일정 가져오기 | :white_check_mark: 03-31 | `import_schedule_from_pm_sheet()` + API + "일정 가져오기" 버튼 |
| 7 | PM 시트 → 수금일정 가져오기 | :white_check_mark: 03-31 | `import_collections_from_pm_sheet()` + API + "수금일정 가져오기" 버튼 |
| 8 | 이전 프로젝트 폴더 | :white_check_mark: 03-31 | `is_archived` 컬럼, `/archive` API, 드래그→보관, 토글 폴더 UI |
| 9 | 타임라인 뷰 (PDF 스타일) | :white_check_mark: 03-31 | 3단 헤더(월/주차/날짜), 팀 그룹핑, 다중 바, 마일스톤 점선, 오늘 마커, 클릭 편집 팝오버 |

