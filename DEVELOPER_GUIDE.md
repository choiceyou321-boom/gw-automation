# 개발자 가이드 (Developer Guide)

> 마지막 업데이트: 2026-03-22 (GW 자동 동기화 스케줄러, 멀티유저 Lock, PM 시트 임포트, 선급금요청 코드 준비)
> 새 세션 시작 시 이 문서와 `MEMORY.md`(auto-memory)를 함께 참고.

---

## 1. 세션 관리 패턴

### 세션 이어가기
- **새 세션 시작 시 필수**: `DEVELOPER_GUIDE.md` + `MEMORY.md`(auto-memory) 읽기
- 컴퓨터 꺼져도 이어갈 수 있도록 세션 마무리 시 기록 필수

### 기록 대상 파일
| 파일 | 용도 | 업데이트 시점 |
|------|------|---------------|
| `DEVELOPER_GUIDE.md` | 기술 패턴 + GW API 분석 + 프로젝트 구조 | 새 API 발견/기술 변경 시 |
| `USER_MANUAL.md` | 사용자 매뉴얼 | 사용자 기능 변경 시 |
| `CLAUDE.md` | 프로젝트 규칙 | 규칙 변경 시만 |
| `MEMORY.md` (auto-memory) | 세션 작업 기록, 발견사항, 파일 경로 | 매 세션/작업 완료 시 |

### 레코더 자동 업데이트 규칙 (★ 필수)
> **모든 작업 완료/보고 시 아래 마크다운 파일을 자동 업데이트해야 한다.**

| 파일 | 업데이트 내용 |
|------|-------------|
| `DEVELOPER_GUIDE.md` | 새 기술 패턴, API 발견, 구현 규칙 추가 |
| `MEMORY.md` (auto-memory) | 새 파일 경로, 메서드, 발견사항, 세션 작업 기록 반영 |
| `USER_MANUAL.md` | 사용자 기능 변경 시 업데이트 |

---

## 2. 명칭 및 코드 스타일 규칙

### 채널 명칭
| 명칭 | 의미 | 파일 |
|------|------|------|
| **챗봇** | 웹(URL) 접속 채팅 | `src/chatbot/app.py` |
| **텔레그램** | 텔레그램 봇 채팅 | `src/chatbot/telegram_bot.py` |

### 코드 스타일
- **한국어 주석** 사용
- **명확한 변수명** (영문)
- docstring은 한국어로 작성
- 로깅: `logging.getLogger(__name__)` 표준 사용

### 프로젝트 용어
| 용어 | 의미 |
|------|------|
| GW | 글로우서울 그룹웨어 (더존 Amaranth10/WEHAGO) |
| Phase 0 | Playwright DOM 탐색 단계 (selector 확정) |
| 보관 | 임시저장 — `div.topBtn:has-text('보관')` 클릭 |
| 상신 | 결재 제출 — `div.topBtn:has-text('상신')` 클릭 |

---

## 3. 프로젝트 디렉토리 구조

