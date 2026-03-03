"""챗봇 예약 취소 기능 테스트"""
import os, sys, json, asyncio
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv('config/.env')

from src.chatbot.agent import analyze_and_route

async def test():
    # 테스트 1: 예약 현황 확인 후 취소 흐름
    print("=== 테스트 1: '내일 예약 취소하고 싶어' ===")
    r1 = await analyze_and_route("내일 예약 취소하고 싶어")
    print(f"Action: {r1['action']}")
    print(f"Response: {r1['response']}")

    print("\n" + "="*50)

    # 테스트 2: 구체적 정보로 바로 취소 (먼저 예약 하나 생성)
    print("=== 테스트 2: 예약 생성 후 취소 ===")
    r2 = await analyze_and_route("내일 오후 4시에 5시까지 3번 회의실 취소테스트 예약해줘")
    print(f"Action: {r2['action']}")
    print(f"Response: {r2['response']}")

    print("\n" + "-"*30)

    # 생성된 예약 취소
    print("=== 테스트 2-2: '내일 취소테스트 취소해줘' ===")
    r3 = await analyze_and_route("내일 취소테스트 예약 취소해줘")
    print(f"Action: {r3['action']}")
    print(f"Response: {r3['response']}")

asyncio.run(test())
