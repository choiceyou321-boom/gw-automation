# 아키텍처 v4 — 프로젝트 관리 ↔ 그룹웨어 자동화 분리 + 윤비서 패러다임 + GW Adapter

> 작성일: 2026-05-25
> 선행: 본 채팅 v1(분리 분석) → v2(에이전트 페르소나) → v3(윤비서 반영) → **v4(GW 인벤토리 반영)**
> 관련 자료: [GW_AUTOMATION_INVENTORY.md](GW_AUTOMATION_INVENTORY.md), [PROJECT_STATUS.md](PROJECT_STATUS.md)

---

## 0. 변경 요약 (v3 → v4)

| 변경 | v3 | v4 |
|---|---|---|
| **GW Adapter Interface** | 추상화 언급만 | **`IGroupwareProvider` 시그니처 구체화** |
| **모듈 인벤토리** | 미반영 | **12 모듈 / 22 페이지 URL / HR LNB 트리 통합** |
| **셀렉터 자산** | 산재 | `src/shared/gw_session/selectors.py` 중앙화 |
| **Track 분리** | 단일 진행 | **Track A(GW 파악) / Track B(분리) 병렬** |
| **Phase 수** | 8 (P0~P5 + 신규 5) | **11 (P0~P10) + 트랙 인터페이스** |

---

## 1. 비전

### 1-1. 한 줄 요약

> 글로우서울 사내 자동화 도구 → **다회사 ERP SaaS 토대**로 확장 가능한 아키텍처.

### 1-2. 윤비서(YunSec) 패러다임 (v3 흡수)

| 키워드 | 적용 방식 |
|---|---|
| **Zero-cost ERP** | 윤자동의 자체 ERP 사례 → 본 프로젝트도 SaaS 의존 최소 |
| **AI-Native** | 챗봇(Gemini) + Claude Code Sidecar 듀얼 브레인 |
| **데이터 중앙집중 = 컨텍스트** | 단일 DB에 CRM/매출/회의록/일정/할일 통합 |
| **기억 의존 금지** | 자동 일일 리포트 + 팔로우업 봇 |
| **2계층 UX** | Web ERP UI (정확) + 메신저 봇 (자연어) |
| **모듈식 즉석 생성** | Claude Code로 메뉴 30초 추가 |

---

## 2. 현재 상태 인벤토리 (v1에서 측정)

| 영역 | LOC | 모듈 | DB |
|---|---|---|---|
| A. Project Management | ~14.8k | fund_table(17), contracts(3) | fund_management.db |
| B. GW Automation | ~24.9k | approval(18), chatbot(13), auth(6), mail(2), meeting(2), vision(7) | (GW 원격) |
| C. Shared (현재) | ~5k | auth, app.py, notion | users.db, chat_history.db |
| **총** | **~39.8k** | **71 파일** | **3 DB** |

### 의존성 (v1 발견)
- A → C (auth): fund_table/base_crawler가 GW 로그인 사용
- C → A: chatbot/handlers.py 16곳에서 fund_table import
- A ↔ B: **직접 의존성 없음** (분리 용이)

---

## 3. 목표 아키텍처 — 6 Layer