```
자동화 work/
├── run_chatbot.py               # 챗봇 실행 진입점
├── pyproject.toml               # 프로젝트 설정 + pytest 설정
├── requirements.txt             # Python 의존성
├── Dockerfile                   # Docker 컨테이너 빌드
├── docker-compose.yml           # Docker Compose 설정
├── deploy.sh                    # 배포 스크립트
├── config/
│   └── .env                     # 환경변수 (GW계정, API키, 암호화키)
│
├── scripts/
│   ├── feature_generator.py         # 기능 생성기 CLI
│   ├── create_fund_table.py         # 프로젝트 관리표 스프레드시트 생성
│   ├── create_contract_template.py  # 계약서 템플릿 생성
│   ├── generate_contracts_from_excel.py  # 엑셀→계약서 일괄 생성
│   ├── setup_google_sheets.py       # Google Sheets API 설정
│   ├── translate_kshia_pdf.py       # KSHIA PDF 번역
│   └── translate_pdf_inplace.py     # PDF 인플레이스 번역
│
├── src/
│   ├── auth/                     # 인증 모듈
│   │   ├── login.py              # GW 로그인 (Playwright)
│   │   ├── jwt_utils.py          # JWT 토큰 생성/검증
│   │   ├── user_db.py            # SQLite + Fernet 사용자 DB
│   │   ├── middleware.py         # FastAPI 인증 미들웨어
│   │   └── session_manager.py    # GW 세션 캐시 (TTL 2시간)
│   ├── approval/                 # 전자결재 자동화 (Mixin 패턴, 7개 모듈)
│   │   ├── approval_automation.py  # Mixin 조합 클래스 (54줄, 진입점)
│   │   ├── base.py                 # 공통 유틸/네비게이션/저장 (~490줄)
│   │   ├── approval_line.py        # 결재선/수신참조 설정 (~268줄)
│   │   ├── expense.py              # 지출결의서 전체 플로우 (~2450줄)
│   │   ├── grid.py                 # OBTDataGrid 그리드 조작 (~490줄)
│   │   ├── vendor.py               # 거래처등록 (~798줄)
│   │   ├── draft.py                # 임시보관 문서 상신 (~464줄)
│   │   ├── other_forms.py          # 기타 양식: 선급금/연장근무/외근 등 (~1079줄)
│   │   ├── budget_helpers.py       # 예산과목 팝업 헬퍼
│   │   └── form_templates.py       # 양식 필드 정의 + 결재선 resolve
│   ├── chatbot/                  # 웹 챗봇 + 텔레그램 봇 + Gemini 에이전트
│   │   ├── app.py                # FastAPI 웹 서버
│   │   ├── agent.py              # Gemini 라우팅 (244줄, 진입점)
│   │   ├── tools_schema.py       # Gemini Function Calling 도구 스키마 (317줄)
│   │   ├── prompts.py            # 시스템 프롬프트 (212줄)
│   │   ├── handlers.py           # 21개 핸들러 함수 + TOOL_HANDLERS (1882줄)
│   │   ├── chat_db.py            # 대화 히스토리 DB (SQLite)
│   │   ├── approval_wizard.py    # 전자결재 단계별 질문 위저드
│   │   ├── stt.py                # Google Cloud Speech-to-Text STT
│   │   ├── telegram_bot.py       # 텔레그램 봇
│   │   └── static/               # 프론트엔드 정적 파일
│   │       ├── index.html, app.js, style.css  # 챗봇 UI
│   │       ├── admin.html         # 관리자 페이지
│   │       └── fund.html, fund.js, fund.css   # 프로젝트 관리 UI
│   ├── contracts/                # 계약서 자동 생성
│   │   ├── contract_generator.py # Word 계약서 생성 엔진
│   │   └── contract_wizard.py    # 챗봇 연동 위저드
│   ├── fund_table/               # 프로젝트 자금관리
│   │   ├── db.py                 # SQLite DB (fund_management.db)
│   │   ├── routes.py             # FastAPI 라우터 (/api/fund/*, 40+ API)
│   │   ├── budget_crawler.py     # GW 예실대비현황(상세) 크롤러
│   │   ├── budget_crawler_by_project.py  # GW 예실대비현황(사업별) 크롤러
│   │   ├── project_crawler.py    # GW 프로젝트 등록정보 크롤러
│   │   ├── scheduler.py          # GW 자동 동기화 스케줄러 (APScheduler cron)
│   │   └── sheets_import.py      # Google Sheets 연동 임포트 + PM 시트
│   ├── mail/                     # 메일 요약
│   │   └── summarizer.py         # GW 메일 수집 + 요약
│   ├── meeting/                  # 회의실 예약
│   │   └── reservation_api.py    # WEHAGO API (httpx + HMAC)
│   └── notion/                   # Notion 연동
│       └── client.py             # Notion API 클라이언트
│
├── tests/                        # pytest 테스트 (94개, 0.72초)
│   ├── conftest.py               # 공유 픽스처 (TEST_JWT_SECRET, monkeypatch)
│   ├── unit/
│   │   ├── test_user_db.py       # 사용자 DB (18 tests)
│   │   ├── test_jwt_utils.py     # JWT (9 tests)
│   │   ├── test_fund_db.py       # 프로젝트 관리 DB (27 tests)
│   │   ├── test_chat_db.py       # 대화 DB (16 tests)
│   │   └── test_session_manager.py  # 세션 캐시 (9 tests)
│   └── integration/
│       └── test_api_auth.py      # FastAPI 인증 API (8 tests)
│
├── data/
│   ├── fund_management.db        # 프로젝트 관리 SQLite DB
│   ├── users.db                  # 사용자 DB (SQLite + Fernet)
│   ├── chatbot/                  # 챗봇 대화 히스토리 DB + 로그
│   ├── contracts/                # 계약서 생성 결과물
│   ├── approval_screenshots/     # 결재 디버그 스크린샷
│   ├── kshia_translation/        # KSHIA 번역 자료
│   ├── 계약서_입력양식.xlsx       # 계약서 일괄 생성용 양식
│   └── 프로젝트_프로젝트 관리표_양식.xlsx  # 프로젝트 관리표 양식
│
├── docs/
│   └── google_sheets_setup_guide.md  # Google Sheets 설정 가이드
├── nginx/                        # Nginx 리버스 프록시 설정
│   ├── nginx.conf
│   └── ssl/
└── logs/                         # 서버 로그
```

