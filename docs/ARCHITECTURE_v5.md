# 아키텍처 v5 — PM 프론트엔드 분리 + 고도화 (이중 서버 / React+Vite+TanStack+shadcn)

> 작성일: 2026-05-28
> 선행: [ARCHITECTURE_v4.md](ARCHITECTURE_v4.md) — 백엔드 도메인 분리 (P1~P8 완료, master HEAD 58cbb93)
> 연계: [HANDOFF_v5_kickoff.md](HANDOFF_v5_kickoff.md), [NEXT_SESSION_PROMPT_v5.md](NEXT_SESSION_PROMPT_v5.md)
> 범위: **PM 트랙만**. GW(approval/mail/meeting/vision)와 Office(CRM/세금계산서)는 v5 범위 밖 (그대로 FastAPI 직접 호출)

---

## 0. 변경 요약 (v4 → v5)

| 변경 | v4 | v5 |
|---|---|---|
| **프론트 구조** | FastAPI 정적 서빙 (`src/pm/static/fund.{html,js,css}` 12,396줄 단일 파일) | **별도 Vite 서버 (이중 서버) + React 18 SPA** |
| **UI 스택** | Vanilla JS + 자체 CSS 5,005줄 | **TypeScript + shadcn/ui + Tailwind + TanStack Router/Query** |
| **데이터 페칭** | 80개 fetch() 직접 호출 | **TanStack Query queryKey 일원화 + invalidation** |
| **라우팅** | data-tab 토글 (9 탭, URL 미반영) | **TanStack Router (file-based, deep-link)** |
| **타입 안전성** | 없음 (런타임 KeyError 빈발) | **OpenAPI → TypeScript 자동 생성** |
| **고도화** | 단일 페이지 안에 신규 기능 추가 | **3 트랙(A 대시보드·아카이브 / B 간트·칸반 / C 파이프라인·알림)** |
| **마이그레이션** | Big-Bang 위험 | **Strangler Fig — `/fund-v2/*` 병행 운영, 탭 단위 점진 이관** |

**범위 외 (v5 비대상)**:
- 백엔드 FastAPI는 **그대로** (포트 51749, 라우터 prefix, JWT 쿠키 모두 유지)
- 챗봇 UI (`/chat`), 관리자 UI (`/admin`), GW 페이지는 기존 vanilla 유지
- 운영 배포 (Docker/nginx)는 별도 Phase

---

## 1. 이중 서버 구조 (개념도)

### 1-1. 개발 모드 (Dev)

```
┌──────────────────────┐         ┌──────────────────────────┐
│  Browser :5173       │ ──fetch─▶ Vite Dev Server :5173    │
│  React App (HMR)     │         │  /api/* → proxy ─────────┼─┐
└──────────────────────┘         └──────────────────────────┘ │
                                                              ▼
                                              ┌──────────────────────────┐
                                              │  FastAPI :51749          │
                                              │  • /api/pm/*  (83 ep)    │
                                              │  • /api/fund/* (alias)   │
                                              │  • /api/auth/*           │
                                              │  • /api/chatbot/*        │
                                              │  • /fund (legacy SSR)    │
                                              │  • /chat /admin (vanilla)│
                                              └──────────────────────────┘
                                                          │
                                                          ▼
                                              ┌──────────────────────────┐
                                              │ data/fund_management.db  │
                                              │ data/users.db            │
                                              └──────────────────────────┘
```

- Vite `server.proxy['/api']` → `http://localhost:51749` 로 모든 API 위임
- **same-origin** 효과 → 쿠키/JWT 그대로 작동, CORS 설정 불필요
- HMR(React Fast Refresh), TS 타입 체크 별도 worker

### 1-2. 운영 모드 (Prod) — 두 옵션

#### 옵션 A: FastAPI가 dist/ 정적 서빙 (★ 권장 시작)
```
Browser ──▶ FastAPI :51749 ──┬─ /pm-v2/*   → frontend/dist/index.html (SPA fallback)
                              ├─ /assets/*  → frontend/dist/assets/*
                              ├─ /api/*     → 기존 라우터
                              └─ /fund      → 기존 vanilla (병행)
```
- 장점: 단일 프로세스, same-origin 자동, 배포 단순 (`vite build && systemctl restart`)
- 구현: `app.mount("/pm-v2", StaticFiles(directory="frontend/dist", html=True))` + SPA fallback

