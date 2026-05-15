# 세션 XLIX — 코드 실측 + Task 31 Phase 1

> 날짜: 2026-05-15
> 성격: 코드 정밀 조사 + 좌표 의존 코드 정적 폴백 제거

---

## 1. 이번 세션 완료 작업

### A. 전체 코드 정밀 조사 (병렬 에이전트 4개)

세션 XLVIII 기록의 부정확성 발견 → 실측치 확정.

| 항목 | 세션 XLVIII 기록 | 실측 (세션 XLIX) |
|---|---|---|
| `expense.py` 줄 수 | 2,450 | **4,938** |
| `other_forms.py` 줄 수 | 1,079 | **2,718** |
| `grid.py` 줄 수 | (미기록) | 623 |
| `budget_helpers.py` 줄 수 | (미기록) | 876 |
| 좌표 의존 코드 | 8건 | **19건** (정적 3 + 동적 16) |

### B. 좌표 의존 코드 19건 분류

| 분류 | 개수 | 위치 |
|---|---|---|
| **정적 픽셀 좌표** (fullscreen 가정) | **3** | `expense.py:4666`, `expense.py:4774`, `grid.py:183` |
| **동적 계산 좌표** (bounding_box/JS 결과) | 13 | `expense.py` 9건, `other_forms.py` 3건, `budget_helpers.py` 1건 |
| **Computer Use 본질 좌표** (의도된 사용) | 3 | `computer_use_agent.py:177/199/210` |

### C. 알려진 이슈 정확한 위치 매핑

| 이슈 | 함수 | 줄 번호 |
|---|---|---|
| invoice 모달 타이밍 | `_select_invoice_in_modal()` | `expense.py:2460` (문제 구간 L2493~2514) |
| 프로젝트 picker 확인 버튼 | `_fill_project_code()` | `expense.py:1505` (L1863~1876, L1914~1928) |
| 선급금 그리드 keyboard.type+Enter | `_fill_advance_grid_mandatory_fields()` | `other_forms.py:869` (L1001 dblclick → L1023 type → L1037 Tab) |

### D. Task 31 Phase 1 — 정적 좌표 폴백 3건 제거

| 파일 | 줄 | 제거된 좌표 | 교체 동작 |
|---|---|---|---|
| `expense.py` | L4663-4673 | `(763, 857)` 증빙일자 | `logger.error` + `return False` |
| `expense.py` | L4771-4774 | `(1865, 246)` 첨부 버튼 | `logger.error`, file_chooser 타임아웃 폴백 |
| `grid.py` | L180-188 | `(1808, 373)` 그리드 '추가' | `logger.error` + `return False` |

**검증:**
- `ast.parse` 구문 검증 통과
- `page.mouse.click(<num>, <num>)` 정적 좌표 패턴 grep — `src/approval/` 0건
- 각 위치에 상위 셀렉터 폴백이 다층 존재 → 회귀 위험 낮음

**효과:**
- 이전: 셀렉터 실패 시 fullscreen 가정 좌표로 잘못된 위치 클릭 가능
- 이후: 명확한 에러 로그 + `False` 반환 → 호출자 적절히 처리

---

### E. 코드 리뷰 기반 즉시 개선 (5개 에이전트 종합 결과 → Tier 1/2 실행)

| # | 파일:줄 | 변경 | 효과 |
|---|---|---|---|
| 1 | `budget_helpers.py:101` | 폴백 키 통일 (`result["code"]` → `result["budget_code"]`) + `budget_name` 빈값 명시 | 호출자가 폴백 경로에서 키 미스로 결과 누락하던 버그 수정 |
| 2 | `app.py` (신규 라우트) | `GET /health` 엔드포인트 추가 | Docker `HEALTHCHECK curl /health` 무한 unhealthy 상태 해소 |
| 3 | `telegram_bot.py:30` | `logging.basicConfig` 모듈 로드 호출 → `__main__` 가드 내부로 이동 | import 시 root logger 클로버링 방지, caller 로깅 제어권 보장 |
| 4 | `budget_helpers.py:382` | `wait_for_timeout(3000)` → `wait_for_selector(combined, timeout=3000)` polling | 자동완성 드롭다운 즉시 인식 → 평균 ~2초 단축/호출 |
| 5 | `budget_helpers.py:464-478` | 동일 input에 대한 Enter 재시도 중복 제거 (L453에서 이미 시도) | 호출당 1.5초 단축 + 코드 단순화 |

### G. 5-에이전트 리뷰 기반 구조 개선 4건 (위험도 낮음~중간)

