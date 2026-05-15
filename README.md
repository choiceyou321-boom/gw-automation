# GW 자동화 프로젝트

글로우서울 그룹웨어(더존 Amaranth10/WEHAGO) 업무 자동화 시스템.
자연어 챗봇으로 회의실 예약, 전자결재, 메일 요약 등을 처리합니다.

---

## 문서 안내

| 문서 | 내용 |
|------|------|
| [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) | 개발자 가이드 — 기술 패턴, GW API, 양식 관리, 프로젝트 구조 |
| [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) | 사용자 매뉴얼 — 웹 챗봇/텔레그램 봇 사용법 |
| [`docs/GW_PAGES_ANALYSIS.md`](docs/GW_PAGES_ANALYSIS.md) | GW 페이지 분석 — DOM 구조, API 패턴 |
| [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) | 프로젝트 현황 스냅샷 |

---

## 현재 기능 상태

| 기능 | 상태 | 비고 |
|------|------|------|
| 회의실 예약/취소/조회 | ✅ 완료 | WEHAGO API (HMAC) |
| 지출결의서 자동 작성 | ✅ 완료 | Playwright 22단계 (mixin facade + 4모듈 분할) |
| 거래처등록 자동 작성 | ✅ 완료 | dzEditor API |
| 선급금요청 | 🔧 진행 중 | 그리드 필수 필드 입력 — 실 GW 검증 대기 |
| 연장근무/외근신청 | 🔧 진행 중 | HR 권한 계정 필요 |
| 임시보관 → 상신 | ✅ 완료 | 문서 검색 후 상신 |
| 메일 요약 | ✅ 완료 | 수신인(To) 본인만 |
| 계약서 자동 생성 | ✅ 완료 | DOCX 템플릿, 단건/다건 |
| 프로젝트 자금관리 (`/fund`) | ✅ 완료 | SQLite + REST API + 웹 UI |
| 예실대비 크롤링 | ✅ 완료 | RealGrid DataProvider |
| GW 자동 동기화 | ✅ 완료 | 매일 08:00 APScheduler |
| 텔레그램 봇 | ✅ 완료 | 웹 챗봇과 동일 기능 |
| 음성 인식 (STT) | ✅ 완료 | Google Cloud STT |
| Docker 헬스체크 | ✅ 완료 | `/health` 엔드포인트 (세션 XLIX) |
| 핸들러 안전 wrapper | ✅ 완료 | `_safe_handler` 34개 핸들러 일괄 적용 (세션 L) |

---

## 개발자 진입점

```
gw-automation/
├── run_chatbot.py          # 서버 실행 진입점
├── src/
│   ├── chatbot/
│   │   ├── agent.py        # Gemini 라우팅 (도구 선택)
│   │   ├── handlers.py     # 34개 핸들러 함수 + _safe_handler 데코레이터
│   │   ├── tools_schema.py # Function Calling 스키마
│   │   └── prompts.py      # 시스템 프롬프트 (105줄, 세션 L에서 -57% 압축)
│   ├── approval/                       # Mixin 조합 (세션 LI에 거대 파일 분할)
│   │   ├── approval_automation.py      # 전자결재 진입점 (Mixin 조합)
│   │   ├── expense.py                  # 지출결의서 mixin facade (2147줄, ↓ 4938)
│   │   ├── invoice_modal.py            # 매입(세금)계산서 모달 (1039줄, LI Phase B)
│   │   ├── project_picker.py           # 프로젝트 코드도움 모달 (812줄, LI Phase C)
│   │   ├── attachment.py               # 첨부파일 업로드 (136줄, L Phase A)
│   │   ├── budget_capture.py           # 예실대비 스크린샷 (137줄, L Phase A)
│   │   ├── other_forms.py              # 선급금/연장근무/외근/추천장려금 (2683줄)
│   │   ├── grid.py                     # OBTDataGrid 셀 입력 (596줄)
│   │   ├── budget_helpers.py           # 예산과목 헬퍼 (876줄)
│   │   └── base.py                     # 공통 유틸 + _find_first_visible + _GET_GRID_IFACE_JS
│   ├── fund_table/
│   │   ├── base_crawler.py # 신규 BaseCrawler (266줄, 세션 XLIX)
│   │   ├── routes.py       # 40+ REST API 엔드포인트
│   │   └── db.py           # SQLite DB (fund_management.db)
│   └── meeting/
│       └── reservation_api.py  # 회의실 API (HMAC)
├── tests/                  # pytest (가상환경 필요)
├── .github/workflows/      # CI 파이프라인 (구문/테스트/ruff)
└── DEVELOPER_GUIDE.md      # 기술 패턴 상세
```

**새 기능 추가 체크리스트**:
1. `handlers.py` — 핸들러 함수 추가 (`handle_xxx(params, user_context=None) -> str`)
2. `tools_schema.py` — Gemini 도구 스키마 추가
3. `handlers.py` — `TOOL_HANDLERS` dict에 등록 (`_safe_handler`는 자동 적용)
4. `pytest tests/unit/` 통과 확인 (CI에서도 자동 실행)

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| **AI** | Google Gemini 2.5 Flash (Function Calling) |
| **백엔드** | FastAPI (Python) |
| **브라우저 자동화** | Playwright (sync API) |
| **DB** | SQLite (사용자 + 대화 히스토리 + 자금관리) |
| **인증** | JWT + Fernet 대칭 암호화 |
| **API 통신** | httpx (회의실 예약 - HMAC 서명) |
| **프론트엔드** | Vanilla HTML/CSS/JS (다크 테마) |
| **봇** | python-telegram-bot |
| **배포** | Docker + Nginx + HTTPS |

---

## 빠른 시작

```bash
pip install -r requirements.txt
playwright install chromium

# config/.env 파일에 환경변수 설정 후
python run_chatbot.py
# http://localhost:51749
```

```bash
# 테스트 실행
pytest                    # 전체 (193개)
pytest tests/unit/        # 단위 테스트만
```

---

## 주의사항

- `config/.env` 파일은 절대 커밋하지 않음
- 전자결재는 "보관"(임시저장) 모드 — 사용자가 직접 확인 후 상신
- GW 비밀번호는 Fernet 암호화 저장, 평문 절대 커밋 금지
- 자세한 기술 패턴: [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md)

---

## 라이선스

내부 프로젝트 (글로우서울 PM팀)
