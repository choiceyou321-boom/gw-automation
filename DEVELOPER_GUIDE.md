# 개발자 가이드 (Developer Guide)

> 마지막 업데이트: 2026-03-04 (세션 X — OBT 위젯 대응 패턴 추가)
> 새 세션 시작 시 `PROJECT_STATUS.md`와 함께 참고.

---

## 1. 세션 관리 패턴

### 세션 이어가기
- **새 세션 시작 시 필수**: `PROJECT_STATUS.md`를 먼저 읽기 (세션 VI 완료 현황 포함)
- 컴퓨터 꺼져도 이어갈 수 있도록 세션 마무리 시 기록 필수
- 세션 번호: 알파벳(A~I) → 로마숫자(I~VI) 순으로 증가

### 기록 대상 파일
| 파일 | 용도 | 업데이트 시점 |
|------|------|---------------|
| `PROJECT_STATUS.md` | 세션 이어가기 + 작업 로그 | 매 세션/작업 완료 시 |
| `DEVELOPER_GUIDE.md` | 기술 패턴 + GW API 분석 | 새 API 발견/기술 변경 시 |
| `USER_MANUAL.md` | 사용자 매뉴얼 | 사용자 기능 변경 시 |
| `CLAUDE.md` | 프로젝트 규칙 | 규칙 변경 시만 |

### 레코더 에이전트
- 작업 기록 전담 에이전트 1개 운영
- 기존 내용 유지, 신규 섹션만 추가/갱신
- 한국어로 작성

### 레코더 자동 업데이트 규칙 (★ 필수)
> **모든 작업 완료/보고 시 레코더 에이전트가 아래 마크다운 파일을 자동 업데이트해야 한다.**
> 이 규칙은 모든 세션, 모든 팀 작업에 항상 적용된다.

| 파일 | 업데이트 내용 |
|------|-------------|
| `PROJECT_STATUS.md` | 새 세션 섹션 추가, 완료 항목 기록, 현재 상태 요약 갱신 |
| `DEVELOPER_GUIDE.md` | 새 기술 패턴, API 발견, 구현 규칙 추가 |
| `MEMORY.md` (auto-memory) | 새 파일 경로, 메서드, 발견사항 반영 |

- 작업 중간에도 주요 마일스톤 달성 시 문서 업데이트
- 팀 작업 시 레코더 에이전트를 별도 배치하거나, 마지막 에이전트가 레코더 역할 수행
- 기존 내용은 유지하고 신규 섹션만 추가/갱신 (덮어쓰기 금지)
- 팀 작업 마무리 시 마지막 태스크로 문서 갱신을 포함할 것

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

## 3. 기술 패턴

### GW 접근 방식 (2가지)

#### 방식 A: API 직접 호출 (회의실 예약)
```
Playwright 로그인 → 쿠키/토큰 추출 → httpx API 호출
```
- **사용처**: 회의실 예약 (rs121A 시리즈)
- **인증**: wehago-sign HMAC
- **조건**: API payload 구조를 완벽히 파악한 경우

#### 방식 B: Playwright 폼 자동화 (전자결재)
```
Playwright 로그인 → 페이지 이동 → DOM 조작으로 폼 채우기
```
- **사용처**: 전자결재 (API payload 미확보)
- **인증**: 브라우저 세션 쿠키
- **조건**: Phase 0 DOM 탐색 필수 선행

### 새 기능 개발 순서 (전자결재 기준)
1. **Phase 0**: Playwright로 대상 페이지 열기 → 스크린샷 + HTML + JSON 저장
2. **selector 확정**: 실제 DOM 구조에서 안정적인 selector 결정
3. **스크립트 작성**: 탐색 스크립트 작성 (완료 후 `scripts/archive/`로 이동)
4. **모듈 구현**: `src/` 폴더에 프로덕션 모듈 작성
5. **에이전트 연결**: `agent.py` 핸들러에 연결
6. **통합 테스트**: `scripts/full_test.py`에 새 테스트 메서드 추가 (T번호)
7. **문서 갱신**: PROJECT_STATUS.md, DEVELOPER_GUIDE.md, MEMORY.md 업데이트

