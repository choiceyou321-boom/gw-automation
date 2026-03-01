# 세션 III 작업 기록 - 전자결재 자동화 + 대화 히스토리 DB

> 작업일: 2026-03-01
> 작업자: Claude (에이전트 팀 병렬 구현)

---

## 작업 계획

| 순서 | 작업 | 우선순위 | 상태 |
|------|------|----------|------|
| 1 | chat_db.py 생성 + app.py 연결 | 서브 | 완료 |
| 2 | 사이드바 대화 목록 UI | 서브 | 완료 |
| 3 | form_templates.py 생성 | 메인 | 완료 |
| 4 | approval_automation.py 생성 | 메인 | 완료 |
| 5 | agent.py 결재 핸들러 구현 | 메인 | 완료 |
| 6 | Phase 0: 결재 페이지 DOM 탐색 | 메인 | **미완** |
| 7 | 통합 테스트 | 전체 | **미완** |

---

## 1. [서브] 대화 히스토리 DB

### 1-1. 신규 파일: `src/chatbot/chat_db.py` (200줄)

SQLite 기반 대화 히스토리 영구 저장 모듈.

**DB 위치**: `data/chatbot/chat_history.db`

**테이블 구조**:
```sql
-- 세션 테이블 (사용자별 대화 단위)
CREATE TABLE sessions (
    session_id TEXT,
    gw_id TEXT,
    title TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (gw_id, session_id)
);

-- 메시지 테이블 (개별 메시지)
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    gw_id TEXT NOT NULL,
    role TEXT NOT NULL,          -- 'user' / 'assistant'
    content TEXT NOT NULL,
    action TEXT,                 -- 도구 이름 (예: reserve_meeting_room)
    action_result TEXT,          -- 도구 실행 결과
    file_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**함수 목록**:
| 함수 | 설명 |
|------|------|
| `_get_db()` | SQLite 연결 + 테이블 자동 생성 (user_db.py 패턴) |
| `save_message(gw_id, session_id, role, content, ...)` | 메시지 저장 + 세션 updated_at 갱신 |
| `get_session_history(gw_id, session_id, limit=40)` | 최신 limit개 메시지 시간순 반환 |
| `list_sessions(gw_id)` | 사용자 세션 목록 (최신순, 마지막 메시지 미리보기 포함) |
| `delete_session(gw_id, session_id)` | 세션 + 메시지 삭제 |
| `get_or_create_session(gw_id, session_id, title)` | 세션 조회/생성 |
| `update_session_title(gw_id, session_id, title)` | 세션 제목 변경 |

**설계 포인트**:
- `user_db.py`의 `_get_db()` 패턴 그대로 따름 (sqlite3.Row, try/finally)
- `list_sessions()`는 서브쿼리로 마지막 메시지 미리보기 포함
- `get_session_history()`는 `ORDER BY id DESC LIMIT ?` 후 `reversed()`로 시간순 정렬

---

### 1-2. 수정 파일: `src/chatbot/app.py`

**변경 전** (인메모리):
```python
conversation_sessions: dict[str, list] = {}  # 서버 재시작 시 소실
user_session_key = f"{user['gw_id']}_{session_id}"
history = conversation_sessions[user_session_key]
```

**변경 후** (SQLite DB):
```python
from .chat_db import save_message, get_session_history, list_sessions, delete_session, get_or_create_session, update_session_title

