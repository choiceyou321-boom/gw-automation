# 다음 세션 시작 프롬프트 — 레거시 (gw-automation)

복사해서 다음 세션 첫 메시지에 붙여넣기:

```
이 리포는 레거시 GW 자동화 (gw-automation). PM 트랙은 별도 리포 glow-pm 으로 분리 완료 (2026-05-28).

# 호칭
- 글로우 PM = 별도 리포 /Users/tg_mac_mini/Documents/glow-pm (https://github.com/choiceyou321-boom/glow-pm)
- 레거시 챗봇 = 이 리포의 / (src/chatbot/static/index.html)
- 레거시 프로젝트 관리 = 이 리포의 /fund (src/pm/static/fund.html/js/css)

# 현재 상태
- master HEAD: 39f7591 (PR #31 v8.0 브랜드 리네임 머지 완료)
- 머지된 PR 합계: v5.0~v8.0 = 31개
- pytest 586 PASS (중복 9개 포함 — 정리 후보)
- 서버: .venv/bin/python run_chatbot.py → :51749

# 다음 작업 후보 (사용자 선택)
1. 챗봇 정리 — Smart Import는 글로우 PM에 있으니 챗봇은 GW 자동화 중심으로 축소
2. GW Track A 시연 — scripts/track_a_capture.py 사용자 시연 후 selectors.py 머지
3. frontend/ 잔존 제거 — 글로우 PM이 별도라 이 리포의 frontend/는 안 쓰임
4. src/pm/static/fund.* 레거시 제거 — 사용자 시연 충분 후
5. tests/unit/test_* 2.py 중복 9개 정리
6. 운영 배포 — Docker + nginx (이 리포 + glow-pm 분리 배포)
7. GW 신규 모듈 (PER/BUDGET/LOG/SAL/PUR) 진입 자동화

# 참고 문서
- docs/HANDOFF_2026-05-28_glow_pm_split.md ← 분리 시점 전체 컨텍스트 (먼저 읽기)
- docs/ARCHITECTURE_v5.md
- docs/HANDOFF_v5_kickoff.md (구버전)

# 진행 방식
1) docs/HANDOFF_2026-05-28_glow_pm_split.md 먼저 읽기
2) 사용자에게 다음 작업 1~7 중 무엇인지 묻기 (또는 자율 추천 채택)
3) 브랜치 + PR + 머지 패턴 그대로
```

## 검증 명령 (세션 시작 시)

```bash
cd "/Users/tg_mac_mini/Documents/자동화 work"
git log --oneline -3
.venv/bin/python -m pytest -q --tb=no   # 586 passed
.venv/bin/python run_chatbot.py         # :51749 기동
```
