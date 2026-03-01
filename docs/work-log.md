# 작업 로그 (work-log.md)

> 작성자: recorder 에이전트
> 최초 작성: 2026-03-01
> 목적: 세션별 작업 기록 + 사용자 요청 패턴 분석

---

## 1. 세션별 작업 로그

### 세션 A: 초기 설정 및 분석 (날짜 미상 ~ 2026-03-01 이전)

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | Python 3.14, Playwright, httpx 등 환경 구성 | 완료 |
| 2 | 프로젝트 폴더 구조 생성 | 완료 |
| 3 | `config/.env` 환경변수 설정 (GW_URL, ID, PW, GEMINI_API_KEY) | 완료 |
| 4 | `src/auth/login.py` 로그인 모듈 작성 (2단계: ID→Enter→PW→Enter) | 완료 |
| 5 | 로그인 시 disabled 필드(#reqCompCd) 오인 버그 수정 | 완료 |
| 6 | 세션 저장/복원 기능 (`data/session_state.json`) | 완료 |

### 세션 B: 그룹웨어 분석 및 챗봇 개발 (2026-03-01 이전)

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | Playwright로 그룹웨어 전체 구조 분석 | 완료 |
| 2 | 전자결재, 메일, 회의실(자원) 메뉴 구조 파악 | 완료 |
| 3 | 89+ API 엔드포인트 캡처 → `data/gw_analysis/` 저장 | 완료 |
| 4 | 결재 양식 8개, 결재선(3단계) 구조 확인 | 완료 |
| 5 | `docs/gw-analysis.md` 분석 보고서 작성 | 완료 |
| 6 | `src/chatbot/agent.py` Gemini 2.5 Flash 의도 분석 모듈 개발 | 완료 |
| 7 | `src/chatbot/app.py` FastAPI 백엔드 개발 | 완료 |
| 8 | `templates/chat.html` 채팅 UI 개발 | 완료 |
| 9 | Playwright sync + asyncio 충돌 → ThreadPoolExecutor로 해결 | 완료 |
| 10 | `src/meeting/reservation.py` (~938줄) Playwright 기반 예약 모듈 개발 | 완료 |
| 11 | Anthropic API 크레딧 부족 → Google Gemini 무료 API로 전환 결정 | 완료 |

### 세션 C: PM 요구사항 수집 및 정리 (2026-03-01)

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | pm 에이전트가 사용자와 챗봇 요구사항 구체화 | 완료 |
| 2 | 회의실 예약 = 1순위 확정 | 완료 |
| 3 | 결재 이력 조회 기능 목적 정정 (사용자용 ❌ → 내부 분석용 ✅) | 완료 |
| 4 | 외부 접속(클라우드), 파일 첨부, 로컬 저장 요구사항 확정 | 완료 |
| 5 | 에이전트 팀 구성: team-lead, researcher, pm, meeting-dev, chatbot-dev, approval-dev | 완료 |

### 세션 D: 회의실 예약 API 분석 및 전환 (2026-03-01)

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | SESSION_RESUME.md 작성 및 상태 정리 (15:08) | 완료 |
| 2 | rs121A 시리즈 API 엔드포인트 발견 (/schres/ 경로) | 완료 |
| 3 | 1번 회의실 resSeq="45" 확인 | 완료 |
| 4 | rs121A11 예약 생성 파라미터 분석 (JS 소스 기반) | 완료 |
| 5 | wehago-sign 동적 서명 인증 문제 발견 | 완료 |
| 6 | 해결책 도출: Playwright page.evaluate()로 fetch 호출 | 완료 |
| 7 | 인증 헤더 캡처: `data/gw_analysis/rs121_auth_headers.json` | 완료 |
| 8 | `scripts/test_rs121_api_v2.py` 등 다수 분석 스크립트 작성 | 완료 |

### 세션 E: meeting-api 팀 구성 및 wehago-sign 인증 분석 (2026-03-01)

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | 마크다운 파일 전체 확인 및 SESSION_RESUME.md 검토 | 완료 |
| 2 | meeting-api 팀 생성: team-lead, researcher, api-dev | 완료 |
| 3 | **Task #1**: rs121A11 파라미터 완전 분석 (researcher) | 완료 |
| 4 | **Task #2**: `scripts/test_evaluate_api.py` 작성 - call_api_via_evaluate() 공통 함수, rs121A01/A05/A14/A49 테스트 포함 (api-dev) | 완료 |
| 5 | **Task #3**: `src/meeting/reservation_api.py` MeetingRoomAPI 클래스 작성 - get_rooms/reservations/check_availability/find_available_slots/make_reservation/cancel_reservation + create_api_with_session() (api-dev) | 완료 |
| 6 | **Task #4**: `src/chatbot/agent.py` 수정 - reservation.py → reservation_api.py 연동 전환, handle_reserve_meeting_room()에서 create_api_with_session() 사용 (api-dev) | 완료 |
| 7 | 테스트 실행: 모든 API 401 에러 (resultCode=601, "허용된 쿠키 인증 URL이 아닙니다") | 실패 확인 |
| 8 | **Task #8**: wehago-sign JS 함수 탐색 (researcher) - scheduleApiCommon이 webpack closure 내부에 있어 직접 호출 불가 확인 | 완료 |
| 9 | **Task #9**: `scripts/capture_auth_headers.py` 작성 및 실행 (interceptor) - 52건 인증 헤더 캡처, signKey 쿠키 발견 | 완료 |
| 10 | recorder 에이전트 추가 및 작업 기록 업데이트 | 완료 |
| 11 | **Task #10**: wehago-sign 알고리즘 완전 해독 (researcher) - 13/13 샘플 검증 성공 | 완료 |

---

## 2. 사용자 요청 패턴 분석

> 근거: docs/SESSION_RESUME.md, plan.md, requirements.md, docs/agents/pm.md, docs/agents/README.md

### 2-1. 요청 언어 스타일

| 패턴 | 예시 | 근거 |
|------|------|------|
| 자연어 한국어 명령 | "회의실 예약해줘, 내일 오후 3시" | requirements.md 사용 시나리오 |
| "~해줘" 형태 직접 명령 | "내일 오후 2시 회의실 예약해줘" | requirements.md, SESSION_RESUME.md |
| 구체적 조건 포함 | "내일 오후 2시 5번 회의실" | plan.md Phase 6 핵심 기능 |
| 작업 + 자료 조합 | "이 영수증으로 경비 결재 올려줘" + PDF 첨부 | requirements.md 시나리오 2 |

**핵심 패턴**: 짧고 직접적인 자연어 명령 + 필요시 파일 첨부

### 2-2. 우선순위 표현 방식

- 명시적 "1순위" 레이블 사용: "회의실 예약 자동화 ★ 1순위"
- 별표(★) 기호로 중요도 표시
- 반복 언급으로 중요도 강조 (회의실 예약이 여러 문서에 걸쳐 반복 등장)
- 순서 번호 + "우선순위" 목록으로 정리 요청

**근거**: requirements.md "요구사항 4: 회의실 예약 자동화 ★ 1순위", plan.md 우선순위 목록

### 2-3. 피드백 및 수정 패턴

| 상황 | 반응 방식 | 근거 |
|------|-----------|------|
| 기능 목적 오해 | 직접 정정 요청 → 문서에 반영 요청 | pm.md "Task #2 목적 정정 전달" |
| 기술 전환 결정 | 이유 납득 후 승인 (Gemini 전환) | plan.md Phase 6 "해결된 이슈" |
| 진행 상황 확인 | 문서로 상태 정리 요청 ("컴퓨터 꺼져도 이어갈 수 있게") | MEMORY.md |

### 2-4. 작업 지시 방식

- **추상적 목표 제시**: "챗봇으로 그룹웨어를 자동화하고 싶다"
- **구체화는 에이전트에 위임**: 세부 구현 방법은 개발팀이 결정
- **확인 포인트만 명시**: 접속 범위, AI 엔진 선택 등 비개발자 결정 사항만 직접 답변
- **비개발자 관점 유지**: 기술 용어보다 기능 설명 선호

**근거**: pm.md "비개발자 소통", plan.md "사용자: 비개발자 (상담 기반 요구사항 수집)"

### 2-5. 커뮤니케이션 선호 스타일

| 선호 | 비선호 | 근거 |
|------|--------|------|
| 한국어 소통 | 영어 기술 용어 나열 | MEMORY.md "한국어 소통" |
| 진행 상황 자세히 기록 | 기록 없는 작업 진행 | MEMORY.md "진행 상황 자세히 기록 요청" |
| 세션 이어가기 가능한 문서 | 휘발성 대화 | MEMORY.md "컴퓨터 꺼져도 이어갈 수 있게" |
| 비개발자 눈높이 설명 | 기술적 상세 설명 | pm.md "비개발자 소통" |

---

## 3. 사용자 프로필 요약

### 기본 정보
- **이름**: 전태규 대리
- **소속**: 주식회사 글로우서울 PM팀
- **기술 수준**: 비개발자 (사용자 관점, 기능 중심)

### 업무 특성
- PM팀으로 프로젝트 관리 업무 담당
- 전자결재 사용 빈도 높음 (월 66건 이상)
- 주요 결재 양식: [프로젝트]지출결의서 (최다), 국내 거래처등록 신청서
- 회의실 예약, 경비 결재, 메일 확인 등 반복 업무 자동화 필요

### 기능 우선순위 (확정)
1. ★ 회의실 예약 자동화 (챗봇으로 "내일 오후 2시 예약해줘")
2. ★ 챗봇 웹 인터페이스 (파일 첨부 + 자연어)
3. 결재 문서 자동 작성
4. 메일 요약 → Notion 저장
5. 결재 이력 조회 (내부 분석용)

### 중요 요구사항 (비협상)
- 세션 종료 후에도 이어서 작업 가능한 문서화
- 외부에서도 접속 가능한 클라우드 배포
- 채팅창에서 파일 드래그앤드랍 지원
- 처리 결과를 채팅으로 바로 응답

---

## 4. 현재 진행 중인 작업 (2026-03-01 기준)

### 핵심 목표
Playwright UI 자동화 → rs121A API 직접 호출로 전환

### 기술적 현황
- 문제: wehago-sign 동적 서명 인증 (매 요청마다 변경)
- 해결 방향: `page.evaluate('fetch(...)')` 방식으로 브라우저에서 직접 호출
- 예약 생성 API: `POST /schres/rs121A11`
- 1번 회의실: resSeq="45"

### 팀 구성 (세션 E 최신)
- team-lead: 총괄
- researcher: wehago-sign 서명 생성 방법 분석 (Task #10 진행 중)
- interceptor: 인증 헤더 캡처 전문 (신규, Task #9 완료 후 대기)
- recorder (본 에이전트): 문서화 담당
- ※ api-dev, 이전 recorder는 종료됨

### Task 상태 요약 (세션 E 기준)

| Task# | 내용 | 담당 | 상태 |
|-------|------|------|------|
| #1 | rs121A11 파라미터 분석 | researcher | 완료 |
| #2 | test_evaluate_api.py 작성 | api-dev | 완료 |
| #3 | reservation_api.py 작성 | api-dev | 완료 |
| #4 | 챗봇 연동 (agent.py 수정) | api-dev | 완료 |
| #8 | wehago-sign JS 함수 탐색 | researcher | 완료 |
| #9 | 인증 헤더 캡처 | interceptor | 완료 |
| #10 | wehago-sign 알고리즘 해독 (13/13 검증) | researcher | 완료 |
| #14 | reservation_api.py httpx 방식으로 재작성 | api-dev | 진행 중 |
| #15 | httpx 방식 API 호출 테스트 | api-dev | 대기 중 |

---

## 5. 핵심 기술 이슈: wehago-sign 인증 문제 ★ 해결됨 (2026-03-01)

### 문제 정의
- rs121A 시리즈 API는 쿠키 인증 외에 `wehago-sign` 헤더가 필수
- 단순 fetch() 호출 시 서명이 붙지 않아 401 에러 (resultCode=601) 발생
- 오류 메시지: "허용된 쿠키 인증 URL이 아닙니다"

### 분석 결과 (Task #8, #9)
| 항목 | 내용 |
|------|------|
| 서명 생성 함수 | `scheduleApiCommon` (webpack closure 내부, window 접근 불가) |
| authorization 헤더 | `Bearer gcmsAmaranth36068|2922|wAgC3PYkqN3SlTVCqijvEkXYCh02uD` (모든 요청 동일) |
| wehago-sign | 요청마다 다름 (HMAC 기반 동적 생성) |
| signKey 쿠키 | `95233990162914950487395159959680005262700721` → HMAC 서명 키 확정 |
| oAuthToken 쿠키 | authorization 헤더값과 URL 디코딩 일치 (동일 값) |
| BIZCUBE_HK | signKey와 동일한 값 |
| BIZCUBE_AT | oAuthToken과 동일한 값 |
| fetch/XHR | 네이티브 (오버라이드 없음, 가로채기 우회 필요) |

### axios/XHR 폴백 시도 결과
- axios 및 XHR 방식으로 폴백 시도 → 여전히 401 에러 동일 발생
- 단순 HTTP 클라이언트로는 wehago-sign 헤더를 자동 생성 불가

### ★ wehago-sign 알고리즘 완전 해독 (13/13 샘플 검증 성공)

**공식**:
```
wehago-sign = Base64( HMAC-SHA256( signKey, oAuthToken + transactionId + timestamp + pathname ) )
```

| 구성 요소 | 값 / 생성 방법 |
|-----------|----------------|
| signKey | 쿠키 `signKey` 값: `95233990162914950487395159959680005262700721` |
| oAuthToken | 쿠키 `oAuthToken` 값 (URL 디코딩 후 사용) |
| transactionId | `uuid4().hex` (랜덤 32자리 hex, 요청마다 새로 생성) |
| timestamp | `int(time.time())` (Unix 초) |
| pathname | 요청 URL 경로 (예: `/schres/rs121A11`) |

**Python 구현 예시**:
```python
import hmac, hashlib, base64, time
from uuid import uuid4

def make_wehago_sign(sign_key, oauth_token, pathname):
    transaction_id = uuid4().hex
    timestamp = str(int(time.time()))
    message = oauth_token + transaction_id + timestamp + pathname
    sig = hmac.new(sign_key.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig).decode()
```

**핵심 결론**:
- Playwright `page.evaluate()` 방식 불필요 → 완전히 제거 가능
- 로그인 후 쿠키 2개(`signKey`, `oAuthToken`)만 추출하면 Python `httpx`로 직접 API 호출 가능
- 13개 실제 캡처 샘플 100% 검증 완료

### 해결 방향 최종 확정
- **방향 A 채택 완료**: signKey + HMAC-SHA256으로 wehago-sign 직접 생성 → httpx로 API 직접 호출
- ~~방향 B: CDP 인터셉트~~ (불필요, 폐기)
- ~~방향 C: UI 자동화 유지~~ (불필요, 폐기)

### 관련 파일
- `scripts/capture_auth_headers.py`: 인증 헤더 캡처 스크립트
- `data/gw_analysis/rs121_auth_headers.json`: 52건 캡처 데이터 (검증 샘플 포함)
- `scripts/test_evaluate_api.py`: Playwright evaluate 방식 테스트 (이제 불필요)
- `src/meeting/reservation_api.py`: MeetingRoomAPI 클래스 (httpx 방식으로 업데이트 예정)

---

## 6. 그룹웨어 인증 구조 (해독 완료, 2026-03-01)

### 쿠키 구조
| 쿠키명 | 용도 | 값 예시 |
|--------|------|---------|
| oAuthToken | API 인증 토큰 (URL 인코딩) | `gcmsAmaranth36068%7C2922%7CwAgC3PYkqN3SlTVCqijvEkXYCh02uD` |
| signKey | HMAC 서명 키 | `95233990162914950487395159959680005262700721` |
| BIZCUBE_AT | oAuthToken과 동일 (중복) | (위와 동일) |
| BIZCUBE_HK | signKey와 동일 (중복) | (위와 동일) |
| BIZCUBE_TYPE | 접속 타입 | `WEB` |

### oAuthToken 구조
`{groupSeq}|{empSeq}|{sessionToken}` 형태
- groupSeq: `gcmsAmaranth36068` (테넌트 ID)
- empSeq: `2922` (사원 시퀀스)
- sessionToken: 로그인 시 발급

### API 인증 헤더 구조
| 헤더 | 생성 방법 |
|------|-----------|
| authorization | `Bearer ` + oAuthToken (URL 디코딩) |
| timestamp | `int(time.time())` - Unix 초 단위 |
| transaction-id | `uuid4().hex` - 32자 랜덤 hex |
| wehago-sign | `Base64(HMAC-SHA256(signKey, oAuthToken + transactionId + timestamp + pathname))` |

### wehago-sign 생성 공식
```
message = oAuthToken + transactionId + timestamp + pathname
wehago-sign = Base64(HMAC-SHA256(signKey, message))
```
- 13개 실제 캡처 샘플로 100% 검증됨
- JS 소스 위치: `1.95189df6.chunk.js`

### API 경로 체계
| 경로 | 인증 방식 | 용도 |
|------|-----------|------|
| `/gw/APIHandler/{코드}` | 쿠키 인증 (단순) | 일반 gw API |
| `/gw/{코드}` | 쿠키 인증 | 일부 gw API |
| `/schres/{코드}` | wehago-sign 서명 인증 | 자원 예약 API |
| `/mail/api/{코드}` | 쿠키 인증 | 메일 API |

### 접근 방식 전환 이력
| 단계 | 방식 | 결과 |
|------|------|------|
| 1차 시도 | Playwright `page.evaluate()` → fetch() | 실패 (401) |
| 2차 시도 | axios/XHR 폴백 | 실패 (401) |
| **최종 확정** | Playwright 로그인 → 쿠키 추출 → Python httpx + wehago-sign 직접 생성 | 성공 |

---

## 7. 세션 F: httpx 전환 완료 (2026-03-01 20:10)

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | **Task #14**: `reservation_api.py` httpx + wehago-sign HMAC 방식으로 완전 재작성 | 완료 |
| 2 | Playwright page.evaluate() 방식 전체 제거, httpx 직접 호출로 교체 | 완료 |
| 3 | MeetingRoomAPI 생성자 변경: `(page: Page)` → `(oauth_token, sign_key, cookies)` | 완료 |
| 4 | `create_api_with_session()`: 로그인→쿠키 추출→브라우저 종료→httpx API 반환 | 완료 |
| 5 | **Task #15**: httpx API 호출 테스트 실행 | 완료 |
| 6 | rs121A01 (회의실 목록): HTTP 200, resultCode=0, 5개 회의실 정상 조회 | 성공 |
| 7 | rs121A05 (예약 현황): HTTP 200, resultCode=0, 0건 (주말) | 성공 |
| 8 | rs121A14 (중복 체크): HTTP 200, resultCode=500 (주말 날짜 한계) | 부분 성공 |
| 9 | `agent.py` 수정 불필요 확인 (create_api_with_session 인터페이스 동일) | 확인 |
| 10 | SESSION_RESUME.md 업데이트 | 완료 |

### 핵심 성과
- **401 에러 완전 해결**: wehago-sign HMAC 서명 직접 생성으로 인증 통과
- **Playwright 의존도 최소화**: 로그인+쿠키 추출에만 사용, API 호출은 httpx
- **속도 향상**: 브라우저 내 JS 실행 → Python httpx 직접 호출

---

## 8. 세션 G: 챗봇 예약 조회 기능 추가 (2026-03-01)

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | `agent.py`에 Function Calling 2개 추가: `check_reservation_status`, `check_available_rooms` | 완료 |
| 2 | `handle_check_reservation_status()` 핸들러 작성 — `get_reservations()` API 호출 → 예약 목록 포맷팅 | 완료 |
| 3 | `handle_check_available_rooms()` 핸들러 작성 — `find_available_slots()` API 호출 → 회의실별 그룹핑 표시 | 완료 |
| 4 | `reservation_api.py` `find_available_slots()` 개선 — 빈 구간 슬롯 하나만 반환 → 빈 구간 전체 반환, `duration_minutes`는 최소 필요시간 필터로 변경 | 완료 |
| 5 | 테스트 (3월 2일 기준): 예약 현황 2건 조회 성공 — 1번 회의실 PM팀 일일회의, 회계팀 주간회의 | 성공 |
| 6 | 빈 시간대 조회: 1번 회의실 09:00~10:00 + 11:30~18:00, 2~5번 회의실 09:00~18:00 전체 | 성공 |
| 7 | 모든 API HTTP 200, resultCode=0 정상 응답 확인 | 성공 |
| 8 | **미해결**: rs121A12 (반복 예약) 생성 — `resSubscriberList` 파라미터 이슈 (에러 코드 9201/9202) | 보류 |

### 세션 G 핵심 성과
- 챗봇에서 "이번 주 예약 현황 알려줘", "내일 빈 회의실 있어?" 등 자연어 조회 가능
- `find_available_slots()` 개선으로 빈 시간대 전체 구간 표시 (기존: 슬롯 하나만)

---

---

## 9. 세션 H: 예약 생성 API 엔드포인트 확정 (2026-03-01 저녁)

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | rs121A12로 예약 생성 시도 → 500 FAIL | 실패 확인 |
| 2 | JS 소스 분석 — rs121A12가 신규 생성이 아닌 **기존 예약 수정용** 엔드포인트임을 발견 | 원인 확인 |
| 3 | JS save 핸들러 분석 — **rs121A06**이 신규 단건 예약 생성 엔드포인트임을 확인 | 완료 |
| 4 | `reservation_api.py` `make_reservation()` 메서드를 rs121A06으로 변경 | 완료 |
| 5 | rs121A06 예약 생성 테스트: HTTP 200, resultCode=0, successTf=true | **성공** |
| 6 | rs121A11 예약 취소 테스트 (statusCode="CA"): HTTP 200, resultCode=0 | **성공** |

### 핵심 발견: 엔드포인트 용도 정정

JS 신규 폼 save 핸들러:
- `repeatType === "10"` (단건) → **rs121A06**
- `repeatType !== "10"` (반복) → **rs121A15**

JS 수정 폼 save 핸들러:
- `repeatType === "10"` (단건) → rs121A12 ← 기존에 잘못 사용하던 엔드포인트
- `repeatType !== "10"` (반복) → rs121A15

### API 엔드포인트 확정 목록

| API | 용도 | 상태 |
|-----|------|------|
| rs121A01 | 자원(회의실) 목록 조회 | 동작 확인 |
| rs121A05 | 예약 현황 조회 | 동작 확인 |
| rs121A06 | **신규 단건 예약 생성** | 동작 확인 ★ |
| rs121A11 | 예약 취소/상태 변경 | 동작 확인 |
| rs121A12 | 기존 예약 수정 (단건) | 수정용 (신규 생성 아님) |
| rs121A14 | 예약 중복 체크 | 동작 확인 |
| rs121A15 | 반복 예약 생성/수정 | 미테스트 |

### 예약 취소 챗봇 기능 추가

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 7 | `agent.py`에 `cancel_meeting_reservation` Function Declaration 추가 | 완료 |
| 8 | `handle_cancel_meeting_reservation()` 핸들러 구현 — 날짜별 본인 예약 조회 → 조건(제목/회의실/시간) 필터링 → 취소 실행 | 완료 |
| 9 | 여러 건 매칭 시 목록 표시 후 사용자 선택 요청 로직 추가 | 완료 |
| 10 | 시스템 프롬프트에 취소 흐름 가이드 추가 — "취소하고 싶어" → check_reservation_status 먼저 호출 후 cancel_meeting_reservation 실행 | 완료 |
| 11 | 대화 히스토리 기반 3단계 흐름 테스트 성공: 현황 확인 → 사용자 선택 → 취소 실행 | **성공** |

### 세션 H 핵심 성과
- **예약 생성 완전 해결**: 잘못된 엔드포인트(rs121A12) → 올바른 엔드포인트(rs121A06) 전환
- **예약 취소 확인**: rs121A11으로 statusCode="CA" 전송 방식 동작 검증
- **취소 챗봇 흐름 완성**: 자연어 "취소해줘" → 현황 조회 → 선택 → 취소 3단계 자동화
- **챗봇 예약 기능 실사용 가능 수준 도달**: 조회 + 생성 + 취소 모두 정상

---

---

## 10. 세션 I: 다중 사용자 + 대화 히스토리 DB (2026-03-01 ~ 2026-03-02)

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | 다중 사용자 시스템 구현: SQLite + Fernet 암호화 사용자 DB | 완료 |
| 2 | JWT 쿠키 인증 (httpOnly, 24시간 만료) | 완료 |
| 3 | 관리자 페이지: 사용자 목록/삭제/프로필 관리 | 완료 |
| 4 | 대화 히스토리 DB 전환: 인메모리 dict → SQLite (`data/chatbot/chat_history.db`) | 완료 |
| 5 | 테이블 구조: sessions (PK: gw_id+session_id) + messages (AUTOINCREMENT) | 완료 |
| 6 | 신규 API: `GET /sessions` (세션 목록), `GET /history/{id}` (조회), `DELETE /history/{id}` (삭제) | 완료 |
| 7 | 사이드바에 이전 대화 목록 표시, 세션 전환/삭제 가능 | 완료 |
| 8 | 전자결재 자동화 Phase 1: `src/approval/approval_automation.py` 기초 구현 | 완료 |
| 9 | 양식 템플릿 1개: 지출결의서 (`src/approval/form_templates.py`) | 완료 |
| 10 | 결재 2단계 안전장치: confirm(미리보기) → draft(Playwright 실제 작성) | 완료 |
| 11 | 결재선 구조 확인: 기안자(auto) → 신동관(합의) → 최기영(최종) | 완료 |

---

## 11. 세션 IV: 텔레그램 봇 확장 + 결재 양식 세분화 + Phase 0 DOM 탐색 완료 (2026-03-02)

### 11-1. 텔레그램 봇 업데이트

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | 대화 히스토리 DB 연동 → **인메모리 방식으로 변경** (사용자 요청) | 완료 |
| 2 | `/clear` 명령어 추가 (대화 기록 지우기, 로그인 상태 유지) | 완료 |
| 3 | `/newchat` 명령어 제거 | 완료 |
| 4 | 이미지 및 PDF 파일 첨부 지원 추가 | 완료 |
| 5 | 명칭 통일 확정: "텔레그램" = `telegram_bot.py`, "챗봇" = 웹 `app.py` | 완료 |

**파일**: `src/chatbot/telegram_bot.py`

### 11-2. 상신 문서 현황 수집

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | `scripts/fetch_approval_docs.py` 작성 — 결재 HOME 스크린샷 기반 양식 사용 현황 분석 | 완료 |
| 2 | 상신 문서 현황 파악: [프로젝트]지출결의서 30건, [회계팀]국내 거래처등록 26건, 연장근무신청서 3건, 기타 7건 | 완료 |
| 3 | 총 상신 문서: **66건** | 완료 |

**파일**: `scripts/fetch_approval_docs.py`

### 11-3. 전자결재 양식 세분화

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | 기존 지출결의서 1개 → **8개 양식**으로 확장 | 완료 |
| 2 | 추가 양식 7개: 국내거래처등록, 증빙발행신청, 선급금요청, 선급금정산, 연장근무신청, 외근신청, 사내추천비 | 완료 |
| 3 | 각 양식에 `status` 필드 추가: `"verified"` (DOM 확인됨) / `"template_only"` (미확인) | 완료 |
| 4 | `aliases` 지원 — 자연어 매핑 (예: "경비", "지출" → 지출결의서) | 완료 |
| 5 | `list_form_names()` 유틸 함수 추가 | 완료 |
| 6 | 보관(임시저장) 경로 확인: 상신/보관함 > 임시보관문서 | 확인 |

**파일**: `src/approval/form_templates.py`

### 11-4. Phase 0 DOM 탐색 완료

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | `scripts/explore_approval_dom_v2.py` — 지출결의서 실제 DOM 구조 캡처 | 완료 |
| 2 | 실제 selector 확정 (양식 URL, 테이블 구조, 필드 접근 방식) | 완료 |
| 3 | **핵심 발견**: "보관" 버튼 없음 — "결재상신" 버튼만 존재 | 확인 |
| 4 | `approval_automation.py` Phase 0 결과 반영, 실제 selector로 전체 재작성 | 완료 |
| 5 | `form_templates.py` Phase 0 결과 반영 (formId=255, 실제 필드 구조) | 완료 |
| 6 | `agent.py` `get_or_create_session` 버그 수정 → `login_and_get_context` 직접 사용 | 완료 |
| 7 | `agent.py` 타임아웃 120초 → 180초로 증가 | 완료 |

**데이터**: `data/approval_dom_v2/` (inputs.json, buttons.json, tables.json, action_buttons.json, screenshots)

#### Phase 0 핵심 발견사항:
- 네비게이션: `span.module-link.EA` → 결재 HOME → 추천양식 "[프로젝트]지출결의서" 직접 클릭
- 양식 URL: `/#/HP/APB1020/APB1020?formDTp=APB1020_00001&formId=255`
- 양식 테이블: `table.OBTFormPanel_table__1fRyk` (table[0] 상단 + table[7] 하단)
- 필드 접근: `th:has-text(라벨) → following-sibling::td → input:visible`
- 팝업 처리: 로그인 시 5개+ 팝업 페이지 열림, URL "popup" 포함 → 자동 닫기 필요

### 11-5. 세션 IV 핵심 성과 요약

- 텔레그램 봇이 **파일 첨부 지원** + `/clear` 명령어로 사용성 개선
- 전자결재 양식이 1개 → 8개로 대폭 확장 (상위 사용 빈도 기준)
- Phase 0 DOM 탐색으로 지출결의서 실제 selector 100% 확정
- 결재 자동화 파이프라인: 챗봇 → 의도 분석 → Playwright 폼 작성 → 결재상신

---

## 12. 세션 IV 이후 — 다음 할 일

| 우선순위 | 작업 내용 | 비고 |
|---------|-----------|------|
| 1순위 | **통합 테스트**: 지출결의서 결재상신 end-to-end 테스트 | 실제 데이터 필요 |
| 2순위 | **지출내역 그리드 입력** 구현 (용도/내용/금액 등 행 입력) | 현재 제목만 입력됨 |
| 3순위 | **국내 거래처등록 양식 DOM 탐색** (Phase 0 방식) | 2순위 상신 양식 |
| 4순위 | `approval_automation.py`에 다양한 양식 지원 확장 | form_templates.py 8개 양식 |
| 5순위 | 에러 핸들링 강화 (필수 필드 누락, 네트워크 오류, 팝업 등) | 안정화 |

---

---

## 13. 세션 V: 임시보관문서 확인 (2026-03-02)

### 13-1. 임시보관문서 조회

| 순서 | 작업 내용 | 결과 |
|------|-----------|------|
| 1 | `scripts/check_draft_docs.py` 작성 및 실행 — 임시보관문서함 URL 직접 접근 | 완료 |
| 2 | 임시보관문서 **6건** 확인 (모두 [프로젝트]지출결의서 양식) | 완료 |
| 3 | 스크린샷, API 응답 JSON, HTML 저장 → `data/approval_drafts/` | 완료 |
| 4 | 결재홈 eap API 16개 캡처 (eap109A01, eap122A01, eap122A09, eap105A19 등) | 완료 |
| 5 | 결재홈 사이드바 현황 확인 (상신 4건, 기결 4건, 수신참조 591건) | 완료 |

**임시보관문서 목록 (6건, 전부 GS-25-0088 종로 메디빌더 프로젝트):**

| # | 제목 |
|---|------|
| 1 | [종로] 메디빌더 음향공사 대금 지급의 건 |
| 2 | [종로] 메디빌더 유리공사 업체 선급금 지급의 건 |
| 3 | [종로] 메디빌더 제작가구 업체 선급금 지급의 건 |
| 4 | [종로] 메디빌더 타일 시공 업체 선급금 지급의 건 |
| 5 | [종로] 메디빌더 큐비클 업체 선급금 지급의 건 |
| 6 | [종로] 메디빌더 목공 업체 선급금 지급의 건 |

**임시보관문서 URL**: `/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1020`

**관련 파일**:
- `scripts/check_draft_docs.py` — 탐색 스크립트
- `data/approval_drafts/` — 스크린샷, API 응답, HTML

### 13-2. 세션 V 핵심 성과

- 임시보관문서 URL 확정: `pageCode=UBA1020`
- 임시보관문서 6건의 실제 존재 확인 → 결재 자동화 테스트 대상 문서 파악
- eap API 16종 캡처로 결재 관련 API 목록 확충
- 다음 단계: 임시보관문서를 Playwright로 열어 상신 테스트 진행 가능

---

## 14. 세션 V 이후 — 다음 할 일

| 우선순위 | 작업 내용 | 비고 |
|---------|-----------|------|
| 1순위 | **임시보관문서 열기 + 상신 테스트** | `eap122A01` API 또는 Playwright UI 방식 |
| 2순위 | **지출내역 그리드 입력** 구현 | 용도/내용/금액 행 입력 |
| 3순위 | **국내 거래처등록 양식 DOM 탐색** | Phase 0 방식 |
| 4순위 | `approval_automation.py` 다양한 양식 지원 확장 | form_templates.py 8개 양식 |
| 5순위 | 에러 핸들링 강화 | 안정화 |

---

*마지막 업데이트: 2026-03-02 (세션 V, 임시보관문서 확인 완료)*
