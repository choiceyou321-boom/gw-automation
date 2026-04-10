# 개발자 가이드 (Developer Guide)

> 마지막 업데이트: 2026-04-10 (세션 XLIV — 공정표 Full CPM 고도화 + 선급금 bank picker 구현 + 코드 리뷰)
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

### page.evaluate() JS 인젝션 방지 패턴 (세션 XXXIV 확립)

Playwright `page.evaluate()` 내 f-string 보간은 JS 인젝션 위험. 아래 패턴 필수 적용:

```python
# base.py에 정의된 헬퍼
from src.approval.base import _js_str  # json.dumps()로 안전한 JS 리터럴 생성

# ✅ 안전: _js_str()로 이스케이프된 문자열 사용
page.evaluate(f"cols.find(c => c.header === {_js_str(col_name)})")

# ✅ 안전: Playwright 인자 전달 방식 (user HTML 등 긴 문자열)
page.evaluate("(htmlText) => { el.innerHTML = htmlText; }", html_text)

# ❌ 위험: f-string으로 직접 보간 (따옴표/백틱 탈출 가능)
page.evaluate(f"el.innerHTML = `{html_text}`")  # 절대 금지
```

**적용 범위**: grid.py (11개소), expense.py (5개소), vendor.py (3개소)

### Playwright 세션 컨텍스트 매니저 (`handlers.py`)

```python
@contextmanager
def _playwright_session(gw_id: str, encrypted_pw: str):
    """Playwright 세션 생성/정리 — finally에서 browser.close + pw.stop 보장"""
    pw = sync_playwright().start()
    try:
        browser, context, page = login_and_get_context(...)
        yield browser, context, page
    finally:
        if browser: close_session(browser)
        if pw: pw.stop()
```

**적용 핸들러**: `handle_submit_draft_approval`, `handle_search_project_code`

### GW 자격 증명 검증 패턴 (세션 XLI)

회원가입 시 Playwright로 실제 GW 로그인을 시도하여 유효성을 검사한다.

```python
# src/auth/login.py
async def validate_gw_credentials(gw_id: str, password: str) -> tuple[bool, str]:
    """GW 로그인 시도 → (성공여부, 에러메시지) 반환. 90초 타임아웃."""
```

- **세마포어**: `_validation_semaphore = asyncio.Semaphore(1)` — 동시 검증 1개 제한 (Playwright 충돌 방지)
- **타임아웃**: `asyncio.wait_for(..., timeout=90)` — 90초 초과 시 타임아웃 에러
- **적용 위치**: `app.py` 웹 회원가입 + `telegram_bot.py` `_register_with_gw_validation()`
- **에러 변환**: `gw_error_to_user_message(error)` — 내부 에러를 사용자 친화적 한국어 메시지로 변환
- **관리자 보호**: `ADMIN_GW_IDS` 환경변수 계정은 검증 실패해도 삭제 불가
- **일괄 검증 CLI**: `scripts/validate_existing_users.py` — 기존 유저 전체 GW 로그인 검증
- **관리자 페이지 검증 API** (세션 XLII):
  - `POST /admin/users/{gw_id}/validate` — 개별 유저 GW 검증 (90초 타임아웃)
  - `POST /admin/validate-all` — 전체 유저 SSE 스트리밍 검증 (관리자 스킵, 3초 간격)
  - `admin.html`: 유저 테이블에 "GW 검증" 컬럼 + "전체 GW 검증" 버튼 + 프로그레스 바 + "무효 유저 삭제" 버튼
- **테스트**: `tests/unit/test_gw_validation.py` (11개 테스트)

### 업로드 토큰 TTL (`app.py`)
- `_upload_tokens` dict에 TTL 1시간 적용
- `_cleanup_expired_tokens()`: 만료 토큰 삭제 + 연관 임시파일 `unlink()`
- `/upload` 요청 시마다 자동 실행

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
| 연장근무 | code_ready | 43 | `_save_overtime_draft()` 구현 완료 — GW DOM 검증 필요 |
| 외근신청 | code_ready | 41 | `_save_outside_work_draft()` 구현 완료 — GW DOM 검증 필요 |

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

### 지출결의서 OBTAlert 처리 패턴 (세션 XXXVI 확립)

