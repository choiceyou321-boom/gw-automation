# 개발자 가이드 (Developer Guide)

> 마지막 업데이트: 2026-03-17 (자금관리 등급/카테고리/드래그 정렬, STT, 계약서 자동생성)
> 새 세션 시작 시 `PROJECT_STATUS.md`와 함께 참고.

---

## 1. 세션 관리 패턴

### 세션 이어가기
- **새 세션 시작 시 필수**: `PROJECT_STATUS.md`를 먼저 읽기
- 컴퓨터 꺼져도 이어갈 수 있도록 세션 마무리 시 기록 필수

### 기록 대상 파일
| 파일 | 용도 | 업데이트 시점 |
|------|------|---------------|
| `PROJECT_STATUS.md` | 세션 이어가기 + 작업 로그 | 매 세션/작업 완료 시 |
| `DEVELOPER_GUIDE.md` | 기술 패턴 + GW API 분석 | 새 API 발견/기술 변경 시 |
| `USER_MANUAL.md` | 사용자 매뉴얼 | 사용자 기능 변경 시 |
| `CLAUDE.md` | 프로젝트 규칙 | 규칙 변경 시만 |

### 레코더 자동 업데이트 규칙 (★ 필수)
> **모든 작업 완료/보고 시 아래 마크다운 파일을 자동 업데이트해야 한다.**

| 파일 | 업데이트 내용 |
|------|-------------|
| `PROJECT_STATUS.md` | 새 세션 섹션 추가, 완료 항목 기록, 현재 상태 요약 갱신 |
| `DEVELOPER_GUIDE.md` | 새 기술 패턴, API 발견, 구현 규칙 추가 |
| `MEMORY.md` (auto-memory) | 새 파일 경로, 메서드, 발견사항 반영 |

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
scripts/
├── full_test.py              # 통합 테스트 라이브러리 (T1~T13)
├── feature_generator.py      # 기능 생성기 CLI
├── create_fund_table.py      # 자금관리표 스프레드시트 생성
├── create_contract_template.py  # 계약서 템플릿 생성
├── generate_contracts_from_excel.py  # 엑셀→계약서 일괄 생성
├── setup_google_sheets.py    # Google Sheets API 설정
└── archive/                  # 일회성 탐색/분석 스크립트 보관

src/
├── auth/                     # 로그인, 세션 관리, 사용자 DB
│   ├── jwt_utils.py          # JWT 토큰 생성/검증
│   ├── user_db.py            # SQLite + Fernet 사용자 DB
│   └── session_manager.py    # GW 세션 캐시 (TTL 2시간)
├── approval/                 # 전자결재 자동화
│   ├── approval_automation.py  # 메인 (Playwright 폼 자동화, 4000+줄)
│   ├── budget_helpers.py       # 예산과목 팝업 헬퍼
│   └── form_templates.py       # 양식 필드 정의 + 결재선 resolve
├── chatbot/                  # 웹 챗봇 + 텔레그램 봇 + Gemini 에이전트
│   ├── app.py                # Flask/FastAPI 웹 서버
│   ├── agent.py              # Gemini Function Calling 라우터
│   ├── approval_wizard.py    # 전자결재 단계별 질문 위저드
│   ├── stt.py                # Google Cloud Speech-to-Text STT
│   ├── telegram_bot.py       # 텔레그램 봇
│   └── static/               # 프론트엔드 정적 파일
│       ├── index.html, app.js, style.css  # 챗봇 UI
│       └── fund.html, fund.js, fund.css   # 자금관리 UI
├── contracts/                # 계약서 자동 생성
│   ├── contract_generator.py # Word 계약서 생성 엔진
│   └── contract_wizard.py    # 챗봇 연동 위저드
├── fund_table/               # 프로젝트 자금관리
│   ├── db.py                 # SQLite DB (fund_management.db)
│   ├── routes.py             # FastAPI 라우터 (/api/fund/*)
│   └── sheets_import.py      # Google Sheets 연동 임포트
├── mail/                     # 메일 요약 + Notion 연동
├── meeting/                  # 회의실 예약 API (reservation_api.py)
└── notion/                   # Notion API 클라이언트

data/
├── fund_management.db        # 자금관리 SQLite DB
├── users.db                  # 사용자 DB (SQLite + Fernet)
├── session_state.json        # GW 브라우저 세션
├── gw_analysis/              # GW API 분석 데이터
└── approval_dom*/            # Phase 0 DOM 탐색 결과
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

### 로그인 패턴
- 2단계: ID(`#reqLoginId`) → Enter → PW(`#reqLoginPw`) → Enter
- `#reqCompCd`: disabled 필드, 건드리지 않음
- 로그인 후 팝업 5개+ 자동 열림 → URL에 "popup" 포함 시 닫기
- 세션 저장: `data/session_state.json`

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
| 선급금요청 | template_only | 181 | formId 확인됨 |
| 연장근무 | template_only | 43 | 근태관리 모듈 별도 |
| 외근신청 | template_only | 41 | 근태관리 모듈 별도 |