---

## 4. 기술 패턴

### GW 접근 방식 (2가지)

#### 방식 A: API 직접 호출 (회의실 예약)
```
Playwright 로그인 → 쿠키/토큰 추출 → httpx API 호출
```
- **사용처**: 회의실 예약 (rs121A 시리즈)
- **인증**: wehago-sign HMAC

#### 방식 B: Playwright 폼 자동화 (전자결재)
```
Playwright 로그인 → 페이지 이동 → DOM 조작으로 폼 채우기
```
- **사용처**: 전자결재 (API payload 미확보)
- **인증**: 브라우저 세션 쿠키

### 멀티유저 동시 사용 Lock (`handlers.py`)
- Playwright 기반 핸들러는 동시 실행 시 충돌 위험 → per-user `threading.Lock`으로 보호
- `_user_locks: dict[str, threading.Lock]` — GW ID별 Lock 관리, `_user_locks_guard`로 dict 접근 보호
- 보호 대상 핸들러 (4개): `submit_expense_approval`, `submit_draft_approval`, `submit_approval_form`, `search_project_code`
- 동일 사용자의 결재 요청이 중복 실행되지 않도록 직렬화

### 로그인 패턴
- 2단계: ID(`#reqLoginId`) → Enter → PW(`#reqLoginPw`) → Enter
- `#reqCompCd`: disabled 필드, 건드리지 않음
- 로그인 후 팝업 5개+ 자동 열림 → URL에 "popup" 포함 시 닫기
- 세션 캐시: `session_manager.py` 인메모리 (TTL 2시간, 재시작 시 소멸)

---

## 5. API 인증 패턴

### 인증 방식별 URL 패턴
| API 종류 | 인증 방식 | URL 패턴 |
|----------|-----------|----------|
| 일반 gw | 쿠키 인증 | `POST /gw/APIHandler/{코드}` |
| schres (회의실) | wehago-sign HMAC | `POST /schres/rs121A__` |
| eap (전자결재) | 쿠키 인증 | `POST /eap/{코드}` |
| 메일 | 쿠키 인증 | `POST /mail/api/{코드}` |

### wehago-sign 공식
```
Base64(HMAC-SHA256(signKey, oAuthToken + transactionId + timestamp + pathname))
```

### 자동 재인증 패턴 (`reservation_api.py`)
- `call_api(_retry=True)` → HTTP 401/403 또는 resultCode 인증 오류 감지
- `_refresh_session()`: `invalidate_cache()` → `_login_and_cache()` → 토큰/쿠키/httpx Client 갱신

---

## 6. 전자결재 양식 관리

### 현재 양식 현황 (`form_templates.py`)
| 양식 | 상태 | formId | 비고 |
|------|------|--------|------|
| 지출결의서 | verified | 255 | 그리드 입력 포함, 22단계 |
| 거래처등록 | verified | 196 | 팝업 창, dzEditor API |
| 선급금요청 | verified | 181 | `_save_advance_payment_draft()` 구현 완료 (other_forms.py) |
| 연장근무 | template_only | 43 | 근태관리 모듈 별도 |
| 외근신청 | template_only | 41 | 근태관리 모듈 별도 |

### dzEditor 본문 기입 패턴
- **DOM 직접 수정 불가** — 저장 시 반영 안 됨
- 공식 API 사용: `getEditorHTMLCodeIframe(0)` → regex 교체 → `setEditorHTMLCodeIframe(html, 0)`

### 용도코드 → 자동팝업 처리 패턴 (세션 XXV 확립)

```
Step 10:   OBTDataGrid 용도 셀 → setSelection + keyboard.type(code) + Enter
           → 팝업 자동 트리거 (클릭 불필요)
Step 10-A: handle_auto_triggered_popup(page, project_kw, budget_kw)
           → 팝업 감지(3초) → 프로젝트 입력 → 예산과목코드도움 서브팝업 → 확인
           → success=False("팝업 미감지") 시 step 11 fallback
Step 10-1: 지급요청일 그리드 입력 (팝업 닫힌 후만 가능)
Step 11:   select_budget_code() — 예산과목 필드 직접 클릭 방식 (fallback)
```

**핵심**: 용도코드 Enter 후 팝업이 자동으로 열리므로, 팝업을 먼저 닫은 뒤에 지급요청일을 입력해야 함. 기존 step 순서(10-1 → 11)는 팝업 차단 문제 발생.

### 결재선 구조
- 지출결의서: 기안자(전태규) → 신동관(합의) → 최기영(최종) — 3단계
- 거래처등록: 기안자(전태규) → 최기영(최종) — 2단계
- `/setline`으로 사용자별 커스텀 결재선 설정 가능 (user_db에 저장)