**문제**: GW 지출결의서 폼 진입 시 OBTAlert_dimmed 오버레이가 react-reveal 애니메이션으로 지연 등장 (3초 이상 가능)하여 프로젝트코드도움 input 클릭을 차단함.

**근본 원인 분석**:
1. 폼이 이전 임시저장 문서를 자동 로드 → project input에 이전 값 (예: GS-25-0031) 존재
2. project input에 값이 있으면 click 시 GW가 picker를 열지 않음
3. OBTAlert_dimmed가 투명 오버레이로 폼 전체 차단 (pointer-events: all)
4. invoice modal 선택 후 GW가 "매칭된(매입)계산서가 없습니다." OBTAlert를 invoice modal 내부에 표시

**확립된 해결 패턴**:
```python
# _fill_expense_fields 초입: OBTAlert 출현 대기 후 dismiss
try:
    page.wait_for_selector('[class*="OBTAlert_dimmed"]', state="attached", timeout=3000)
except Exception:
    pass  # 3초 내 미출현 → 그냥 진행
self._dismiss_obt_alert()

# _fill_project_code: cascade alert + blur-click 패턴
# 1) 연속 2회 clean 확인으로 OBTAlert 안정화
consecutive_clean = 0
for _ in range(10):  # 최대 5초
    has_obt = page.locator('[class*="OBTAlert_dimmed"]').count() > 0
    if has_obt:
        self._dismiss_obt_alert()
        consecutive_clean = 0
    else:
        consecutive_clean += 1
        if consecutive_clean >= 2: break
    page.wait_for_timeout(500)

# 2) 기존값 초기화 + blur (fill() 후 focus 유지 상태에서 click은 GW picker 미오픈)
current_val = proj_input.input_value()
if current_val:
    proj_input.fill('')
    page.keyboard.press('Tab')  # blur
    page.wait_for_timeout(300)

# 3) 클릭
proj_input.click(timeout=5000)
```

**_dismiss_obt_alert 버튼 우선순위** (base.py):
```javascript
// '취소'를 '확인' 앞에: "이전 작성 중인 결의서" 알림에서 취소(=새 폼)가 확인(=이전 문서 로드)보다 우선
const targetTexts = ['저장안함', '취소', '닫기', 'OK', '확인'];
```

**OBTAlert overlay 완전 제거 확인**:
```python
# JS click 후 DOM에서 실제 제거될 때까지 대기
page.wait_for_selector('[class*="OBTAlert_dimmed"]', state="detached", timeout=5000)
```

**invoice modal 내 OBTAlert 이슈**:
- invoice 선택 후 "매칭된(매입)계산서가 없습니다." OBTAlert가 invoice modal 내부에 표시
- _fill_project_code의 retry loop에서 이 OBTAlert를 감지하여 "확인" 클릭
- "확인" 클릭이 OBTAlert 닫히나 invoice modal 자체는 계속 열려있어 project input 차단
- invoice modal 닫기 로직 필요

**미해결 이슈**:
- invoice modal dataProvider 접근이 expense form grid를 읽음 (invoice modal grid 아님)
- 실제 탑조명 invoice row를 찾지 못해 "매칭된 없음" 발생

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
| `budget_actual` | GW 예실대비현황 (스크래핑, 연도별·계층 구조) — gw_project_code, gisu, def_nm, div_fg, is_leaf 포함 |
| `gw_projects_cache` | GW 전체 프로젝트 목록 캐시 (code UNIQUE, name, start_date, end_date, cached_at) |
| `project_aliases` | 프로젝트 별칭 (다양한 이름으로 같은 프로젝트를 찾기 위한 메타데이터) |
| `project_schedule_items` | 공정 일정 항목 (item_name, start_date, end_date, status, color, notes, group_name, subtitle, item_type, bar_color, sort_order) |