#### 옵션 B: nginx 리버스 프록시 (트래픽 증가/CDN 시)
```
Browser ──▶ nginx :80/:443 ──┬─ /pm-v2/*  → frontend/dist (직접)
                              ├─ /api/*    → http://localhost:51749
                              └─ /         → frontend/dist (fallback)
```
- 장점: 정적 자산 캐시·압축·CDN, TLS 종단, 다중 워커 분리
- 단점: 배포 단계 +1

**결정**: v5.1~v5.N 동안은 **옵션 A** 로 진행. 사용자 수 증가 시 옵션 B로 마이그레이션.

---

## 2. 폴더 구조

### 2-1. 채택: 리포 루트 `frontend/`

```
자동화 work/
├── src/                          ← 백엔드 그대로
│   ├── shared/ pm/ gw/ office/ chatbot/
│   └── pm/static/                ← 레거시 fund.html/js/css (v5.N에서 삭제)
├── frontend/                     ← ★ v5 신규
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── components.json           (shadcn 설정)
│   ├── index.html
│   ├── public/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── routes/               ← TanStack Router file-based
│   │   │   ├── __root.tsx
│   │   │   ├── index.tsx                  (/) → 대시보드
│   │   │   ├── overview.tsx
│   │   │   ├── vendors.tsx
│   │   │   ├── contracts.tsx
│   │   │   ├── payments.tsx
│   │   │   ├── collections.tsx
│   │   │   ├── schedule.tsx
│   │   │   ├── risks.tsx
│   │   │   ├── budget-payment.tsx
│   │   │   └── projects.$projectId.tsx    (/projects/:id deep link)
│   │   ├── features/             ← 도메인별 hooks + UI 묶음
│   │   │   ├── projects/         (api.ts, hooks.ts, ProjectList.tsx, ProjectCard.tsx)
│   │   │   ├── dashboard/        (KPIWidget, PortfolioChart)
│   │   │   ├── schedule/         (GanttChart, MilestoneTable)
│   │   │   ├── kanban/           (KanbanBoard, TodoCard)
│   │   │   ├── contracts/
│   │   │   ├── collections/
│   │   │   ├── payments/
│   │   │   ├── notifications/    (NotificationInbox, DigestPanel)
│   │   │   └── insights/         (AIInsightCard)
│   │   ├── components/
│   │   │   ├── ui/               ← shadcn 컴포넌트 (Button/Dialog/Table...)
│   │   │   ├── layout/           (AppShell, Sidebar, Topbar)
│   │   │   └── charts/           (래퍼: BarChart, LineChart, Sankey)
│   │   ├── lib/
│   │   │   ├── api-client.ts     (fetch 래퍼 + JWT 쿠키 same-origin)
│   │   │   ├── query-client.ts   (TanStack QueryClient)
│   │   │   ├── query-keys.ts     ★ queryKey 명명 규칙 단일 소스
│   │   │   ├── api-types.ts      (openapi-typescript 자동 생성)
│   │   │   └── utils.ts          (cn(), 날짜 포맷, 통화 포맷)
│   │   ├── hooks/                (전역 공용: useAuth, useToast)
│   │   └── styles/
│   │       └── globals.css       (Tailwind directives + CSS vars)
│   └── dist/                     ← Vite build 산출물 (gitignored)
└── docs/
```

**대안 검토**:
- `apps/pm-web/` (Turborepo monorepo) → 향후 `apps/admin-web/` 분리 시 채택. v5 시점에선 과합.
- `src/pm/web/` → Python 패키지와 섞이는 혼란. 비추.

---

## 3. 빌드 파이프라인

```bash
# 개발
cd frontend && pnpm dev                    # Vite :5173 (proxy :51749)
.venv/bin/python run_chatbot.py            # FastAPI :51749 (별도 터미널)

# 프로덕션 빌드
cd frontend && pnpm build                  # → frontend/dist/
# FastAPI 재시작 → /pm-v2 가 dist/ 서빙

# 타입 생성 (스키마 변경 시)
pnpm gen:types                             # openapi-typescript → src/lib/api-types.ts
```

`package.json` 스크립트:
```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "gen:types": "openapi-typescript http://localhost:51749/openapi.json -o src/lib/api-types.ts",
    "lint": "eslint . --max-warnings 0",
    "test": "vitest"
  }
}
```