```
┌─────────────────────────────────────────────────────────────┐
│ L1. Frontends (2계층 UX)                                     │
│  Web: /pm /chat /admin   |   Messenger: 카톡 슬랙 텔레그램    │
├─────────────────────────────────────────────────────────────┤
│ L2. Dual-Brain AI Layer                                     │
│  ┌─ Tool-Use Agent (Gemini)─┐  ┌─ Claude Code Sidecar ───┐  │
│  │  정밀 도구 호출 22+개     │  │  장문/전략/페어 컨설팅   │  │
│  └──────────────────────────┘  └──────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│ L3. Domain Modules                                          │
│  ┌─ A. Project Mgmt ──┐ ┌─ B. GW Automation ┐ ┌─ C. Office Ops ┐│
│  │ • fund_table       │ │ • approval 9종     │ │ • CRM/명함OCR  ││
│  │ • contracts        │ │ • attendance       │ │ • 회의록/Plaud ││
│  │ • CPM schedule     │ │ • mail/meeting     │ │ • 세금/홈택스   ││
│  │ • estimate         │ │ • vision(CU)       │ │ • 매출/입금캡처 ││
│  └────────────────────┘ └────────────────────┘ └───────────────┘│
├─────────────────────────────────────────────────────────────┤
│ L4. Automation Engine (★ 윤비서식)                           │
│  Scheduler(아침7시·저녁6시) | Follow-up Bot | Inbox Classifier│
│  Push Capture(은행알림→DB) | Workflow Engine(Make 스타일)    │
├─────────────────────────────────────────────────────────────┤
│ L5. Integration Adapters (★ GW Adapter Interface)            │
│  IGroupwareProvider ─┬─ DouzoneAmaranth10Provider (현재)     │
│                      ├─ YoungrimwonProvider (향후)            │
│                      └─ EcountProvider (향후)                 │
│  Google(Drive·Cal·Gmail·Contacts) | 홈택스 | Plaud | 아임웹  │
├─────────────────────────────────────────────────────────────┤
│ L6. Shared Infra                                            │
│  Tenant/RBAC | Audit Log | ROI Metric | Masking Mode        │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. ★ GW Adapter Interface 설계

### 4-1. 핵심 추상화 (`src/shared/gw_session/interface.py`)

```python
from typing import Protocol, Literal
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Module:
    home_code: str         # 'SET', 'HR', 'EA', ...
    internal_code: str     # 'UJ', 'HP', 'UB', ...
    label: str             # '시스템설정', '임직원업무관리', ...

@dataclass
class GWPage:
    key: str               # '예실대비현황_상세'
    url_path: str          # '/#/BN/NCC0630/NCC0630'
    module_code: str       # 'BN'
    has_grid: bool
    has_export: bool

@dataclass
class ExportResult:
    path: Path
    sheet_count: int
    row_count: int
    columns: list[str]

class IGroupwareProvider(Protocol):
    # 세션 라이프사이클
    def login(self, user_id: str, password: str) -> "GWSession": ...
    def restore_session(self, user_id: str) -> "GWSession | None": ...

    # 메뉴 탐색
    def list_modules(self) -> list[Module]: ...
    def list_pages(self, module_code: str) -> list[GWPage]: ...
    def navigate_to(self, page_key: str) -> bool: ...

    # 데이터 추출
    def export_xlsx(self, page_key: str, filters: dict | None = None) -> ExportResult: ...
    def read_grid(self, page_key: str, filters: dict | None = None) -> list[dict]: ...

    # 결재
    def submit_approval(self, form_type: str, data: dict, mode: Literal["draft","submit"]) -> dict: ...

    # 근태 / HR
    def get_attendance_summary(self) -> dict: ...
    def request_leave(self, leave_type: str, start: str, end: str, reason: str) -> dict: ...

    # 자원/일정
    def list_reservations(self, range_days: int = 7) -> list[dict]: ...
    def reserve_meeting_room(self, room_code: str, start: str, end: str, title: str) -> dict: ...

class DouzoneAmaranth10Provider(IGroupwareProvider):
    """현재 구현 — Playwright + Computer Use 폴백"""
    ...

class YoungrimwonProvider(IGroupwareProvider):
    """향후 — 영림원 K-System 어댑터"""
    ...
```

### 4-2. 셀렉터 자산 (`src/shared/gw_session/selectors.py`)

```python
# Track A가 발견하는 대로 append-only로 추가됨

# 핵심 셀렉터
EXCEL_DOWNLOAD = "button:has(img[src*='cel_save'])"
HOME_MODULE_LINK = "span.module-link.{code}"
OBT_DATA_GRID = "[class*='OBTDataGrid'], [class*='RealGrid']"
HAMBURGER_COORDS = (82, 22)

# 12 모듈 매핑 (v4 인벤토리)
GW_MODULES: dict[str, Module] = {
    "SET": Module("SET", "UJ", "시스템설정"),
    "HR":  Module("HR",  "HP", "임직원업무관리"),
    "EA":  Module("EA",  "UB", "전자결재"),
    "ML":  Module("ML",  "UD", "메일"),
    "CL":  Module("CL",  "UE", "일정"),
    "RM":  Module("RM",  "UK", "자원"),
    "BD":  Module("BD",  "UG?", "게시판"),
    "KS":  Module("KS",  "?",   "업무관리"),
    "OF":  Module("OF",  "UO?", "ONEFFICE"),
    "OC":  Module("OC",  "UQ?", "ONECHAMBER"),
    "BPM": Module("BPM", "?",   "프로세스관리"),
    "UT":  Module("UT",  "ext", "오피스케어"),
}