### `projects` 테이블 추가 컬럼
- `is_archived INTEGER DEFAULT 0` — 이전 프로젝트 보관 여부 (1=보관, 0=활성)
- `timeline_start_month TEXT DEFAULT ''` — 타임라인 시작월 (YYYY-MM, 프로젝트별 저장)
- `timeline_end_month TEXT DEFAULT ''` — 타임라인 종료월 (YYYY-MM, 프로젝트별 저장)

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
| GET | `/api/fund/projects/{id}/budget/detail` | 예실대비 계층 구조 조회 (gisu, leaf_only 파라미터) |
| POST | `/api/fund/projects/{id}/budget/sync-actuals` | 단일 프로젝트 예실 GW 동기화 (budget_crawler 호출) |
| POST | `/api/fund/gw/sync-all-budget-actuals` | 전체 프로젝트 일괄 동기화 |
| GET | `/api/fund/gw/project-list` | GW 캐시 프로젝트 목록 (keyword 검색) |
| GET | `/api/fund/budget/cross-project` | 전체 프로젝트 예실 집계 (집행률 상위 N) |
| GET/POST | `/api/fund/projects/{id}/schedule` | 공정 일정 항목 조회/저장 |
| POST | `/api/fund/projects/{id}/archive` | 프로젝트 보관/복원 (is_archived) |
| POST | `/api/fund/import-schedule-from-pm-sheet` | PM 시트 → 일정 항목 일괄 가져오기 |
| POST | `/api/fund/import-collections-from-pm-sheet` | PM 시트 → 수금일정 일괄 가져오기 |
| GET | `/api/fund/projects/{id}/tax-invoices` | 세금계산서 발행 내역 조회 |
| GET | `/api/fund/projects/{id}/budget-changes` | 예산 변경 이력 조회 |
| GET | `/api/fund/projects/{id}/collection-schedule` | 수금 예정 내역 조회 |
| GET | `/api/fund/projects/{id}/payment-approvals` | 자금집행 승인 현황 조회 |
| GET | `/api/fund/projects/{id}/risks` | 리스크 목록 조회 |
| GET | `/api/fund/projects/{id}/gw-contracts` | GW 계약 내역 조회 |
| GET | `/fund` | 프로젝트 관리 웹 페이지 서빙 |
| GET | `/insights` | AI 인사이트 페이지 서빙 |

### 공정표 자동 생성 시스템 (세션 XLI, XLIV 고도화)

인테리어 시공 공정표를 자동 생성하는 모듈. Process_Map.xlsx 교육자료 기반 9개 그룹·45개 공종 마스터 데이터를 사용한다.

**세션 XLIV Phase A 고도화**:
- **A-1**: 면적 보정 로그 연속 함수 (기존 5단계 계단 → `math.log2` 기반 연속 곡선, 0.5~2.0 범위)
- **A-2**: Full CPM — Forward + Backward Pass + Float(여유시간) + 임계경로(CP) 판별
- **A-3**: 가중 스케일링 — CP 공종 보호 (scale*1.05), 비CP 공종 우선 축소 (scale*0.95)
- **A-4**: DAG 순환 의존성 검증 — Kahn's algorithm 위상정렬
- 간트차트 CP 표시: ★ 마커 + 빨간 굵은 글씨 + 빨간 테두리 바
- 리스트 시트 CP/Float 컬럼 추가
- 타임라인 뷰 CP 표시: 빨간 테두리 + box-shadow + ★ prefix

**schedule_items 반환 필드** (A-2 추가):
```
is_critical: bool    # 임계경로 여부
total_float: int     # 총 여유시간 (일)
early_start: int     # 최조 시작시점 (상대일)
late_start: int      # 최지 시작시점 (상대일)
```

**summary 반환 필드** (A-2 추가):
```
critical_path_count: int   # 임계경로 공종 수
raw_duration: int          # CPM 역산 원래 총 기간
scale_factor: float        # 비례 스케일 계수
```

| 파일 | 용도 |
|------|------|
| `src/fund_table/process_map_master.py` | 공종 마스터 데이터 (9그룹·45공종, 선행공종·기본공기 포함) |
| `src/fund_table/schedule_generator.py` | Full CPM 엔진 (Forward+Backward Pass, Float, CP, DAG 검증, 로그 면적 보정, 가중 스케일링) |
| `src/fund_table/schedule_export.py` | 엑셀 2시트(간트차트+리스트) + PDF(LibreOffice) 출력, CP 빨간 표시 |
| `src/fund_table/estimate_parser.py` | 내역서 자동 파싱 (별칭 매칭 + 유사도 매칭으로 공종 자동 추출) |

**API 4개** (`routes.py`):