# /chat 엔드포인트에서:
session_info = get_or_create_session(gw_id, session_id)
history_rows = get_session_history(gw_id, session_id, limit=40)
history = [{"role": row["role"], "content": row["content"]} for row in history_rows]
# ... Gemini 호출 ...
save_message(gw_id, session_id, "user", request_body.message, file_count=len(files))
save_message(gw_id, session_id, "assistant", result["response"], action=..., action_result=...)
```

**변경 사항 상세**:

| 위치 | 변경 전 | 변경 후 |
|------|---------|---------|
| 라인 29 | (없음) | `from .chat_db import ...` 6개 함수 import |
| 라인 52-53 | `conversation_sessions: dict = {}` | **삭제됨** |
| `/chat` (라인 300-372) | dict에서 히스토리 로드/저장 | DB에서 로드, `save_message()` 2회 호출 |
| `/chat` (라인 348-354) | (없음) | 첫 메시지 → 세션 제목 자동 설정 (50자 cut) |
| `/history/{id}` GET (라인 418-423) | `conversation_sessions.get()` | `require_auth()` + `get_session_history()` |
| `/history/{id}` DELETE (라인 426-431) | `del conversation_sessions[...]` | `require_auth()` + `delete_session()` |
| `/sessions` GET (라인 434-439) | **신규 엔드포인트** | `require_auth()` + `list_sessions()` |
| `save_chat_log()` | 그대로 유지 | 그대로 유지 (이중 백업) |

**새 API 엔드포인트**:
```
GET /sessions → {"sessions": [{session_id, title, created_at, updated_at, last_message}, ...]}
```

---

### 1-3. 수정 파일: `src/chatbot/static/index.html`

사이드바의 `.quick-actions`와 `.sidebar-footer` 사이에 대화 목록 영역 추가:

```html
<!-- 라인 87-93: 이전 대화 목록 (신규) -->
<div class="chat-history" id="chatHistory">
  <p class="quick-label">이전 대화</p>
  <div class="history-list" id="historyList">
    <!-- JS로 동적 생성 -->
  </div>
</div>
```

---

### 1-4. 수정 파일: `src/chatbot/static/app.js`

**추가된 함수** (라인 623-761):

| 함수 | 설명 |
|------|------|
| `loadSessions()` | `/sessions` API 호출 → 사이드바에 세션 목록 렌더링 |
| `loadSession(sessionId)` | `/history/{id}` API 호출 → 채팅 영역에 히스토리 복원 |
| `deleteSession(sessionId)` | 확인 후 `DELETE /history/{id}` → 목록 갱신 |
| `formatSessionTime(dateStr)` | 상대 시간 표시 (방금/N분 전/N시간 전/N일 전/M월 D일) |

**기존 함수 수정**:
- `showMainApp()` 마지막에 `loadSessions()` 호출 (라인 67)
- `sendMessage()` 성공 후 `loadSessions()` 호출 (라인 284)
- `newChat()` 마지막에 `loadSessions()` 호출 (라인 572)

**세션 항목 HTML 구조**:
```html
<div class="history-item active" data-session="SESSION_ID">
  <div class="history-title">세션 제목 또는 미리보기</div>
  <div class="history-time">3분 전</div>
  <button class="history-delete">&times;</button>
