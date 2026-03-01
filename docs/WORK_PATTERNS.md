# 작업 패턴 및 규칙 가이드

> 이 프로젝트에서 확립된 작업 패턴, 규칙, 명명 규칙을 정리한 문서.
> 새 세션 시작 시 `SESSION_RESUME.md`와 함께 참고.
> 마지막 업데이트: 2026-03-02

---

## 1. 세션 관리 패턴

### 세션 이어가기
- **새 세션 시작 시 필수**: `docs/SESSION_RESUME.md`를 먼저 읽기
- 컴퓨터 꺼져도 이어갈 수 있도록 세션 마무리 시 기록 필수
- 세션 번호: 알파벳(A~I) → 로마숫자(I~V) 순으로 증가

### 기록 대상 파일 (이전 폴더 제외)
| 파일 | 용도 | 업데이트 시점 |
|------|------|---------------|
| `docs/SESSION_RESUME.md` | 세션 이어가기 핵심 문서 | 매 세션 마무리 |
| `docs/work-log.md` | 세션별 상세 작업 로그 | 작업 완료 시 |
| `docs/gw-analysis.md` | GW API/구조 분석 결과 | 새 API 발견 시 |
| `docs/TELEGRAM_USER_MANUAL.md` | 텔레그램 봇 사용자 매뉴얼 | 텔레그램 기능 변경 시 |
| `docs/CLAUDE_COLLABORATION.md` | Claude 인스턴스 간 동기화 | 주요 기술 돌파 시 |
| `CLAUDE.md` | 프로젝트 전체 규칙 | 규칙 변경 시만 |

### 레코더 에이전트
- 작업 기록 전담 에이전트 1개 운영
- `이전/` 폴더 파일은 절대 수정하지 않음
- 기존 내용 유지, 신규 섹션만 추가/갱신
- 한국어로 작성

---

## 2. 명칭 규칙

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
| Phase 1 | 기본 자동화 구현 |
| Phase 2 | 상신/검증/에러처리 |
| 보관 | 임시저장 (결재 폼에는 보관 버튼 없음) |
| 상신 | 결재 제출 (결재상신 버튼) |

---

## 3. 기술 패턴

### GW 접근 방식 (2가지)

#### 방식 A: API 직접 호출 (회의실 예약)
```
Playwright 로그인 → 쿠키/토큰 추출 → httpx API 호출
```
- **사용처**: 회의실 예약 (rs121A 시리즈)
- **인증**: wehago-sign HMAC
- **장점**: 빠르고 안정적
- **조건**: API payload 구조를 완벽히 파악한 경우

#### 방식 B: Playwright 폼 자동화 (전자결재)
```
Playwright 로그인 → 페이지 이동 → DOM 조작으로 폼 채우기
```
- **사용처**: 전자결재 (API payload 미확보)
- **인증**: 브라우저 세션 쿠키
- **장점**: API 몰라도 가능
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
- `#reqCompCd`: disabled 필드, 건드리지 않음
- 로그인 후 팝업 5개+ 자동 열림 → URL에 "popup" 포함 시 닫기
- 세션 저장: `data/session_state.json`

### API 인증 패턴
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

---

## 4. 데이터 저장 패턴

### 디렉토리 구조
```
data/
├── users.db                    # 사용자 DB (SQLite + Fernet)
├── session_state.json          # GW 브라우저 세션
├── sessions/                   # 사용자별 GW 세션 파일
├── chatbot/
│   ├── chat_history.db         # 대화 히스토리 DB (챗봇 전용)
│   ├── logs/                   # 대화 로그 파일 (이중 백업)
│   └── uploads/                # 업로드 파일 저장
├── gw_analysis/                # GW 분석 데이터
├── approval_dom_v2/            # Phase 0 DOM 탐색 결과
└── approval_drafts/            # 임시보관문서 캡쳐 결과
```

### 데이터 이중화
- **대화 히스토리**: SQLite DB (메인) + JSONL 파일 (이중 백업)
- **GW 세션**: 파일 저장 + 인메모리 캐시 (2시간 TTL)

### 탐색/캡쳐 데이터 저장
- 스크린샷: `{폴더}/{순번}_{설명}.png`
- API 응답: `api_responses.json`
- DOM 데이터: `inputs.json`, `buttons.json`, `tables.json`
- 페이지 소스: `page.html`, `page_text.txt`

---

## 5. 에이전트 팀 운영 규칙