### 지출결의서 22단계 자동화 (`_fill_expense_fields`)

| Step | 내용 | data 키 |
|------|------|---------|
| 1 | 프로젝트 코드도움 (상단) | `project` |
| 2~3 | 제목 입력 | `title` |
| 4 | 지출내역 그리드 입력 | `items` |
| 5 | 증빙유형 버튼 클릭 | `evidence_type` |
| 5-1 | 세금계산서 팝업 검색 | `invoice_vendor`, `invoice_amount`, `invoice_date` |
| 6 | 증빙일자 입력 | `receipt_date` |
| 7 | 프로젝트 코드도움 (하단) | `project` |
| 8 | 첨부파일 업로드 | `attachment_path` |
| 9 | 예실대비현황 스크린샷 | `auto_capture_budget` |
| 10 | 용도코드 입력 (OBTDataGrid canvas 셀) | `usage_code` |
| 10-A | 자동 트리거 "공통 예산잔액 조회" 팝업 처리 (신규) | `budget_keyword`, `project` |
| 10-1 | 지급요청일 그리드 입력 | `payment_request_date` |
| 11 | 예산과목 선택 폴백 (팝업 미자동 환경) | `budget_keyword` |
| 18~19 | 지급요청일 선택 | `payment_request_date` |
| 20~21 | 회계처리일자 변경 | `accounting_date` |
| 22 | 검증결과 확인 | 자동 |

---

## 7. 프로젝트 관리 모듈 (`src/fund_table/`)

### DB 구조 (`data/fund_management.db`)

| 테이블 | 용도 |
|--------|------|
| `projects` | 프로젝트 목록 (name, grade, sort_order, owner_gw_id, budget_summary, 금액정보) |
| `trades` | 프로젝트별 공종 |
| `subcontracts` | 하도급 업체별 계약/지급 정보 (4차 지급, 체크박스 확인) |
| `contacts` | 거래처 연락처 |
| `collections` | 수금현황 (설계/시공 단계별 금액, 수금완료 체크) |
| `project_overview` | 개요 (카테고리, 위치, 용도, 면적, 일정, 계약현황, 이슈) |
| `project_members` | 배정인원 (역할, 담당자) |
| `project_milestones` | 진행 마일스톤 (체크리스트) |
| `project_todos` | 프로젝트별 TODO (content, priority, is_completed, created_at) |
| `project_insights` | AI 인사이트 (category=status/risk/cash_flow/action, content) |
| `project_materials` | 자재 관리 |
| `notifications` | 알림 |
| `payment_history` | GW 이체완료 내역 (스크래핑) |
| `budget_actual` | GW 예실대비현황 (스크래핑, 연도별 그룹) |
| `gw_projects_cache` | GW 전체 프로젝트 목록 캐시 (code UNIQUE, name, start_date, end_date, cached_at) |
| `project_aliases` | 프로젝트 별칭 (다양한 이름으로 같은 프로젝트를 찾기 위한 메타데이터) |

### API 엔드포인트 (`routes.py`)

| Method | 경로 | 기능 |
|--------|------|------|
| GET | `/api/fund/projects` | 프로젝트 목록 |
| POST | `/api/fund/projects` | 프로젝트 생성 (grade 포함) |
| PUT | `/api/fund/projects/reorder` | 프로젝트 순서 변경 |
| GET/PUT | `/api/fund/projects/{id}` | 프로젝트 조회/수정 |
| DELETE | `/api/fund/projects/{id}` | 프로젝트 삭제 |
| GET/PUT | `/api/fund/projects/{id}/overview` | 개요 조회/저장 |
| GET/PUT | `/api/fund/projects/{id}/collections` | 수금현황 조회/저장 |
| GET/PUT | `/api/fund/projects/{id}/subcontracts` | 하도급 조회/저장 |
| GET/POST/PUT/DELETE | `/api/fund/projects/{id}/contacts` | 연락처 CRUD |
| GET | `/api/fund/projects/{id}/payments` | 이체내역 조회 |
| GET | `/api/fund/projects/{id}/budget` | 예실대비 조회 |
| GET | `/api/fund/projects/{id}/summary` | 요약 (대시보드용) |
| POST | `/api/fund/projects/{id}/crawl-gw` | 단일 프로젝트 GW 크롤링 (3단계) |
| POST | `/api/fund/crawl-gw-all` | 전체 프로젝트 GW 일괄 크롤링 |
| GET/POST | `/api/fund/todos` | TODO CRUD |
| PUT/DELETE | `/api/fund/todos/{id}` | TODO 수정/삭제 |
| GET | `/api/fund/insights` | AI 인사이트 조회 |
| POST | `/api/fund/insights/generate` | AI 인사이트 생성 (Gemini 2.5 Flash) |
| GET | `/api/fund/portfolio-analysis` | 포트폴리오 종합 분석 조회 |
| POST | `/api/fund/gw/search-projects` | GW 프로젝트 키워드 검색 (캐시 우선) |
| POST | `/api/fund/gw/fetch-project-list` | GW에서 전체 프로젝트 목록 크롤링 → 캐시 저장 |
| POST | `/api/fund/import-pm-sheet` | PM Official 시트에서 프로젝트 기본정보 일괄 임포트 |
| GET | `/fund` | 프로젝트 관리 웹 페이지 서빙 |
| GET | `/insights` | AI 인사이트 페이지 서빙 |

