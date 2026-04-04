# GW 자동화 프로젝트 — 세션 작업 기록 (MEMORY.md)

> 새 세션 시작 시 반드시 이 파일을 읽어 이전 발견사항 및 진행 상황을 파악할 것.


---

## 세션 XL (2026-04-04) — Telegram 봇 통합 + YouTube Gemini 분석 + 노션 업무 관리 구축

### 작업 개요
챗봇 서버 개선, 새 기능 추가, 노션 업무 관리 페이지 구축.

### 완료 작업

#### 1. Telegram 봇 + 챗봇 서버 통합
- `telegram_bot.py`에 `start_telegram_bot()` / `stop_telegram_bot()` 백그라운드 스레드 함수 추가
- `app.py` lifespan에 텔레그램 봇 자동 시작/종료 연결
- 이제 `launchctl stop/start com.gw-chatbot.server` 한 번으로 웹서버 + 텔레그램 봇 함께 재시작
- **문제 해결:** Playwright sync API를 asyncio 루프 안에서 직접 호출 시 충돌 → `_executor` 스레드풀로 분리

#### 2. 프로젝트 공정 일정표 조회 (get_project_schedule)
- `handle_get_project_schedule()` 핸들러 추가
- group_name별 묶음, 진행상태(완료/진행중/예정/지연), D-day 계산
- 실제 데이터: [반포] 폼폼푸린 카페 34개 항목
- 챗봇에서 "폼폼푸린 일정 보여줘"로 바로 조회 가능

#### 3. GW 개인 일정 조회 (get_my_schedule)
- `handle_get_my_schedule()` 핸들러 추가 (_executor로 asyncio 안전 처리)
- GW API `/schd/api/schd001A01` 엔드포인트 시도 (성공 여부 미확인)
- 챗봇에서 "내 일정 보여줘"로 요청 가능

#### 4. YouTube Gemini 분석 기능 (analyze_youtube)
- `src/chatbot/youtube_analyzer.py` 신규 생성
  - `analyze_youtube_video()`: yt-dlp 자막 추출 + Gemini 요약
  - `analyze_youtube_playlist()`: 재생목록 일괄 분석
  - `get_video_transcript()`: 자막 전문 추출
  - 한국어/영어 자막 자동 감지, json3/vtt 포맷 지원
- **주의:** Gemini에 YouTube URL 직접 전달 방식은 hallucination 발생 → yt-dlp 자막 추출 방식으로 구현
- `requirements.txt`에 yt-dlp 추가

#### 5. CLAUDE.md 최신화
- pytest 133/133 PASS (기존 94에서 증가 반영)
- Playwright asyncio 충돌 주의사항 추가
- 새 핸들러 등록 규칙 추가
- 현재 추가된 도구 목록 섹션 신설

#### 6. 노션 업무 관리 (일과나 2 + GS 업무 관리)
- **일과나 2 페이지** 구성:
  - TASK LIST 12개 항목 todolist 2 DB에 추가 (WORK 카테고리)
  - TASK LIST 진행중/시작전 14건 추가
  - MEMO 19건, 회의록 74건 최근 5건 섹션 추가
  - 📖 노션 활용 가이드 (TO DO LIST/캘린더/UNFINISHED/단축키 토글)
  - ⏰ 추천 업무 루틴 (출근/퇴근 5분 루틴)
- **GS 업무 관리 페이지** 신규 생성 (WORKSPACE 하위)
  - URL: https://notion.so/33815a039e0981139912dc64d7f7f5ab
  - ✅ 오늘의 할일 12개 체크박스
  - 📊 프로젝트 현황: 20개 프로젝트 등급별 분류
  - 🗂️ 업무별 진행 현황: 11개 업무 상태
  - 🤖 챗봇 빠른 명령어 카테고리별 정리
  - ⏰ 업무 루틴

### 발견사항
- Gemini 2.5 Flash에 YouTube URL 직접 전달 시 전혀 다른 영상 내용을 hallucination으로 생성함 → 절대 사용 금지
- Telegram 봇을 asyncio 루프 안 스레드에서 `run_polling()` 직접 호출 시 signal handler 오류 발생 → `asyncio.run()` + `await updater.start_polling()` 패턴 사용
- LaunchAgent로 등록된 서버는 `pkill`로 죽여도 자동 재시작됨 → `launchctl stop` 사용