`vite.config.ts` 핵심:
```ts
export default defineConfig({
  plugins: [react(), TanStackRouterVite()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:51749" },
  },
  base: "/pm-v2/",      // 운영 시 prefix
  build: { outDir: "dist", sourcemap: true },
})
```

---

## 4. 인증 흐름

### 4-1. 결정: **same-origin JWT 쿠키 유지** (CORS 회피)

기존 백엔드는 `set_cookie("access_token", ..., httponly=True, samesite="lax")`.
이중 서버라도 Vite proxy로 same-origin 효과 → 쿠키 그대로 전송.

### 4-2. 흐름

```
[1] /pm-v2 진입 → React 부팅
[2] useAuth 훅: GET /api/auth/me  (쿠키 자동 첨부)
     ├─ 200 → 사용자 정보 query cache 저장
     └─ 401 → window.location = '/login'  (기존 vanilla 로그인 페이지 재사용)
[3] 모든 fetch는 lib/api-client.ts 경유 → credentials: 'include'
[4] 401 응답 감지 시 → query cache clear + redirect /login
```

### 4-3. 보호 라우트

`__root.tsx`의 `beforeLoad`에서 `auth.me` query를 강제 호출 → 미인증이면 `throw redirect({ to: '/login' })`. 페이지마다 가드 코드 중복 없음.

### 4-4. CSRF

기존 FastAPI에 CSRF 미구현. same-origin 유지하면 SameSite=Lax가 1차 방어선. v5.N에서 mutating 요청에 X-CSRF-Token 도입 가능.

---

## 5. 9 탭 → TanStack Router 매핑

| 기존 탭 (data-tab) | 라우트 | 컴포넌트 | 주요 API (queryKey 접두) |
|---|---|---|---|
| dashboard (기본) | `/` | `features/dashboard/Page` | `['portfolio']`, `['notifications']`, `['insights']` |
| overview | `/overview` | `features/projects/OverviewPage` | `['projects','list']`, `['projects',id,'overview']` |
| schedule | `/schedule` | `features/schedule/Page` | `['milestones']`, `['schedule-items']` |
| collections | `/collections` | `features/collections/Page` | `['collections']` |
| budget-payment | `/budget-payment` | `features/payments/BudgetPage` | `['budget-actual']` |
| vendors | `/vendors` | `features/vendors/Page` | `['subcontracts']`, `['trades']` |
| payments | `/payments` | `features/payments/Page` | `['payment-history']` |
| contracts | `/contracts` | `features/contracts/Page` | `['contracts']` |
| risks | `/risks` | `features/risks/Page` | `['risks']` |
| (신규) project detail | `/projects/$projectId` | `features/projects/Detail` | `['projects',id,*]` |
| (신규) 알림 인박스 | `/inbox` | `features/notifications/Page` | `['notifications']` |
| (신규) 칸반 | `/kanban` | `features/kanban/Page` | `['todos']` |

**URL deep-link 효과**: 프로젝트 카드 → `/projects/123` → 즉시 해당 프로젝트 상세 + 탭 상태 유지. 챗봇이 링크 생성도 가능.

---

## 6. TanStack Query queryKey 명명 규칙

### 6-1. 원칙
- **계층형 튜플**: `[domain, scope?, id?, sub-resource?, params?]`
- **단일 소스**: `lib/query-keys.ts`에서 팩토리 함수로만 생성 (오타·키 불일치 방지)
- **invalidation은 prefix 기반**: `queryClient.invalidateQueries({ queryKey: ['projects'] })` → 모든 project 관련 cache 무효화

### 6-2. 팩토리 패턴

```ts
// src/lib/query-keys.ts
export const queryKeys = {
  projects: {
    all: ['projects'] as const,
    list: (filters?: ProjectFilters) => ['projects', 'list', filters ?? {}] as const,
    detail: (id: number) => ['projects', id] as const,
    overview: (id: number) => ['projects', id, 'overview'] as const,
    members: (id: number) => ['projects', id, 'members'] as const,
  },
  milestones: {
    all: ['milestones'] as const,
    byProject: (pid: number) => ['milestones', 'project', pid] as const,
  },
  todos: {
    all: ['todos'] as const,
    byProject: (pid: number) => ['todos', 'project', pid] as const,
    byStatus: (s: TodoStatus) => ['todos', 'status', s] as const,
  },
  notifications: {
    all: ['notifications'] as const,
    unread: ['notifications', 'unread'] as const,
  },
  contracts: { all: ['contracts'] as const },
  collections: { all: ['collections'] as const },
  payments: { all: ['payments'] as const },
  portfolio: { summary: ['portfolio', 'summary'] as const },
  insights: (pid: number) => ['insights', pid] as const,
  auth: { me: ['auth', 'me'] as const },
} as const;
```

