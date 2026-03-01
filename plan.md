# 그룹웨어 자동화 프로젝트 - 실행 계획서

> 최종 업데이트: 2026-03-01 21:30

## 프로젝트 개요
- 대상: 글로우서울 그룹웨어 (더존 Amaranth10/klago)
- URL: https://gw.glowseoul.co.kr/#/
- 목표: 챗봇 기반 통합 자동화 (결재, 메일, 회의실 예약)
- 사용자: 비개발자 (상담 기반 요구사항 수집)

---

## Phase 0: 환경 설정 [완료 ✅]
- [x] Python 3.14 설치 확인
- [x] 패키지 설치: playwright, httpx, python-dotenv, openpyxl
- [x] .env 파일 생성 (그룹웨어 ID, Notion API Key)
- [x] 프로젝트 폴더 구조 생성

### 현재 폴더 구조
```
자동화 work/
├── src/
│   ├── auth/           # 로그인/인증 모듈 ✅
│   │   ├── __init__.py
│   │   └── login.py
│   ├── approval/       # 결재 분석 (내부용) ✅
│   │   ├── __init__.py
│   │   └── history.py
│   ├── mail/           # 메일 요약 ✅
│   │   ├── __init__.py
│   │   └── summarizer.py
│   ├── meeting/        # 회의실 예약 ✅
│   │   ├── __init__.py
│   │   └── reservation.py
│   ├── notion/         # Notion 연동 ✅
│   │   ├── __init__.py
│   │   └── client.py
│   ├── chatbot/        # 챗봇 웹 인터페이스 ✅
│   │   ├── __init__.py
│   │   ├── agent.py       # Gemini AI 연동
│   │   ├── app.py         # FastAPI 백엔드
│   │   └── static/        # 프론트엔드 (HTML/CSS/JS)
│   └── utils/          # 공통 유틸리티
│       └── __init__.py
├── config/
│   └── .env            # 환경 변수
├── logs/               # 실행 로그
├── data/               # 수집 데이터 저장
├── plan.md             # 본 계획서
├── requirements.md     # 요구사항
├── work-rules.md       # 작업 규칙
└── gw-analysis.md      # 그룹웨어 분석 보고서
```

---

## Phase 1: 로그인 자동화 [코드 완료 ✅ / 테스트 대기]
- [x] ID/PW 입력 → 로그인 스크립트 작성
- [x] 세션 저장/복원 기능
- [x] 다양한 셀렉터 fallback 로직
- [ ] 실제 로그인 테스트 실행

**파일**: `src/auth/login.py`
**담당**: 공통 (모든 자동화의 기반)

---

## Phase 2: 결재 양식/패턴 분석 [코드 완료 ✅ / 실행 대기]
> ⚠️ 목적 변경: 사용자용 엑셀 정리 기능 ❌ → 개발팀 내부 분석용 ✅

- [x] 전자결재 메뉴 진입 자동화 코드
- [x] 상신 이력 전체 조회 코드
- [x] 네트워크 인터셉트로 내부 API 패턴 캡처
- [ ] 실행하여 결재 양식 종류/필드 구조/결재선 패턴 분석
- [ ] 분석 결과 → Phase 5 (자동 결재 작성) 설계에 반영

**파일**: `src/approval/history.py`
**목적**: 자동 결재 작성(Phase 5)을 위한 사전 조사
**산출물**: 내부 분석 데이터 (JSON)

---

## Phase 3: 메일 요약 → Notion 저장 [코드 완료 ✅ / Notion 설정 대기 ⏸️]
- [x] 메일함 진입 자동화 코드
- [x] 안 읽은 메일 필터링/수집 코드
- [x] 메일 본문 텍스트 추출 코드
- [x] Notion API 클라이언트 코드
- [ ] **NOTION_PAGE_ID 설정 필요** (사용자 확인 중)
- [ ] Notion API Key 재확인 필요
- [ ] 실제 실행 테스트

**파일**: `src/mail/summarizer.py`, `src/notion/client.py`
**대기**: Notion API Key 재확인 + 저장 페이지 URL

---

## Phase 4: 회의실 예약 자동화 [코드 완료 ✅ / 로그인 수정 중 🔧]
- [x] 회의실 예약 페이지 구조 파악 (Playwright)
- [x] 회의실 목록 및 예약 현황 조회
- [x] 빈 시간대 검색 기능
- [x] 회의실 예약 등록 자동화
- [x] 챗봇 연동 (function calling → handle_reserve_meeting_room)
- [ ] 로그인 모듈 수정 (disabled 필드 건너뛰기) ← 현재 수정 완료, 테스트 필요