| Method | 경로 | 기능 |
|--------|------|------|
| GET | `/api/fund/process-map/trades` | 공종 마스터 목록 조회 |
| POST | `/api/fund/process-map/parse-estimate` | 내역서 파싱 (공종 자동 추출) |
| POST | `/api/fund/process-map/generate` | 공정표 생성 (CPM 엔진) |
| POST | `/api/fund/process-map/export` | 엑셀/PDF 내보내기 |

**UI**: `/fund` 일정표 탭에 "공정표 자동생성" 버튼 → 모달 → 내보내기 드롭다운

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

### PM 시트 → 일정 임포트 (`sheets_import.py` — `import_schedule_from_pm_sheet()`)
- PM 시트에서 날짜 필드(착공일/준공일/설계착수/설계완료/오픈일) + 마일스톤 → `project_schedule_items`로 변환
- `overwrite=False`: 이미 일정 항목 있는 프로젝트 건너뜀
- `_normalize_date(raw)`: YYYY-MM-DD, YYYY.MM.DD, YY.MM.DD 형식 정규화
- `_infer_schedule_status(start, end)`: 오늘 기준 planned/ongoing/done 자동 판별
- 색상 자동 배정: 설계=보라, 시공=주황, 오픈=초록, 마일스톤=파랑
- API: `POST /api/fund/import-schedule-from-pm-sheet`
- 웹: fund.html "일정 가져오기" 버튼

### PM 시트 → 수금일정 임포트 (`sheets_import.py` — `import_collections_from_pm_sheet()`)
- PM 시트 전체 프로젝트 워크시트 순회 → 각 프로젝트 DB 매칭 → `_import_collections()` 호출
- `overwrite=True` 기본 (기존 수금 데이터 덮어쓰기)
- 시스템 시트(날짜명) 자동 건너뜀
- API: `POST /api/fund/import-collections-from-pm-sheet`
- 웹: fund.html "수금일정 가져오기" 버튼

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

## 7-1. 일정표 탭 & 타임라인 시스템 (세션 XXXVII)

### 공정 일정 데이터 모델 (`project_schedule_items`)

```sql
CREATE TABLE project_schedule_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    item_name TEXT NOT NULL DEFAULT '',
    start_date TEXT DEFAULT '',        -- YYYY-MM-DD
    end_date TEXT DEFAULT '',
    status TEXT DEFAULT 'planned',     -- planned/ongoing/done/hold
    color TEXT DEFAULT '#3b82f6',
    notes TEXT DEFAULT '',
    group_name TEXT DEFAULT '',        -- 팀/그룹명 (예: 공간팀, 시각팀)
    subtitle TEXT DEFAULT '',          -- 세부 역할 설명
    item_type TEXT DEFAULT 'bar',      -- 'bar' | 'milestone' (세로 점선)
    bar_color TEXT DEFAULT '',         -- 커스텀 색상 (비면 group 색상 팔레트 사용)
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
```

### 타임라인 렌더링 패턴 (`fund.js`)

**3단 헤더**: 월 → 주차(1W, 2W...) → 날짜(MM-DD)
```javascript
// 주차 배열 생성 (월요일 기준)
const weeks = [];
let wStart = new Date(minD);
// 월요일로 조정
const dow = wStart.getDay();
wStart.setDate(wStart.getDate() - (dow === 0 ? 6 : dow - 1));
```

**그룹별 렌더링**: `group_name`으로 묶어 같은 행에 다중 바 표시
```javascript
// 동일 group_name 항목 → 같은 <tr>에 absolute 바로 렌더링
// group_name 없으면 'status' 기반 색상 클래스 사용
const cls = barColor ? '' : (it.group_name ? colorClass : (it.status || 'planned'));
```

**팀 색상 팔레트**: `.c0`~`.c7` CSS 클래스, 그룹 순서대로 자동 배정
```
c0: 주황(#f97316), c1: 청록(#14b8a6), c2: 핑크(#ec4899),
c3: 회색(#9ca3af), c4: 보라(#8b5cf6), c5: 파랑(#3b82f6),
c6: 초록(#22c55e), c7: 노랑(#eab308)
```

**마일스톤**: `item_type='milestone'` → 빨간 점선 세로선 + 레이블
**오늘 마커**: `today` 기준 좌표 % 계산 → 빨간 실선 + "오늘" 칩

