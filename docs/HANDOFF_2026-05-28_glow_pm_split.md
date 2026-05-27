# 핸드오프 — 2026-05-28 (글로우 PM 분리 완료 시점)

> 이 리포 = **레거시 (gw-automation)** — 챗봇 + GW 자동화 + 레거시 `/fund`
> PM 트랙은 별도 리포로 분리됨 → [glow-pm](https://github.com/choiceyou321-boom/glow-pm)

---

## 1. 현재 master 상태

**HEAD**: `39f7591 feat(v8.0): 브랜드 리네임 — '글로우 PM' (#31)`

이 세션에서 머지된 PR 31개 (v5.0~v8.0):

| Phase | PR | 핵심 |
|---|---|---|
| v5.0~v5.10 | #7~#19 | 프론트엔드 신규 (React+Vite+TanStack+shadcn) + 12 라우트 + 인박스 + 인사이트 + Smart Import |
| v6.0~v6.5 | #22~#28 | 디자인 시스템 재구축 + 익스포트 + CRUD + Blind Spot |
| v7.0 | #29 | 사이드바 프로젝트 리스트 + 상단 탭 (레거시 정합) |
| v8.0 | #31 | "글로우 PM" 브랜드 |
| fix #30 | | /fund 캐시 무효화 |

## 2. 호칭 (이후 모든 커뮤니케이션)

| 호칭 | 대상 |
|---|---|
| **글로우 PM** | 별도 리포 `glow-pm` (https://github.com/choiceyou321-boom/glow-pm) |
| **레거시 챗봇** | 이 리포의 `/` (`src/chatbot/static/index.html`) |
| **레거시 프로젝트 관리** | 이 리포의 `/fund` (`src/pm/static/fund.html` + fund.js/css) |

## 3. 이 리포에 남은 자산

```
src/
├── chatbot/        ← 레거시 챗봇 (Gemini agent + tools + index.html)
├── pm/static/      ← 레거시 프로젝트 관리 (fund.html/js/css 12,396줄)
├── pm/fund_table/  ← PM 백엔드 (글로우 PM도 같은 코드 복사해서 사용)
├── gw/             ← GW 자동화 (approval + mail + meeting + vision)
├── office/         ← CRM + 세금계산서
└── shared/         ← auth + gw_session
frontend/           ← v5/v6/v7/v8 — /pm-v2 에서 서빙. 글로우 PM 분리 후
                      이 경로는 운영하지 않고 유지만 (별도 미러). 향후 삭제 가능.
```

## 4. 서버

| URL | 용도 |
|---|---|
| http://localhost:51749 | 레거시 FastAPI (`.venv/bin/python run_chatbot.py`) |
| http://localhost:51749/ | 레거시 챗봇 |
| http://localhost:51749/fund | 레거시 프로젝트 관리 |
| http://localhost:51749/pm-v2/ | (참고) 분리 전 v7/v8 잔존 — 글로우 PM이 별도 |

## 5. 후속 작업 후보 (이 리포 내)

- **레거시 정리** — `frontend/`, `src/pm/static/fund.{html,js,css}` 제거 (사용자 시연 충분 후)
- **챗봇 도구 39종 유지/축소** — Smart Import가 글로우 PM에 있으니 챗봇은 GW 자동화 중심으로
- **GW Track A 시연 대기** — `scripts/track_a_capture.py` 사용자 시연 후 selectors.py 머지
- **운영 배포** — Docker + nginx (별도 PR)
- **pytest 432 duplicate 정리** — `tests/unit/test_* 2.py` 9개 삭제

## 6. 검증 명령

```bash
cd "/Users/tg_mac_mini/Documents/자동화 work"
git log --oneline -3                     # 39f7591 최상단
.venv/bin/python -m pytest -q --tb=no    # 586 passed (duplicates 포함)
.venv/bin/python -c "from src.pm.fund_table import db; print(len(db.list_projects()))"  # 53
.venv/bin/python run_chatbot.py          # :51749 기동
```

## 7. 글로우 PM과의 관계

- PM 백엔드 코드는 **양 리포에 동일 복사본** 존재 (`src/pm/fund_table/`)
- 데이터 DB (`fund_management.db`)는 **각각 별도** (글로우 PM 백엔드는 자체 `backend/data/fund_management.db` 사용)
- 한쪽에서 데이터 변경 시 다른 쪽 미반영 — 분기 의도적
- ENCRYPTION_KEY는 공유 (양쪽 .env에 동일 값)
- users.db 도 양쪽 복사본이 같이 출발 (이후 개별 진화)
