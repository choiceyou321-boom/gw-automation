# 세션 이어가기 가이드

> **이 파일을 새 Claude 세션에서 먼저 읽어주세요.**
> 마지막 업데이트: 2026-03-02 (세션 V — 임시보관문서 확인 완료)

---

## 1. 프로젝트 개요

글로우서울 그룹웨어(더존 Amaranth10/WEHAGO) 자동화 프로젝트.
- **목표**: 회의실 예약, 전자결재, 메일 등을 자연어 챗봇으로 자동화
- **GW URL**: `https://gw.glowseoul.co.kr/#/`
- **프로젝트 루트**: `D:\전체\1. project\자동화 work`
- **다중 사용자**: 팀 전체가 사용 가능 (회원가입/로그인 시스템)

---

## 2. 현재 작업 상태

### ★ 세션 V — 임시보관문서 확인 완료 (2026-03-02)

#### 임시보관문서 현황 조회 — 완료!

**목표**: 임시보관문서함에 실제로 저장된 문서 목록 확인 (결재 자동화 이전 단계 검증)
**상태**: 완료 (스크린샷 + API 응답 + HTML 저장)

**임시보관문서 6건 확인:**
| # | 문서 제목 | 양식 |
|---|-----------|------|
| 1 | GS-25-0088. [종로] 메디빌더 음향공사 대금 지급의 건 | [프로젝트]지출결의서 |
| 2 | GS-25-0088. [종로] 메디빌더 유리공사 업체 선급금 지급의 건 | [프로젝트]지출결의서 |
| 3 | GS-25-0088. [종로] 메디빌더 제작가구 업체 선급금 지급의 건 | [프로젝트]지출결의서 |
| 4 | GS-25-0088. [종로] 메디빌더 타일 시공 업체 선급금 지급의 건 | [프로젝트]지출결의서 |
| 5 | GS-25-0088. [종로] 메디빌더 큐비클 업체 선급금 지급의 건 | [프로젝트]지출결의서 |
| 6 | GS-25-0088. [종로] 메디빌더 목공 업체 선급금 지급의 건 | [프로젝트]지출결의서 |

**임시보관문서 URL**: `/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1020`

**탐색 스크립트**: `scripts/check_draft_docs.py`
**캡처 데이터**: `data/approval_drafts/` (스크린샷, API 응답 JSON, HTML 등)

**결재홈 사이드바 현황 (세션 V 확인):**
- 상신문서: 4건
- 기결문서: 4건
- 기결문서(진행): 4건
- 수신참조문서: 591건

**캡처된 eap API (16개):**
`eap109A01`, `eap122A01`, `eap122A09`, `eap105A19`, `eap130A01`, `eap022A01`, `eap130A04`, `gw104B02`, `gw104B01`, `getMenuCountInfo`, `eap022A03`, `eap130A05`, `eap107A06` 등

---

### 세션 IV — Phase 0 DOM 탐색 완료 + 코드 업데이트 (2026-03-02)

#### Phase 0: DOM 탐색 — 완료!

**목표**: Playwright로 지출결의서 양식 열어서 실제 DOM 구조 캡쳐 → selector 확정
**상태**: 완료 (스크린샷 + JSON 데이터 저장)

**핵심 발견사항:**
1. **"보관"(임시저장) 버튼 없음** — "결재상신" 버튼만 존재
2. **네비게이션 경로**: `span.module-link.EA` → 결재 HOME → 추천양식 "[프로젝트]지출결의서" 직접 클릭
3. **양식 URL**: `/#/HP/APB1020/APB1020?formDTp=APB1020_00001&formId=255`
4. **양식 테이블**: `table.OBTFormPanel_table__1fRyk` 2개 (상단 table[0] + 하단 table[7])
5. **필드 접근**: `th:has-text(라벨) → following-sibling::td → input:visible`
6. **팝업 처리**: 로그인 시 5개+ 팝업 페이지 열림, URL에 "popup" 포함 → 닫기 필요