### 커밋
- `509acd2`: 텔레그램 봇 통합 + 프로젝트 일정표/GW 개인 일정 조회
- `2e31e98`: handle_get_my_schedule asyncio 충돌 수정
- `4bf3867`: YouTube Gemini 분석 기능 + CLAUDE.md 최신화

---

## 세션 XXVIII (2026-03-27) — GW 크롤링 심층 분석 + DB 스키마 확장

### 작업 개요
GW 그룹웨어에서 크롤링 가능한 데이터 전체 분석 → DB 스키마 확장 → 프로젝트 관리 페이지 개선점 도출.
소스 분석 대상: `project_crawler.py`, `budget_crawler.py`, `budget_crawler_by_project.py`, `sheets_import.py`, `db.py`, `routes.py`, `fund.html`, `fund.js` (8개 파일, 총 ~500KB)

### 발견사항: GW 크롤링 현황 vs 가능한 데이터

#### 현재 수집 중
| 크롤러 | 수집 데이터 |
|---|---|
| `project_crawler.py` | 코드, 이름, 시작일, 종료일, 담당자, 발주처명 (6개 필드) |
| `budget_crawler.py` | 예산과목, 예산액, 집행액, 잔액, 집행률 (5개 필드) |
| `budget_crawler_by_project.py` | 동일 + 연도별 누적 |
| `sheets_import.py` | Sheets: 하도급, 연락처, 지급내역, 수금 |

#### 미수집 (GW에 있는데 안 가져옴)
- PM/현장소장/설계팀장/부서 → `project_overview`에 컬럼 자체 없었음
- 계약금액(ctrtAm), 발주처 담당자/연락처 → 저장 경로 없음
- 사업유형/진행상태/진행률 → `gw_projects_cache`에 컬럼 없음
- 예산 변경 이력, 월별 집행계획, 자금집행 승인 목록 → 크롤러 없음
- 세금계산서 발행 내역, 수금 예정 내역, 하도급 계약 현황 → 크롤러 없음
- `payment_history`: 공급가/부가세 분리 없음, project_id 연결 오탐 가능

### 작업 완료

#### db.py 수정 (55,593B → 62,377B + ~7,000B 추가)
1. **`gw_projects_cache` 컬럼 7개 추가**: manager, client, department, project_type, status, contract_amount, progress_rate
2. **`project_overview` 컬럼 9개 추가**: client, client_contact, client_phone, pm_name, site_manager, design_manager, gw_status, gw_project_type, gw_last_synced
3. **`payment_history` 컬럼 4개 추가**: supply_amount, tax_amount, payment_type, trade_id
4. **신규 테이블 6개 생성**:
   - `gw_tax_invoices`: 세금계산서 발행 내역
   - `gw_budget_changes`: 예산 변경·전용 이력
   - `gw_collection_schedule`: 수금 예정 내역
   - `gw_payment_approvals`: 자금집행 승인 현황
   - `project_risk_log`: 리스크 이력 (수동+AI)
   - `gw_contracts`: GW 하도급 계약 현황
5. **신규 CRUD 함수 추가**: save/list_tax_invoices, save/list_budget_changes, save/list_collection_schedule, save/list_payment_approvals, add/list/update_risk, save/list_gw_contracts, save_gw_projects_cache_v2

#### project_crawler.py 수정
- JS 추출 스크립트에 확장 필드 추가: pm_name, site_manager, design_manager, department, project_type, status, contract_amount, client_contact, client_phone
- React fiber 매핑 확장: pmEmpNm, siteEmpNm, desgEmpNm, deptNm, pjtTpNm, ctrtAm, clntMgrNm, clntTelNo, prgsRt

### 미착수 (분석 완료, 구현 대기)
- **신규 크롤러 3종**: tax_invoice_crawler.py, collection_schedule_crawler.py, payment_approval_crawler.py
- **routes.py**: 신규 6개 엔드포인트
- **fund.html/js**: 계약 탭, 리스크 탭, 발주처 자동 채우기, 예산변경이력 토글

