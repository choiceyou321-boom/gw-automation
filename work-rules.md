# 작업 패턴 및 규칙

## 1. 팀 운영 규칙

### 에이전트 역할 분담
| 역할 | 담당 영역 | 금지 사항 |
|------|----------|-----------|
| 상담 팀장 | 요구사항 수집, 진행상황 보고 | 직접 코드 작성 금지 |
| researcher | 시스템 분석, API 탐색 | 기능 개발 금지 |
| approval-dev | 결재/회의실 자동화 개발 | 메일 모듈 수정 금지 |
| mail-dev | 메일 요약/Notion 연동 개발 | 결재 모듈 수정 금지 |

### 동시 작업 규칙
- 동일 파일 동시 편집 절대 금지
- 공통 모듈(auth, utils) 수정 시 팀 전체 공유 후 진행
- 각 에이전트는 자신의 담당 폴더(src/approval, src/mail 등)만 작업

---

## 2. 코드 작성 규칙

### 언어 및 스타일
- 언어: Python 3.11+
- 주석: 한국어 사용
- 변수명: 영문 snake_case, 의미 명확하게
- 함수명: 동사로 시작 (get_, create_, send_ 등)

### 파일 구조 규칙
```python
# 파일 상단 주석 양식
"""
모듈명: 결재 이력 조회
작성자: approval-dev
최종수정: 2026-03-01
설명: 과거 상신한 전자결재 목록을 조회하고 정리하는 모듈
"""
```

### 환경 변수 관리
- 비밀번호, API Key 등은 반드시 .env 파일에 저장
- .env 파일은 절대 커밋/공유 금지
- config 로딩은 python-dotenv 사용

```python
# .env 예시
GW_URL=https://gw.glowseoul.co.kr
GW_USER_ID=사용자아이디
GW_USER_PW=비밀번호
NOTION_API_KEY=노션api키
NOTION_PAGE_ID=저장할페이지id
```

---

## 3. Playwright 작업 패턴

### 기본 패턴: 페이지 탐색
```python
async def navigate_to_menu(page, menu_path):
    """그룹웨어 메뉴로 이동하는 공통 패턴"""
    # 1. 메뉴 클릭
    # 2. 페이지 로딩 대기 (React SPA이므로 networkidle 대기)
    # 3. 요소 존재 확인
    await page.goto(f"{BASE_URL}/#/{menu_path}")
    await page.wait_for_load_state("networkidle")
```

### 기본 패턴: 로그인 세션 관리
```python
# 세션 저장 (로그인 후)
await context.storage_state(path="config/session.json")

# 세션 복원 (다음 실행 시)
context = await browser.new_context(storage_state="config/session.json")
```

### 기본 패턴: 네트워크 인터셉트 (API 캡처)
```python
async def capture_api_calls(page):
    """내부 API 호출을 캡처하여 기록"""
    api_logs = []

    async def on_response(response):
        if "/api/" in response.url or "/system/" in response.url:
            api_logs.append({
                "url": response.url,
                "method": response.request.method,
                "status": response.status,
            })

    page.on("response", on_response)
    return api_logs
```

### 기본 패턴: 에러 처리 및 재시도
```python
from playwright.async_api import TimeoutError

MAX_RETRIES = 3

async def safe_action(page, action_func, retries=MAX_RETRIES):
    """실패 시 재시도하는 안전한 실행 패턴"""
    for attempt in range(retries):
        try:
            return await action_func(page)
        except TimeoutError:
            if attempt < retries - 1:
                # 세션 만료 가능성 → 재로그인 시도
                await re_login(page)
            else:
                raise
```

---

## 4. 데이터 저장 패턴

### 수집 데이터 → 파일 저장
```python
import json
from datetime import datetime

def save_data(data, filename):
    """수집 데이터를 JSON으로 저장"""
    filepath = f"data/{filename}_{datetime.now().strftime('%Y%m%d')}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
```

### Notion 저장 패턴
```python
import httpx

async def save_to_notion(api_key, page_id, content):
    """Notion 페이지에 내용 저장"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    # Notion API 호출로 블록 추가
```

---

## 5. 로그 규칙

### 로그 파일 위치
- 실행 로그: `logs/YYYY-MM-DD_실행명.log`
- 세션 로그: `logs/YYYY-MM-DD_session.md`
- 에러 로그: `logs/YYYY-MM-DD_error.log`

### 로그 레벨
| 레벨 | 용도 |
|------|------|
| INFO | 정상 실행 흐름 (로그인 성공, 데이터 수집 완료 등) |
| WARNING | 재시도 발생, 예상과 다른 응답 |
| ERROR | 실패, 예외 발생 |

### Python 로그 설정
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(f"logs/{date}_run.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
```

---

## 6. 테스트 규칙

### 테스트 순서
1. 단위 테스트: 개별 함수 동작 확인
2. 통합 테스트: 로그인 → 기능 실행 → 결과 확인
3. 사용자 확인: 비개발자에게 결과 보여주고 피드백

### 테스트 전 체크리스트
- [ ] .env 파일에 테스트용 계정 정보 설정됨
- [ ] 그룹웨어 접속 가능한 네트워크 환경
- [ ] Playwright 브라우저 설치 완료

---

## 7. 커밋 규칙

### 커밋 메시지 형식
```
[영역] 작업 내용

예시:
[auth] 로그인 세션 저장/복원 기능 추가
[approval] 결재 이력 조회 기능 구현
[mail] 안 읽은 메일 목록 추출 기능 추가
[meeting] 회의실 예약 현황 조회 기능 구현
[notion] Notion API 연동 모듈 작성
[config] 환경 변수 설정 파일 추가
[fix] 세션 만료 시 재로그인 오류 수정
```

### 커밋 전 확인
- 테스트 통과 확인
- .env 파일이 포함되지 않았는지 확인
- 다른 에이전트 담당 파일을 수정하지 않았는지 확인
