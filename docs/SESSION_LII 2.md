# 세션 LII — expense.py Phase D + other_forms.py 4분할

> 날짜: 2026-05-20
> 성격: 거대 파일 분할 마무리 (콜백 주입 + mixin 분리 패턴 병행)
> 선행: 세션 L (Phase A + handler 정비), 세션 LI (Phase B + C)
> 진행: 병렬 sonnet 에이전트 2명(A/B) + Opus 검토자(LII) 통합

---

## 완료 작업

### Phase D — `_fill_expense_fields` 722줄 추출 (Agent A)

`src/approval/expense_fields.py` 신규 (771줄)

**self 의존성 변환:**

| 원본 | 추출 후 |
|---|---|
| `self.page` (다회) | `page` 인자 |
| `self._dismiss_obt_alert` | `dismiss_alert_fn` 콜백 |
| `self._fill_project_code` | `fill_project_code_fn` 콜백 |
| `self._fill_field_by_label` | `fill_field_by_label_fn` 콜백 |
| `self._check_field_has_value` | `check_field_has_value_fn` 콜백 |
| `self._close_open_modals` | `close_modals_fn` 콜백 |
| `self._click_evidence_type_button` | `click_evidence_type_fn` 콜백 |
| `self._select_invoice_in_modal` | `select_invoice_fn` 콜백 |
| `self._fill_grid_items` | `fill_grid_items_fn` 콜백 |
| `self._fill_receipt_date` | `fill_receipt_date_fn` 콜백 |
| `self._fill_project_code_bottom` | `fill_project_code_bottom_fn` 콜백 |
| `self._link_reference_document` | `link_reference_doc_fn` 콜백 |
| `self._upload_attachment` | `upload_attachment_fn` 콜백 |
| `self._capture_and_attach_budget_screenshot` | `capture_budget_fn` 콜백 |

mixin 메서드 → 18줄 위임 wrapper. 명명 컨벤션(`*_fn`)은 Phase B/C와 일치.

### other_forms.py 4분할 (Agent B) — mixin 클래스 분리 패턴

`src/approval/other_forms.py` 2683 → 541줄 facade.

신규 모듈 4개:

| 파일 | 줄수 | 포함 mixin |
|---|---|---|
| `advance_payment.py` | 1289 | `AdvancePaymentMixin` — 선급금 요청서/정산서 |
| `overtime.py` | 496 | `OvertimeMixin` — 연장근무신청서 + `_navigate_to_hr_attendance` (공통 헬퍼) |
| `outside_work.py` | 367 | `OutsideWorkMixin` — 외근신청서(당일) |
| `recommendation.py` | 134 | `ReferralBonusMixin` — 사내추천비 지급 요청서 |

**other_forms.py 잔류 메서드 5개**:
- `search_project_codes` — 프로젝트 코드도움 자동완성 (챗봇 검색용)
- `create_proof_issuance` — [회계팀] 증빙발행 신청서 작성
- `_create_proof_issuance_draft` — 증빙발행 임시보관
- `save_form_draft` — 양식별 draft 라우팅
- `create_form` — 양식 키별 작성 메서드 라우팅 디스패처

**MRO**: `OtherFormsMixin(AdvancePaymentMixin, OvertimeMixin, OutsideWorkMixin, ReferralBonusMixin)` —
4개 mixin을 조합하는 facade. 외부 인터페이스는 100% 보존(approval_automation.py 무변경).

---

## 두 분할 방식의 차이 — 콜백 주입 vs mixin 분리

세션 LII에서 거대 파일 분할 전략의 **2가지 변형**이 확립되었다.

### 콜백 주입 (Phase A~D)

- **대상**: `expense.py`의 단일 거대 메서드 (~700~1000줄)
- **방식**: 함수형 모듈로 추출 + self.* 의존성을 `Callable` 인자로 주입
- **이점**: 함수 단위 테스트 가능, 인터페이스 명시, ast 검증 용이

### mixin 분리 (other_forms.py)