### 평가 기준 확정 (5축)
| 축 | 가중치 |
|---|---|
| 데이터 완결성 | 30% |
| 데이터 신선도 | 20% |
| 화면 정보 밀도 | 20% |
| 작업 효율 | 15% |
| 상태 가시성 | 15% |

현재 점수: 완결성 35% / 신선도 50% / 정보밀도 45% / 작업효율 55% / 상태가시성 40%

### 핵심 패턴: project_overview에 client 필드 없음
- GW 크롤링 결과를 `_save_to_db`에서 저장 시 `client` → `project_overview.client` 매핑했지만 컬럼 자체가 없었음 (이번에 추가 완료)
- `gw_projects_cache.save_gw_projects_cache_v2()` — 확장 필드 버전 신규 함수

## 세션 XXVII — 2026-03-27

### 작업 내용

#### ① Google Sheets 협력업체 리스트 포맷 개선 (Apps Script)

**대상 파일:** `글로우서울 협력업체 리스트 (gid=939411051, gid=1854007113)`

**작업 1 — WORKING LIST_협력사 포맷 개선 (`formatSheet()`)**
- 타이틀(1~2행): 진한 남색(`#1B3A6B`) 배경, 흰색 14pt bold
- 헤더(3행): 파란(`#2E5BA8`) 배경, 흰색 10pt bold, 컬럼 레이블 재설정
- 데이터 행: 선호업체(`starBg=#EBF4FF`), 일반(`normalBg=#FFFFFF`), 카테고리(`catBg=#D6E4F7`)
- 빈 행: 7px 높이로 시각 분리
- 테두리(`#BDD0E8`), 열 너비 최적화
- 핵심 발견: `setRowHeight(r, 26)` 호출이 숨겨진 행(5~16)을 노출시킴 → `updateSheet`에서 `sheet.hideRows(5, 12)` 재실행으로 해결

**작업 2 — 빈 행 삭제 + 참여 프로젝트/평가 컬럼 추가 (`updateSheet`, `updateBothSheets`)**
- 두 시트 모두 rows 5~16 숨김 처리
- WORKING LIST_협력사: 빈 행 삭제 + L열 "참여 프로젝트" + M열 "평가" 추가
- 자재 LIST_협력사: **64개 빈 행 삭제** (165행 → 101행)
  - 핵심 발견: J열에 "-" 기본값이 있어 `allData.every(c => c === '')` 감지 불가
  - 해결: B열(업체명)이 비어있고 A열도 비어있는 행만 삭제하는 `cleanZajaeRows()` 함수로 해결
- L/M 헤더: 파란(`#2E5BA8`) 배경, 흰색, bold
- M열 드롭다운: 상/중/하 (requireValueInList)
- 조건부 서식: 상=초록(`#C6EFCE`), 중=노랑(`#FFEB9C`), 하=빨강(`#FFC7CE`)
- 열 너비: L=190px, M=55px

**Apps Script 프로젝트 제목 제안:**
- 추천: `GW 협력사 시트 업데이터` 또는 `협력사 시트 정리 & 평가 컬럼 자동화`

---

#### ② 프로젝트 관리 페이지 전체 개선 분석 (fund.html / fund.js)

사용자 요청으로 `/fund` 페이지 전체 6개 탭 + 사이드바 + 포트폴리오 화면을
소스코드(fund.html 1025줄, fund.js 3500줄, routes.py 1583줄, db.py 1585줄) 기반으로
상세 분석하여 개선 계획 수립.

**평가 기준 5개 축:** 정보 밀도(25%), 작업 효율(25%), 상태 가시성(20%), 빈 상태 처리(15%), 일관성(15%)

**개선 항목 총계: 42개** (🔴높음 18개 / 🟡중간 17개 / 🟢낮음 7개)

**영역별 주요 개선 항목:**