**DOM 구조 (확정된 필드):**
- Table 0 (상단): 회계단위(ph="사업장코드"), 회계처리일자, 품의서첨부, 첨부파일, 프로젝트(ph="프로젝트코드도움"), 전표구분(radio), 제목, 자금집행(radio)
- Grid: 용도, 내용, 거래처, 공급가액, 부가세, 합계액, 증빙, 증빙번호
- Table 7 (하단): 증빙일자, 지급요청일, 사원(ph="사원코드도움"), 은행/계좌번호(ph="금융기관코드도움"), 예금주, 사용부서(ph="부서코드도움"), 프로젝트, 예산

**탐색 스크립트**: `scripts/explore_approval_dom_v2.py`
**캡쳐 데이터**: `data/approval_dom_v2/` (inputs.json, buttons.json, tables.json, action_buttons.json, screenshots)

#### 코드 업데이트 — 실제 selector 반영 완료!

| 파일 | 변경 |
|------|------|
| `src/approval/approval_automation.py` | Phase 0 결과 반영: 실제 selector로 전체 재작성 |
| `src/approval/form_templates.py` | Phase 0 결과 반영: 실제 필드 구조, formId=255 |
| `src/chatbot/agent.py` | `get_or_create_session` 버그 수정 → `login_and_get_context` 직접 사용 |

**주요 변경:**
- `approval_automation.py`: 네비게이션 `span.module-link.EA` → 추천양식 직접 클릭 방식
- `approval_automation.py`: `_fill_field_by_label()` + `_fill_field_by_placeholder()` 2가지 필드 입력 방식
- `approval_automation.py`: "결재상신" 버튼으로 상신 (보관 없음)
- `agent.py`: 핸들러에서 직접 `sync_playwright() → login_and_get_context() → ApprovalAutomation` 사용
- `agent.py`: 타임아웃 120초 → 180초

#### 텔레그램 봇 확장 — 추가됨!

| 파일 | 변경 |
|------|------|
| `src/chatbot/telegram_bot.py` | ★ 신규 - 텔레그램 봇 (python-telegram-bot) |
| `config/.env` | TELEGRAM_TOKEN 추가 |

- 명령어: `/start`(안내), `/login`(GW계정연동), `/register`(회원가입), `/clear`(대화 지우기)
- 일반 메시지 → 기존 Gemini 에이전트(`analyze_and_route`) 호출
- 보안: 비밀번호 포함 메시지 자동 삭제
- 인메모리 세션: 텔레그램 user ID ↔ GW user context 매핑 (DB 연동 아님, 사용자 요청)
- **이미지/PDF 파일 첨부 지원** 추가됨
- `/newchat` 명령어 제거됨
- 명칭 통일: "텔레그램" = telegram_bot.py, "챗봇" = 웹 app.py

### 세션 III — 대화 히스토리 DB (완료)

**목표**: 인메모리 대화 히스토리 → SQLite DB 영구 저장 + 이전 대화 UI
**상태**: 구현 완료

- DB 위치: `data/chatbot/chat_history.db`
- 새 API: `GET /sessions` (세션 목록)
- 사이드바에 이전 대화 목록 표시, 세션 전환/삭제 가능
- 파일 로그(`save_chat_log`)는 이중 백업으로 유지

---

## 3. 완료된 작업

### 다중 사용자 시스템 (세션 I)
- SQLite + Fernet 암호화 사용자 DB
- JWT 쿠키 인증, 사용자별 GW 세션 캐시
- 관리자 페이지 (사용자 목록/삭제/프로필 관리)

### 회의실 예약 API (세션 H)
- wehago-sign HMAC 인증 13/13 검증
- rs121A06 신규 예약 / rs121A11 취소 / rs121A05 조회 / rs121A14 중복체크
- Playwright는 로그인+쿠키 추출만, API 호출은 httpx

### 챗봇 프레임워크 (세션 G)
- Gemini 2.5 Flash + Function Calling
- FastAPI 백엔드 + 다크 테마 UI
- 6개 도구: 예약생성/취소/조회/빈시간/경비결재/메일요약