</div>
```

---

### 1-5. 수정 파일: `src/chatbot/static/style.css`

**추가된 스타일** (886행 이후):

| 클래스 | 스타일 |
|--------|--------|
| `.chat-history` | `flex: 1; overflow-y: auto; border-top` — 남은 공간 차지, 스크롤 |
| `.history-list` | `flex column, gap: 4px` |
| `.history-item` | `flex row, padding 8px, border-radius, hover 배경` |
| `.history-item.active` | `accent 배경 + 보더` |
| `.history-title` | `text-overflow: ellipsis` |
| `.history-time` | `11px, text-muted` |
| `.history-delete` | `opacity: 0 → hover 시 1, 빨간색` |

**기존 수정**: `.quick-actions`에서 `flex: 1` 제거 → `.chat-history`가 남은 공간 차지

---

## 2. [메인] 전자결재 자동 작성

### 2-1. 신규 파일: `src/approval/form_templates.py` (55줄)

양식별 필드 매핑 정의. 현재 지출결의서 1개.

```python
FORM_TEMPLATES = {
    "지출결의서": {
        "search_keyword": "지출결의서",
        "display_name": "[프로젝트]지출결의서",
        "fields": {
            "project": {"label": "프로젝트명", "type": "text", "required": True},
            "title": {"label": "제목", "type": "subject", "required": True},
            "date": {"label": "지출일", "type": "date", "required": True},
            "description": {"label": "적요", "type": "text", "required": False},
            "items": {"type": "table", "columns": ["항목", "금액", "비고"], "required": True},
            "total_amount": {"label": "합계", "type": "number", "required": True},
            "payee": {"label": "지급처", "type": "text", "required": False},
            "bank_info": {"label": "계좌정보", "type": "text", "required": False},
        },
        "approval_line": {
            "drafter": "auto",    # 기안자 = 로그인 사용자
            "agree": "신동관",     # 합의
            "final": "최기영",     # 최종결재
        },
    },
}
```

**함수**:
- `get_template(form_name)` — 정확 매칭 + 부분 매칭
- `get_required_fields(form_name)` — 필수 필드 라벨 목록

---

### 2-2. 신규 파일: `src/approval/approval_automation.py` (323줄)

Playwright 기반 전자결재 폼 자동화 클래스.

**클래스**: `ApprovalAutomation(page: Page, user_context: dict)`

**메서드 목록**:

| 메서드 | 설명 |
|--------|------|
| `create_expense_report(data)` | 지출결의서 전체 플로우 (이동→양식→채우기→보관) |
| `_navigate_to_approval_write()` | 전자결재 → 결재작성 페이지 이동 |
| `_select_form(form_name)` | 양식 검색 + 선택 + iframe 감지 |
| `_detect_form_frame()` | 양식이 로드된 iframe 감지 (input 5개 이상) |
| `_fill_field_by_label(label, value)` | 라벨 기반 필드 채우기 (TD xpath 패턴) |
| `_fill_expense_fields(data)` | 지출결의서 필드 매핑 후 채우기 |
| `_fill_table_items(items)` | 테이블 형태 항목 리스트 채우기 |
| `_set_approval_line()` | 결재선 설정 (Phase 0 후 구현 예정) |
| `_save_draft()` | 보관(임시저장) 버튼 클릭 |
| `_submit()` | 상신(제출) — Phase 2 예정 |

**핵심 패턴** (레거시 `fill_lbl` 기반):
```python
def _fill_field_by_label(self, label, value):
    lbl_el = frame.locator(f"td:has-text('{label}')").first
    inp = lbl_el.locator("xpath=following-sibling::td//input").first
    if not inp.is_visible():
        inp = lbl_el.locator("xpath=..//input").last
    inp.fill(str(value))
```

---

### 2-3. 수정 파일: `src/chatbot/agent.py`

**변경 1: Function Declaration 교체** (라인 38-66)

변경 전:
```python
name="submit_expense_approval",
parameters: {expense_type, amount, description, has_receipt}
required: ["expense_type", "description"]
```

변경 후:
```python
name="submit_expense_approval",
parameters: {project, title, amount, date, description, items(ARRAY), payee, action}
required: ["title", "description"]
```

- `items`는 `ARRAY` 타입으로, 각 항목은 `{item, amount, note}` 구조
- `action` 파라미터 추가: `"confirm"` (확인) 또는 `"draft"` (실제 작성)

**변경 2: 핸들러 함수 교체** (라인 484-561)

변경 전 (stub):
```python
def handle_submit_expense_approval(params, user_context=None):
    return "그룹웨어 연동 후 자동 결재 신청이 가능합니다. (현재 준비 중)"
```

변경 후 (2단계 구현):
```python
def handle_submit_expense_approval(params, user_context=None):
    action = params.get("action", "confirm")

    if action != "draft":
        # 1단계: 확인 메시지 반환
        return "다음 내용으로 지출결의서를 작성합니다:\n..."

    # 2단계: Playwright로 실제 작성
    with ThreadPoolExecutor() as executor:
        future = executor.submit(_run_approval)
        result = future.result(timeout=120)