| 영역 | 핵심 이슈 | 우선순위 |
|------|-----------|----------|
| 사이드바 | 숫자 뱃지 의미 불명확 / 상태별 그룹핑 없음 | 🔴 |
| 대시보드 | 요약 카드 없음 / TODO AI 권고 vs 사용자 항목 미구분 / 완료 피드백 없음 | 🔴 |
| 개요 탭 | grade 설정 UI 없음 / 구성원 역할 표준화 없음 | 🔴 |
| 수금현황 | 수금 예정일 컬럼 없음 / 빈 상태 템플릿 유도 없음 / 상단 요약 없음 | 🔴 |
| 예산&자금 | 손익 카드 없음 / item 코드 그대로 표시 / 동기화 버튼 위치 불명확 | 🔴 |
| 하도급 탭 | 공종별 합계 없음 / unsaved 경고 없음 / 업체 연락처 팝오버 없음 | 🔴 |
| 지급내역 | 월별 집계 없음 / 지급 예정일 없음 | 🟡 |
| 공통 | 탭명 "이메세역" 불명확 / 데이터 내보내기 없음 / 에러 토스트 없음 | 🔴 |

**전체 개선 계획 문서:** `user_task_list.md` 섹션 8 참조

---

### 신규 생성/수정 파일

없음 (이번 세션은 분석/기록 위주)

### Apps Script 패턴 발견

```javascript
// 빈 행 감지 시 주의: 일부 컬럼에 "-" 기본값 있을 경우
// → B열(업체명) 기준으로 판단하는 것이 더 정확
const aEmpty = (aVal === '' || aVal === null || aVal === '-');
const bEmpty = (bVal === '' || bVal === null || bVal === '-');
if (aEmpty && bEmpty) sheet.deleteRow(r);

// Monaco 에디터 코드 교체 (Apps Script 편집 시)
window.monaco.editor.getEditors()[0].getModel().setValue(code);
```

---
## 세션 XXVI — 2026-03-26

### 작업 내용

**기결재 문서 수신참조(CC) 추가 기능 구현**

Claude Cowork 세션에서 GS-24-0025 청수당 프로젝트 지출결의서들에 수신참조를 직접 추가하며
실제 GW 모달 동작을 관찰하고, 이를 Playwright 자동화 코드로 구현.

#### 처리 완료 문서 (총 11건)
- docID 55531~55545 (8건): 이재명 과장 수신참조 추가 완료
- docID 55654: 이재명 과장 추가 완료
- docID 55625: 결재 잠금 → 처리 불가
- docID 55700: 임종훈 과장 추가 완료

#### 핵심 발견: 수신참조 지정 모달 (UBAP003) 동작 방식

```
모달 열기: .modifyButton (#btnRefer) 클릭
  → 결재 잠금 문서: .modifyButton 없음 (또는 저장 시 "상위 결재자 상태 변경" 오류)

검색: input[placeholder="검색어를 입력하세요."] 에 이름 입력 + Enter

검색결과 그리드: RealGrid canvas 기반
  → canvas[0].click() 으로 그리드 활성화
  → window.Grids.getActiveGrid().checkRow(0, true) 로 첫 번째 행 체크

수신참조 버튼: button(text="수신참조")
  → 여러 개 존재 → y 좌표 가장 위쪽 = 모달 헤더 근처 버튼
  → React fiber memoizedProps.onClick 직접 호출이 가장 안정적

저장: button(text="저장") 클릭 → 모달 자동 닫힘 = 성공
성공 검증: 수신및참조 "외 N명" 카운트 증가 확인
```

#### 결재 잠금 판별

- `.modifyButton` DOM 미존재
- 또는 저장 시 토스트: "상위 결재자의 상태가 변경되어 수정할 수 없습니다"
- → `CcManagerMixin._click_modify_button()` 에서 False 반환 → skip 처리

### 신규 생성/수정 파일

#### `src/approval/cc_manager.py` (신규)
- `CcManagerMixin` 클래스
- `add_cc_to_document(doc_id, cc_name)` — 단건 처리
- `batch_add_cc(doc_ids, cc_name)` — 일괄 처리
- 내부 헬퍼: `_open_doc_popup`, `_click_modify_button`, `_search_cc_name`,
  `_check_first_result`, `_fallback_check_canvas_row`, `_click_cc_add_button`,
  `_save_modal`, `_verify_cc_added`

#### `src/approval/approval_automation.py` (수정)
- `CcManagerMixin` import 및 MRO 추가

#### `src/approval/cc_manager.py` — 제목 검색 메서드 추가
- `search_docs_by_title(title_keyword, max_results)` — 기안문서함 검색 → 더블클릭 팝업 → docID 파싱
- `add_cc_by_title(title_keyword, cc_name)` — 제목 키워드로 검색 후 일괄 수신참조 추가