### 6-3. mutation 후 invalidation 표준

```ts
const { mutate } = useMutation({
  mutationFn: (p: NewProject) => api.post('/api/pm/projects', p),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: queryKeys.projects.all });
    qc.invalidateQueries({ queryKey: queryKeys.portfolio.summary });
  },
});
```

### 6-4. Stale time 가이드

| 데이터 | staleTime | 이유 |
|---|---|---|
| 프로젝트 리스트 | 30s | 자주 보지만 변동 적음 |
| 알림 unread count | 10s | 인박스 뱃지 |
| 포트폴리오 KPI | 60s | 무거운 집계 |
| AI 인사이트 | Infinity (수동 refetch) | 비용 큰 LLM 호출 |
| auth.me | 5min | 세션 유효성 |

---

## 7. 컴포넌트 계층 + shadcn/ui 인벤토리

### 7-1. 계층
```
AppShell (Sidebar + Topbar + main outlet)
└── Route Page (features/<domain>/Page.tsx)
    ├── PageHeader (제목, breadcrumb, 액션)
    ├── Toolbar (필터 SearchBox, Select, DateRangePicker)
    └── Content
        ├── DataTable (shadcn Table + TanStack Table)
        ├── Card 그리드
        └── 차트 (recharts wrapped)
```

### 7-2. shadcn/ui 컴포넌트 초기 인벤토리

| 카테고리 | 컴포넌트 | 용도 |
|---|---|---|
| **레이아웃** | `Sheet`, `Tabs`, `Separator`, `ScrollArea`, `Resizable` | 사이드시트, 탭, 분할 패널 |
| **데이터 표시** | `Table`, `Card`, `Badge`, `Avatar`, `Progress`, `Skeleton` | 53 프로젝트 카드/표 |
| **입력** | `Input`, `Textarea`, `Select`, `Combobox`, `DatePicker`, `Checkbox`, `RadioGroup`, `Form` (react-hook-form 연동) | 필터/등록 |
| **피드백** | `Toast` (sonner), `Dialog`, `AlertDialog`, `Tooltip`, `HoverCard` | 알림/확인 |
| **네비** | `Command` (⌘K 팔레트), `DropdownMenu`, `NavigationMenu`, `Breadcrumb` | Quick 검색·메뉴 |
| **고급** | `Calendar`, `Popover`, `ContextMenu`, `Drawer` | 일정/액션 |

### 7-3. 차트 라이브러리
- **recharts** — Bar/Line/Pie/Area (KPI 카드, 월별 매출)
- **간트**: 자체 SVG 컴포넌트 (`features/schedule/GanttChart.tsx`) — frappe-gantt 검토 후 fallback
- **칸반**: `@dnd-kit/core` + 자체 보드 (4 컬럼: backlog/in_progress/blocked/done)

---

## 8. 3개 고도화 트랙 통합 도면