```

**변경 3: SYSTEM_PROMPT에 결재 흐름 추가** (라인 171-176)

```
## 경비 결재 흐름
사용자가 경비 결재를 요청하면:
1. 먼저 submit_expense_approval(action="confirm")으로 확인 메시지 생성
2. 사용자가 '확인', '맞아', '작성해줘' 등으로 승인하면
3. submit_expense_approval(action="draft")으로 실제 작성 실행
4. 정보가 부족하면 친근하게 물어보기 (제목, 금액, 내용 등)
```

---

## 3. 변경된 파일 전체 목록

| # | 파일 | 상태 | 줄수 | 담당 |
|---|------|------|------|------|
| 1 | `src/chatbot/chat_db.py` | **신규** | 200 | history-dev |
| 2 | `src/approval/form_templates.py` | **신규** | 55 | approval-dev |
| 3 | `src/approval/approval_automation.py` | **신규** | 323 | approval-dev |
| 4 | `src/chatbot/app.py` | **수정** | 471 | history-dev |
| 5 | `src/chatbot/agent.py` | **수정** | 741 | approval-dev |
| 6 | `src/chatbot/static/index.html` | **수정** | 170 | history-dev |
| 7 | `src/chatbot/static/app.js` | **수정** | 765 | history-dev |
| 8 | `src/chatbot/static/style.css` | **수정** | 956 | history-dev |
| 9 | `docs/SESSION_RESUME.md` | **갱신** | - | recorder |

---

## 4. 아키텍처 변경 요약

### Before (세션 II)
```
사용자 메시지 → /chat API → conversation_sessions(인메모리 dict) → Gemini
                            ↓
                   save_chat_log() → JSONL 파일 (읽기 불가)
```

### After (세션 III)
```
사용자 메시지 → /chat API → chat_db(SQLite) ← GET /sessions (세션 목록)
                |            ↓                 ← GET /history/{id} (히스토리)
                |     save_message() × 2       ← DELETE /history/{id} (삭제)
                |            ↓
                |     get_session_history() → Gemini 대화 컨텍스트
                |
                ↓
           save_chat_log() → JSONL 파일 (이중 백업, 유지)
```

### 결재 자동화 플로우 (신규)
```
"경비 결재 신청해줘"
    ↓
Gemini Function Calling → submit_expense_approval(action="confirm")
    ↓
handle_submit_expense_approval() → 확인 메시지 반환
    ↓
"확인" / "작성해줘"
    ↓
Gemini → submit_expense_approval(action="draft")
    ↓
ThreadPoolExecutor → session_manager.get_or_create_session()
    ↓
ApprovalAutomation(page) → _navigate → _select_form → _fill_fields → _save_draft
    ↓
"지출결의서가 임시저장되었습니다"
```

---

## 5. 미완료 항목

### Phase 0: 결재 페이지 DOM 탐색 (필수 선행)
- [ ] Playwright로 전자결재 → 결재작성 → 지출결의서 열기
- [ ] 실제 DOM 구조 캡쳐 (스크린샷 + HTML 덤프)
- [ ] 필드 selector 확정 (현재는 레거시 기반 추정값)
- [ ] 결재선 UI 구조 확인
- [ ] 보관/상신 버튼 selector 확정

### 통합 테스트
- [ ] 서버 시작 → 로그인 → 채팅 → 대화 저장 확인
- [ ] 서버 재시작 후 이전 대화 유지 확인
- [ ] 사이드바 세션 목록 표시 확인
- [ ] 세션 전환 (이전 대화 로드) 확인
- [ ] 세션 삭제 확인
- [ ] "경비 결재 신청해줘" → 확인 메시지 → "확인" → 작성 시도

---

## 6. 기술적 참고사항

### SQLite 동시성
- 각 함수에서 `_get_db()` → `conn.close()` 패턴 (단일 연결, 즉시 해제)
- FastAPI async 핸들러에서 동기 SQLite 호출 → 문제없음 (I/O 바운드 아님)
- 향후 동시 접속 많아지면 `aiosqlite` 전환 고려

### Playwright 결재 자동화
- `concurrent.futures.ThreadPoolExecutor`로 async/sync 분리
- `session_manager.get_or_create_session()`로 기존 GW 세션 재사용
- 양식 iframe 감지: `input` 5개 이상인 frame 탐색
- 라벨 기반 필드 채우기: `td:has-text() → xpath=following-sibling::td//input`
- **안전 우선**: 현재는 보관(임시저장)만, 상신은 Phase 2

### 프론트엔드 대화 목록
- 세션 목록은 메시지 전송, 새 대화, 로그인 시 자동 갱신
- 활성 세션에 `.active` 클래스 표시
- 삭제 버튼은 hover 시에만 표시 (opacity 0 → 1)
- 시간 표시: 방금 / N분 전 / N시간 전 / N일 전 / M월 D일