**담당**: meeting-dev
**파일**: `src/meeting/reservation.py`
**이슈**: 로그인 시 회사코드 입력란(disabled)을 ID 필드로 오인하는 버그 → 수정 완료

---

## Phase 5: 결재 양식 자동 작성 [미시작]
- [ ] Phase 2 분석 결과 기반 양식 파악
- [ ] 지출/경비 청구 양식 자동 채우기
- [ ] 첨부 파일 자동 업로드 (PDF, 이미지)
- [ ] 결재선 자동 설정
- [ ] 상신 자동 실행

**선행조건**: Phase 2 분석 완료

---

## Phase 6: 챗봇 웹 인터페이스 [개발 완료 ✅ / 운영 중]
> 사용자의 핵심 요청: 채팅으로 자동화 작업을 요청하는 통합 인터페이스

### 확정 사항
- **AI 모델**: ~~Claude Sonnet 4.6~~ → **Google Gemini 2.5 Flash** (무료, function calling 지원)
- **접속 범위**: 현재 로컬 (http://localhost:51749), 클라우드 배포 예정
- **파일 첨부**: 드래그앤드랍으로 이미지/PDF 첨부 가능
- **결과 보관**: 로컬 폴더에 파일 저장 (`data/chatbot/logs/`)
- **1순위 기능**: 회의실 예약

### 핵심 기능
1. 채팅 UI (파일 드래그앤드랍 지원) ✅
2. Gemini API로 요청 의도 분석 (function calling) ✅
3. 자연어 이해: "내일 오후 2시 5번 회의실" 등 한국어 자연어 처리 ✅
4. 분석된 의도에 따라 자동화 작업 실행:
   - "회의실 예약해줘" → 회의실 예약 모듈 호출 ✅ (로그인 수정 중)
   - "경비 결재 올려줘" → 접수 메시지 (그룹웨어 연동 준비 중)
   - "메일 요약해줘" → 접수 메시지 (그룹웨어 연동 준비 중)
5. 처리 결과를 채팅으로 응답 + 로컬 파일 저장 ✅

### 기술 스택
- 프론트엔드: 바닐라 HTML/CSS/JS (다크 테마) ✅
- 백엔드: FastAPI + uvicorn ✅
- AI: Google Gemini 2.5 Flash (function calling) ✅
- 실행: `python run_chatbot.py` → http://localhost:51749
- 배포: 클라우드 (미정)

### 해결된 이슈
- Anthropic API 크레딧 부족 → Gemini 무료 API 전환
- Playwright sync + asyncio 충돌 → ThreadPoolExecutor 사용
- 자연어 이해 부족 → 시스템 프롬프트에 한국어 파싱 규칙 추가

---

## Phase 7: 통합 및 마무리 [미시작]
- [ ] 전체 기능 통합 테스트
- [ ] 클라우드 배포
- [ ] 사용자 가이드 작성

---

## 의존성 관계
```
Phase 0 (환경 설정) ✅
  └─→ Phase 1 (로그인) ✅ ← 로그인 수정 완료 (disabled 필드 건너뛰기)
       ├─→ Phase 2 (결재 분석) ✅ ─→ Phase 5 (결재 자동 작성)
       ├─→ Phase 3 (메일 요약) ✅ ─→ ⏸️ Notion 설정 대기
       ├─→ Phase 4 (회의실 예약) ✅ ─→ 로그인 수정 후 재테스트 필요
       └─→ Phase 6 (챗봇 웹) ✅ 운영 중 ─→ Phase 7 (통합/배포)
```

## 우선순위 (2026-03-01 기준)
1. ★ 회의실 예약 자동화 (Phase 4)
2. ★ 챗봇 웹 인터페이스 설계/개발 (Phase 6)
3. 결재 양식 분석 실행 (Phase 2 실행)
4. 메일 요약 → Notion (Phase 3, Notion 설정 후)
5. 결재 자동 작성 (Phase 5, 분석 후)

## 리스크 및 대응
| 리스크 | 영향 | 대응 |
|--------|------|------|
| 그룹웨어 UI 변경 | 스크립트 동작 불가 | Playwright 셀렉터를 유연하게 설계 |
| 세션 만료 | 자동화 중단 | 세션 저장/복원 + 자동 재로그인 |
| Notion API 제한 | 저장 실패 | 재시도 로직 + 로컬 백업 |
| 캡차/2차 인증 | 자동 로그인 불가 | 수동 로그인 후 세션 재사용 |
| 클라우드 배포 보안 | 외부 접속 시 보안 이슈 | HTTPS + 인증 적용 |