# 22 페이지 URL 카탈로그 (Track A에서 확장)
GW_PAGES: dict[str, GWPage] = {
    "근태신청현황":        GWPage("근태신청현황",        "/#/HP/HPD0122/HRD0220", "HP", True, False),
    "지출결의이체현황":     GWPage("지출결의이체현황",     "/#/HP/APB1020/APB1020", "HP", True, False),
    "실행예산신청":        GWPage("실행예산신청",        "/#/BN/NCB0020/NCB0020", "BN", True, False),
    "프로젝트등록":        GWPage("프로젝트등록",        "/#/BN/NCF0090/SYB0060", "BN", True, False),
    "예실대비현황_상세":    GWPage("예실대비현황_상세",    "/#/BN/NCC0630/NCC0630", "BN", True, False),
    "예실대비현황_사업별":  GWPage("예실대비현황_사업별",  "/#/BN/NCC0631/NCC0631", "BN", True, False),
    "자원예약":           GWPage("자원예약",           "/#/UK/UKA/UKA0000",     "UK", True, True),
    "일정":              GWPage("일정",              "/#/UE/UEA/UEA0000",     "UE", True, True),
    # ... Track A에서 발견 시 추가
}

# 페이지별 조회 버튼 셀렉터 (Track A에서 시연으로 매핑)
INQUIRY_BUTTONS: dict[str, str] = {
    # "예실대비현황_상세": "button.OBTButton_typedefault:has-text('조회')",
    # Track A 작업으로 채워짐
}

# 다운로드 옵션 모달 dismiss 패턴
DOWNLOAD_MODAL_BUTTONS = ["확인", "다운로드", "OK", "전체"]
```

### 4-3. 사용 예시 (분리 후 호출 코드)

```python
# Before (현재):
from src.fund_table.base_crawler import login_and_get_page
page = login_and_get_page("tgjeon")
page.goto("https://gw.glowseoul.co.kr/#/BN/NCC0630/NCC0630")
# ... 페이지별 노가다 ...