### 프로젝트 등급
| 등급 | 색상 | 설명 |
|------|------|------|
| 1등급 | 빨강 | 당사 직영(ETF), 확장 가능성 |
| 2등급 | 노랑 | KOM, 2~3차 보고, 결과 보고 |
| 3등급 | 파랑 | KOM, 2차 보고, 결과 보고 |
| 4등급 | 회색 | 기타 |

### 프로젝트 카테고리
| 카테고리 | 설명 |
|----------|------|
| 설계 | 설계 계약 |
| 시공 | 시공 계약 |
| 설계&시공 | 통합솔루션 포함 |
| 브랜드 | 브랜드 개발, 사용 등 프로젝트 |
| 운영 | 위탁운영 계약 |
| 직영 | 직영 프로젝트 |
| 기획 | 기획 프로젝트 (컨셉만) |

### Google Sheets 연동 (`sheets_import.py`)
- 서비스 계정: `gsgw-bot@support-officer-gmail.iam.gserviceaccount.com`
- 프로젝트 관리표 시트 ID: `1LcmZPsDC-rqi2jofQup9G8xo6MOTVupSei0oZMm8nzE`
- PM팀 Official 시트 ID: `1zABshhlzDB_bkBPMpV4OY11xtHXYeQaHZPITaX75lOA`
- 임포트 대상: 하도급상세, 연락처, 이체내역(260316_지급내역), 수금현황

### PM Official 시트 임포트 (`sheets_import.py` — `import_from_pm_sheet()`)
- PM팀 Official 스프레드시트에서 전체 프로젝트 기본정보를 일괄 읽어 DB에 반영
- 자동 시트 감지: 날짜명 시트 (예: "260316_지급내역")에서 최신 시트 자동 선택
- 임포트 모드: `upsert` (기존 덮어쓰기) / `insert_only` (신규만 추가)
- API: `POST /api/fund/import-pm-sheet`
- 웹: fund.html "PM 시트 가져오기" 버튼

### GW 자동 동기화 스케줄러 (`scheduler.py`)
- **APScheduler** `BackgroundScheduler` + `CronTrigger` 사용
- 환경변수:
  - `GW_SYNC_CRON`: cron 표현식 (기본 `"0 8 * * *"` = 매일 08:00)
  - `GW_SYNC_ENABLED`: 활성화 여부 (기본 `"true"`)
  - `ADMIN_GW_IDS`: 동기화에 사용할 관리자 GW 계정 ID
- 3단계 크롤링: project_crawler → budget_by_project → budget_summary (기존 수동 동기화와 동일)
- 중복 실행 방지: `threading.Event` 플래그 (`sync_running`)
- 결과 저장: `notifications` 테이블에 `sync_success` / `sync_error` 타입으로 기록
- app.py lifespan 이벤트로 시작/종료 관리 (`start_scheduler()` / `stop_scheduler()`)

---

## 8. 계약서 자동 생성 (`src/contracts/`)

### 지원 양식
| 양식 | 템플릿 파일 | 설명 |
|------|-------------|------|
| 자재납품 | `자재납품_template.docx` | 자재 납품 계약서 |
| 공사 | `공사_template.docx` | 공사 하도급 계약서 |

### 생성 방식
- **단건**: 챗봇 대화로 항목 입력 → Word 문서 생성 → `/download/` 엔드포인트로 다운로드
- **다건**: 엑셀(XLSX) 파일 첨부 → 각 행별 계약서 일괄 생성
- 템플릿 변수: `{{회사명}}`, `{{계약금액}}`, `{{착공일}}` 등 Jinja2 형식

---

## 9. STT 음성 인식 (`src/chatbot/stt.py`)