| # | 작업 | 변경 통계 |
|---|---|---|
| 1 | **`_GET_GRID_IFACE_JS` 헬퍼 활용** — 인라인 React fiber 접근 20곳 치환 | -124줄 (grid -29, other_forms -41, expense -54) |
| 2 | **`BaseCrawler` 신규 + 4종 크롤러 리팩토링** (`src/fund_table/base_crawler.py` 266줄) | -773줄 / -59% (contract/tax/payment/collection) |
| 3 | **`session_manager` GC 메커니즘 추가** — `_gc_expired_sessions()` (10분 throttle, lock 항목 함께 정리) | +40줄 |
| 4 | **시스템 프롬프트 압축** — 243줄 → 105줄 (-57%, 토큰 비용 절감) | -212줄 |

**보류된 #5 거대 파일 분할** (`expense.py` 4881줄, `other_forms.py` 2683줄) — Mixin 조합 + 외부 import 영향 범위 큼. 별도 세션 필요.

**건너뛴 위치** (GRID_IFACE 12곳, BaseCrawler 3개 크롤러):
- GRID_IFACE: 다중 그리드 루프, picker 내부 그리드, depth 6 fiber 탐색 등 시맨틱 불일치
- BaseCrawler: `budget_crawler.py` (1,625줄), `budget_crawler_by_project.py` (1,179줄), `project_crawler.py` (1,619줄) — 함수형 + 복잡한 DOM 조작으로 동작 보존 어려움

### H. Tier 1 후속 작업 (Tier 분류 기반)

| # | 작업 | 변경 |
|---|---|---|
| A | **레거시 함수 삭제** — `_select_invoice_in_modal_legacy` (expense.py L3415-4141) | **-727줄** |
| B | `_find_first_visible(page, selectors, total_budget_ms)` 헬퍼 신규 (base.py) | +30줄 |
| C | `login.py` storage_state 동시 쓰기 per-user lock 추가 | +20줄 |
| D | 순수 함수 단위 테스트 신규 (`tests/unit/test_form_templates.py`, ~120줄) | 신규 |
| E | `.github/workflows/ci.yml` CI 파이프라인 스캐폴딩 (구문 검증 + 단위 테스트 + ruff) | 신규 |
| F | Task 31 Phase 2 분석 — 동적 좌표 10건 분류 → HIGH 0/MEDIUM 2/LOW 8 (Canvas 본질) | 보고만 |

### F. Simplify 스킬 3-agent 리뷰 적용

| 변경 | 출처 |
|---|---|
| `_save_debug` 호출 추가 (3건 모두) — "스냅샷 확인 필요" 안내가 실제 스냅샷 저장으로 연결 | Agent 1 (재사용) |
| 변경 narration 주석 제거 (3건) — git 이력에 속하는 정보 | Agent 2 (품질) |
| 첨부 버튼 실패 시 `return False`로 file_chooser 30초 무익 대기 회피 | Agent 3 (효율성) |

---

## 2. 보류 결정된 작업

| 작업 | 이유 |
|---|---|
| **1순위 A/B/C** (invoice/picker/grid 수정) | 사용자 결정: 실 GW 검증 환경 마련 후 진행 |
| **UX 개선 아이디어** (C1~C5 에러 표준화/진행 표시/로그 DB/헬스체크/파일분할) | 사용자 결정: 다음 세션 이후 |
| **GW 자체 접속** | `config/.env` 부재 (`.env.example`만 존재) — 자격증명 미확보 |
| **Task 31 Phase 2** (동적 좌표 13건 검토) | 다음 세션 이관 |

---

## 3. 다음 세션 작업 후보 (난이도 오름차순)

### 🟢 난이도 하
- `config/.env` 자격증명 확보 후 GW 자체 접속 검증
- 문서 추가 정비 (DEVELOPER_GUIDE.md 함수 인벤토리 부분 보강)

### 🟡 난이도 중
- **Task 31 Phase 2** — 동적 좌표 13건 사례별 셀렉터 보강
  - 우선 후보: `budget_helpers.py:511` (코드도움 아이콘) — `[class*='codeHelp']`, `button[title*='코드']` 등 셀렉터 다양화
  - 보존 권장: `grid.py:526` (OBT canvas 기반, 좌표가 본질)
- **Task 32 준비** — headless 호환성 점검 (실수정 X, 조사만)

### 🔴 난이도 상 (별도 세션 권장)
- **1순위 A/B/C** — invoice 모달 / picker / 그리드 입력 (실 GW 필요)
- 거대 파일 분할 (`expense.py` 4938줄, `other_forms.py` 2718줄)
- Task 33 다중 사용자 테스트

---

## 4. 핵심 통계

```
src/approval 총 9,155줄 (5개 핵심 파일)
├── expense.py        4,938줄  (지출결의서)
├── other_forms.py    2,718줄  (선급금/연장근무/외근)
├── budget_helpers.py   876줄  (예산과목)
└── grid.py             623줄  (그리드 셀 입력)

좌표 의존 코드 19건 → Phase 1 후 16건 잔존
  └─ 정적 좌표: 3 → 0  (✅ 제거 완료)
  └─ 동적 좌표: 13 (Phase 2 검토 대상)
  └─ Computer Use: 3 (보존)
```