### 팀 구성 원칙
- 필요한 만큼만 에이전트 생성 (과다 생성 지양)
- **레코더 에이전트**: 1개로 통합, 문서 기록 전담
- 작업 완료 후 불필요한 에이전트 비활성화
- 동일 파일 동시 편집 금지

### 에이전트 유형
| 유형 | 역할 | 예시 |
|------|------|------|
| recorder | 문서 기록/업데이트 | 마크다운 파일 갱신 |
| explorer | DOM/API 탐색 | Phase 0 스크립트 실행 |
| dev | 코드 구현 | 모듈 개발 |

### 팀 단축키
- `Shift+Down`: 팀원 간 전환
- `Ctrl+T`: 태스크 리스트 보기

---

## 6. 보안 규칙

### 비밀번호 처리
- GW 비밀번호: **Fernet 대칭 암호화** (해싱 불가 — Playwright 로그인에 평문 필요)
- 텔레그램: 비밀번호 포함 메시지 **자동 삭제** (`context.bot.delete_message`)
- `.env` 파일에 민감 정보 집중 관리

### 인증 토큰
- JWT: httpOnly 쿠키, 24시간 만료, sameSite=lax
- GW 세션: 2시간 TTL 캐시

### 관리자
- 관리자 GW ID: `tgjeon` (하드코딩)
- 관리자 전용: 사용자 목록/삭제/프로필 관리

---

## 7. 채널별 아키텍처 차이

### 챗봇 (웹)
- FastAPI + SQLite (chat_db)
- JWT 쿠키 인증
- 대화 히스토리: DB 영구 저장
- 세션 목록/전환/삭제 UI
- 파일 업로드: base64 인코딩 → Gemini 전달

### 텔레그램
- python-telegram-bot 라이브러리
- 인메모리 세션 (`tg_sessions: dict`)
- 대화 히스토리: 인메모리 (최근 40개, 서버 재시작 시 소실)
- `/clear` 명령어로 대화 지우기 (로그인 유지)
- DB 연동 없음 (사용자 요청에 따라)

### 공통
- Gemini 에이전트(`analyze_and_route`) 재사용
- `user_context` 딕셔너리로 사용자 정보 전달
- 파일 첨부 지원 (이미지 JPG/PNG/GIF/WebP + PDF, 10MB 제한)

---

## 8. 전자결재 양식 관리

### 양식 상태
| 상태 | 의미 |
|------|------|
| `verified` | Phase 0 완료, 실제 selector 확정됨 |
| `template_only` | 필드 구조만 정의, DOM 탐색 미완 |

### 현재 양식 현황 (form_templates.py)
| 양식 | 상태 | 사용 빈도 |
|------|------|-----------|
| 지출결의서 | verified | 30건 (1위) |
| 거래처등록 | template_only | 26건 (2위) |
| 연장근무 | template_only | 3건 |
| 증빙발행 | template_only | - |
| 선급금요청 | template_only | - |
| 선급금정산 | template_only | - |
| 외근신청 | template_only | - |
| 사내추천비 | template_only | - |

### 양식 추가 절차
1. `form_templates.py`에 필드 구조 정의 (`template_only`)
2. Phase 0 DOM 탐색으로 실제 selector 확정
3. `approval_automation.py`에 작성 메서드 추가
4. `agent.py` 핸들러에서 양식 라우팅
5. 상태를 `verified`로 변경

---

## 9. GW URL 패턴

### 주요 URL
| 페이지 | URL |
|--------|-----|
| 메인 | `/#/` |
| 결재 HOME | `/#/EA/` (span.module-link.EA 클릭) |
| 지출결의서 양식 | `/#/HP/APB1020/APB1020?formDTp=APB1020_00001&formId=255` |
| 임시보관문서 | `/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1020` |

### URL 구조 규칙
- 해시 라우팅 (`/#/`) — SPA
- 모듈코드: EA(전자결재), UB(상신/보관함), HP(양식), ML(메일) 등
- `specialLnb=Y`: 특수 좌측 네비게이션 표시

---

## 10. 회의실 예약 데이터

### 회의실 매핑
| 회의실 | resSeq |
|--------|--------|
| 1번 | 45 |
| 2번 | 46 |
| 3번 | 47 |
| 4번 | 48 |
| 5번 | 49 |

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

## 11. 사용자 선호 및 소통 규칙

- **한국어 소통** 기본
- **비개발자 관점** 설명 (기술 용어 최소화)
- **진행 상황 자세히 기록** 요청
- **컴퓨터 꺼져도 이어갈 수 있게** 정리
- 작업 분기 시 사용자에게 선택지 제시
- 명칭 통일 준수 (챗봇 vs 텔레그램)