- Google Cloud Speech-to-Text API 사용
- 서비스 계정: `config/support-officer-gmail-4f050c6631d4.json`
- 지원 형식: OGG, MP3, WAV, M4A, FLAC
- 프로세스: 음성 파일 업로드 → STT 변환 → 변환된 텍스트를 일반 메시지로 처리
- 웹 챗봇: 파일 업로드 UI로 음성 파일 전송
- 텔레그램: 음성 메시지 또는 오디오 파일 자동 인식

---

## 10. Gemini Function Calling 도구 (`tools_schema.py` / `handlers.py`)

| 도구명 | 기능 | 카테고리 |
|--------|------|----------|
| `reserve_meeting_room` | 회의실 예약 | 회의실 |
| `cancel_meeting_reservation` | 예약 취소 | 회의실 |
| `check_reservation_status` | 예약 조회 | 회의실 |
| `check_available_rooms` | 빈 시간 검색 | 회의실 |
| `list_my_reservations` | 향후 N일 본인 예약 목록 | 회의실 |
| `cleanup_test_reservations` | [TEST_] 예약 일괄 취소 | 회의실 |
| `submit_expense_approval` | 지출결의서 작성 (22단계) | 전자결재 |
| `submit_draft_approval` | 임시보관 문서 상신 | 전자결재 |
| `submit_approval_form` | 전자결재 대화형 플로우 (거래처등록 등) | 전자결재 |
| `start_approval_wizard` | 전자결재 단계별 위저드 시작 | 전자결재 |
| `search_project_code` | 프로젝트 코드 검색 | 전자결재 |
| `start_contract_wizard` | 계약서 작성 위저드 시작 | 계약서 |
| `generate_contracts_from_file` | 엑셀 파일 → 계약서 일괄 생성 | 계약서 |
| `get_mail_summary` | 메일 요약 | 메일 |
| `transcribe_audio` | 음성→텍스트 변환 STT | 음성 |
| `get_fund_summary` | 프로젝트 자금현황 요약 | 프로젝트 관리 |
| `get_project_detail` | 프로젝트 상세 조회 (개요/수금/하도급/TODO 종합) | 프로젝트 관리 |
| `compare_projects` | 전체 포트폴리오 비교 | 프로젝트 관리 |
| `generate_project_report` | 프로젝트 종합 보고서 생성 | 프로젝트 관리 |
| `update_project_info` | 프로젝트 개요 정보 수정 | 프로젝트 관리 |
| `add_project_note` | 프로젝트 메모/자료 추가 | 프로젝트 관리 |
| `add_project_subcontract` | 하도급 업체 추가 | 프로젝트 관리 |
| `update_collection_status` | 수금 상태 변경 | 프로젝트 관리 |
| `add_project_todo` | TODO 항목 추가 | 프로젝트 관리 |
| `add_project_contact` | 거래처 연락처 추가 | 프로젝트 관리 |
| `get_overdue_items` | 기한 초과/미수금/긴급 TODO 조회 | 프로젝트 관리 |
| `update_project_milestone` | 마일스톤 완료/추가 | 프로젝트 관리 |

---

## 11. 회의실 예약 API

### 회의실 매핑
| 회의실 | resSeq |
|--------|--------|
| 1번 | 45 |
| 2번 | 46 |
| 3번 | 47 |
| 4번 | 48 |
| 5번 | 49 |

### rs121A 엔드포인트
| API | 용도 | 상태 |
|-----|------|------|
| rs121A01 | 자원(회의실) 목록 조회 | 동작 확인 |
| rs121A05 | 예약 현황 조회 | 동작 확인 |
| rs121A06 | 신규 예약 생성 | 동작 확인 ★ |
| rs121A11 | 예약 취소 (statusCode="CA") | 동작 확인 |
| rs121A14 | 예약 중복 체크 | 동작 확인 |
| rs121A24/A28/A29/A38 | 자원예약 추가 API | 확인됨 |

### 회사 정보 (고정)
```json
{
  "compSeq": "1000",
  "groupSeq": "gcmsAmaranth36068",
  "deptSeq": "2017"
}
```
- empSeq: "2922" (전태규)

### 회의실 예약 취소 핵심
- `schmSeq`: rs121A05 조회 시 항상 빈값 → `seqNum`으로 취소
- `empSeq`: company_info에서 획득
- 본인 필터: `res.get('empSeq') == company_info.get('empSeq')`

---

## 12. GW URL 패턴

| 페이지 | URL |
|--------|-----|
| 메인 | `/#/` |
| 결재 HOME | `/#/EA/` (`span.module-link.EA` 클릭) |
| 지출결의서 양식 | `/#/HP/APB1020/APB1020?formDTp=APB1020_00001&formId=255` |
| 임시보관문서 | `/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1020` |
| 회의실 예약 | `/#/UK/UKA/UKA0000?specialLnb=Y&moduleCode=UK&menuCode=UKA&pageCode=UKA0000` |
| 메일 | `/#/UD/UDA/UDA0000?specialLnb=Y&moduleCode=UD&menuCode=UDA&pageCode=UDA0020` |

