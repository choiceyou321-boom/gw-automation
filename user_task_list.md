# GW 자동화 프로젝트 — 작업 목록

> 마지막 업데이트: 2026-03-25
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
| 8 | 전자결재 위저드 (챗봇 단계별 질문) | :white_check_mark: | 03-09 | approval_wizard.py |
| 9 | 선급금요청 양식 (code_ready) | :construction: | — | formId 181, 코드 작성 완료 → GW DOM 검증 필요 |
| 10 | 연장근무 양식 (template_only) | :clipboard: | — | formId 43, 근태관리 모듈 |
| 11 | 외근신청 양식 (template_only) | :clipboard: | — | formId 41, 근태관리 모듈 |
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
| 9 | **GW 프로젝트 목록 크롤링 + 검색 모달** | :construction: | — | 전체데이터보기 OBTDataGrid에서 ~199개 추출 → gw_projects_cache |

### 1-6. STT 음성 인식 :white_check_mark:

| # | 작업 | 상태 | 완료일 | 비고 |
|---|------|------|--------|------|
| 1 | Google Cloud STT API 연동 | :white_check_mark: | 03-16 | `stt.py` |
| 2 | 웹 챗봇 음성 파일 업로드 | :white_check_mark: | 03-16 | audio/* MIME 허용 |
| 3 | 텔레그램 음성 메시지 자동 인식 | :white_check_mark: | 03-16 | voice/audio 핸들러 |
| 4 | 시스템 프롬프트에 STT 안내 추가 | :white_check_mark: | 03-22 | prompts.py에 능동적 안내 규칙 3줄 추가 |

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

---

## 7. 요약 통계

| 항목 | 수치 |
|------|------|
| 총 완료 작업 | **50개** |
| 진행 중 | **2개** (GW 프로젝트 목록 크롤링, 선급금요청 DOM 검증) |
| 미착수 | **5개** |
| 세션 수 | **25회** (03-01 ~ 03-25) |
| 테스트 | **133개** (전체 PASS, 0.77초) |
| 챗봇 도구 | **21개** |
| 전자결재 양식 | verified 2개 / template_only 3개 |
