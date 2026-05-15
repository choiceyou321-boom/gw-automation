# 다음 세션 시작 프롬프트

> 이 파일을 복사해서 Claude Code 새 세션 첫 메시지로 붙여넣기

---

## 붙여넣기용 프롬프트

```
gw-automation 프로젝트 세션 LII 시작.

📁 프로젝트 경로: D:\TG\gw-automation
📄 직전 세션: docs/SESSION_LI.md (expense.py Phase B/C 분할)
📄 정비 흐름: docs/SESSION_XLIX.md → SESSION_L.md → SESSION_LI.md
📄 프로젝트 현황: docs/PROJECT_STATUS.md
📄 개발자 가이드: DEVELOPER_GUIDE.md (콜백 주입 + _safe_handler + _find_first_visible 패턴 등재)

## 환경 정보
- Python 3.13 (WindowsApps), pytest는 가상환경 필요
- gh CLI v2.92.0 인증 완료
- 훅 설정: Stop(pytest 자동 실행), PreToolUse(config/.env 커밋 차단)
- CI: .github/workflows/ci.yml (구문 검증 + 단위 테스트 + ruff)

## 누적 정비 성과 (XLIX + L + LI)
- expense.py: 4938 → 2147 (-56.6%)
- prompts.py: 243 → 105 (-57%)
- 4종 크롤러: 1315 → 542 (-59%)
- 신규 모듈: invoice_modal / project_picker / attachment / budget_capture / base_crawler
- 헬퍼: _safe_handler(34 핸들러 일괄) / _find_first_visible / _GET_GRID_IFACE_JS

## 이번 세션 후보 작업 (난이도 오름차순)

### 🟢 안전 영역 (테스트/GW 불필요)
1. **expense.py Phase D 분할** — `_fill_expense_fields` (~722줄) → `expense_fields.py`
   - 콜백 주입 패턴 4번째 적용
2. **expense.py 추가 분할** — `_create_expense_report_via_popup` (~296줄) → `expense_popup.py`
3. **other_forms.py 4분할**:
   - `advance_payment.py` (선급금 요청+정산)
   - `overtime.py` (연장근무)
   - `outside_work.py` (외근신청)
   - `recommendation.py` (사내추천비)
4. `_find_first_visible` 추가 적용 (expense.py 4곳)

### 🟡 실 GW 검증 필요
1. **1순위 A/B/C** (자격증명 확보 후)
   - invoice 모달 타이밍 (expense.py → invoice_modal.py)
   - 프로젝트 picker 확인 버튼 (expense.py → project_picker.py)
   - 선급금 그리드 입력 (other_forms.py L869)
2. 분할된 모듈 회귀 검증 (invoice_modal, project_picker, attachment, budget_capture)
3. GRID_IFACE 치환 회귀 검증 (세션 XLIX 20곳)
4. `_safe_handler` 데코레이터 실제 동작 확인

### 🔴 큰 작업 (전용 세션)
1. 진행 상황 SSE 스트리밍 (Playwright 1~3분 무응답 해소)
2. 자동화 결과 로그 DB + 모니터링 대시보드
3. ApprovalError 계층 + 사용자 친화 메시지 표준화

## 시작 전 권장
- DEVELOPER_GUIDE.md에서 **콜백 주입 패턴** 절 읽기 (Phase D에 동일 패턴 적용)
- docs/SESSION_LI.md에서 자동 변환 스크립트 패턴 참고
```

---

## 빠른 컨텍스트 요약

### 핵심 파일 구조 (현재)

```
src/approval/
├── expense.py          2,147줄  (mixin facade, 시작 4,938)
├── invoice_modal.py    1,039줄  (LI Phase B)
├── project_picker.py     812줄  (LI Phase C)
├── other_forms.py      2,683줄  (선급금/연장근무/외근/추천장려금 ← 분할 후보)
├── budget_helpers.py     876줄
├── grid.py               596줄
├── attachment.py         136줄  (L Phase A)
├── budget_capture.py     137줄  (L Phase A)
└── base.py + 공통 헬퍼

src/fund_table/
├── base_crawler.py      266줄   (XLIX)
└── contract/tax/payment/collection_crawler.py  (각 65~73줄, -59%)

src/chatbot/
├── handlers.py        2,698줄  (+_safe_handler, 34 핸들러)
└── prompts.py           105줄  (-57%)
```

### 핵심 기술 패턴 (XLIX+L+LI 확립)
- **콜백 주입**: 거대 mixin 메서드 추출 시 `Callable` 인자로 의존성 주입
- **`_safe_handler`**: TOOL_HANDLERS dict comprehension wrap으로 일괄 적용
- **`_find_first_visible`**: 셀렉터 폴백 체인을 polling 헬퍼로 통합
- **OBTDataGrid**: `_GET_GRID_IFACE_JS` 헬퍼 (base.py)
- **OBTDialog2**: `dimClicker` 차단 → JS로 dialog 내부 직접 탐색

### 알려진 이슈 (실 GW 필요)
| 이슈 | 위치 | 증상 |
|---|---|---|
| invoice 모달 타이밍 | `invoice_modal.py` | 모달 열림 전 진행 |
| 프로젝트 picker | `project_picker.py` | 확인 버튼 미클릭 |
| 선급금 그리드 | `other_forms.py:869` | keyboard.type+Enter 후 값 미반영 |