```
┌─────────────────────────────────────────────────────────────────────┐
│                    React App (Vite :5173 / /pm-v2)                  │
│                                                                     │
│  ┌──────────── A. 대시보드+아카이브+추천 ────────────┐               │
│  │ /  /overview                                       │               │
│  │ ├ KPI 위젯 (활성/완료/임대 53건 그룹)             │               │
│  │ ├ 포트폴리오 차트 (월별 매출·예산 408행)          │               │
│  │ ├ 태그/상태 필터 + 검색 (Command 팔레트)          │               │
│  │ └ 추천 카드 (insights 209건, Gemini)              │               │
│  └────────────────┬──────────────────────────────────┘               │
│                   │                                                  │
│  ┌────────────── B. 간트 + 칸반 ───────────────────┐                │
│  │ /schedule  /kanban  /projects/:id              │                │
│  │ ├ GanttChart  ← milestones 783 + schedule 109  │                │
│  │ ├ KanbanBoard ← todos 286 (dnd-kit, 4 컬럼)    │                │
│  │ └ CPM Critical Path 강조 (기존 schedule_*)    │                │
│  └────────────────┬──────────────────────────────────┘             │
│                   │                                                  │
│  ┌── C. 계약→수금→이체 + 알림 다이제스트 ───────────┐                │
│  │ /contracts → /collections → /payments → /inbox  │                │
│  │ ├ Pipeline 보드 (단계별 카드 — Sankey 시각화)   │                │
│  │ ├ 계약 contracts → 수금 collections 168          │                │
│  │ │  → 이체 payment_history 357                     │                │
│  │ ├ NotificationInbox 1556건 (필터·읽음 처리)     │                │
│  │ └ DigestPanel (월요일 자동 요약, /api/pm/digest)│                │
│  └────────────────┬──────────────────────────────────┘             │
│                                                                     │
│           TanStack Query (단일 cache, queryKey 일원화)             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ /api/pm/*  (same-origin via proxy)
                               ▼
       ┌─────────────────────────────────────────────────┐
       │  FastAPI :51749  (기존 라우터 그대로)          │
       │  src/pm/fund_table/routes.py  — 83 endpoint     │
       │  + (v5.N 신규) /api/pm/digest, /api/pm/kanban   │
       └─────────────────────┬───────────────────────────┘
                             ▼
              data/fund_management.db (16 테이블)
```

**트랙별 신규 백엔드 추가 (점진)**
- A: `/api/pm/portfolio/groups` (활성/완료/임대 분류 집계)
- B: `/api/pm/kanban` (todos 컬럼별 그룹화), `/api/pm/gantt/:projectId`
- C: `/api/pm/pipeline/summary`, `/api/pm/digest/weekly`

---

## 9. Phase v5.0 ~ v5.N 로드맵 (점진 / Strangler Fig)

### 원칙
- **기존 `/fund` 페이지는 v5.N까지 유지** — 사용자 작업 중단 없음
- **탭 1개씩 마이그레이션** — 새 탭 완성 → 사용자 검증 → 다음 탭
- 각 Phase 끝에 **PR 1~2개** 머지, pytest 100% 유지

| Phase | 범위 | 산출물 | 예상 |
|---|---|---|---|
| **v5.0** | **본 아키텍처 문서** | `docs/ARCHITECTURE_v5.md` (이 문서) + PR | 0.5세션 |
| **v5.1** | FE 초기 셋업 | `frontend/` 생성, Vite+TS+Tailwind+shadcn 초기화, TanStack Router/Query, api-client, queryKeys, auth.me, AppShell, 빈 9 라우트, Vite proxy 동작, FastAPI `/pm-v2` mount, openapi 타입 생성 | 1세션 |
| **v5.2** | **대시보드 PoC** (트랙 A 일부) | `/` 라우트에서 포트폴리오 KPI + 53건 카드 그리드 + 알림 unread 뱃지. 기존 `/fund#dashboard`와 결과 동등 검증 | 1세션 |
| **v5.3** | Overview + 프로젝트 상세 deep link | `/overview`, `/projects/:id` (개요/멤버/예산 탭). 검색·필터 Command 팔레트 | 1세션 |
| **v5.4** | **간트** (트랙 B-1) | `/schedule` GanttChart + CPM 강조. 마일스톤 CRUD | 1세션 |
| **v5.5** | **칸반** (트랙 B-2) | `/kanban` dnd-kit 보드. todos drag/drop → optimistic update + invalidate | 1세션 |
| **v5.6** | Contracts/Collections/Payments | 트랙 C-1: 3 탭 마이그레이션, Pipeline 보드 초안 | 1.5세션 |
| **v5.7** | **알림 인박스 + 다이제스트** (트랙 C-2) | `/inbox` 1556건 페이지네이션, 필터, 읽음 처리. `/api/pm/digest` 신규 + DigestPanel | 1세션 |
| **v5.8** | Vendors / Risks / Budget-payment | 잔여 3 탭 마이그레이션 | 1세션 |
| **v5.9** | AI 인사이트 + 추천 필터 (트랙 A 완성) | insights 209건 UI, "비슷한 프로젝트" 추천, 아카이브 그룹화 | 1세션 |
| **v5.10** | 레거시 제거 | `src/pm/static/fund.*` 삭제, `/fund` 라우트 → `/pm-v2`로 308 리다이렉트 | 0.5세션 |
| **v5.11** | (옵션) Docker + nginx 운영 배포 | 옵션 B 전환 | 1세션 |