#### `src/chatbot/tools_schema.py` (수정)
- `add_cc_to_approval_doc` FunctionDeclaration 추가
  - params: `doc_ids` (list, 선택), `doc_title` (str, 선택), `cc_name` (str), `confirm` (bool)
  - `doc_ids` 또는 `doc_title` 중 하나 필수 (`cc_name`만 required)

#### `src/chatbot/handlers.py` (수정)
- `handle_add_cc_to_approval_doc()` 추가 — doc_title / doc_ids 분기 로직
  - `doc_title` 제공 시: `add_cc_by_title()` 호출
  - `doc_ids` 제공 시: `batch_add_cc()` 호출
- TOOL_HANDLERS 등록

### 테스트 결과
```
실제 GW 화면에서 11건 처리 완료 (수동 Claude Cowork)
단위 테스트 미변경 (기존 133개 PASS 유지)
```

---


## 세션 XXV — 2026-03-25

### 작업 내용

**지출결의서 용도코드 자동팝업 처리 구현**

사용자의 실시간 시연 관찰을 통해 기존 코드의 처리 순서 오류를 발견하고 수정.

#### 핵심 발견: 용도코드 → 팝업 자동 트리거 플로우

1. OBTDataGrid 용도 셀에 숫자 코드 입력 (예: `5020`) → Enter
2. **자동으로** "공통 예산잔액 조회" 팝업이 즉시 열림 (클릭 불필요)
3. 팝업 내 프로젝트 입력 → 예산과목코드도움 서브 팝업 → 확인
4. 팝업이 닫힌 **이후에** 지급요청일 그리드 입력 가능

#### 기존 코드의 문제점

```
Step 10:   usage_code 입력 → Enter     (팝업 자동 열림)
Step 10-1: 지급요청일 그리드 입력       ← 팝업이 열려있어 그리드 접근 불가
Step 11:   예산과목 필드 클릭 → 팝업   ← 팝업이 이미 열려있는 상태에서 또 클릭
```

#### 수정 후 올바른 순서

```
Step 10:   usage_code 입력 → Enter
Step 10-A: 자동 트리거 팝업 즉시 처리 (신규)
           → project 입력 → 예산과목코드도움 서브팝업 → 확인
Step 10-1: 지급요청일 그리드 입력 (팝업 닫힌 후)
Step 11:   팝업 미자동 환경 fallback (예산과목 필드 직접 클릭)
```

### 수정된 파일

#### `src/approval/budget_helpers.py`
- `handle_auto_triggered_popup(page, project_keyword, budget_keyword)` 신규 추가
- 이미 열린 팝업을 처리 (`select_budget_code()`와 달리 예산과목 필드 클릭 없음)
- 3초 내 팝업 미감지 시 `success=False` + `"팝업 미감지"` 반환 → step 11 fallback 위임

#### `src/approval/expense.py` — `_fill_expense_fields()` 내부
- Step 10-A 블록 신규 삽입 (step 10과 step 10-1 사이)
  - `_budget_auto_handled = False` 초기화 (usage_code 유무와 무관하게 항상 실행)
  - `handle_auto_triggered_popup()` 호출, 성공 시 `_budget_auto_handled = True`
- Step 11 조건 변경: `if usage_code and budget_keyword` → `if usage_code and budget_keyword and not _budget_auto_handled`

### 테스트 결과

```
133 passed in 1.25s   (0 failed, 0 error)
```

---

## 세션 XXIV — 2026-03-22

### 작업 내용 요약

- **좌표 의존 코드 제거** (13건): `expense.py` 7건 + `grid.py` 5건 + `budget_helpers.py` 1건 → JS click / OBTDataGrid API 우선, 좌표는 최후 폴백으로 유지
- **STT 시스템 프롬프트**: `prompts.py`에 음성 입력 자동 전사 안내 규칙 3줄 추가
- **GW 데이터 자동 동기화**: `scheduler.py` (APScheduler) 매일 08:00 3단계 크롤링 (프로젝트 목록 → 회계 정보 → Sheets 임포트)
- **멀티유저 동시 사용 Lock**: `handlers.py` 4개 핸들러 per-user `asyncio.Lock` 추가 (전자결재·계약서·회의실·프로젝트)
- **수금현황 Sheets 임포트**: `sheets_import.py` 매트릭스 + 테이블 이중 레이아웃 파싱

