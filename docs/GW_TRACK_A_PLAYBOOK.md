# GW Track A 플레이북 — Export 마지막 1마일 해결

> Track A 목표: 22개 GW 페이지에서 엑셀 다운로드 자동화를 100% 완성하기 위해
> **사용자 시연으로 페이지별 조회 버튼/다운로드 모달 셀렉터를 한 번에 캡처**한다.

---

## 1. 현재까지 알아낸 것 (v8 결과)

| 항목 | 상태 |
|---|---|
| 페이지 URL 22개 매핑 | ✅ `src/shared/gw_session/selectors.py:GW_PAGES` |
| URL 직접 진입 성공률 | 22/22 (100%) |
| 그리드 컨테이너 식별 | 19/22 (`[class*=OBTDataGrid]`) |
| 엑셀 아이콘 즉시 노출 | 3/22 (CL/RM/ML — 즉시 발견) |
| 엑셀 아이콘 셀렉터 | ✅ `button:has(img[src*='cel_save'])` |
| 다운로드 실제 성공 | 2/22 (CL·RM 단일 시도, v8에서 0/22) |

## 2. 남은 1마일

| 미해결 | 원인 가설 | 해결 단계 |
|---|---|---|
| BN/HR 19개 페이지에서 엑셀 아이콘 미노출 | "조회" 버튼을 먼저 눌러야 활성화 | 페이지별 조회 버튼 셀렉터 매핑 |
| 엑셀 클릭 후 다운로드 미발생 | "전체 페이지/포맷 선택" 모달 dismiss 실패 | 모달 구조 캡처 + 버튼 텍스트 매핑 |

## 3. 사용자 시연 절차 (페이지당 약 5분)

### 3-1. 준비

```bash
cd "/Users/tg_mac_mini/Documents/자동화 work"
.venv/bin/python scripts/track_a_capture.py
```

- Chromium이 headed 모드로 열림
- 저장된 tgjeon 세션으로 자동 로그인
- 콘솔에 "✋ 사용자 조작 대기 — 페이지 진입 후 Enter를 누르세요" 표시

### 3-2. 단계별 캡처

페이지 1개씩 다음을 반복:

| # | 사용자 동작 | 캡처되는 정보 |
|---|---|---|
| 1 | 브라우저에서 캡처 대상 페이지로 이동 (URL 직접 입력 또는 LNB 클릭) | URL · frame 구조 |
| 2 | 콘솔에 페이지 라벨 입력 (예: `예실대비현황_상세`) | label key |
| 3 | **"조회" 버튼 클릭하기 전에** 콘솔에서 Enter | "before-inquiry" DOM dump |
| 4 | 사용자가 직접 조회 버튼 클릭 | (사용자 동작) |
| 5 | 데이터 로드 확인 후 콘솔에서 Enter | "after-inquiry" DOM dump + 조회 버튼 셀렉터 추출 |
| 6 | **엑셀 다운로드 버튼 클릭하기 전에** 콘솔에서 Enter | (선택) |
| 7 | 엑셀 클릭 → 모달 뜨면 그 상태에서 콘솔에서 Enter | 모달 DOM dump + 버튼 텍스트 |
| 8 | 사용자가 모달에서 다운로드 실행 → 파일 저장 위치 콘솔에 표시 | 다운로드 검증 |

### 3-3. 권장 우선순위

| 우선 | 페이지 | 이유 |
|---|---|---|
| 🔴 1 | 예실대비현황_상세 (`/BN/NCC0630/NCC0630`) | 자금관리 핵심 |
| 🔴 2 | 지출결의이체현황 (`/HP/APB1020/APB1020`) | 매출/매입 실시간 |
| 🟡 3 | 프로젝트등록 (`/BN/NCF0090/SYB0060`) | 200건 마스터 |
| 🟡 4 | 예실대비현황_사업별 (`/BN/NCC0631/NCC0631`) | 시계열 |
| 🟢 5 | 근태신청현황 (`/HP/HPD0122/HRD0220`) | HR 600행 |

3~5개만 캡처해도 패턴이 확정되면 나머지 17개 페이지에 동일 패턴 적용 가능.

---

## 4. 캡처 결과 통합 — `selectors.py` 자동 업데이트

`track_a_capture.py` 종료 후 `data/track_a_captures.json` 생성:

```json
{
  "예실대비현황_상세": {
    "url_path": "/#/BN/NCC0630/NCC0630",
    "inquiry_button_selectors": [
      "button.OBTButton_typedefault__1V4nr:has-text('조회')",
      "[class*='OBTToolbar'] button:nth-child(1)"
    ],
    "download_modal": {
      "container_selector": "[class*='OBTDialog']",
      "confirm_buttons": ["확인", "다운로드"]
    }
  },
  ...
}
```

이 JSON을 사람이 한 번 검토한 뒤 `selectors.INQUIRY_BUTTONS`에 반영
(append-only 정책).

---

## 5. 자동 적용 — v9 크롤러 (선택)

`selectors.py:INQUIRY_BUTTONS` 가 채워지면 v9 크롤러 자동 작성:

```python
# scripts/crawl_export_v9.py
from src.shared.gw_session.selectors import GW_PAGES, INQUIRY_BUTTONS, EXCEL_DOWNLOAD

for key, page_meta in GW_PAGES.items():
    page.goto(BASE + page_meta.url_path)
    inquiry_sel = INQUIRY_BUTTONS.get(key)
    if inquiry_sel:
        page.locator(inquiry_sel).click()
        page.wait_for_load_state()
    with page.expect_download() as dl_info:
        page.locator(EXCEL_DOWNLOAD).click()
        # 모달 자동 dismiss (캡처된 confirm_buttons)
    dl_info.value.save_as(f"data/amaranth_exports/{key}.xlsx")
```

---

## 6. 시연 없이 가능한 보조 작업 (병렬)

사용자 시연 일정 잡기 전 다음을 미리 자동화:

- [x] 페이지별 진입 직후 DOM 자동 dump → `scripts/track_a_capture.py` (이번 PR 신설)
- [ ] DOM dump 결과를 `selectors.py:INQUIRY_BUTTONS`에 자동 추가하는 ingest CLI
- [ ] capture 세션 비디오 녹화 (Playwright `record_video_dir`) — 디버그용

---

## 7. 기대 효과

캡처 5분 × 5페이지 = **25분 안에** 22 페이지 export 자동화 80~100% 완성 가능. 향후 영림원/이카운트 같은 다른 GW로 어댑터 교체 시 동일 절차 재사용.