### 로그인 패턴
- 2단계: ID(`#reqLoginId`) → Enter → PW(`#reqLoginPw`) → Enter
- `#reqCompCd`: disabled 필드, 건드리지 않음 (`must_be_enabled=True` 기본값으로 자동 건너뜀)
- 로그인 후 팝업 5개+ 자동 열림 → URL에 "popup" 포함 시 닫기
- 세션 저장: `data/session_state.json`

---

## 4. API 인증 패턴

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

| 구성 요소 | 값/생성 방법 |
|-----------|-------------|
| signKey | 쿠키 `signKey` 값 |
| oAuthToken | 쿠키 `oAuthToken` 값 (URL 디코딩 후) |
| transactionId | `uuid4().hex` (32자 랜덤 hex) |
| timestamp | `int(time.time())` (Unix 초) |
| pathname | 요청 URL 경로 (예: `/schres/rs121A06`) |

### 쿠키 구조
| 쿠키명 | 용도 |
|--------|------|
| `oAuthToken` | API 인증 토큰 (`{groupSeq}|{empSeq}|{sessionToken}`) |
| `signKey` | HMAC 서명 키 |
| `BIZCUBE_AT` | oAuthToken과 동일 |
| `BIZCUBE_HK` | signKey와 동일 |

### 자동 재인증 패턴 (`reservation_api.py`, 세션 VI)
- `call_api(_retry=True)` → HTTP 401/403 또는 resultCode 인증 오류 감지
- `_is_auth_error()` 정적 메서드로 인증 오류 판별
- `_refresh_session()`: `invalidate_cache()` → `_login_and_cache()` → 토큰/쿠키/httpx Client 갱신
- 갱신 성공 시 `call_api(_retry=False)`로 1회 재시도
- 실패 시 `{"auth_expired": True, ...}` 반환
- `session_manager.create_api()`에서 `api._gw_id = gw_id` 주입 (사용자 식별용)

---

## 5. 전자결재 양식 관리

### 양식 상태
| 상태 | 의미 |
|------|------|
| `verified` | Phase 0 완료, 실제 selector 확정됨 |
| `template_only` | 필드 구조만 정의, DOM 탐색 미완 |