### dzEditor 본문 기입 패턴
- **DOM 직접 수정 불가** — 저장 시 반영 안 됨
- 공식 API 사용: `getEditorHTMLCodeIframe(0)` → regex 교체 → `setEditorHTMLCodeIframe(html, 0)`

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
| 10~11 | 용도코드 + 동적 필드 | `usage_code` |
| 12~17 | 예산과목 선택 | `budget_keyword`, `budget_project` |
| 18~19 | 지급요청일 선택 | `payment_request_date` |
| 20~21 | 회계처리일자 변경 | `accounting_date` |
| 22 | 검증결과 확인 | 자동 |

---

## 7. 자금관리 모듈 (`src/fund_table/`)

### DB 구조 (`data/fund_management.db`)

| 테이블 | 용도 |
|--------|------|
| `projects` | 프로젝트 목록 (name, grade, sort_order, 금액정보) |
| `trades` | 프로젝트별 공종 |
| `subcontracts` | 하도급 업체별 계약/지급 정보 (4차 지급, 체크박스 확인) |
| `contacts` | 거래처 연락처 |
| `collections` | 수금현황 (설계/시공 단계별 금액, 수금완료 체크) |
| `project_overview` | 개요 (카테고리, 위치, 용도, 면적, 일정, 계약현황, 이슈) |
| `project_members` | 배정인원 (역할, 담당자) |
| `project_milestones` | 진행 마일스톤 (체크리스트) |
| `payment_history` | GW 이체완료 내역 (스크래핑) |
| `budget_actual` | GW 예실대비현황 (스크래핑) |

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
| GET | `/fund` | 자금관리 웹 페이지 서빙 |

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
- 자금관리표 시트 ID: `1LcmZPsDC-rqi2jofQup9G8xo6MOTVupSei0oZMm8nzE`
- PM팀 Official 시트 ID: `1zABshhlzDB_bkBPMpV4OY11xtHXYeQaHZPITaX75lOA`
- 임포트 대상: 하도급상세, 연락처, 이체내역(260316_지급내역), 수금현황

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

## 10. Gemini Function Calling 도구 (`agent.py`)

| 도구명 | 기능 |
|--------|------|
| `reserve_meeting_room` | 회의실 예약 |
| `cancel_meeting_reservation` | 예약 취소 |
| `check_reservation_status` | 예약 조회 |
| `check_available_rooms` | 빈 시간 검색 |
| `list_my_reservations` | 향후 N일 본인 예약 목록 |
| `cleanup_test_reservations` | [TEST_] 예약 일괄 취소 |
| `submit_expense_approval` | 지출결의서 작성 (22단계) |
| `submit_approval_form` | 전자결재 대화형 플로우 (거래처등록 등) |
| `start_approval_wizard` | 전자결재 단계별 위저드 시작 |
| `search_project_code` | 프로젝트 코드 검색 |
| `fetch_mail_summary` | 메일 요약 |
| `transcribe_audio` | 음성→텍스트 변환 STT |

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
- 상세: `data/gw_analysis/obtdatagrid_api_discovery.json`

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
- 텔레그램: 비밀번호 포함 메시지 **자동 삭제**
- JWT: httpOnly 쿠키, 24시간 만료, sameSite=lax
- GW 세션: 2시간 TTL 캐시
- 관리자 GW ID: `tgjeon` (하드코딩)
- `config/.env` 파일에 민감 정보 집중 관리, 절대 커밋 금지

---

## 16. 통합 테스트 (`scripts/full_test.py`)

| ID | 테스트 | 카테고리 | skip 옵션 |
|----|--------|---------|-----------|
| T1 | GW 로그인 | 인증 | - |
| T2 | 회의실 목록 조회 | 회의실 | `--skip-meeting` |
| T3 | 빈 회의실 검색 | 회의실 | `--skip-meeting` |
| T4 | 회의실 예약 생성+취소 | 회의실 | `--skip-meeting` |
| T5 | 프로젝트 코드 검색 | 결재 | `--skip-approval` |
| T6 | 지출결의서 임시보관 | 결재 | `--skip-approval` |
| T7 | 거래처등록 임시보관 | 결재 | `--skip-approval` |
| T8 | 메일 요약 | 메일 | `--skip-mail` |
| T9 | 챗봇 라우팅 (Gemini) | 챗봇 | - |
| T10 | 지출결의서 22단계 전체 | 결재 | `--skip-approval` |
| T11 | 챗봇 예약 취소 (자연어) | 챗봇+회의실 | `--skip-meeting` |
| T12 | 챗봇 다중 턴 대화 | 챗봇+회의실 | `--skip-meeting` |
| T13 | 임시보관문서 상신 E2E | 결재 | `--skip-approval` |

---

## 17. 세션 마무리 체크리스트

1. `PROJECT_STATUS.md` — 새 세션 섹션 추가, 현재 상태 요약 갱신
2. `DEVELOPER_GUIDE.md` — 새 기술 패턴/API/규칙 추가
3. `MEMORY.md` — 새 파일 경로, 발견사항, 세션 참조 갱신
4. 탐색 스크립트가 남아있으면 `scripts/archive/`로 이동
5. 새 테스트가 있으면 `full_test.py`에 통합 여부 확인
