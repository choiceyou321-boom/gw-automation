# 다음 세션 시작 프롬프트 — v5 PM 분리·고도화 킥오프

> 작성: 2026-05-27 (이전 세션 종료 시점)
> 사용법: **다음 세션 첫 메시지에 아래 "시작 프롬프트"를 그대로 붙여넣기**

---

## ▶ 시작 프롬프트 (복사 → 붙여넣기)

```
v4 분리 후속 작업 — PM 프론트 분리 + 고도화 (v5) 킥오프.

# 사전 결정 사항 (이전 세션에서 확정)
- 분리 수준: 프론트만 분리 (이중 서버 구조). 백엔드 FastAPI 그대로
- FE 스택: React 18 + Vite + TanStack(Router+Query) + shadcn/ui + Tailwind + TypeScript (사용자 승인)
- 고도화 트랙: 3개 모두 — (A) 대시보드+아카이브+추천 (B) 간트+칸반 (C) 계약→수금→이체 + 알림 다이제스트
- 구현 순서: v5 아키텍처 문서 먼저 → 1탭 PoC(대시보드) → 점진 마이그레이션
- 분리 우선순위: PM 트랙. GW Track A(export 마지막 1마일)는 사용자 시연 대기로 병렬

# 현재 상태 (master HEAD 58cbb93)
- v4 분리 4개 PR 머지 완료: #3(P1~P5 코어) + #4(P6 CRM + P8 홈택스) + #5(A+C+D) + #6(path 핫픽스)
- pytest 424/424 PASS
- 패키지: src/{shared,pm,gw,office,chatbot/handlers}/
- 챗봇 도구 39종 (PM 14 / GW 15 / Shared 5 / Office 5)
- DB: projects 53, milestones 783, todos 286, notifications 1556

# 첫 작업 (한 줄)
docs/ARCHITECTURE_v5.md 작성:
  - 이중 서버 구조 도면 (FastAPI :51749 ↔ Vite :5173)
  - 빌드 파이프라인 + nginx/FastAPI 정적 서빙 옵션
  - 폴더 구조 제안 (frontend/ 또는 apps/pm-web/)
  - 인증 흐름 (JWT 쿠키 same-origin vs CORS)
  - 9 탭 → TanStack Router 라우트 매핑
  - TanStack Query queryKey 명명 규칙
  - 컴포넌트 계층 + shadcn/ui 컴포넌트 인벤토리
  - 3개 고도화 트랙 통합 도면 (A/B/C 데이터 흐름)
  - Phase v5.0~v5.N 마이그레이션 로드맵 (Big-Bang 아닌 점진)

# 참고 파일
- docs/HANDOFF_v5_kickoff.md  ← 모든 컨텍스트 (반드시 먼저 읽기)
- docs/ARCHITECTURE_v4.md     ← 백엔드 분리 도면 (v5는 이걸 확장)
- docs/GW_AUTOMATION_INVENTORY.md
- src/pm/static/{fund.html,fund.js,fund.css} ← v5 대체 대상 (현재 12,396줄)
- src/pm/fund_table/routes.py ← 83 API endpoint (Vite proxy 대상)

# 진행 방식
1) docs/HANDOFF_v5_kickoff.md 먼저 읽기 (컨텍스트 복원)
2) ARCHITECTURE_v5.md 작성 (브랜치: feature/v5-arch-doc)
3) PR 생성 → 사용자 리뷰 → 머지
4) 그 다음 세션에서 frontend/ 초기 셋업 (Phase v5.1)
```

---

## 시작 직후 추천 검증 명령 (sanity check)

```bash
cd "/Users/tg_mac_mini/Documents/자동화 work"

git branch --show-current       # master
git log --oneline -3            # 58cbb93 최상단 확인
.venv/bin/python -m pytest -q --tb=no   # 424 passed
.venv/bin/python -c "from src.pm.fund_table import db; print(len(db.list_projects()))"   # 53
```

---

## 즉시 시작 안 하는 경우 (다른 우선순위 발생 시)

병렬로 진행 가능한 대안:
- **Track A 시연**: 사용자가 GW에서 1~5페이지 클릭 시퀀스 시연 → `scripts/track_a_capture.py` 실행 → selectors.py 머지
- **운영 배포**: Docker + Nginx + 환경 변수 정리 → 외부 접근 가능 상태로
- **PM 외 도메인 손보기**: 영업관리(SAL)/예산관리(BUDGET) 신규 모듈 도입

→ 자세한 옵션 E~K는 `docs/HANDOFF_v5_kickoff.md` § 7 참고.