### GW 모듈 CSS 셀렉터
- 전자결재: `span.module-link.EA`
- 회의실: `span.module-link.RM` → "회의실" 탭 클릭
- 메일: `span.module-link.ML`
- 임직원업무관리: `span.module-link.HR` (HP가 아님!)
- 예산관리: `span.module-link.BM` (BN이 아님!)

---

## 12-1. GW 크롤러 (3종)

### 하이브리드 크롤링 전략
routes.py에서 GW 동기화 시 3단계 순차 실행:
1. **project_crawler** → 프로젝트 등록정보 (시작일, 기간, 발주처, 담당자)
2. **budget_crawler_by_project** → 예실대비현황(사업별) — 기간선택으로 전기+당기 일괄 조회
3. **budget_crawler (summary)** → 예실대비현황(상세) — 수입합계/지출합계/총잔액만 보충

### budget_crawler_by_project.py (사업별, 메인)
- **DatePicker 3방식**: JS React state, Playwright fill, 조건패널 input
- 프로젝트 코드에서 연도 추출 (GS-25-XXXX → 2025) → 시작일 자동 설정
- 메서드: `crawl_budget_by_project()` (단건), `crawl_all_by_project()` (배치)

### budget_crawler.py (상세, 보충)
- 예실대비현황(상세) 페이지에서 합계 데이터만 추출
- `crawl_budget_summary()`, `crawl_all_summary()` (경량 합계 전용)
- `_save_budget_summary_to_db()`: projects.budget_summary TEXT 컬럼에 JSON 저장

### project_crawler.py (프로젝트 등록정보 + 전체 목록)
- 경로: 예산관리(BM) → 예산기초정보설정 → 프로젝트 등록
- `crawl_project_info()` (단건), `crawl_all_project_info()` (배치)
- `search_gw_projects()` — GW 전체 프로젝트 목록 크롤링 (3단계 폴백):
  1. "전체데이터보기" 버튼 → OBTDataGrid 팝업에서 ~199개 추출
  2. React fiber에서 프로젝트 배열 탐색
  3. 프로그레시브 스크롤 (카드 리스트 가상 렌더링 대응)
- **그룹 컬럼 처리**: `getColumns()`가 그룹 컬럼 반환 시 `collectCols()` 재귀로 리프 컬럼 추출
- **컬럼 매핑**: 헤더 텍스트("프로젝트코드", "프로젝트명") → 실제 필드명 매핑 + 값 패턴 폴백
- **캐시**: `gw_projects_cache` 테이블에 저장, `/api/fund/gw/search-projects`로 키워드 검색

### HTTP 에러 처리 (fund.js gwFetch)
프론트엔드에서 GW 호출 시 `gwFetch()` 래퍼 사용:
- 401 → "로그인이 만료되었습니다. 다시 로그인해주세요."
- 403 → "권한이 없습니다. 페이지를 새로고침하세요."
- 504 → "서버 응답 시간이 초과되었습니다."
- 500 → "서버 오류가 발생했습니다."

---

## 13. 채널별 아키텍처

