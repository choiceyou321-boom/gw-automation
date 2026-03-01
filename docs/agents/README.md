# 에이전트 팀 구성 (gw-automation)

> 글로우서울 그룹웨어 자동화 프로젝트 팀

## 팀 개요

| 에이전트 | 역할 | 모델 | 상태 |
|----------|------|------|------|
| [team-lead](./team-lead.md) | 총괄/PM | Sonnet 4.6 | 활동 중 |
| [researcher](./researcher.md) | 시스템 분석 | Sonnet 4.6 | Task #1 완료 |
| [pm](./pm.md) | 사용자 상담 | Sonnet 4.6 | 대기 중 |
| [approval-dev](./approval-dev.md) | 결재 자동화 | Sonnet 4.6 | 대기 중 |
| [meeting-dev](./meeting-dev.md) | 회의실 예약 | Sonnet 4.6 | 모듈 완료 |
| [chatbot-dev](./chatbot-dev.md) | 챗봇 개발 | Sonnet 4.6 | 모듈 완료 |

## 아키텍처

```
사용자 ↔ 챗봇(웹UI) ↔ Gemini AI(의도분석) ↔ 자동화 모듈
                                                  ├── 회의실 예약 (meeting-dev)
                                                  ├── 결재 자동화 (approval-dev)
                                                  └── 메일 요약 (추후)
```

## 소통 흐름
- 사용자 ↔ team-lead ↔ 각 에이전트
- pm이 사용자 요구사항 정리/확인 담당
- 에이전트 간 소통 기록: [agent-log.md](../../agent-log.md)