**총 예상**: 약 11세션. v5.2의 PoC 완성 시점에 사용자 시연 → 스타일·UX 피드백 1회 반영.

---

## 10. 기술 부채/리스크 + 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| 5,005줄 fund.css의 디자인 토큰 손실 | UI 회귀 | v5.1에서 색상/간격 토큰을 `tailwind.config.ts`에 추출. fund.css를 참고용으로 보존 |
| 80개 fetch 경로 누락 | API 호출 실패 | openapi-typescript로 전체 엔드포인트 타입화 → 컴파일 시 검출 |
| TanStack Router 학습 곡선 | 진행 지연 | v5.1에 라우트 5개만 만들어 익숙해진 후 확장 |
| 간트/칸반 외부 라이브러리 무게 | 번들 크기 | recharts + dnd-kit + 자체 간트 SVG (frappe-gantt 보류) |
| 챗봇이 fund 페이지 직접 호출 | 마이그 시 단절 | 챗봇은 `/api/pm/*` 백엔드만 호출 → 영향 없음. 다만 챗봇 응답 안에 fund URL 링크가 있다면 v5.10에서 일괄 치환 |
| 백엔드 API breaking change | FE 깨짐 | v5 동안 백엔드 라우터는 **추가형만** (alias 유지). 응답 스키마 변경은 새 endpoint로 분기 |
| Vite proxy/쿠키 SameSite 이슈 | 로그인 실패 | proxy로 same-origin 유지 (CORS 안 씀). Lax 쿠키 동작 검증 v5.1에 포함 |

---

## 11. 다음 액션 (v5.0 머지 후)

1. 이 문서 PR → 사용자 리뷰 → `master` 머지
2. 새 브랜치 `feature/v5-frontend-init` → Phase v5.1 진행
3. v5.1 PR 검증 항목:
   - `cd frontend && pnpm dev` 동작
   - `pnpm build` 성공 + FastAPI가 `/pm-v2`에서 서빙
   - `/api/auth/me` 쿠키 인증 통과 (로그인 후 진입)
   - 빈 9 라우트 URL 직접 진입 시 AppShell 렌더

---

## 부록 A. 백엔드 그대로 vs 일부 추가

v5.0 시점에서 백엔드는 **추가만**, 기존 변경 없음:

| 신규 endpoint (v5.6~v5.9) | 목적 |
|---|---|
| `GET /api/pm/portfolio/groups` | 활성/완료/임대 분류 집계 (트랙 A) |
| `GET /api/pm/gantt/:projectId` | 마일스톤+공정 통합 응답 |
| `GET /api/pm/kanban` | todos 컬럼별 그룹화 |
| `GET /api/pm/pipeline/summary` | 계약→수금→이체 Sankey 데이터 |
| `GET /api/pm/digest/weekly` | 월요일 다이제스트 (notifications + milestones 마감) |

기존 83 endpoint는 `/api/pm/*` + `/api/fund/*` alias 그대로 사용.

---

## 부록 B. 결정 기록 (ADR-style)

- **ADR-v5-001 (이중 서버 채택)**: 단일 서버(FastAPI Jinja 유지)·monorepo·Next.js 풀스택 셋 중 **이중 서버** 채택. 이유: 백엔드 무수정, React Vite의 HMR/타입 생산성, Next.js의 SSR 불필요.
- **ADR-v5-002 (TanStack Router)**: React Router v6 vs TanStack Router 비교 후 후자 채택. 이유: file-based + type-safe params, loader/beforeLoad가 Query와 자연스럽게 통합.
- **ADR-v5-003 (shadcn/ui)**: MUI/Mantine 대신 shadcn. 이유: 코드 복사 방식으로 디자인 자유도 + Tailwind와 일관성 + 번들 슬림.
- **ADR-v5-004 (pnpm)**: npm/yarn 대비 디스크·속도 우위. 다른 도구와 호환 충분.
- **ADR-v5-005 (Strangler Fig)**: Big-Bang 금지. 기존 `/fund` 유지하며 탭 단위 점진. 사용자 작업 무중단이 최우선.

---

**핵심**: 이 문서가 v5.0의 성과물. 다음 세션은 `feature/v5-frontend-init`에서 `frontend/` 디렉토리 생성 + Vite/TS/Tailwind/shadcn/TanStack 초기 셋업.
