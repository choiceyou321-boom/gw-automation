# 개발자 가이드 (Developer Guide)

> 마지막 업데이트: 2026-03-02 (세션 VI — Task #20 통폐합 완료)
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
3. **스크립트 작성**: `scripts/` 폴더에 탐색/테스트 스크립트 작성
4. **모듈 구현**: `src/` 폴더에 프로덕션 모듈 작성
5. **에이전트 연결**: `agent.py` 핸들러에 연결
6. **통합 테스트**: 챗봇 → 에이전트 → 모듈 end-to-end

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
| 연장근무 | template_only | - | 3건 | DOM 탐색 미완료 |
| 증빙발행 | template_only | - | - | DOM 탐색 미완료 |
| 선급금요청 | template_only | - | - | DOM 탐색 미완료 |
| 선급금정산 | template_only | - | - | DOM 탐색 미완료 |
| 외근신청 | template_only | - | - | DOM 탐색 미완료 |
| 사내추천비 | template_only | - | - | DOM 탐색 미완료 |

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

### Gemini Function Calling 도구 목록 (`agent.py`)
- `reserve_meeting_room` — 회의실 예약
- `cancel_meeting_reservation` — 예약 취소
- `check_reservation_status` — 예약 조회
- `check_available_rooms` — 빈 시간 검색
- `create_expense_report` — 지출결의서 작성
- `create_vendor_registration` — 거래처등록 작성
- `get_mail_summary` — 메일 요약
- `submit_approval_form` — 전자결재 대화형 플로우 (세션 VI: 단계별 질문, 프로젝트 자동완성, 세금계산서 매칭)

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

