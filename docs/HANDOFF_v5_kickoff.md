# 세션 핸드오프 — v5 프론트엔드 분리 + PM 고도화 킥오프

> 작성: 2026-05-27 종료 시점
> 다음 세션 즉시 사용 — 이 문서 + 시작 프롬프트(`docs/NEXT_SESSION_PROMPT_v5.md`)로 컨텍스트 복원

---

## 1. 다음 세션 첫 작업 (한 줄)

**`docs/ARCHITECTURE_v5.md` 작성** — PM 프론트 분리(이중 서버) + React/Vite/TanStack/shadcn 스택 + 3개 고도화 트랙(대시보드/간트칸반/파이프라인) 통합 도면 + Phase 0~N 로드맵.

---

## 2. 사용자가 확정한 결정 사항

| 축 | 결정 | 비고 |
|---|---|---|
| **분리 수준** | **프론트만 분리 (이중 서버 구조)** | 백엔드 FastAPI는 그대로, 프론트는 별도 Vite 서버 + 빌드 산출물 |
| **FE 스택** | **React 18 + Vite + TanStack Router/Query + shadcn/ui + Tailwind + TypeScript** | 직전 메시지에서 사용자 "승인" |
| **고도화 우선순위** | **세 가지 모두 진행** | (1) 대시보드+아카이브+추천 필터 (2) 간트+칸반 (3) 계약/수금/이체 파이프라인 + 알림/다이제스트 |
| **구현 순서** | **v5 아키텍처 문서 먼저** → 그 후 PoC(1탭) → 점진 마이그레이션 | Big-Bang 아님 |
| **분리 트랙** | **PM** 분리·고도화 우선. GW Track A(export 1마일) 병렬 가능 | A 트랙은 사용자 시연 대기 |

### FE 스택 선택 근거 요약
- React + Vite — FastAPI(:51749) ↔ Vite(:5173) 이중 서버 구조에 가장 자연스러움
- TanStack Query — 53 프로젝트 / 357 결제 / 1556 알림 서버 상태 캐시·invalidation 일원화
- TanStack Router — 9개 탭 + 프로젝트별 deep link type-safe
- shadcn/ui — 컴포넌트 코드 복사 방식, 9 탭 + 칸반 + 간트 + 차트에 풍부한 사례
- Tailwind — fund.css 5005줄을 design tokens 기반으로 재구성

---

## 3. v4 완료 상태 (이 세션에서 머지)

