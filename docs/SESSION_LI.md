# 세션 LI — expense.py Phase B/C 분할

> 날짜: 2026-05-15
> 성격: 거대 파일 분할 (콜백 주입 패턴 확립)
> 선행: 세션 XLIX (정비), 세션 L (Phase A + 핸들러)

---

## 완료 작업

### Phase B — `_select_invoice_in_modal` 1013줄 추출

`src/approval/invoice_modal.py` 신규 (1039줄)

**self 의존성 변환:**
| 원본 | 추출 후 |
|---|---|
| `self.page` (34회) | `page` 인자 |
| `self._dismiss_obt_alert` (4회) | `dismiss_alert_fn` 콜백 |

mixin 메서드 → 11줄 위임 wrapper.

### Phase C — `_fill_project_code` 784줄 추출

`src/approval/project_picker.py` 신규 (812줄)

**self 의존성 변환:**
| 원본 | 추출 후 |
|---|---|
| `self.page` (12회) | `page` 인자 |
| `self._dismiss_obt_alert` (4회) | `dismiss_alert_fn` 콜백 |
| `self._close_open_modals` (1회) | `close_modals_fn` 콜백 |

→ base.py 변경 없이 깔끔 분리.

---

## 핵심 패턴: 콜백 주입 (Callback Injection)

거대 mixin 메서드를 함수형 모듈로 분리할 때 base.py의 다른 mixin 메서드 의존성을
`Callable` 인자로 전달:

```python
def fill_project_code(
    page: Page,
    dismiss_alert_fn: Callable[[], None],   # = self._dismiss_obt_alert
    close_modals_fn: Callable[[], None],    # = self._close_open_modals
    project: str,
    y_hint: float = None,
):
    ...
```

mixin 메서드는 위임 wrapper로 5~10줄로 축약. 외부 시그니처 100% 보존.

**자동 변환 스크립트**: regex로 `self.page → page`, `self.<method> → <fn>` 일괄 치환 + ast 검증. 신뢰성 높음.

---

## 누적 성과 (XLIX + L + LI)

### 거대 파일 분할 진척

| 파일 | 시작 | 현재 | 감소 | 비율 |
|---|---|---|---|---|
| `expense.py` | 4,938 | **2,147** | **-2,791** | **-56.6%** |
| `prompts.py` | 243 | 105 | -138 | -57% |
| 4종 크롤러 | 1,315 | 542 | -773 | -59% |

### 신규 모듈 구조

```
src/approval/
├── invoice_modal.py     1039줄  (세션 LI Phase B)
├── project_picker.py     812줄  (세션 LI Phase C)
├── attachment.py         136줄  (세션 L Phase A)
├── budget_capture.py     137줄  (세션 L Phase A)
├── expense.py           2147줄  (mixin facade)
└── base.py + 공통 헬퍼
```

---

## 구문 검증
- ✅ `expense.py` + `invoice_modal.py` + `project_picker.py` 모두 `ast.parse` 통과
- ✅ self 참조 자동 변환 검증 (잔존 0)
- ✅ Mixin 시그니처 보존 (외부 영향 0)

---

## 다음 세션 후보

### 🟢 안전 영역 (분할 계속)
1. **`_fill_expense_fields` (L719, ~722줄)** — 양식 필드 채우기 분리
2. **`_create_expense_report_via_popup` (L127, ~296줄)** — 팝업 처리 분리
3. **`other_forms.py` 4개 양식 분할** — `advance_payment.py` / `overtime.py` / `outside_work.py` / `recommendation.py`
4. `_find_first_visible` 추가 적용 (셀렉터 폴백 체인 통합)

### 🟡 실 GW 검증 필요
1. 1순위 A/B/C
2. 추출된 invoice_modal / project_picker 동작 회귀 검증
3. `_safe_handler` 실제 동작 확인

### 🔴 큰 작업 (전용 세션)
1. 진행 상황 SSE 스트리밍
2. 자동화 결과 로그 DB + 대시보드
3. ApprovalError 계층