### 이전 프로젝트 폴더 (사이드바)
- `is_archived=1` → 활성 목록에서 숨김, 사이드바 하단 폴더로 이동
- 드래그 → `#archivedDropZone`에 drop → `archiveProject(id, true)` 호출
- 폴더 토글: `toggleArchivedFolder()` — 확장/축소 상태 유지
- "↩" 버튼 → `archiveProject(id, false)` 복원
- 보관된 프로젝트 0개 시 폴더 숨김

### 마일스톤 D-Day 배지 (`fund.js`)
```javascript
function calcDday(dateStr) { /* 오늘 기준 정수 차이 */ }
function ddayHtml(dateStr, completed) {
  // 완료: 초록 "✓완료"
  // 0: 빨강 "D-Day"
  // -7~-1: 주황 펄스 애니메이션 "D-N"
  // 미래: 파랑 "D-N"
  // 과거(미완료): 빨강 "D+N"
}
```

---

## 7-2. /fund 페이지 신규 기능 (세션 XXXVIII, 2026-04-02)

### 타임라인 시작/종료월 저장 (`_saveTlRange`)
- `projects` 테이블에 `timeline_start_month`, `timeline_end_month` TEXT 컬럼 추가
- `_saveTlRange(startMonth, endMonth)`: PUT `/api/fund/projects/{id}` 호출 후 `projectsCache` 동기 갱신
- `loadSchedule()`: 프로젝트 전환 시 `projectsCache`에서 저장된 월 값 복원 (재API 호출 불필요)

### 이전 프로젝트 폴더 CSP 수정 패턴
- **문제**: `fund.html`에 `script-src 'self'` CSP → 정적 HTML의 `onclick=` 모두 차단
- **해결**: 정적 HTML의 `onclick` 제거 → JS `addEventListener` + `data-*` 이벤트 위임
  ```javascript
  // 정적 헤더에 onclick 대신
  document.getElementById('archivedFolderHeader')?.addEventListener('click', toggleArchivedFolder);
  // 동적 생성 버튼에 data-* 속성
  `<button data-restore-project="${p.id}">↩</button>`
  // 부모에서 위임
  archivedList.addEventListener('click', e => {
    const btn = e.target.closest('[data-restore-project]');
    if (btn) archiveProject(+btn.dataset.restoreProject, false);
  });
  ```
- 아카이브 폴더: 보관 0개일 때도 폴더 항상 표시 (드롭존 역할) — `archivedProjectList`만 숨김

### 대시보드 경고 카드 패턴
- `renderDashCollectionAlert(collections)`: 미수금 + `collection_date` 있는 항목 → D-7 이내 필터 → 경고 카드
- `renderDashBudgetAlert(projectId)`: `GET /budget/detail?leaf_only=true` → 집행률 95% 이상 항목 → 경고 카드
- 두 함수 모두 `loadDashboard()` 내에서 호출, 데이터 없으면 카드 숨김

### 포트폴리오 수익성 그래프 (`_renderProfitChart`)
- `renderPortfolio()` 또는 `loadPortfolioView()` 내에서 호출
- `projectsCache` 배열 기반 (추가 API 없음)
- 수주액 0인 프로젝트 제외, 이익률 = `profit_amount / (design_amount + construction_amount) * 100`
- 순수 CSS 막대 그래프: `.pf-profit-chart-section` 컨테이너, `.pf-profit-bar` 바

### 신규 탭: 계약 / 리스크
- `data-tab="contracts"` → `loadGwContracts(projectId)` → `GET /api/fund/projects/{id}/gw-contracts`
- `data-tab="risks"` → `loadRisks(projectId)` → `GET /api/fund/projects/{id}/risks`
- 리스크 탭: 심각도 뱃지(high=빨강, medium=주황, low=초록) + 해결/재오픈 버튼 + 추가 버튼
- CSP 준수: `panel-risks`에 이벤트 위임

### gw_projects_cache v2 연동
- `routes.py` fetch-project-list 엔드포인트: `save_gw_projects_cache()` → `save_gw_projects_cache_v2()` 교체
- `db.py search_gw_projects_cache()`: SELECT에 확장 7개 필드 포함
- `project_crawler.py`: `_parse_project_list()`, `_try_full_data_view()` v2 확장 필드 전달