# After (v4):
from src.shared.gw_session import get_provider
gw = get_provider().restore_session("tgjeon")
result = gw.export_xlsx("예실대비현황_상세", filters={"project": "GS-25-0088"})
print(f"저장: {result.path} ({result.row_count}행)")
```

---

## 5. 새 패키지 구조

```
src/
├── shared/                      ← 신규 C 레이어
│   ├── auth/                    ← 현 src/auth/
│   ├── gw_session/              ← 신규 ★
│   │   ├── interface.py         ← IGroupwareProvider Protocol
│   │   ├── selectors.py         ← 중앙 셀렉터 자산
│   │   ├── douzone.py           ← Amaranth10 구현
│   │   └── __init__.py          ← get_provider() 팩토리
│   ├── notion/                  ← 현 src/notion/
│   ├── telegram_bot.py
│   └── db_common.py
│
├── pm/                          ← 신규 A 네임스페이스
│   ├── fund_table/              ← 현 src/fund_table/ 이동
│   ├── contracts/               ← 현 src/contracts/ 이동
│   ├── schedule/                ← schedule_generator/export 분리
│   ├── estimate/                ← estimate_parser 분리
│   ├── routes.py                ← /api/pm/* 라우터
│   └── static/                  ← fund.html/js/css
│
├── gw/                          ← 신규 B 네임스페이스
│   ├── approval/                ← 현 src/approval/ (9양식)
│   ├── attendance/              ← 연차/외근/연장근무
│   ├── mail/                    ← 현 src/mail/
│   ├── meeting/                 ← 현 src/meeting/
│   ├── vision/                  ← Computer Use 폴백
│   ├── routes.py                ← /api/gw/* 라우터
│   └── static/                  ← 챗봇 UI
│
├── office/                      ← 신규 윤비서 스타일 (P6~P10)
│   ├── crm/                     ← 명함 OCR + Google Contacts
│   ├── meeting_notes/           ← Plaud 회의록
│   ├── tax_invoice/             ← 홈택스
│   ├── deposit_capture/         ← 은행 푸시
│   └── daily_report/            ← 아침/저녁 봇
│
└── chatbot/                     ← C 레이어 (도구 dispatch)
    ├── agent.py
    ├── handlers/
    │   ├── pm_handlers.py       ← 7 도구
    │   ├── gw_handlers.py       ← 11 도구
    │   └── shared_handlers.py   ← 4 공통
    └── tools_schema/
```

---

## 6. 22 도구 재분류 (v3 정리분 그대로)

| 그룹 | 도구 |
|---|---|
| **PM (7)** | get_fund_summary, update_project_info, add_project_note, add_project_subcontract, add_project_todo, get_project_detail, add_project_contact |
| **GW (11)** | reserve_meeting_room, check_available_rooms, cancel_meeting_reservation, list_my_reservations, cleanup_test_reservations, submit_expense_approval, submit_approval_form, submit_draft_approval, start_approval_wizard, get_mail_summary, transcribe_audio |
| **공통 (4)** | search_project_code, start_contract_wizard, generate_contracts_from_file, check_reservation_status |

---

## 7. Phase 0~10 실행 계획

### Phase 0 — 분리 계획 v4 문서화 ✅ (이 문서)

### Phase 1 — `shared/auth/` + `shared/gw_session/` 추출 (1~2일)
- [ ] `src/auth/` → `src/shared/auth/` 이동
- [ ] `IGroupwareProvider` Protocol 정의 (`interface.py`)
- [ ] 셀렉터 상수 추출 (`selectors.py`)
- [ ] 기존 `base_crawler.py`의 GW 로그인 부분 → `DouzoneAmaranth10Provider`로 이식
- [ ] import 경로 일괄 치환 + pytest 145/145 PASS 확인

### Phase 2 — `chatbot/handlers.py` 3분할 (1일)
- [ ] `pm_handlers.py` (7개) / `gw_handlers.py` (11개) / `shared_handlers.py` (4개)
- [ ] `tools_schema.py` 분할

### Phase 3 — `pm/`, `gw/` 네임스페이스 이동 (2~3일)
- [ ] `src/fund_table/` → `src/pm/fund_table/`
- [ ] `src/contracts/` → `src/pm/contracts/`
- [ ] `src/approval/` → `src/gw/approval/`
- [ ] `src/mail/`, `src/meeting/`, `src/vision/` → `src/gw/`
- [ ] import 경로 일괄 치환 + pytest PASS 확인

### Phase 4 — FastAPI 라우터 분리 (1일)
- [ ] `/api/fund/*` → `/api/pm/*` 마이그레이션 + alias 유지
- [ ] `/api/gw/*` 신규 prefix
- [ ] 정적 파일 경로 `/pm/static`, `/gw/static`

### Phase 5 — 정적 UI 분리 (1일)
- [ ] `fund.html/js/css` → `src/pm/static/`
- [ ] 챗봇 UI → `src/gw/static/`

### ★ 체크포인트 — 분리 코어 완료 (이 시점에 commit + tag `v4-core-split`)

### Phase 6 — CRM 모듈 신규 (3~5일, 윤비서 스타일)
- [ ] `src/office/crm/` 신설
- [ ] 명함 사진 → Gemini Vision OCR → 구조화 데이터
- [ ] Google Contacts API 동기화
- [ ] 사업자등록증 PDF 파싱

### Phase 7 — 회의록 파이프라인 (3일)
- [ ] `src/office/meeting_notes/`
- [ ] Plaud → Zapier 웹훅 수신 endpoint
- [ ] 프로젝트 자동 연결 (제목/참여자 키워드 매칭)

### Phase 8 — 홈택스 세금계산서 (2~3일)
- [ ] `src/office/tax_invoice/`
- [ ] 매출 → 홈택스 API 자동 발행
- [ ] 거래처 정보 자동 채움

### Phase 9 — 입금 푸시 캡처 (2~3일)
- [ ] `src/office/deposit_capture/`
- [ ] 안드로이드 NotificationListener 앱 (또는 SMS 파싱)
- [ ] 매출/매입 자동 매칭

### Phase 10 — 자동 일일 리포트 (2일)
- [ ] `src/office/daily_report/`
- [ ] 아침 7시: 오늘의 일정 + 우선순위 알림
- [ ] 저녁 6시: GitHub commits + 매출 + 미팅 요약

---

## 8. Track A ↔ Track B 인터페이스 명세

### 8-1. 단방향 데이터 흐름
```
Track A (그룹웨어 계속 파악)
   │  data/gw_selectors_v2.json (append)
   │  data/gw_pages_index.json (append)
   ▼
src/shared/gw_session/selectors.py (Track B가 import)
```

### 8-2. 파일 소유권
- **Track A 전용 쓰기**: `data/gw_*.json`, `docs/GW_SELECTORS_GUIDE.md`, `docs/GW_EXPORT_PLAYBOOK.md`
- **Track B 전용 쓰기**: `src/*`, `docs/ARCHITECTURE_v4.md`, `docs/SEPARATION_PLAN_v4.md`
- **공유 쓰기**: `docs/GW_AUTOMATION_INVENTORY.md` (인벤토리 누적, append-only)
- **공유 import**: `src/shared/gw_session/selectors.py` (Track A 발견 → Track B read)

### 8-3. 동기화 의식 (주 1회)
- Track A: 새 셀렉터 발견 시 selectors.py 업데이트 + PR
- Track B: selectors.py 변경 시 영향 받는 메서드 회귀 테스트

---

## 9. 테스트 전략

| 단계 | 회귀 기준 |
|---|---|
| Phase 1~5 | **기존 pytest 198/198 PASS 유지** (현재 main 브랜치 기준) |
| Phase 6~10 | 신규 모듈 단위 테스트 + 통합 테스트 |
| 모든 Phase | `src/shared/gw_session/` 변경 시 GW 통합 테스트 (test_gw_validation.py 등) |

### 신규 테스트 추가
- `tests/unit/test_gw_provider.py` — IGroupwareProvider 인터페이스 모킹
- `tests/integration/test_pm_routes.py` — /api/pm/* 라우터
- `tests/integration/test_gw_routes.py` — /api/gw/* 라우터

---

## 10. 마이그레이션 리스크 + 완화

| 리스크 | 완화 |
|---|---|
| import 경로 일괄 치환 시 누락 | `grep -r "from src.fund_table"` 후 점검 + CI |
| `base_crawler.py`의 GW 로그인 추출 시 회귀 | DouzoneAmaranth10Provider 단위 테스트 먼저 |
| 챗봇 22 도구 dispatch 변경 시 누락 | `tools_schema` 통합 테스트 |
| 정적 파일 경로 변경 시 fetch URL 깨짐 | fund.js 내부 fetch URL grep + 일괄 치환 |
| 같은 commit에 너무 많은 변경 | Phase 단위 commit + tag |

---

## 11. 다음 액션

### 즉시 (Track B P1 시작)
1. `git checkout -b feature/v4-shared-extract`
2. `mkdir -p src/shared/{auth,gw_session,notion}`
3. `src/auth/` → `src/shared/auth/` 이동 + import 치환
4. `src/shared/gw_session/interface.py` 신규 작성 (위 4-1 코드)
5. `src/shared/gw_session/selectors.py` 신규 작성 (위 4-2 코드)
6. `pytest` PASS 확인 → commit "P1: shared/auth + gw_session 추출"

### 동시 (Track A 시작)
1. 사용자께서 GW 한 페이지(예: 예실대비현황) 클릭 시퀀스 시연
2. 영상/스크린샷으로 조회 버튼 + 엑셀 다운 옵션 모달 셀렉터 추출
3. `src/shared/gw_session/selectors.py`의 `INQUIRY_BUTTONS`에 추가
4. 자동화 1페이지 성공 → 패턴 다음 페이지로 확장

---

## 12. 결정 사항 기록

| 결정 | 내용 | 근거 |
|---|---|---|
| 단일 리포 모노레포 유지 | 별도 리포 분리 안 함 | 사용자 v1 답변 "문서/계획만 정리" |
| GW Adapter Interface 도입 | 더존 외 영림원/이카운트 갈아끼우기 | v3 윤비서 ERP SaaS 컨셉 |
| Track A·B 병렬 진행 | 의존성 분리로 안전 | 사용자 v4 답변 "병렬 진행" |
| P0 우선 | v4 문서로 아키텍처 프레임 확정 | 사용자 v4 답변 "B 트랙 P0 먼저" |

---

## 참고 문서

- [GW_AUTOMATION_INVENTORY.md](GW_AUTOMATION_INVENTORY.md) — GW 모듈/페이지 인벤토리
- [PROJECT_STATUS.md](PROJECT_STATUS.md) — 현재 Task 진행률
- [SESSION_LI.md](SESSION_LI.md) — expense.py 분할 (P3 선행 작업)
