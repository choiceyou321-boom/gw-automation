# GW 자동화 프로젝트

## WHY — 프로젝트 목적
글로우서울 PM팀의 그룹웨어(더존 Amaranth10/WEHAGO) 업무를 자연어 챗봇으로 자동화.
회의실 예약, 전자결재, 메일 요약, 계약서 생성, 프로젝트 관리 등을 처리한다.

## WHAT — 기술 스택
- **언어**: Python 3.11+
- **AI**: Google Gemini 2.5 Flash (Function Calling, 21개 도구)
- **웹 서버**: FastAPI + Uvicorn
- **브라우저 자동화**: Playwright (sync API) — 전자결재 폼 자동화
- **DB**: SQLite 3개 (users.db, fund_management.db, chat_history.db) — WAL 모드
- **인증**: JWT(httpOnly 쿠키) + Fernet 대칭 암호화
- **API 통신**: httpx (HMAC 서명) — 회의실 예약
- **프론트엔드**: Vanilla HTML/CSS/JS (다크 테마)
- **봇**: python-telegram-bot
- **배포**: Docker + Nginx + HTTPS

## WHAT — 핵심 디렉토리 구조
```
src/
├── auth/          # 로그인, JWT, Fernet DB, 세션 캐시
├── approval/      # 전자결재 (7 Mixin 모듈, 진입점: approval_automation.py)
├── chatbot/       # Gemini 에이전트 (4 모듈), 웹/텔레그램 봇, STT
├── contracts/     # 계약서 자동 생성 (DOCX 템플릿)
├── fund_table/    # 프로젝트 관리 (DB + REST API + GW 크롤러 3종 + Sheets 연동)
├── mail/          # 메일 요약
├── meeting/       # 회의실 API (HMAC)
└── notion/        # Notion 연동
tests/             # pytest 94개 (unit + integration)
scripts/           # 운영 스크립트 7개
```
> 상세 구조: @DEVELOPER_GUIDE.md 섹션 3

## HOW — 실행 명령어

```bash
# 챗봇 서버 실행
python run_chatbot.py                     # http://localhost:51749

# 텔레그램 봇 실행
python -m src.chatbot.telegram_bot

# 테스트 실행
pytest                                    # 전체 (94 tests, ~0.72초)
pytest tests/unit/                        # 단위 테스트만
pytest -k "test_fund"                     # 키워드 매칭

# Docker 배포
docker-compose up -d
```

## HOW — 코드 스타일

- **한국어 주석** 사용, docstring도 한국어
- 영문 변수명, 명확한 이름
- 로깅: `logging.getLogger(__name__)`
- Playwright: `page.wait_for_timeout()` 사용 (`time.sleep` 금지)
- Gemini SDK: `asyncio.to_thread()`로 비동기 래핑
- DB 연결: WAL 모드 필수 (`PRAGMA journal_mode=WAL`)

## HOW — 작업 규칙

### 필수
- 코드 수정 후 `pytest` 통과 확인 (현재 94/94 PASS)
- 커밋 전 테스트 실행
- `config/.env` 파일 절대 커밋 금지
- GW 비밀번호는 반드시 Fernet 암호화 후 저장

### 전자결재 작업 시
- CSS 셀렉터 우선, 좌표 클릭은 최후 수단
- OBTDataGrid: React fiber → depth 3 → `stateNode.state.interface` 접근
- "보관"(임시저장) 모드 기본 — 사용자가 직접 확인 후 "상신"
- 상세: @DEVELOPER_GUIDE.md 섹션 6, 14

### 프로젝트 관리 작업 시
- REST API: `/api/fund/*` (routes.py)
- 프론트엔드: `/fund` 페이지 (fund.html/js/css)
- 상세: @DEVELOPER_GUIDE.md 섹션 7

## HOW — Agent Teams

### 팀 생성
- "3명의 에이전트 팀을 만들어서 이 작업을 분담해줘"
- 각 팀원은 독립적으로 작업, 공유 태스크 리스트로 소통

### 팀 단축키
- `Shift+Down`: 팀원 간 전환
- `Ctrl+T`: 태스크 리스트 보기

### 규칙
- 동일 파일 동시 편집 금지
- Agent 작업은 항상 백그라운드(`run_in_background: true`)

## HOW — 세션 관리

### 새 세션 시작 시
1. `DEVELOPER_GUIDE.md` 읽기 (기술 패턴, 프로젝트 구조)
2. `MEMORY.md` 읽기 (세션 작업 기록, 발견사항)
3. `user_task_list.md` 읽기 (남은 작업 확인)

### 세션 마무리 시
1. `DEVELOPER_GUIDE.md` — 새 기술 패턴/구조 변경 반영
2. `MEMORY.md` — 세션 작업 기록, 발견사항
3. `user_task_list.md` — 완료/추가 작업 업데이트
4. `pytest` 전체 통과 확인

## 참고 문서
- @DEVELOPER_GUIDE.md — 기술 상세 (GW API, 양식 관리, DB 구조, 테스트)
- @USER_MANUAL.md — 사용자 매뉴얼
- @user_task_list.md — 전체 작업 목록 (완료/대기/미착수)