### 연장근무/외근신청 양식 (`other_forms.py`)
- `_save_overtime_draft(data)`: HR 모듈 → 연장근무신청서 → 날짜/시작-종료시각/사유 입력 → 저장
- `_save_outside_work_draft(data)`: HR 모듈 → 외근신청서 → 외근일/외출-복귀시각/외근지/사유 입력 → 저장
- `save_form_draft(form_type, data)` 디스패처: `"연장근무"/"overtime"`, `"외근신청"/"outside_work"` 분기
- **상태**: `code_ready` — GW HR 모듈 DOM 검증 진행 중 (세션 XLII)

### 근태관리 모듈 DOM 분석 (세션 XLII 발견사항)

**네비게이션 경로 (확인됨)**:
1. `span.module-link.HR` 클릭 → 임직원업무관리 모듈 (`/#/HP/HPM0110/HPM0110`) ✓
2. LNB `li.nav-item:has-text('근태관리')` 스크롤+클릭 → 근태관리 모듈 (`/#/UF/UFA/UFA0000?specialLnb=Y&moduleCode=UF&menuCode=UFA&pageCode=UFA1000`) ✓

**LNB 구조 (HR 모듈 sideLnbMenu)**:
```
마이페이지 > 내정보관리 > 개인인사정보조회 / 인사정보변경신청 / 인증기기 설정
             업무보고 / 주소록 > 주소록관리 / 노트
             근태관리 > 근태신청 / 연차관리
             인사관리 / 급여관리 / 경비청구 / 지출결의·계산서 / 예산관리
```

**specialLnb 사이드바 (근태관리 모듈, 스크린샷 확인됨)**:
- 근태신청현황
- 비출퇴근사유
- **시간외근무** ← 연장근무 메뉴 (코드의 "연장근무신청서" 키워드 불일치)
- 휴가관리
- 학자금 반영현황

**⚠️ 핵심 이슈**: specialLnb 사이드바 메뉴 항목이 **표준 DOM에 노출되지 않음**
- `document.body.innerText`에 "시간외근무" 텍스트 미포함
- `querySelectorAll('*')`로 좌표 스캔해도 해당 요소 미발견
- Shadow DOM/Web Component 아님 — GW SPA 자체 가상 렌더링 추정
- 좌표 클릭 시 하위 게시판 사이드바로 관통 (z-index 문제)

### 근태관리 UFA URL 권한 문제 (세션 XLIII 최종 확인)

**발견 사항**:
- `tgjeon` 계정 기준, UFA1010~UFA1060 모든 URL에서 "권한 없는 메뉴" 팝업 후 게시판으로 리다이렉트
- HR 모듈 LNB에서 `근태관리`는 `nav-item-close` 상태 = 하위 메뉴 없음 (계정 권한 없음)
- `formId=43` 직접 URL 접근 → GW가 마지막 열린 탭(지출결의서)으로 리다이렉트
- 좌표 클릭(120, 260~380) URL 변화가 포착되었으나 `menuCode=3000300_00200X` = 게시판 서브메뉴
- `POST /system/orbit/getMenuOptions` API는 CSRF 보호로 직접 호출 불가

**결론**: 근태관리 권한이 없는 계정으로는 어떤 UFA URL도 동작하지 않음.
실제 시간외근무 신청 권한이 있는 일반 직원 계정으로 DOM 검증이 필요.

**`_navigate_to_hr_attendance()` 현재 전략** (`src/approval/other_forms.py` line 1471):
1. HR LNB `근태관리` 펼치기 → "근태신청" / "시간외근무" JS force 클릭
2. 전자결재 결재작성 → "시간외근무" 양식 검색 후 선택
3. HP 모듈 HPA0010/HPA1010/HPA1020 URL 직접 시도

**상태**: `code_ready` — 근태 권한이 있는 계정으로 실제 DOM 검증 필요

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

## 10-1. 핸들러 시그니처 규칙

모든 핸들러는 동일한 시그니처를 사용해야 함:

```python
def handle_xxx(params: dict, user_context: dict = None) -> str:
```

**절대 사용 금지 패턴**:
- `async def handle_xxx(args: dict, context: dict) -> str:` — agent.py에서 동기 호출하므로 async 불가
- 두 번째 인자 이름이 `context`이면 `user_context=user_context` 키워드 인자 전달 시 TypeError 발생

