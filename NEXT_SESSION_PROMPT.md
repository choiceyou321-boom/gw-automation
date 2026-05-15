# 다음 세션 시작 프롬프트

> 이 파일을 복사해서 Claude Code 새 세션 첫 메시지로 붙여넣기

---

## 붙여넣기용 프롬프트

```
gw-automation 프로젝트 세션 XLIX 시작.

📁 프로젝트 경로: D:\TG\gw-automation
📄 세션 기록: docs/SESSION_XLVIII.md 참고
📄 프로젝트 현황: docs/PROJECT_STATUS.md 참고
📄 개발자 가이드: DEVELOPER_GUIDE.md 참고

## 환경 정보
- Python 3.13 (WindowsApps), pytest는 가상환경 필요
- gh CLI v2.92.0 인증 완료 (choiceyou321-boom)
- 훅 설정 완료: Stop(pytest 자동 실행), PreToolUse(config/.env 커밋 차단)

## 이번 세션 목표

### 🔴 1순위 — 지출결의서 수정
`src/approval/expense.py`
- invoice 모달 열림 타이밍 이슈 수정
- 프로젝트 picker 선택 로직 수정
- 실 GW에서 E2E 검증

### 🔴 2순위 — 선급금요청 E2E 완성
`src/approval/other_forms.py`
- 그리드 필수 필드 자동 입력 완성
- keyboard.type + Enter 시퀀스 검증

### 🟡 3순위 — Task 31 (여유 있으면)
잔존 좌표 의존 코드 8개 → 셀렉터 기반으로 교체

시작 전에 `docs/SESSION_XLVIII.md` 먼저 읽고 이전 세션 작업 파악 후 진행해줘.
```

---

## 빠른 컨텍스트 요약 (세션 시작 시 참고)

### 핵심 파일 구조
```
src/approval/
├── approval_automation.py   # 진입점 (Mixin 조합)
├── expense.py               # 지출결의서 (2450줄) ← 수정 대상
└── other_forms.py           # 선급금/연장근무/외근 (1079줄) ← 수정 대상
```

### 알려진 이슈
| 이슈 | 위치 | 증상 |
|------|------|------|
| invoice 모달 타이밍 | `expense.py` | 모달 열리기 전에 다음 단계 진행 |
| 프로젝트 picker | `expense.py` | 프로젝트 선택 후 확인 버튼 미클릭 or 잘못된 셀렉터 |
| 선급금 그리드 필드 | `other_forms.py` | 그리드 셀 입력 후 값 미반영 |

### GW 핵심 기술 패턴
- **OBTDataGrid**: `__reactFiber` → depth 3 → `stateNode.state.interface`
- **OBTDialog2**: `dimClicker` 차단 → JS로 dialog 내부 직접 탐색
- **용도코드 팝업**: Enter 입력 → 즉시 팝업 처리 → 지급요청일 입력 순서 필수
- **grid 셀 입력**: `keyboard.type(value)` + `keyboard.press('Enter')` 시퀀스