### 머지된 PR (4개, 모두 master)
| PR | 작업 | 커밋 |
|---|---|---|
| [#3](https://github.com/choiceyou321-boom/gw-automation/pull/3) | v4 분리 코어 P1~P5 | `9bd4e73` |
| [#4](https://github.com/choiceyou321-boom/gw-automation/pull/4) | P6 CRM + P8 홈택스 + 17 모듈 인벤토리 | `b08270e` |
| [#5](https://github.com/choiceyou321-boom/gw-automation/pull/5) | A+C+D 챗봇 도구 + Google Contacts + Track A | `628363e` |
| [#6](https://github.com/choiceyou321-boom/gw-automation/pull/6) | v4 path 핫픽스 (parent×3 → ×4, 16파일) | `58cbb93` |

### master HEAD
```
58cbb93 Merge pull request #6 (v4 path 핫픽스)
```

### 회귀 안전
- **pytest 424/424 PASS**

### 최종 패키지 구조
```
src/
├── shared/                      ← P1 신규 (공유 인프라)
│   ├── auth/                    (src/auth → 이동, 인증/JWT/세션)
│   └── gw_session/              (IGroupwareProvider Protocol + 17 모듈 카탈로그)
├── pm/                          ← P3 신규 (프로젝트 관리, A 도메인)
│   ├── fund_table/              (db.py + routes.py 83 endpoint + 크롤러 6종)
│   ├── contracts/               (계약서 생성기)
│   └── static/                  (fund.html/css/js — 본 세션 v5 대체 대상)
├── gw/                          ← P3 신규 (그룹웨어 자동화, B 도메인)
│   ├── approval/                (9 양식 + 근태 3종)
│   ├── mail/ meeting/ vision/
├── office/                      ← P6/P8 신규 (윤비서 스타일)
│   ├── crm/                     (명함 OCR + Google Contacts)
│   └── tax_invoice/             (Provider 패턴: Noop/Hometax/Popbill)
└── chatbot/
    ├── handlers/                ← P2 패키지화
    │   ├── _impl.py             (기존 handlers.py 2698줄)
    │   ├── pm.py    (14 도구)
    │   ├── gw.py    (15 도구)
    │   ├── shared.py (5 도구)
    │   └── office.py (5 도구 — CRM/세금계산서)
    ├── app.py                   (라우터 prefix 분리: /api/pm + /api/fund alias)
    └── static/                  (admin/guide/index 공통 UI)
```

### 챗봇 도구 39종 (PM 14 + GW 15 + Shared 5 + Office 5)

---

## 4. 현재 PM 인벤토리 (v5 작업 대상)

### 규모
| 영역 | 라인/건수 |
|---|---|
| **백엔드** | fund_table 9000 LOC / 83 API endpoint / 16 핵심 테이블 |
| **프론트엔드** | fund.html **1445줄** + fund.js **5946줄** + fund.css **5005줄** (단일 파일) |
| **fund.js fetch 호출** | 80 라인 (대부분 /api/fund/* 또는 /api/pm/*) |

### 9개 탭 (data-tab 값)
```
overview      개요
dashboard     대시보드
vendors       하도급상세
contracts     계약
payments      이체내역 (budget-payment 도?)
collections   수금현황
schedule      일정표
risks         리스크
budget-payment (?)
```
+ 별도 AI 인사이트 섹션

### 데이터 모델 (16 테이블, 행수)
| 테이블 | 행수 | 비고 |
|---|---|---|
| **projects** | 53 | GS-YY-XXXX 정규 코드 보유 (정리됨) |
| project_overview | 53 | location/usage/scale/area/일정 등 |
| project_members | 233 | |
| **project_milestones** | 783 | 간트 데이터 원천 |
| **project_todos** | 286 | 칸반 데이터 원천 |
| **project_notifications** | 1,556 | 알림/다이제스트 원천 |
| project_insights | 209 | AI 인사이트 (Gemini) |
| project_schedule_items | 109 | CPM 공정표 |
| contacts | 102 | CRM 통합 대상 |
| subcontracts | 53 | 하도급 |
| trades | 50 / construction_trades 55 | 공종 마스터 |
| collections | 168 | 수금 |
| payment_history | 357 | 이체 |
| budget_actual | 408 | 예산 vs 실행 |
| gw_projects_cache | 204 | GW에서 크롤한 캐시 |
| project_aliases | 73 | 별칭 |

### DB 위치
```
data/fund_management.db                                 (운영, 921KB)
data/fund_management.db.before_restore_20260527_211751  (오늘 안전 백업)
data/fund_management.db.bak_20260326_083842             (3/26, 103건 비정규 포함)
```

### API 경로 (이중 등록, 호환성)
- `/api/pm/*`   — 신규 권장 (v4 P4)
- `/api/fund/*` — 호환 alias

---

## 5. v5 작업 큰 그림 (다음 세션에서 구체화)

### Phase v5.0 — 아키텍처 문서 (★ 첫 작업)
- [ ] `docs/ARCHITECTURE_v5.md` 작성
  - 이중 서버 구조 (FastAPI :51749 ↔ Vite :5173)
  - 빌드 파이프라인 (Vite build → dist/ → FastAPI 정적 서빙 or nginx)
  - 폴더 구조 제안 (`frontend/` or `apps/pm/` or `packages/pm-web/`)
  - 인증 흐름 (쿠키 기반 JWT 유지, CORS 또는 same-origin)
  - 9 탭 → React Router 라우트 매핑
  - 데이터 페칭 계층 (TanStack Query queryKey 명명 규칙)
  - 컴포넌트 계층 (atoms/molecules/templates 또는 features/...)
  - shadcn/ui 컴포넌트 목록 (Table/Dialog/Tabs/Form/Sheet/Toast 등)
  - 3개 고도화 트랙 통합 도면
  - Phase 0~N 마이그레이션 로드맵 (점진)

### Phase v5.1 — 프론트엔드 초기 셋업
- [ ] `frontend/` 디렉토리 + `pnpm create vite` (React + TS)
- [ ] Tailwind + shadcn/ui init
- [ ] TanStack Router + Query 셋업
- [ ] FastAPI 인증 쿠키 fetch 패턴 + API 클라이언트 (`/api/pm/*`)
- [ ] OpenAPI → TypeScript 타입 자동 생성 (openapi-typescript)
- [ ] `vite.config.ts` proxy 설정 (개발: /api → FastAPI:51749)

### Phase v5.2 — 1탭 PoC (대시보드)
- [ ] Dashboard 페이지 React로 구현 (53 프로젝트 KPI, 차트 1~2개)
- [ ] 기존 `/fund` 페이지와 병행 운영 (`/fund-v2/dashboard` 식으로)

### Phase v5.3~v5.N — 나머지 8 탭 점진 마이그레이션 + 고도화

---

## 6. 3개 고도화 트랙 — 데이터 원천 매핑

| 트랙 | 핵심 화면 | DB 원천 |
|---|---|---|
| **A. 대시보드+아카이브+추천** | 포트폴리오 요약, KPI, 53건 그룹화 (활성/완료/임대) + 태그 필터 | `projects`, `project_overview`, `budget_actual` |
| **B. 간트+칸반** | 공정표 그래픽 간트 + 할일 칸반 보드 | `project_milestones(783)`, `project_todos(286)`, `project_schedule_items(109)` |
| **C. 계약→수금→이체 + 알림** | 영업 파이프라인 + 알림 인박스 + 월요일 다이제스트 | `subcontracts`, `collections`, `payment_history`, `project_notifications(1556)` |

---

## 7. 미해결 / 병렬 진행 가능한 작업

### Track A (GW Export 마지막 1마일) — 사용자 시연 대기
- `scripts/track_a_capture.py` 사용
- 5분/페이지 × 5페이지 시연 → `data/track_a_captures.json` 생성 → `selectors.INQUIRY_BUTTONS` 머지
- 우선순위: 예실대비현황(상세) → 지출결의이체현황 → 프로젝트등록 → 근태신청현황

### 향후 옵션 (E~K)
- E: track_a_capture → selectors.py 자동 머지 CLI
- F: PopbillProvider 실 구현 (팝빌 API)
- G: HometaxProvider 실 구현 (공인인증서)
- H: GW 신규 5 모듈(PER/BUDGET/LOG/SAL/PUR) 진입 자동화
- I: 챗봇 UI 명함 업로드 폼 (←v5 작업에 자연스럽게 흡수 가능)
- J: 운영 배포 (Docker + Nginx)
- K: path 같은 종류 잠재 버그 회귀 방지 테스트

---

## 8. 환경/서버 상태

| 항목 | 값 |
|---|---|
| 작업 디렉토리 | `/Users/tg_mac_mini/Documents/자동화 work` |
| Python | `.venv/bin/python` (Python 3.12) |
| FastAPI 서버 | 종료됨. 재기동: `.venv/bin/python run_chatbot.py` → http://localhost:51749 |
| 관리자 계정 | `tgjeon` (DB의 `is_admin=1`) |
| GitHub | `https://github.com/choiceyou321-boom/gw-automation.git` |
| 현재 브랜치 | `master` (모든 v4 PR 머지됨) |
| 권장 다음 브랜치 | `feature/v5-arch-doc` (문서 PR) → `feature/v5-frontend-init` |

### 핵심 환경 변수 (`config/.env`)
- `GW_USER_ID`, `GW_USER_PW` — 그룹웨어 자격
- `ENCRYPTION_KEY` — Fernet 키 (절대 변경 금지)
- `GEMINI_API_KEY` — 챗봇 + 명함 OCR
- `ANTHROPIC_API_KEY` — Computer Use (현재 크레딧 부족)
- `NOTION_API_KEY`, `NOTION_PAGE_ID` — Notion 연동
- `TAX_INVOICE_PROVIDER` (미설정 시 Noop) / `ENABLE_GOOGLE_CONTACTS_SYNC` (미설정 시 Noop)

### v4 핫픽스 메모 (재발 방지)
P1/P3로 폴더가 한 단계 깊어졌을 때 `Path(__file__).parent.parent.parent` 패턴이 깨졌음. 이번에 16개 파일 일괄 패치. **앞으로 폴더 이동 시 PROJECT_ROOT 계산을 함께 점검**.

---

## 9. 다음 세션 시작 프롬프트

별도 파일에 작성: `docs/NEXT_SESSION_PROMPT_v5.md`

요약:
> "이전 세션에서 v4 분리 4개 PR 머지 완료(#3~#6). v5 시작: PM 프론트만 분리 + React+Vite+TanStack+shadcn 승인됨. **`docs/ARCHITECTURE_v5.md` 작성부터 진행하세요.** docs/HANDOFF_v5_kickoff.md 참고."

---

## 10. 검증 명령 (다음 세션 시작 시 sanity check)

```bash
cd "/Users/tg_mac_mini/Documents/자동화 work"

# 1) git 상태
git branch --show-current        # → master
git log --oneline -3             # → 58cbb93 (#6 핫픽스) 최상단

# 2) pytest 회귀
.venv/bin/python -m pytest -q --tb=no   # → 424 passed

# 3) DB 정상
.venv/bin/python -c "from src.pm.fund_table import db; print(len(db.list_projects()))"   # → 53

# 4) 도구 39개 확인
.venv/bin/python -c "
from src.chatbot.handlers import pm, gw, shared, office
print('PM', len(pm.TOOLS), 'GW', len(gw.TOOLS), 'Shared', len(shared.TOOLS), 'Office', len(office.TOOLS))
"   # → PM 14 GW 15 Shared 5 Office 5

# 5) 서버 기동 (필요 시)
.venv/bin/python run_chatbot.py
# → http://localhost:51749 (관리자 계정: tgjeon)
```

---

## 11. 작업 시간 소요 추정 (참고)

| 작업 | 예상 |
|---|---|
| v5 아키텍처 문서 (Phase v5.0) | 1세션 |
| 프론트엔드 초기 셋업 (v5.1) | 0.5세션 |
| 1탭 PoC — 대시보드 (v5.2) | 1세션 |
| 9탭 점진 마이그레이션 | 3~5세션 |
| 3개 고도화 트랙 통합 | 5~8세션 |
| 운영 배포 (Docker/nginx) | 1세션 |

---

핵심: **다음 세션 첫 액션은 `docs/ARCHITECTURE_v5.md` 작성이다.**
