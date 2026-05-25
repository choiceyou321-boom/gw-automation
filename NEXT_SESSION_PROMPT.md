# 다음 세션 시작 프롬프트

> 이 파일을 복사해서 Claude Code 새 세션 첫 메시지로 붙여넣기

---

## 붙여넣기용 프롬프트

```
gw-automation 프로젝트 세션 LIII 시작.

📁 프로젝트 경로: D:\TG\gw-automation
📄 직전 세션: docs/SESSION_LII.md (Phase D + other_forms.py 4분할, 병렬 sonnet 2 + Opus 검토)
📄 정비 흐름: docs/SESSION_XLIX.md → L → LI → LII
📄 프로젝트 현황: docs/PROJECT_STATUS.md
📄 개발자 가이드: DEVELOPER_GUIDE.md
   (콜백 주입 + Mixin 분리 trade-off 표 / _safe_handler / _find_first_visible 패턴 등재)

## 환경 정보
- Python 3.13 (윈도우 .venv 사용 — `D:/TG/gw-automation/.venv/Scripts/pytest.exe`)
- gh CLI v2.92.0 인증 완료
- 훅 설정: Stop(pytest 자동 실행), PreToolUse(config/.env 커밋 차단)
- CI: .github/workflows/ci.yml (구문 검증 + 단위 테스트 + ruff)
- git: origin = https://github.com/choiceyou321-boom/gw-automation.git
- 외부 운영: https://unchidingly-hybridizable-maranda.ngrok-free.dev (타 본체 ngrok)

## 누적 정비 성과 (XLIX → L → LI → LII)
- expense.py: 4,938 → 1,446 (-70.7%, Phase A/B/C/D 4회)
- other_forms.py: 2,683 → 541 (-79.8%, mixin 4분할 LII)
- prompts.py: 243 → 105 (-57%)
- 4종 크롤러: 1,315 → 542 (-59%)
- 신규 모듈: invoice_modal / project_picker / expense_fields / attachment / budget_capture
  / advance_payment / overtime / outside_work / recommendation / base_crawler
- 헬퍼: _safe_handler (34 핸들러 wrap) / _find_first_visible / _GET_GRID_IFACE_JS

## 테스트 기준선
- pytest **164/164 PASS** (~0.6초) — origin/master 추적 기준
- 일부 세션 기록의 "193"은 타 본체 로컬 미커밋분(test_gw_validation +11, test_construction_trades +13 등) 포함 수치
- 누락 테스트 29개 복원은 후속 과제

## 이번 세션 후보 작업 (난이도 오름차순)

### 🟢 안전 영역 (테스트/GW 불필요)
1. **expense.py Phase E** — `_create_expense_report_via_popup` (~296줄) → `expense_popup.py`
   - 콜백 주입 패턴 5번째 적용
2. **`_find_first_visible` 추가 적용** — expense.py 잔여 4곳
3. **other_forms.py 추가 슬림화** — `search_project_codes`(115줄) + `_create_proof_issuance_draft`(204줄) → `proof_issuance.py`
   - facade ~200줄로 축소 가능 (over-engineering 주의)

### 🟡 실 GW 검증 필요
1. **선급금 그리드 셀 에디터 활성화** (세션 XLVII 미완)
   - focus() → 내부 INPUT 활성화는 셀 에디터 아님
   - canvas dblclick 패턴 시도 필요
2. **invoice modal dataProvider 정확한 grid 선택** (세션 XXXVI 미완)
   - 현재 expense form grid 읽음 → invoice modal grid 직접 접근 경로 발굴
3. **연장근무/외근** — HR 권한 보유 계정 확보 후 DOM 검증
4. 분할 모듈 회귀 검증 (expense_fields, invoice_modal, project_picker, attachment, budget_capture)
5. GRID_IFACE 치환 회귀 검증 (세션 XLIX 20곳)
6. `_safe_handler` 데코레이터 실제 동작 확인

### 🔴 큰 작업 (전용 세션)
1. **누락 테스트 29개 복원** — 타 본체 브랜치/스태시 확인 → 머지
2. 진행 상황 SSE 스트리밍 (Playwright 1~3분 무응답 해소)
3. 자동화 결과 로그 DB + 모니터링 대시보드
4. ApprovalError 계층 + 사용자 친화 메시지 표준화

## 시작 전 권장
- DEVELOPER_GUIDE.md 섹션 4 "콜백 주입 + Mixin 분리 trade-off" 표 읽기 (분할 패턴 결정 시)
- docs/SESSION_LII.md에서 병렬 에이전트 흐름 + Opus 검토 패턴 참고
```