### 현재 양식 현황 (`form_templates.py`)
| 양식 | 상태 | formId | 사용 빈도 | 비고 |
|------|------|--------|-----------|------|
| 지출결의서 | verified | 255 | 30건 (1위) | 그리드 입력 포함 |
| 거래처등록 | verified (E2E 완료) | 196 | 26건 (2위) | 팝업 창, dzEditor API, 보관 검증됨 |
| 선급금요청 | template_only | 181 | - | formId 확인됨 (Task #21) |
| 연장근무 | template_only | 43 | 3건 | 근태관리 모듈 별도 — formId 확인됨 (Task #21) |
| 외근신청 | template_only | 41 | - | 근태관리 모듈 별도 — formId 확인됨 (Task #21) |
| 증빙발행 | template_only | - | - | formId 미확인 |
| 선급금정산 | template_only | - | - | formId 미확인 |
| 사내추천비 | template_only | - | - | formId 미확인 |

### 양식 열기 방식
- **지출결의서**: 추천양식 직접 클릭 → 같은 페이지에서 양식 로드
- **거래처등록**: 결재작성 → 양식 검색 → Enter → **팝업 창**으로 열림
- 팝업 URL: `/#/popup?MicroModuleCode=eap&formId={ID}&callComp=UBAP001`

### 거래처등록 팝업 프레임 구조
```
popup (frame[0]) → URL: /#/popup?MicroModuleCode=eap&formId=196&callComp=UBAP001
  ├── editorView_UBAP001 (frame[1]) → URL: editorView.html
  │   └── dzeditor_0 (frame[2]) → URL: about:blank
  └── dzeditor_9999 (frame[3])
```

### dzEditor 본문 기입 패턴 (중요)
- **DOM 직접 수정 불가** — 저장 시 반영 안 됨
- 반드시 공식 API 사용:
  ```
  getEditorHTMLCodeIframe(0) → regex 교체 → setEditorHTMLCodeIframe(html, 0)
  ```
- regex에 `\s*` 필수 (API HTML에 줄바꿈/탭 포함)
- replacement에 `re.escape()` 사용 금지 → 함수형 `repl(m)` 사용

### 결재선 구조
- 지출결의서: 기안자(전태규) → 신동관(합의) → 최기영(최종) — 3단계
- 거래처등록: 기안자(전태규) → 최기영(최종) — 2단계

### 임시보관문서 상신 패턴 (`approval_automation.py`, Task #1)
- 진입점: `open_draft_and_submit(doc_title, dry_run=True)`
- 문서 클릭: `_click_draft_document(doc_title)` — 텍스트→selector→좌표 3단계 폴백
- 팝업 감지: docid/formid/micromodulecode=eap 키워드, 최대 15초 대기
- 상신 버튼: `_find_submit_button()` → `div.topBtn:has-text('상신')`
- **dry_run=True(기본값)**: 버튼 확인만, 실제 클릭 안 함 (안전장치)
- 테스트: `full_test.py` T13 (dry_run 모드) — 원본 `scripts/archive/test_draft_submit_e2e.py`

### 지출결의서 22단계 자동화 (`_fill_expense_fields`, 세션 VIII)

`_fill_expense_fields(data)` 하나의 메서드로 전체 22단계를 처리:

| Step | 내용 | data 키 |
|------|------|---------|
| 1 | 프로젝트 코드도움 (상단, y≈292) | `project` |
| 2~3 | 제목 입력 | `title` |
| 4 | 지출내역 그리드 입력 | `items` |
| 5 | 증빙유형 버튼 클릭 | `evidence_type` |
| 5-1 | 세금계산서 팝업 검색 | `invoice_vendor`, `invoice_amount`, `invoice_date` |
| 6 | 증빙일자 입력 (하단, y=857) | `receipt_date` |
| 7 | 프로젝트 코드도움 (하단) | `project` |
| 8 | 첨부파일 업로드 | `attachment_path` |
| 9 | 예실대비현황 스크린샷 캡처 | `auto_capture_budget` |
| 10~11 | 용도코드 입력 + 동적 필드 대기 | `usage_code` |
| 12~17 | 예산과목 선택 (budget_helpers) | `budget_keyword`, `budget_project` |
| 18~19 | 지급요청일 선택 | `payment_request_date` |
| 20~21 | 회계처리일자 변경 | `accounting_date` |
| 22 | 검증결과 확인 (적합/부적합 + 툴팁) | 자동 |

### 예산과목 선택 패턴 (`budget_helpers.py`, 세션 VIII)

- 모듈: `src/approval/budget_helpers.py`
- 함수: `select_budget_code(page, project_keyword, budget_keyword)`
- 반환: `{"success": bool, "budget_code": str, "budget_name": str, "message": str}`
- 플로우:
  1. 예산과목 필드(placeholder="예산과목") 클릭 → "공통 예산잔액 조회" 모달
  2. 모달 내 프로젝트 입력(placeholder="사업코드도움") → 자동완성 선택
  3. 예산과목 입력(placeholder="예산과목코드도움") → 코드도움 아이콘 → 서브 팝업
  4. 서브 팝업에서 **2로 시작하는 코드만** 선택 (4xxx 제외)
  5. 서브 팝업 확인 → 모달 확인 → 메인 폼 반영

### 검증결과 부적합 시 툴팁 확인 (세션 VIII)
- 검증결과 셀에서 "부적합" 감지 시 `page.hover()` → 툴팁 텍스트 추출
- title 속성 우선, 없으면 동적 tooltip div 탐색
- 로그에 `logger.warning`으로 미비 사항 기록

### 양식 추가 절차
1. `form_templates.py`에 필드 구조 정의 (`template_only`)
2. Phase 0 DOM 탐색으로 실제 selector 확정
3. `approval_automation.py`에 작성 메서드 추가
4. `agent.py` 핸들러에서 양식 라우팅
5. 상태를 `verified`로 변경

---

## 6. GW URL 패턴

### 주요 URL
| 페이지 | URL |
|--------|-----|
| 메인 | `/#/` |
| 결재 HOME | `/#/EA/` (`span.module-link.EA` 클릭) |
| 지출결의서 양식 | `/#/HP/APB1020/APB1020?formDTp=APB1020_00001&formId=255` |
| 임시보관문서 | `/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1020` |
| 회의실 예약 | `/#/UK/UKA/UKA0000?specialLnb=Y&moduleCode=UK&menuCode=UKA&pageCode=UKA0000` |
| 메일 | `/#/UD/UDA/UDA0000?specialLnb=Y&moduleCode=UD&menuCode=UDA&pageCode=UDA0020` |

### URL 구조 규칙
- 해시 라우팅 (`/#/`) — React SPA
- 모듈코드: EA(전자결재), UB(상신/보관함), HP(양식), UK(자원), UD(메일)
- `specialLnb=Y`: 특수 좌측 네비게이션 표시

---

## 7. 회의실 예약 API

### 회의실 매핑
| 회의실 | resSeq |
|--------|--------|
| 1번 | 45 |
| 2번 | 46 |
| 3번 | 47 |
| 4번 | 48 |
| 5번 | 49 |

### rs121A 엔드포인트 목록 (확인된 것)
| API | 용도 | 상태 |
|-----|------|------|
| rs121A01 | 자원(회의실) 목록 조회 | 동작 확인 |
| rs121A05 | 예약 현황 조회 | 동작 확인 |
| rs121A06 | **신규 단건 예약 생성** | 동작 확인 ★ |
| rs121A11 | 예약 취소 (statusCode="CA") | 동작 확인 |
| rs121A12 | 기존 예약 수정 (단건) — 신규 생성 아님 | 수정 전용 |
| rs121A14 | 예약 중복 체크 | 동작 확인 |
| rs121A15 | 반복 예약 생성/수정 | 미테스트 |

### 회사 정보 (고정)
```json
{
  "compSeq": "1000",
  "groupSeq": "gcmsAmaranth36068",
  "deptSeq": "2017"
}
```
- empSeq: "2922" (전태규)
- 테넌트: `gcmsAmaranth36068`

---

## 8. 채널별 아키텍처 차이

### 챗봇 (웹)
- FastAPI + SQLite (chat_db), JWT 쿠키 인증
- 대화 히스토리: DB 영구 저장 (`data/chatbot/chat_history.db`)
- 세션 목록/전환/삭제 UI
- 파일 업로드: base64 인코딩 → Gemini 전달

### 텔레그램
- python-telegram-bot 라이브러리
- 인메모리 세션 (`tg_sessions: dict`, 최근 40개, 재시작 시 소실)
- `/clear` 명령어로 대화 지우기 (로그인 유지), DB 연동 없음
- `/mailcheck` 명령어 (Task #8): 로그인 확인 → `run_for_chatbot()` → Notion 저장 + 텔레그램 응답 (최대 4000자)

### 메일 요약 + Notion 저장 패턴 (Task #8)
- `src/mail/summarizer.py`: `run_for_chatbot(user_context)` — 메일 수집 + Notion 저장 + 결과 반환
- `src/notion/client.py`: `append_to_page()`, `save_mail_summaries()` — Notion API 연동
- 환경 변수: `NOTION_API_KEY`, `NOTION_PAGE_ID` (`config/.env`)
- Notion 저장 형식: 날짜 헤더 + 발신자/제목/요약 블록

### Gemini Function Calling 도구 목록 (`agent.py`) — 9개
- `reserve_meeting_room` — 회의실 예약
- `cancel_meeting_reservation` — 예약 취소
- `check_reservation_status` — 예약 조회
- `check_available_rooms` — 빈 시간 검색
- `submit_expense_approval` — 지출결의서 작성 (22단계, usage_code/budget_keyword/payment_request_date/accounting_date)
- `submit_approval_form` — 전자결재 대화형 플로우 (거래처등록 등 범용)
- `search_project_code` — 프로젝트 코드 검색 (자동완성 확인)
- `get_mail_summary` — 메일 요약
- 도구 8+1개: submit_expense_approval과 submit_approval_form은 양식별 분리

### 파일 첨부 처리 패턴 (`build_message_parts()`, line 821~852)
- 첨부파일 앞에 `[첨부파일: 파일명]` 텍스트 힌트 삽입 → Gemini 문서 종류 인식 향상
- 지원 형식: 이미지 JPG/PNG/GIF/WebP + PDF, 10MB 제한

---

## 9. 보안 규칙

- GW 비밀번호: **Fernet 대칭 암호화** (해싱 불가 — Playwright 로그인에 평문 필요)
- 텔레그램: 비밀번호 포함 메시지 **자동 삭제** (`context.bot.delete_message`)
- JWT: httpOnly 쿠키, 24시간 만료, sameSite=lax
- GW 세션: 2시간 TTL 캐시
- 관리자 GW ID: `tgjeon` (하드코딩)
- `config/.env` 파일에 민감 정보 집중 관리, 절대 커밋 금지

---

## 10. 데이터 저장 패턴

```
data/
├── users.db                    # 사용자 DB (SQLite + Fernet)
├── session_state.json          # GW 브라우저 세션
├── sessions/                   # 사용자별 GW 세션 파일
├── chatbot/
│   ├── chat_history.db         # 대화 히스토리 DB
│   ├── logs/                   # 대화 로그 (이중 백업)
│   └── uploads/                # 업로드 파일
├── gw_analysis/                # GW API 분석 데이터
├── approval_dom_v2/            # 지출결의서 Phase 0 DOM 탐색 결과
├── approval_dom_vendor/        # 거래처등록 Phase 0 DOM 탐색 결과
├── approval_dom_remaining/     # 6개 양식 Phase 0 DOM 탐색 결과
├── approval_dom_invoice/       # 세금계산서 팝업 DOM 탐색 결과
└── approval_drafts/            # 임시보관문서 캡쳐 결과
```

- **대화 히스토리**: SQLite DB (메인) + JSONL 파일 (이중 백업)
- **GW 세션**: 파일 저장 + 인메모리 캐시 (2시간 TTL)
- Phase 0 탐색 데이터: 스크린샷 + `inputs.json` + `buttons.json` + `tables.json`

---

## 11. GW 분석 보고서 (요약)

> 원본 분석: 세션 B (2026-03-01), 갱신: 세션 VI (2026-03-02)

### 전자결재 eap API 목록
- `eap109A01` — 결재 건수 조회
- `eap122A01` — 임시보관 문서 목록
- `eap122A09`, `eap105A19`, `eap130A01` 등 16종 캡처 완료
- 문서 팝업 URL 패턴: `/#/popup?MicroModuleCode=eap&docID={id}&formId={formId}&callComp=UBAP002`

### GW 내부 API 주요 엔드포인트
| 목적 | URL 패턴 |
|------|----------|
| 전자결재 관련 | `/gw/APIHandler/gw032A09`, `/gw/gw027A21` |
| 결재선 | `/gw/gw125A04` |
| 조직도 | `/gw/APIHandler/gw018A05` |
| 결재함 | `/gw/gw050A24` |
| 메일 | `/mail/api/mail019A01` |

---

## 12. 작업 패턴 (★ 세션 X 갱신)

### 프로젝트 디렉토리 구조

```
scripts/
├── full_test.py              # 통합 테스트 라이브러리 (T1~T13)
└── archive/                  # 일회성 탐색/분석 스크립트 보관 (42개)

src/
├── auth/                     # 로그인, 세션 관리, 사용자 DB
├── approval/                 # 전자결재 자동화
│   ├── approval_automation.py  # 메인 (Playwright 폼 자동화)
│   ├── budget_helpers.py       # 예산과목 팝업 헬퍼
│   └── form_templates.py       # 양식 필드 정의
├── chatbot/                  # 웹 챗봇 + 텔레그램 봇 + Gemini 에이전트
├── mail/                     # 메일 요약 + Notion 연동
├── meeting/                  # 회의실 예약 API (reservation_api.py)
└── notion/                   # Notion API 클라이언트
```

### 파일 관리 규칙

| 규칙 | 설명 |
|------|------|
| **스크립트 관리** | 탐색/분석 스크립트는 완료 후 `scripts/archive/`로 이동 |
| **테스트 통합** | 새 테스트는 `scripts/full_test.py`에 메서드로 추가 (별도 파일 생성 금지) |
| **데드코드 삭제** | 대체된 모듈은 즉시 삭제 (예: reservation.py → reservation_api.py) |
| **빈 패키지 금지** | 사용하지 않는 `__init__.py`만 있는 디렉토리는 삭제 |
| **동일 파일 동시 편집 금지** | 팀 작업 시 같은 파일을 두 에이전트가 동시에 수정하지 않음 |

### 통합 테스트 (`scripts/full_test.py`)

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

**테스트 추가 방법**: `FullTestRunner` 클래스에 `_test_xxx()` 메서드 추가 → `_phase2_tests()` 리스트에 등록

### 코드 정리 판단 기준

| 판단 | 조치 |
|------|------|
| 아무 데서도 import 안 되는 src/ 모듈 | 삭제 |
| 대체된 이전 버전 모듈 (예: v1→v2) | 삭제 |
| 일회성 탐색 스크립트 | `scripts/archive/` 이동 |
| 반복 사용 가능한 테스트 | `full_test.py` 통합 |
| data/ 폴더 탐색 아티팩트 | 보수적 유지 (참고용) |
| 빈 패키지 (`__init__.py`만 존재) | 삭제 |

### OBT 위젯 대응 패턴 (★ 세션 X 추가)

| OBT 위젯 | 특성 | 대응 방법 |
|-----------|------|-----------|
| **OBTGrid** | canvas 기반, DOM 행 없음, RealGrid API도 window에 없음 | 모달 제목 기준 상대 좌표 클릭/더블클릭 |
| **OBTDialog2** | dimClicker 오버레이가 뒤쪽 요소 차단 | JS로 dialog 컨테이너 내부 요소 직접 탐색 |
| **OBTAutoComplete** | 입력 → 드롭다운 → Tab으로 확정 | `type()` → `wait_for_selector('.autocomplete')` → `press('Tab')` |
| **OBTDatePicker** | 날짜 input + 캘린더 팝업 | `fill(date)` → `press('Tab')` (캘린더 우회) |
| **OBTCheckBox** | 커스텀 div 체크박스, input[type=checkbox] 아님 | `[class*='Checkbox']`, `[role='checkbox']` 셀렉터 사용 |

**풀스크린 좌표 규칙**: 하드코딩 좌표 사용 금지. 반드시 동적 기준점(텍스트 라벨, 모달 제목, 헤더) bounding_box 기준 상대 좌표 사용.

**force=True 주의**: OBT 이벤트 핸들러를 우회하므로 모달이 열리지 않는 등 부작용 발생. 꼭 필요한 경우만 사용.

### 세션 마무리 체크리스트

1. `PROJECT_STATUS.md` — 새 세션 섹션 추가, 현재 상태 요약 갱신
2. `DEVELOPER_GUIDE.md` — 새 기술 패턴/API/규칙 추가
3. `MEMORY.md` — 새 파일 경로, 발견사항, 세션 참조 갱신
4. 탐색 스크립트가 남아있으면 `scripts/archive/`로 이동
5. 새 테스트가 있으면 `full_test.py`에 통합 여부 확인