- **대상**: 한 파일 내 **다중** 거대 메서드 (4종 양식 × 작성/draft = 8+ 메서드)
- **방식**: 양식별 mixin 클래스 분리 + facade에서 다중 상속
- **이점**: self.* 공유 메서드 의존성이 12~13개에 달해 콜백 주입 시 인자가 폭증
- **trade-off**:
  - 장점: 인자 폭증 방지, 상태 공유, 기존 호출부 무변경
  - 단점: mixin 단독 인스턴스화 어려움 — `OutsideWorkMixin`은 `_navigate_to_hr_attendance`를
    `OvertimeMixin`에서 MRO로 상속받아야 동작 → mixin 간 묵시적 의존성 발생

### 판단 기준 (확립)

| 상황 | 권장 패턴 |
|---|---|
| 단일 거대 메서드, self.* 의존 ≤5개 | 콜백 주입 (Phase A~D) |
| 한 파일 내 다중 메서드, 공유 self.* 많음 | mixin 분리 (LII) |

**Agent B의 mixin 채택 정당성 측정**:
- `_fill_advance_payment_fields`만 해도 self 메서드 의존성 **12개**
- `create_advance_payment_request` self 메서드 의존성 **13개**
- 콜백 주입 시 한 함수당 13~15개 콜백 인자 → 가독성/유지보수 저하

→ **Opus 검토 결론**: Agent B의 mixin 채택은 정당 (a) 그대로 둠.

---

## Opus 통합 검토 결과

### ✅ MRO / 임포트 정상

```
ApprovalAutomation MRO:
  ApprovalAutomation → ApprovalBaseMixin → ApprovalLineMixin → CcManagerMixin
  → ExpenseReportMixin → GridMixin → VendorRegistrationMixin → DraftSubmissionMixin
  → OtherFormsMixin → AdvancePaymentMixin → OvertimeMixin → OutsideWorkMixin
  → ReferralBonusMixin → AttendanceMixin → object
```

`ApprovalAutomation`이 정상적으로 모든 메서드를 노출(13개 핵심 메서드 확인).

### ✅ pytest 164/164 PASS

- 분할 전후 동일하게 164 collected / 164 passed (19.16s)
- "193 PASS"는 세션 XLV에서 보고된 수치이나, 현 워킹디렉토리에는
  `test_gw_validation.py`(11) / `test_construction_trades.py`(13) 등이 부재 → **환경/체크아웃 차이**
- 현 상태에서는 164가 기준선. 추후 누락 테스트 복원은 별도 과제.

### ✅ 회귀 위험 없음

- 모든 7개 모듈 `ast.parse` 통과
- 분할된 메서드 본문은 자동 변환 스크립트로 1:1 추출 (세션 LI와 동일 방식)
- 호출 wrapper의 콜백 순서는 expense_fields.py 시그니처와 완전 일치
- `_save_advance_payment_draft` 등 세션 XLVI에서 작성된 로직 글자 그대로 보존 확인

### ✅ 콜백 시그니처 일관성

- expense_fields.py 13개 콜백 모두 `*_fn` 접미사
- Phase B/C(invoice_modal/project_picker)의 `dismiss_alert_fn`/`close_modals_fn`과 명명 동일

### ✅ 코드 스타일

- 한국어 docstring/주석 유지
- `logging.getLogger("approval_automation")` 일관성
- 모든 mixin 헤더에 "분할 출처: other_forms.py (세션 LII)" 명시

---

## 직접 수정한 항목

`src/approval/other_forms.py` line 19-22:
- dead import 정리 (6개 미사용 심볼)
- 제거: `Page`, `GW_URL`, `SCREENSHOT_DIR`, `_GET_GRID_IFACE_JS`, `_js_str`, `resolve_cc_recipients`
- 분할 전 본문에 있던 import가 4개 mixin으로 이동했으나 facade에는 잔존
- 제거 후 pytest 164/164 재PASS 검증 완료

---

