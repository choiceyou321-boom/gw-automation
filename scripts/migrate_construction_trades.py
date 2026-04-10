#!/usr/bin/env python3
"""
공종 마스터 데이터 마이그레이션 스크립트

process_map_master.py의 하드코딩 45공종 + 5 프리셋을 DB로 시드.
멱등성 보장: 이미 데이터가 있으면 건너뜀.

실행: python scripts/migrate_construction_trades.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fund_table.db import seed_construction_trades_from_master, list_construction_trades, list_construction_presets


def main():
    print("=== 공종 마스터 DB 마이그레이션 ===")

    result = seed_construction_trades_from_master()
    print(f"결과: {result['message']}")

    if result.get("success"):
        trades = list_construction_trades()
        presets = list_construction_presets()
        print(f"\n현재 DB 상태:")
        print(f"  공종: {len(trades)}개")
        print(f"  프리셋: {len(presets)}개")

        # 그룹별 공종 수 출력
        groups = {}
        for t in trades:
            g = t["group_name"]
            groups[g] = groups.get(g, 0) + 1
        print(f"\n그룹별 공종 수:")
        for g, c in groups.items():
            print(f"  {g}: {c}개")

        print(f"\n프리셋 목록:")
        for p in presets:
            print(f"  {p['preset_name']}: {len(p['trade_names'])}개 공종")
    else:
        print(f"오류: {result.get('message')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