---

## 세션 XXIII — 2026-03-20

### 작업 내용 요약

- **GW 프로젝트 목록 크롤링 개선**
  - OBTDataGrid 그룹 컬럼 처리: `getColumns()` 재귀 순회로 리프 컬럼 수집
  - 검색 모달 UI 추가 (fund.html / fund.js)
  - 버그 7건 수정

---

## 세션 XIX~XXII — 2026-03-19~20

### 주요 기술 발견사항

#### OBTDataGrid 그룹 컬럼 재귀 순회 (세션 XXIII 정립)

```python
def _collect_leaf_columns(cols):
    """OBTDataGrid getColumns() 결과에서 리프 컬럼만 재귀 수집"""
    result = []
    for c in cols:
        if hasattr(c, 'columns') and c.columns:
            result.extend(_collect_leaf_columns(c.columns))
        else:
            result.append(c)
    return result
```

- `getColumns()` → 최상위 반환 (그룹 컬럼은 `.columns` 배열 보유)
- 리프 컬럼의 `c.header.text`로 헤더 매핑
- `c.name`으로 `getValue(row, fieldName)` 접근

---

## 세션 XVIII — 2026-03-19

### 주요 작업

- pytest 테스트 인프라 구축 (94개 → 133개로 증가)
- `approval_automation.py` 5831줄 → 7 Mixin 모듈로 분해
- `agent.py` 2103줄 → 4개 모듈로 분할
- Playwright `time.sleep` 93개 → `wait_for_timeout`으로 전환

---

## 중요 기술 패턴 모음

### 1. OBTDataGrid 용도코드 입력 후 팝업 처리 패턴 (세션 XXV)

```python
# Step 10: OBTDataGrid setSelection + keyboard.type + Enter
page.evaluate(f"""() => {{
    const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
    const fk = Object.keys(el).find(k => k.startsWith('__reactFiber'));
    let f = el[fk];
    for (let i = 0; i < 3; i++) f = f.return;
    const iface = f.stateNode.state.interface;
    iface.setSelection({{ rowIndex: 0, columnName: '{usage_col_name}' }});
    iface.focus();
}}""")
page.keyboard.type(usage_code, delay=30)
page.keyboard.press("Enter")

# Step 10-A: 자동 트리거 팝업 처리
from src.approval.budget_helpers import handle_auto_triggered_popup
result = handle_auto_triggered_popup(page, project_keyword, budget_keyword)
# result["success"] True면 팝업 처리 완료
# False + "팝업 미감지"면 step 11 fallback 사용
```

### 2. 공통 예산잔액 조회 팝업 구조 (세션 XIV~XXV 분석)

```
팝업 제목: H1 태그 "공통 예산잔액 조회" (CSS modal class 없음)
프로젝트 입력: input[placeholder='사업코드도움']  (x≈869, y≈363)
예산과목 입력: input[placeholder='예산과목코드도움']  (x≈869, y≈404)
  → 초기 disabled, 프로젝트 선택 후 활성화
  → Enter 입력 시 "예산과목코드도움" 서브 팝업 열림
서브 팝업: H1 "예산과목코드도움"
  → 테이블에서 2로 시작하는 5~7자리 코드 행 선택
  → 확인 버튼 클릭 → 메인 팝업으로 복귀
메인 팝업 확인 → 메인 폼에 예산정보 반영
```

### 3. 용도코드 예시

| 코드 | 설명 |
|------|------|
| 5020 | 프로젝트(외주공사비)_외주공사비 |

### 4. 예산과목코드 예시

| 코드 | 설명 | 그룹 |
|------|------|------|
| 2300700 | 냉난방 | 디자인스튜디오 |
| 4300700 | 냉난방 | 신규컨설팅/해외사업 |

### 5. GW 프로젝트 코드 파싱

```python
# "GS-25-0088. [종로] 메디빌더 음향공사" → project_keyword 추출
project_keyword = project.split(". ", 1)[-1].split("]")[-1].strip()
# → "메디빌더 음향공사"
```

---


---

## 세션 XXIX — 2026-03-27

### 작업 내용 요약