## 누적 성과 (XLIX + L + LI + LII)

### 거대 파일 분할 진척

| 파일 | 시작 | 현재 | 감소 | 비율 |
|---|---|---|---|---|
| `expense.py` | 4,938 | **1,446** | **-3,492** | **-70.7%** |
| `other_forms.py` | 2,683 | **541** | **-2,142** | **-79.8%** |
| `prompts.py` | 243 | 105 | -138 | -57% |
| 4종 크롤러 | 1,315 | 542 | -773 | -59% |

### 신규 모듈 구조 (approval/ 디렉토리)

```
src/approval/
├── approval_automation.py    66줄  (Mixin 조합 진입점)
├── base.py                          (공통 유틸 + _find_first_visible)
├── expense.py             1,446줄  (지출결의서 mixin facade)
├── expense_fields.py        771줄  (LII Phase D — 콜백 13개)
├── invoice_modal.py       1,039줄  (LI Phase B — 콜백 1개)
├── project_picker.py        812줄  (LI Phase C — 콜백 2개)
├── attachment.py            136줄  (L Phase A)
├── budget_capture.py        137줄  (L Phase A)
├── other_forms.py           541줄  (LII facade + 공통)
├── advance_payment.py     1,289줄  (LII — AdvancePaymentMixin)
├── overtime.py              496줄  (LII — OvertimeMixin)
├── outside_work.py          367줄  (LII — OutsideWorkMixin)
├── recommendation.py        134줄  (LII — ReferralBonusMixin)
└── ... (grid/vendor/draft/budget_helpers/cc_manager/form_templates)
```

---

## 구문 검증

- ✅ 7개 신규/수정 모듈 모두 `ast.parse` 통과
- ✅ `from src.approval.approval_automation import ApprovalAutomation` 정상
- ✅ MRO 정상 (object 포함 14 클래스)
- ✅ 13개 핵심 메서드 hasattr 통과
- ✅ pytest 164/164 PASS (19초)
- ✅ 분할된 mixin들의 외부 시그니처 보존 (외부 호출부 영향 0)

---

## 권장 후속 작업 (사용자 결정 필요)

1. **누락 테스트 복원 검토** — 세션 XLV 시점 `tests/unit/test_gw_validation.py`(11),
   `tests/unit/test_construction_trades.py`(13) 등이 현 워킹디렉토리에 없음. 별도 브랜치/체크아웃 차이 확인.
2. **OutsideWorkMixin 단독 사용 시 의존성 명시** — `_navigate_to_hr_attendance`가
   `OvertimeMixin`에 있고 `OutsideWorkMixin`이 MRO로 상속받는 묵시적 의존이 있음.
   향후 `OutsideWorkMixin` 단위 테스트 시 OvertimeMixin도 함께 mix-in 해야 동작.
3. **other_forms.py 추가 슬림화 옵션** — 잔류 5개 메서드 중
   `search_project_codes`(115줄)와 `_create_proof_issuance_draft`(204줄)를
   `proof_issuance.py` mixin으로 또 분리하면 facade가 ~200줄로 축소 가능.
   현재로서는 over-engineering — 추후 필요 시.

---

## 다음 세션 후보

### 🟢 안전 영역 (분할 계속)
1. `vendor.py` (798줄) — 거래처등록 분할 검토
2. `draft.py` (464줄) — 분할 효용 낮음 (이미 적정 크기)
3. `chatbot/handlers.py` (1882줄) — 도구 핸들러 카테고리별 분리

### 🟡 실 GW 검증 필요
1. Phase D 분할 후 지출결의서 22단계 E2E (`tgjeon` 계정)
2. 선급금 그리드 필수 필드 자동 입력 검증 (세션 XLVII 후속)
3. 근태관리 권한 보유 계정 확보 (연장근무/외근 DOM 검증)

### 🔴 큰 작업 (전용 세션)
1. 진행 상황 SSE 스트리밍
2. 자동화 결과 로그 DB + 대시보드
3. ApprovalError 계층
