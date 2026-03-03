"""챗봇 예약 취소 대화 흐름 테스트 (대화 히스토리 포함)"""
import os, sys, json, asyncio
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv('config/.env')

from src.chatbot.agent import analyze_and_route

async def test():
    history = []

    # 1단계: 취소 요청
    print("=== [사용자] '내일 예약 취소하고 싶어' ===")
    r1 = await analyze_and_route("내일 예약 취소하고 싶어", conversation_history=history)
    print(f"Action: {r1['action']}")
    print(f"Response:\n{r1['response']}\n")
    history.append({"role": "user", "content": "내일 예약 취소하고 싶어"})
    history.append({"role": "assistant", "content": r1['response']})

    # 2단계: 사용자가 특정 예약 지정
    print("=== [사용자] '취소테스트 취소해줘' ===")
    r2 = await analyze_and_route("취소테스트 취소해줘", conversation_history=history)
    print(f"Action: {r2['action']}")
    print(f"Response:\n{r2['response']}\n")
    history.append({"role": "user", "content": "취소테스트 취소해줘"})
    history.append({"role": "assistant", "content": r2['response']})

    # 3단계: 취소 후 현황 확인
    print("=== [사용자] '내일 예약 현황 보여줘' ===")
    r3 = await analyze_and_route("내일 예약 현황 보여줘", conversation_history=history)
    print(f"Action: {r3['action']}")
    print(f"Response:\n{r3['response']}")

asyncio.run(test())