### 챗봇 (웹)
- FastAPI + SQLite (chat_db), JWT 쿠키 인증
- 대화 히스토리: DB 영구 저장 (`data/chatbot/chat_history.db`)
- 세션 목록/전환/삭제 UI
- 파일 업로드: base64 인코딩 → Gemini 전달
- 음성 파일: MIME 타입 audio/* 허용 → STT 변환

### 텔레그램
- python-telegram-bot 라이브러리
- 인메모리 세션 (최근 40개, 재시작 시 소실)
- `/clear` 명령어로 대화 지우기 (로그인 유지)
- 음성/오디오 메시지 핸들러: OGG 다운로드 → STT → 텍스트로 처리

---

## 14. OBTDataGrid API 접근법

- **RealGrid가 아님** → OBTDataGrid (더존 자체 canvas 그리드, 내부 RealGrid 래핑)
- `window.gridView` 등 전역 변수 **없음** (null)
- **접근 경로**: `.OBTDataGrid_grid__22Vfl` → React fiber (`__reactFiber`) → depth 3 → `stateNode.state.interface`
- 주요 메서드: `setValue()`, `getValue()`, `getRowCount()`, `getColumns()`, `setSelection()`, `focus()`, `commit()`
- **그룹 컬럼 처리** (세션 XXIII 발견):
  - `getColumns()` → 최상위 컬럼 반환 (그룹 컬럼은 `.columns` 배열을 가짐)
  - 재귀 순회: `c.columns` 있으면 재귀, 없으면 리프 컬럼으로 수집
  - 리프 컬럼의 `c.header.text`로 헤더 텍스트 매핑 (예: "프로젝트코드" → 실제 필드명)
  - `getDataSource().getFieldNames()`는 내부 필드명만 반환 (`basicGroup`, `dtlDc` 등) → 헤더 텍스트와 불일치
  - `getValue(row, fieldName)`으로 값 읽기 시 리프 컬럼의 `.name` 사용
- 상세: MEMORY.md의 "OBTDataGrid API 접근법" 섹션 참고

### OBT 위젯 대응 패턴

| OBT 위젯 | 특성 | 대응 방법 |
|-----------|------|-----------|
| **OBTGrid** | canvas 기반, DOM 행 없음 | 모달 제목 기준 상대 좌표 클릭/더블클릭 |
| **OBTDialog2** | dimClicker 오버레이가 뒤쪽 요소 차단 | JS로 dialog 컨테이너 내부 요소 직접 탐색 |
| **OBTAutoComplete** | 입력 → 드롭다운 → Tab으로 확정 | `type()` → `wait_for_selector('.autocomplete')` → `press('Tab')` |
| **OBTDatePicker** | 날짜 input + 캘린더 팝업 | `fill(date)` → `press('Tab')` (캘린더 우회) |
| **OBTCheckBox** | 커스텀 div 체크박스 | `[class*='Checkbox']`, `[role='checkbox']` 셀렉터 사용 |

---

## 15. 보안 규칙

- GW 비밀번호: **Fernet 대칭 암호화** (Playwright 로그인에 평문 필요)
- 텔레그램: 비밀번호 포함 메시지 **자동 삭제** + 2단계 인증 (아이디/비번 분리)
- JWT: httpOnly 쿠키, 24시간 만료, sameSite=lax
- GW 세션: 2시간 TTL 캐시
- 관리자 GW ID: `tgjeon` (하드코딩)
- `config/.env` 파일에 민감 정보 집중 관리, 절대 커밋 금지
- **RBAC**: `owner_gw_id` 컬럼으로 프로젝트 소유자 검증 (빈 값 = 전체 허용, admin 바이패스)
- **CSRF**: Double-Submit Cookie 패턴 (`CSRFMiddleware` + `X-CSRF-Token` 헤더)
- **CSP**: `script-src 'self'` (unsafe-inline 제거) + event delegation
- **파일 경로**: 업로드 시 UUID 토큰 반환 (서버 경로 숨김)

---

## 16. 테스트 (`tests/` — pytest)

### 실행 방법
```bash
pytest                    # 전체 실행 (94 tests, ~0.72초)
pytest tests/unit/        # 단위 테스트만
pytest tests/integration/ # 통합 테스트만
pytest -k "test_fund"     # 특정 키워드 매칭
```

### 테스트 구성
| 파일 | 테스트 수 | 대상 |
|------|-----------|------|
| `tests/unit/test_user_db.py` | 18 | Fernet 암호화, 사용자 CRUD, approval_config |
| `tests/unit/test_jwt_utils.py` | 9 | JWT 토큰 생성/검증/만료 |
| `tests/unit/test_fund_db.py` | 27 | 프로젝트/공종/하도급/연락처/수금/요약 |
| `tests/unit/test_chat_db.py` | 16 | 세션/메시지/미지원요청 |
| `tests/unit/test_session_manager.py` | 9 | 캐시 TTL/hit/miss/스레드 안전성 |
| `tests/integration/test_api_auth.py` | 8 | FastAPI 로그인/인증/세션 API |
| **합계** | **94** | — |

### 픽스처 (`tests/conftest.py`)
- `TEST_JWT_SECRET`, `TEST_FERNET_KEY`: 테스트 전용 키
- `autouse monkeypatch`: 환경변수 자동 주입 (실제 `.env` 불필요)
- `tmp_path`: pytest 내장 — 임시 DB 파일 자동 생성/정리

---

## 17. 세션 마무리 체크리스트

1. `DEVELOPER_GUIDE.md` — 새 기술 패턴/API/규칙/구조 변경 반영
2. `MEMORY.md` (auto-memory) — 새 파일 경로, 발견사항, 세션 작업 기록
3. `USER_MANUAL.md` — 사용자 기능 변경 시 업데이트
4. 탐색 스크립트가 남아있으면 정리 (불필요 시 삭제)
5. 새 테스트가 있으면 `tests/` 디렉토리에 추가 및 `pytest` 실행 확인
6. `pytest` 전체 통과 확인