### 로그인 / GW 분석 (이전 세션)
- 2단계 로그인 + 세션 저장/복원
- 89+ API 엔드포인트 캡처, 결재 양식 8개

---

## 4. 핵심 파일 구조

```
자동화 work/
├── config/.env                    # 환경변수 + ENCRYPTION_KEY + JWT_SECRET
├── data/
│   ├── users.db                   # 사용자 DB (SQLite)
│   ├── chatbot/
│   │   ├── chat_history.db        # ★ 대화 히스토리 DB (신규)
│   │   └── logs/                  # 대화 로그 (파일 백업)
│   ├── approval_drafts/           # ★ 임시보관문서 스크린샷 + API 응답 (세션 V)
│   └── sessions/                  # 사용자별 GW 세션 파일
├── src/
│   ├── auth/
│   │   ├── login.py               # GW 로그인 (사용자별 지원)
│   │   ├── user_db.py             # 사용자 DB (SQLite + Fernet)
│   │   ├── jwt_utils.py           # JWT 토큰 유틸
│   │   └── session_manager.py     # GW 세션 캐시 매니저
│   ├── chatbot/
│   │   ├── agent.py               # Gemini 의도 분석 (결재 핸들러 포함)
│   │   ├── app.py                 # FastAPI (인증 + 채팅 + 세션 API)
│   │   ├── chat_db.py             # 대화 히스토리 DB (SQLite)
│   │   ├── telegram_bot.py        # ★ 텔레그램 봇 (신규)
│   │   └── static/                # 프론트엔드 (대화 목록 UI 포함)
│   ├── approval/
│   │   ├── history.py             # 결재 이력 조회
│   │   ├── approval_automation.py # ★ 결재 폼 자동화 (신규)
│   │   └── form_templates.py      # ★ 양식 필드 매핑 (신규)
│   └── meeting/
│       └── reservation_api.py     # httpx API (company_info 동적화)
├── scripts/
│   ├── check_draft_docs.py        # ★ 임시보관문서 확인 스크립트 (세션 V)
│   └── explore_approval_dom_v2.py # Phase 0 DOM 탐색 스크립트
└── run_chatbot.py                 # 챗봇 실행 (port 51749)
```

---

## 5. 다음 할 일

### 즉시 필요
1. **임시보관문서 열기 + 상신 테스트**: 임시보관 6건 중 1건을 Playwright로 열어서 내용 확인 및 결재상신 end-to-end 테스트
   - `data/approval_drafts/` 스크린샷으로 실제 문서 구조 재확인
   - `scripts/check_draft_docs.py`에서 확인된 eap API(`eap122A01` 등)를 활용해 문서 상세 조회
2. **지출내역 그리드 입력**: 현재 제목만 입력됨 → 용도/내용/금액 등 그리드 행 입력 구현 필요
3. **국내 거래처등록 양식 DOM 탐색**: Phase 0 방식으로 실제 selector 확정 (상신 문서 2순위)
4. **에러 핸들링**: 필수 필드 누락, 네트워크 오류, 팝업 등 예외 처리 강화

### 이후
- `approval_automation.py`에 다양한 양식 지원 확장 (`form_templates.py` 8개 양식 커버)
- 결재선 설정 자동화 (현재는 기본값 사용)
- 메일 요약 기능 (gw API + Gemini)
- 클라우드 배포

---

## 6. 환경 설정

### 챗봇 실행
```bash
cd "D:\전체\1. project\자동화 work"
python run_chatbot.py
# http://localhost:51749
```

---

## 7. 주의사항
- Playwright는 로그인+쿠키 추출에만 사용, API 호출은 httpx (회의실)
- 전자결재는 Playwright 폼 자동화 (API 미확보)
- **결재 자동화는 "결재상신" 직접 실행** (보관 버튼 없음 — Phase 0에서 확인)
- 대화 히스토리 DB + 파일 로그 이중 백업
- GW 비밀번호는 Fernet 대칭 암호화 (해싱 불가)
- JWT 토큰: httpOnly 쿠키, 24시간 만료