**발견 경위 (세션 XXX)**: `handle_compare_projects`, `handle_generate_project_report`, `handle_update_project_milestone` 3개 핸들러가 `async def` + `context: dict` 시그니처를 사용하여 `compare_projects` 호출 시 TypeError 발생 → 수정 완료.

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

### budget_crawler.py (상세 + RealGrid DataProvider)
- **시도 0 (최우선)**: `window.Grids.getActiveGrid().getDataProvider().getJsonRow(i)` — RealGrid v1.0 DataProvider 직접 접근
  - 필드: `lastYn, bottomFg, divFg, defNm, bgtCd, bgtNm, abgtSumAm, unitAm, subAm, sumRt, T0*`
  - 계층 구조: divFg (1:장, 2:관, 3:항, 4:목), lastYn (말단여부=is_leaf), bottomFg (상위여부)
- `crawl_budget_summary()`, `crawl_all_summary()` (경량 합계 전용)
- `crawl_budget_actual()` — 단건 상세 (project_id + project_code)
- `crawl_all_projects()` — 전체 일괄 상세
- `_transform_grid_data()`: def_nm/div_fg/is_leaf/gw_project_code → budget_actual 저장
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

## 12-2. 예실대비 프론트엔드 (fund.js / fund.html / fund.css)

### 계층 구조 테이블 렌더링 패턴

`loadBudget()` 함수에서 `/api/fund/projects/{id}/budget/detail` 응답을 계층 구조로 표시.

```javascript
const LEVEL_INDENT = { 1: 0, 2: 12, 3: 24, 4: 36 };  // divFg 기반 들여쓰기(px)
const DIV_BADGES = {
  '장': '<span class="budget-level-badge lv1">장</span>',
  '관': '<span class="budget-level-badge lv2">관</span>',
  '항': '<span class="budget-level-badge lv3">항</span>',
  '목': '<span class="budget-level-badge lv4">목</span>',
};
// rowClass: 장/관 상위 행은 budget-row-parent (배경 강조)
const rowClass = (divFg === 1 || divFg === 2) && !isLeaf ? 'budget-row-parent' : '';
```

### 집행액 상위 5 미니차트 (`_renderBudgetTopChart`)

- 컨테이너: `<div id="budgetTopChart">` (fund.html에 추가, table-wrapper 위)
- 말단 항목(is_leaf=1)만 대상, 집행액 내림차순 상위 5개
- 집행률에 따라 바 색상 분기:
  - 95% 이상 → `#ef4444` (빨강, 위험)
  - 80~95% → `#f97316` (주황, 경고)
  - 미만 → `#3b82f6` (파랑, 정상)

### CSS 클래스 요약 (fund.css)

| 클래스 | 용도 |
|--------|------|
| `.budget-level-badge.lv1` | 장 — 보라 배지 |
| `.budget-level-badge.lv2` | 관 — 파랑 배지 |
| `.budget-level-badge.lv3` | 항 — 초록 배지 |
| `.budget-level-badge.lv4` | 목 — 주황 배지 |
| `.budget-row-parent > td` | 상위(합계) 행 — 배경색 + 볼드 |
| `#budgetTopChart` | 미니차트 컨테이너 |
| `.chart-mini-row` | 각 항목 행 (라벨 + 바 + 값) |
| `.chart-mini-bar-wrap` | 바 배경 컨테이너 |
| `.chart-mini-bar` | 실제 진행 바 (너비 = 최대값 대비 비율) |
| `#pfProfitChartSection` | 포트폴리오 수익성 막대 그래프 컨테이너 |
| `.pf-profit-row` | 프로젝트 1행 (라벨+바+%) |
| `.pf-profit-bar` | 이익률 바 (20%이상=초록, 10~20%=파랑, 0~10%=주황, 음수=빨강) |
| `.dash-alert-danger` | 대시보드 기한 초과 경고 카드 (빨강) |
| `.dash-alert-warning` | 대시보드 임박 경고 카드 (주황) |
| `.collection-progress-wrap` | 수금 탭 수금률 진행바 컨테이너 |
| `.gw-sync-badge` | GW 데이터 신선도 배지 (N일 전 동기화) |

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

## 14-1. RealGrid v1.0 API (더존 예산관리 그리드)