#### GW 직접 탐색 (Chrome MCP)

- **URL 탐색**: `gw.glowseoul.co.kr` → BN 모듈(예산관리) 직접 접근
- **GW 프로젝트 목록 확인**: NPCodePicker API 파라미터 확인 (XHR 인터셉터 활용)
  - `langKind:"KOR", coCd:"1000", empCd:"GS251105", gisu:"9", helpTy:"SMGT_CODE"`
  - 총 197개 전체 / 157개 유효 프로젝트 (GS-24-XXXX ~ GS-26-XXXX 패턴)
- **RealGrid v1.0 API 확인**:
  - `window.Grids.getActiveGrid().getDataProvider()` 방식이 동작함
  - 15개 데이터 필드 직접 확인: `lastYn, bottomFg, divFg, defNm, bgtCd, bgtNm, abgtSumAm, unitAm, subAm, sumRt, T0AbgtSumAm, T0UnitAm, T0SubAm, T0SumRt, T0TotalSumRt`
  - 계층 구조: divFg (1:장, 2:관, 3:항, 4:목), lastYn (말단여부), bottomFg (상위여부)
- **GW CSRF 확인**: 직접 API fetch 불가 ("허용된 쿠키 인증 URL이 아닙니다") → Playwright 필요

#### 코드 변경사항

1. **`src/fund_table/db.py`**: `budget_actual` 테이블 확장
   - 마이그레이션 추가: `gw_project_code, gisu, def_nm, div_fg, is_leaf` 컬럼
   - `save_budget_actual()` 함수 확장: 동일 project_id+gisu 데이터 교체 지원

2. **`src/fund_table/budget_crawler.py`**: RealGrid DataProvider 방식 추가
   - `_extract_data()` 최우선 방법으로 `window.Grids` DataProvider 추가 (시도 0)
   - `_transform_grid_data()` 개선: def_nm, div_fg, is_leaf, gw_project_code 저장

3. **`src/fund_table/routes.py`**: 5개 신규 API 엔드포인트 추가
   - `GET /api/fund/projects/{id}/budget/detail` — 계층 구조 예실데이터 조회
   - `POST /api/fund/projects/{id}/budget/sync-actuals` — 단일 프로젝트 동기화
   - `POST /api/fund/gw/sync-all-budget-actuals` — 전체 일괄 동기화
   - `GET /api/fund/gw/project-list` — GW 캐시 프로젝트 목록
   - `GET /api/fund/budget/cross-project` — 전체 집계 (집행률 상위 N)

4. **`src/chatbot/static/fund.js`**: 예실대비 UI 업그레이드
   - `loadBudget()` 계층 구조 테이블 렌더링 (장/관/항/목 배지, 들여쓰기)
   - `_renderBudgetTopChart()` 신규 함수: 집행액 상위 5 과목 수평 바 차트

5. **`src/chatbot/static/fund.html`**: `budgetTopChart` 컨테이너 div 추가

6. **`src/chatbot/static/fund.css`**: 신규 CSS 추가
   - `.budget-level-badge` (lv1~lv4 색상 코딩)
   - `.budget-row-parent` (상위 행 강조)
   - `#budgetTopChart`, `.chart-mini-*` (미니 차트 스타일)

### 테스트 결과

- pytest: **133/133 PASS** (이전 세션 94개에서 133개로 증가)

### 발견된 기술 사항

- **RealGrid 접근법**: `window.Grids.getActiveGrid()` → `getDataProvider()` → `getRowCount()` + `getJsonRow(i)`
- **사업코드 피커 제약**: iframe 내부, cross-origin 제한으로 JS 직접 접근 불가 → XHR 인터셉터로 API 응답 캡처 방식 사용
- **GW API 엔드포인트 패턴**: `/nonprofit/{화면코드}/{모듈코드}` (POST, CSRF 보호)


## 향후 관찰 필요 사항 (사용자 확인 예정)

1. **첨부파일 드래그앤드랍 방식** — 파일 업로드 UI 정확한 셀렉터 미확인
2. **참조문서 거는 법** — 전자결재 참조문서 연결 플로우 미확인
3. **예실대비현황(상세) 스크린샷 첨부** — 상세 화면 캡처 후 첨부 플로우 미확인