---

## 빠른 컨텍스트 요약

### 핵심 파일 구조 (LII 종료 시점)

```
src/approval/
├── expense.py          1,446줄  (mixin facade, 시작 4,938)
├── expense_fields.py     771줄  (LII Phase D)
├── invoice_modal.py    1,039줄  (LI Phase B)
├── project_picker.py     812줄  (LI Phase C)
├── attachment.py         136줄  (L Phase A)
├── budget_capture.py     137줄  (L Phase A)
├── other_forms.py        541줄  (LII facade, 시작 2,683)
├── advance_payment.py  1,289줄  (LII)
├── overtime.py           496줄  (LII, _navigate_to_hr_attendance 보유)
├── outside_work.py       367줄  (LII)
├── recommendation.py     134줄  (LII)
├── budget_helpers.py     876줄
├── grid.py               596줄
└── base.py + 공통 헬퍼

src/fund_table/
├── base_crawler.py      266줄   (XLIX)
└── contract/tax/payment/collection_crawler.py  (각 65~73줄, -59%)

src/chatbot/
├── handlers.py        2,698줄  (+_safe_handler, 34 핸들러)
└── prompts.py           105줄  (-57%)
```

### 핵심 기술 패턴 (XLIX → LII 확립)
- **콜백 주입**: 단일 거대 메서드 분할, 의존성 `Callable` 인자로 주입 (Phase A~D)
- **Mixin 분리**: 다중 거대 메서드 분할, MRO로 facade 유지 (LII other_forms)
- **`_safe_handler`**: TOOL_HANDLERS dict comprehension wrap으로 일괄 적용
- **`_find_first_visible`**: 셀렉터 폴백 체인을 polling 헬퍼로 통합
- **OBTDataGrid**: `_GET_GRID_IFACE_JS` 헬퍼 (base.py)
- **OBTDialog2**: `dimClicker` 차단 → JS로 dialog 내부 직접 탐색

### 알려진 이슈 (실 GW 필요)
| 이슈 | 위치 | 증상 |
|---|---|---|
| invoice 모달 dataProvider | `invoice_modal.py` | 잘못된 grid 읽음, 탑조명 invoice 미발견 |
| 프로젝트 picker | `project_picker.py` | invoice OBTAlert가 project input 차단 |
| 선급금 셀 에디터 | `advance_payment.py` (구 other_forms.py:869) | focus() → 셀 에디터 미활성화 (canvas dblclick 필요) |
| 연장근무/외근 | `overtime.py` / `outside_work.py` | HR 권한 보유 계정 필요 |

### 환경 동기화 메모 (타 본체 ↔ 이 PC)
- 이 저장소(origin/master)와 타 본체 로컬 사이 차이:
  - 누락 테스트 29개 (test_gw_validation 11 + test_construction_trades 13 + α)
  - 타 본체에 미커밋 작업이 있으면 push 후 이 PC에서 pull
- 운영 서버는 타 본체에서 구동, 외부 노출 https://unchidingly-hybridizable-maranda.ngrok-free.dev
- 양 PC 작업 충돌 방지: 작업 시작 시 `git pull`, 마무리 시 `git push`
