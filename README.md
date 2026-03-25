# GW 자동화 프로젝트

글로우서울 그룹웨어(더존 Amaranth10/WEHAGO) 업무 자동화 시스템.
자연어 챗봇으로 회의실 예약, 전자결재, 메일 요약 등을 처리합니다.

---

## 문서 안내

| 문서 | 내용 |
|------|------|
| [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) | 개발자 가이드 — 기술 패턴, GW API, 양식 관리, 프로젝트 구조 |
| [`USER_MANUAL.md`](USER_MANUAL.md) | 사용자 매뉴얼 — 웹 챗봇/텔레그램 봇 사용법 |
| [`CLAUDE.md`](CLAUDE.md) | Claude Code 프로젝트 지침 (자동 로드) |

---

## 프로젝트 구조

```
자동화 work/
├── config/.env                    # 환경변수 (GW계정, API키, 암호화키)
├── data/
│   ├── users.db                   # 사용자 DB (SQLite + Fernet 암호화)
│   ├── fund_management.db         # 프로젝트 관리 DB
│   └── chatbot/                   # 대화 히스토리 DB + 로그
├── src/
│   ├── auth/                      # 인증 모듈
│   │   ├── login.py               # GW 로그인 (Playwright)
│   │   ├── user_db.py             # 사용자 DB (SQLite + Fernet)
│   │   ├── jwt_utils.py           # JWT 토큰
│   │   └── session_manager.py     # GW 세션 캐시
│   ├── chatbot/                   # 챗봇 모듈
│   │   ├── agent.py               # Gemini 라우팅 (244줄)
│   │   ├── tools_schema.py        # 도구 스키마 정의
│   │   ├── prompts.py             # 시스템 프롬프트
│   │   ├── handlers.py            # 16개 핸들러 함수
│   │   ├── app.py                 # FastAPI 서버
│   │   ├── chat_db.py             # 대화 히스토리 DB
│   │   ├── telegram_bot.py        # 텔레그램 봇
│   │   └── static/                # 웹 프론트엔드 (HTML/CSS/JS)
│   ├── approval/                  # 전자결재 자동화 (7개 Mixin 모듈)
│   │   ├── approval_automation.py # Mixin 조합 클래스 (54줄)
│   │   ├── base.py                # 공통 유틸/네비게이션
│   │   ├── expense.py             # 지출결의서
│   │   ├── grid.py                # OBTDataGrid 조작
│   │   ├── vendor.py              # 거래처등록
│   │   ├── draft.py               # 임시보관 상신
│   │   ├── other_forms.py         # 기타 양식
│   │   └── form_templates.py      # 양식 8개 필드 매핑
│   └── meeting/                   # 회의실 예약
│       └── reservation_api.py     # WEHAGO API (httpx + HMAC)
├── scripts/                       # 탐색/테스트 스크립트
└── run_chatbot.py                 # 챗봇 실행 진입점
```

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| **AI** | Google Gemini 2.5 Flash (Function Calling) |
| **백엔드** | FastAPI (Python) |
| **브라우저 자동화** | Playwright (sync API) |
| **DB** | SQLite (사용자 + 대화 히스토리) |
| **인증** | JWT + Fernet 대칭 암호화 |
| **API 통신** | httpx (회의실 예약 - HMAC 서명) |
| **프론트엔드** | Vanilla HTML/CSS/JS (다크 테마) |
| **봇** | python-telegram-bot |
| **에이전트** | Claude Code (Opus 4.6) |

---

## 빠른 시작

### 1. 환경 설정

```bash
cd "자동화 work"   # 프로젝트 디렉토리로 이동
pip install -r requirements.txt
playwright install chromium
```

### 2. 환경 변수 설정

`config/.env` 파일에 필요한 값 설정:

```env
ENCRYPTION_KEY=...
JWT_SECRET=...
GEMINI_API_KEY=...
TELEGRAM_TOKEN=...   # 텔레그램 봇 사용 시
```

### 3. 챗봇 실행

```bash
python run_chatbot.py
# http://localhost:51749 에서 접속
```

### 4. 텔레그램 봇 실행 (선택)

```bash
python -m src.chatbot.telegram_bot
```

---

## 주요 기능

### 회의실 예약 (완료)
- "내일 오후 2시 3번 회의실 예약해줘"
- WEHAGO API 직접 호출 (HMAC 서명 인증), 예약 생성/취소/조회/빈 시간 검색

### 전자결재 (세션 VI 고도화 완료)
- "지출결의서 작성해줘" / "거래처등록 신청해줘"
- Playwright로 GW 양식 자동 작성 → 임시보관 → 사용자 확인 후 상신
- 양식 현황 (verified 2개 / template_only 6개) → [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md#5-전자결재-양식-관리) 참고

### 메일 요약 (세션 VI 완료)
- "메일 요약해줘" / "새 메일 있어?"
- 수신인(To) 본인 메일만 요약 (참조 CC 제외)

### 챗봇 인터페이스
- 웹 UI (FastAPI + 다크 테마), 텔레그램 봇
- 파일 첨부 지원 (사업자등록증, 통장사본 → Gemini 직접 분석)
- 이전 대화 히스토리 조회 (웹 챗봇)

---

## 주의사항

- `config/.env` 파일은 절대 커밋하지 않음
- 전자결재는 "보관"(임시저장) 모드 — 사용자가 직접 확인 후 상신
- 기술적 상세 사항은 [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) 참고

---

## 라이선스

내부 프로젝트 (글로우서울 PM팀)