더존 BN 모듈(예산관리)의 예실대비현황(NCC0630, NCC0631) 화면은 OBTDataGrid가 아닌 **RealGrid v1.0**을 사용.

### 기본 접근 패턴

```javascript
// 브라우저 콘솔 / Playwright evaluate()에서 사용
const Grids = window.Grids;                        // RealGrid 전역 레지스트리
const grid  = Grids.getActiveGrid();               // 현재 활성 그리드
const dp    = grid.getDataProvider();              // DataProvider
const count = dp.getRowCount();                    // 전체 행 수
const row   = dp.getJsonRow(i);                    // i번째 행 (0-based) → JSON object 반환
```

### 예실대비현황 데이터 필드 (15개)

| 필드명 | 타입 | 설명 |
|--------|------|------|
| `bgtCd` | str | 예산과목 코드 |
| `bgtNm` | str | 예산과목 명 |
| `defNm` | str | 구분명 (장/관/항/목) |
| `divFg` | int | 계층 플래그 (1:장, 2:관, 3:항, 4:목) |
| `lastYn` | str | 말단 여부 ("Y"/"N") |
| `bottomFg` | str | 상위 여부 ("Y"/"N") |
| `abgtSumAm` | int | 예산액 (원) |
| `unitAm` | int | 집행액 (원) |
| `subAm` | int | 잔액 (원) |
| `sumRt` | float | 집행률 (%) |
| `T0AbgtSumAm` | int | 전기 예산액 |
| `T0UnitAm` | int | 전기 집행액 |
| `T0SubAm` | int | 전기 잔액 |
| `T0SumRt` | float | 전기 집행률 |
| `T0TotalSumRt` | float | 전기 누계 집행률 |

### budget_crawler.py 시도 0 전체 코드

```javascript
(() => {
    try {
        const Grids = window.Grids;
        if (!Grids || typeof Grids.getActiveGrid !== 'function') {
            return { error: 'Grids_not_found' };
        }
        const activeGrid = Grids.getActiveGrid();
        const dp = activeGrid.getDataProvider ? activeGrid.getDataProvider() : null;
        if (!dp) return { error: 'no_DataProvider' };
        const rowCount = dp.getRowCount ? dp.getRowCount() : 0;
        if (rowCount === 0) return { error: 'empty_grid', rowCount: 0 };
        const rows = [];
        for (let i = 0; i < rowCount; i++) {
            const row = dp.getJsonRow ? dp.getJsonRow(i) : null;
            if (row) rows.push(row);
        }
        const cols = rows.length > 0
            ? Object.keys(rows[0]).map(k => ({ name: k, header: k }))
            : [];
        return { source: 'window.Grids.DataProvider', row_count: rows.length, columns: cols, rows: rows };
    } catch(e) { return { error: 'exception: ' + e.message }; }
})()
```

### 화면별 GW URL 및 API

| 화면 | URL | API 엔드포인트 |
|------|-----|---------------|
| 예실대비현황(상세) | `/nonprofit/NCC0630/0BN00001` | POST CSRF 보호 |
| 예실대비현황(사업별) | `/nonprofit/NCC0631/0BN00001` | POST CSRF 보호 |
| 예산과목원장 | `/nonprofit/NCC0640/0BN00001` | POST CSRF 보호 |
| 사업코드도움(피커) | `/nonprofit/NPCodePicker/0BN00001` | POST, gisu/helpTy 필요 |

### GW CSRF 제약

- 직접 `fetch()`/`httpx` 호출 시 → `"허용된 쿠키 인증 URL이 아닙니다"` 에러
- 해결책: Playwright 브라우저 컨텍스트 내에서만 API 접근 가능
- XHR 인터셉터로 파라미터 캡처 후 → Playwright evaluate()로 동일 요청 재현

### 사업코드피커 API 파라미터 (NPCodePicker)

```json
{
  "langKind": "KOR",
  "coCd": "1000",
  "empCd": "GS251105",
  "gisu": "9",
  "helpTy": "SMGT_CODE",
  "searchWord": "",
  "startIndex": 0,
  "endIndex": 200
}
```
- `gisu`: 회계 연도 인덱스 (2024=8, 2025=9, 2026=10 추정)
- 총 197개 전체 / 157개 유효 프로젝트 (GS-24-XXXX ~ GS-26-XXXX 패턴)

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
