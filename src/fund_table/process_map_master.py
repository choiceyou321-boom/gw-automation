"""인테리어 시공 공정표 마스터 데이터

Process_Map.xlsx (ALT_1 일반, ALT_2 확장형) 교육자료를 기반으로 구성.
각 공종에 기본 소요일수, 선행 공종, 하위 단계, 그룹 색상을 정의한다.
"""

# ──────────────────────────────────────────────
# 공종 그룹 마스터 (Process Map 기반)
# ──────────────────────────────────────────────
PROCESS_GROUPS = [
    # ── 1. 사전단계 ──
    {
        "group": "사전단계",
        "color": "#6b7280",
        "items": [
            {
                "name": "계약",
                "item_type": "milestone",
                "default_days": 0,
                "predecessors": [],
                "steps": [],
            },
            {
                "name": "현장사무소 개설",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["계약"],
                "steps": [],
            },
            {
                "name": "도면접수",
                "item_type": "bar",
                "default_days": 2,
                "predecessors": ["현장사무소 개설"],
                "steps": [],
            },
            {
                "name": "시공계획서 작성",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["도면접수"],
                "steps": ["공정관리", "품질관리", "안전관리", "환경관리"],
            },
            {
                "name": "시공계획서 발표 (P.C.M)",
                "item_type": "milestone",
                "default_days": 0,
                "predecessors": ["시공계획서 작성"],
                "steps": [],
            },
            {
                "name": "시공계획서 승인",
                "item_type": "milestone",
                "default_days": 0,
                "predecessors": ["시공계획서 발표 (P.C.M)"],
                "steps": [],
            },
            {
                "name": "Shop Drawing",
                "item_type": "bar",
                "default_days": 10,
                "predecessors": ["시공계획서 승인"],
                "steps": [
                    "먹매김도면승인", "오버랩도면승인", "벽체디테일도면승인",
                    "골조승인", "외부가공제작도면승인", "천정디테일도면승인", "준공도면",
                ],
            },
            {
                "name": "물량산출",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["시공계획서 승인"],
                "steps": [],
            },
            {
                "name": "착공",
                "item_type": "milestone",
                "default_days": 0,
                "predecessors": ["물량산출"],
                "steps": [],
            },
            {
                "name": "발주 (수입자재 外)",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["물량산출"],
                "steps": [],
            },
        ],
    },

    # ── 2. 구조/골조 ──
    {
        "group": "구조/골조",
        "color": "#f97316",
        "items": [
            {
                "name": "먹매김",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["착공"],
                "steps": ["레벨먹/검측/승인", "바닥기준선/승인", "바닥마감먹매김/승인"],
            },
            {
                "name": "조적",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["먹매김"],
                "steps": ["검수", "승인", "메지시공"],
            },
            {
                "name": "METAL STUD",
                "item_type": "bar",
                "default_days": 7,
                "predecessors": ["먹매김"],
                "steps": ["자재승인", "런너시공", "STUD시공", "검수/승인"],
            },
            {
                "name": "ST'L PIPE 구조틀",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["먹매김"],
                "steps": ["자재승인", "앙카/하스너시공", "PIPE시공", "검수/승인"],
            },
            {
                "name": "그리스트랩/트랜치",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["먹매김"],
                "steps": ["도면승인", "공장제작", "반입 및 설치/검수/승인"],
            },
            {
                "name": "방수미장",
                "item_type": "bar",
                "default_days": 12,
                "predecessors": ["조적"],
                "steps": [
                    "방수자재 승인", "파취", "고름몰탈",
                    "액체방수/검수/승인", "우레탄방수/검수/승인",
                    "담수", "보호몰탈", "미장",
                ],
            },
        ],
    },

    # ── 3. 문틀/프레임 ──
    {
        "group": "문틀/프레임",
        "color": "#8b5cf6",
        "items": [
            {
                "name": "목문틀",
                "item_type": "bar",
                "default_days": 10,
                "predecessors": ["METAL STUD"],
                "steps": [
                    "도면작성/승인/발주", "공장제작/검수/승인",
                    "현장반입/검수/승인", "설치/검수/승인", "보양",
                ],
            },
            {
                "name": "금속문틀 및 금속프레임",
                "item_type": "bar",
                "default_days": 10,
                "predecessors": ["METAL STUD"],
                "steps": [
                    "도면작성/승인/발주", "공장제작/검수/승인",
                    "현장반입/검수/승인", "설치/검수/승인", "보양",
                ],
            },
            {
                "name": "P.L 창틀",
                "item_type": "bar",
                "default_days": 10,
                "predecessors": ["METAL STUD"],
                "steps": [
                    "도면작성/승인/발주", "공장제작/검수/승인",
                    "현장반입/검수/승인", "설치/검수/승인", "보양",
                ],
            },
            {
                "name": "타일/석재 (벽체)",
                "item_type": "bar",
                "default_days": 8,
                "predecessors": ["방수미장"],
                "steps": [
                    "도면승인", "자재승인", "자재발주",
                    "자재검수", "자재반입/검수/승인", "시공",
                ],
            },
        ],
    },

    # ── 4. 천정 ──
    {
        "group": "천정",
        "color": "#14b8a6",
        "items": [
            {
                "name": "천정골조 (T-Bar, M-Bar)",
                "item_type": "bar",
                "default_days": 7,
                "predecessors": ["METAL STUD"],
                "steps": ["앙카 시공", "행거볼트 시공", "케링 시공", "M-Bar시공/검수/승인"],
            },
            {
                "name": "천정등박스",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["천정골조 (T-Bar, M-Bar)"],
                "steps": ["천정도면승인", "천정등박스 시공/검수/승인", "녹방지 페인트"],
            },
            {
                "name": "단열재 취부",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["천정골조 (T-Bar, M-Bar)"],
                "steps": ["단열재자재/승인", "단열재취부/검수/승인"],
            },
            {
                "name": "석고보드/합판 취부",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["천정등박스", "단열재 취부"],
                "steps": ["석고보드/합판 자재/승인", "석고보드/합판 취부/검수/승인", "시공"],
            },
            {
                "name": "등타공/기구타공",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["석고보드/합판 취부"],
                "steps": ["도면승인", "천정먹매김", "타공", "보강"],
            },
            {
                "name": "흡음판 취부",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["석고보드/합판 취부"],
                "steps": ["흡음판 자재/승인", "흡음판 취부/검수/승인", "시공"],
                "alt2_only": True,
            },
        ],
    },

    # ── 5. 벽체 마감 ──
    {
        "group": "벽체마감",
        "color": "#ec4899",
        "items": [
            {
                "name": "벽체 도장",
                "item_type": "bar",
                "default_days": 7,
                "predecessors": ["석고보드/합판 취부"],
                "steps": ["PUTTY", "샌딩", "도장재 자재/승인", "도장마감/검수/승인"],
            },
            {
                "name": "벽체 타일/석재",
                "item_type": "bar",
                "default_days": 8,
                "predecessors": ["석고보드/합판 취부"],
                "steps": [
                    "도면승인", "자재승인", "자재발주",
                    "자재반입", "자재검수/승인", "시공",
                ],
            },
            {
                "name": "도배",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["벽체 도장"],
                "steps": [
                    "도면승인", "자재승인", "자재발주",
                    "자재반입", "자재검수/승인", "시공",
                ],
            },
            {
                "name": "무늬목 판넬/원목",
                "item_type": "bar",
                "default_days": 7,
                "predecessors": ["석고보드/합판 취부"],
                "steps": ["도면승인", "공장제작/검수/승인", "현장반입 및 설치"],
            },
            {
                "name": "유리",
                "item_type": "bar",
                "default_days": 7,
                "predecessors": ["석고보드/합판 취부"],
                "steps": ["도면승인(H.W포함)", "실측", "발주", "공장제작", "현장시공"],
            },
            {
                "name": "재료분리대",
                "item_type": "bar",
                "default_days": 2,
                "predecessors": ["석고보드/합판 취부"],
                "steps": ["도면승인", "시공/검수/승인"],
            },
        ],
    },

    # ── 6. 천정 마감 ──
    {
        "group": "천정마감",
        "color": "#3b82f6",
        "items": [
            {
                "name": "천정 도배",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["등타공/기구타공"],
                "steps": [
                    "도면승인", "자재승인", "자재발주",
                    "자재반입", "자재검수/승인", "시공",
                ],
                "alt2_only": True,
            },
            {
                "name": "천정 도장",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["등타공/기구타공"],
                "steps": ["PUTTY", "샌딩", "도장재 자재/승인", "도장마감/검수/승인"],
            },
        ],
    },

    # ── 7. 바닥 마감 ──
    {
        "group": "바닥마감",
        "color": "#22c55e",
        "items": [
            {
                "name": "바닥미장",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["방수미장"],
                "steps": [],
            },
            {
                "name": "타일/석재 (바닥)",
                "item_type": "bar",
                "default_days": 8,
                "predecessors": ["바닥미장"],
                "steps": [
                    "도면승인", "자재승인", "자재발주",
                    "자재검수", "자재반입/검수/승인", "시공",
                ],
            },
            {
                "name": "P-TILE/비닐쉬트",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["바닥미장"],
                "steps": [
                    "도면승인", "자재승인", "자재발주",
                    "자재반입", "자재검수/승인", "시공",
                ],
            },
            {
                "name": "카펫",
                "item_type": "bar",
                "default_days": 4,
                "predecessors": ["바닥미장"],
                "steps": [
                    "도면승인", "자재승인", "자재발주",
                    "자재반입", "자재검수/승인", "시공",
                ],
            },
            {
                "name": "마루",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["바닥미장"],
                "steps": [
                    "도면승인", "자재승인", "자재발주",
                    "자재반입", "자재검수/승인", "시공",
                ],
            },
            {
                "name": "악세스플로어",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["바닥미장"],
                "steps": [
                    "도면승인", "자재승인", "자재발주",
                    "자재반입", "자재검수/승인", "시공",
                ],
            },
            {
                "name": "노출마감",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["바닥미장"],
                "steps": ["자재승인", "자재발주", "바탕고르기", "시공"],
            },
            {
                "name": "목재데크",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["바닥미장"],
                "steps": [
                    "도면승인", "자재승인", "자재발주",
                    "자재반입", "자재검수/승인", "시공",
                ],
                "alt2_only": True,
            },
        ],
    },

    # ── 8. 설비/가구 ──
    {
        "group": "설비/가구",
        "color": "#eab308",
        "items": [
            {
                "name": "주방기구 설치",
                "item_type": "bar",
                "default_days": 5,
                "predecessors": ["바닥미장"],
                "steps": ["자재승인", "발주", "자재반입/설치/검수/승인"],
            },
            {
                "name": "도시가스 공사",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["주방기구 설치"],
                "steps": [],
            },
            {
                "name": "위생기구/액세서리",
                "item_type": "bar",
                "default_days": 4,
                "predecessors": ["바닥미장"],
                "steps": ["자재승인", "발주", "자재반입/설치/검수/승인"],
            },
            {
                "name": "큐비클/유리시공",
                "item_type": "bar",
                "default_days": 4,
                "predecessors": ["바닥미장"],
                "steps": ["자재승인", "발주", "자재반입/설치/검수/승인"],
            },
            {
                "name": "붙박이가구",
                "item_type": "bar",
                "default_days": 10,
                "predecessors": ["벽체 도장"],
                "steps": [
                    "도면승인(H.W포함)", "실측", "발주",
                    "공장제작", "몸체시공", "문짝설치/검수/승인",
                ],
            },
            {
                "name": "창호",
                "item_type": "bar",
                "default_days": 10,
                "predecessors": ["벽체 도장"],
                "steps": [
                    "도면승인(H.W포함)", "실측", "발주",
                    "공장제작", "문짝설치/검수/승인", "하드웨어설치",
                ],
            },
            {
                "name": "이동가구 설치",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["붙박이가구"],
                "steps": ["도면승인", "공장제작/검수/승인", "현장반입 및 설치"],
            },
            {
                "name": "롤스크린 설치",
                "item_type": "bar",
                "default_days": 2,
                "predecessors": ["창호"],
                "steps": ["도면승인", "공장제작/검수/승인", "현장반입 및 설치"],
                "alt2_only": True,
            },
            {
                "name": "각종기구 설치",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["천정 도장"],
                "steps": [],
            },
            {
                "name": "크린룸 공사",
                "item_type": "bar",
                "default_days": 10,
                "predecessors": ["석고보드/합판 취부"],
                "steps": [
                    "도면승인", "자재승인", "자재발주",
                    "자재반입", "자재검수/승인", "시공",
                ],
                "alt2_only": True,
            },
        ],
    },

    # ── 9. 마무리 ──
    {
        "group": "마무리",
        "color": "#ef4444",
        "items": [
            {
                "name": "준공청소",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["이동가구 설치", "각종기구 설치"],
                "steps": ["보양지철거", "준공청소"],
            },
            {
                "name": "준공",
                "item_type": "milestone",
                "default_days": 0,
                "predecessors": ["준공청소"],
                "steps": [],
            },
            {
                "name": "인수인계",
                "item_type": "bar",
                "default_days": 3,
                "predecessors": ["준공청소"],
                "steps": ["TEST", "PUNCH LIST", "잉여자재인수인계", "준공", "현장사무실철수"],
                "alt2_only": True,
            },
        ],
    },
]


# ──────────────────────────────────────────────
# 공사 유형별 기본 포함 공종 프리셋
# ──────────────────────────────────────────────

# 모든 유형에 공통으로 포함되는 공종
_COMMON_TRADES = [
    "계약", "현장사무소 개설", "도면접수", "시공계획서 작성",
    "시공계획서 발표 (P.C.M)", "시공계획서 승인", "Shop Drawing",
    "물량산출", "착공", "발주 (수입자재 外)",
    "먹매김", "METAL STUD",
    "천정골조 (T-Bar, M-Bar)", "천정등박스", "석고보드/합판 취부", "등타공/기구타공",
    "천정 도장",
    "준공청소", "준공",
]

TYPE_PRESETS = {
    "오피스": _COMMON_TRADES + [
        "조적", "방수미장",
        "목문틀", "금속문틀 및 금속프레임",
        "단열재 취부",
        "벽체 도장", "도배", "재료분리대",
        "바닥미장", "카펫", "P-TILE/비닐쉬트",
        "위생기구/액세서리", "큐비클/유리시공",
        "붙박이가구", "창호", "이동가구 설치", "각종기구 설치",
        "악세스플로어",
    ],
    "상업시설": _COMMON_TRADES + [
        "조적", "방수미장",
        "목문틀", "금속문틀 및 금속프레임", "P.L 창틀",
        "단열재 취부",
        "벽체 도장", "벽체 타일/석재", "도배", "무늬목 판넬/원목", "유리", "재료분리대",
        "바닥미장", "타일/석재 (바닥)", "마루",
        "붙박이가구", "창호", "이동가구 설치", "각종기구 설치",
    ],
    "병원": _COMMON_TRADES + [
        "조적", "방수미장",
        "목문틀", "금속문틀 및 금속프레임",
        "단열재 취부",
        "벽체 도장", "벽체 타일/석재", "재료분리대",
        "바닥미장", "P-TILE/비닐쉬트", "타일/석재 (바닥)",
        "위생기구/액세서리", "큐비클/유리시공",
        "붙박이가구", "창호", "이동가구 설치", "각종기구 설치",
        "크린룸 공사",
    ],
    "식음": _COMMON_TRADES + [
        "조적", "ST'L PIPE 구조틀", "그리스트랩/트랜치", "방수미장",
        "목문틀", "금속문틀 및 금속프레임",
        "단열재 취부",
        "벽체 도장", "벽체 타일/석재", "도배", "유리",
        "바닥미장", "타일/석재 (바닥)", "노출마감",
        "주방기구 설치", "도시가스 공사", "위생기구/액세서리", "큐비클/유리시공",
        "붙박이가구", "창호", "이동가구 설치", "각종기구 설치",
    ],
    "주거": _COMMON_TRADES + [
        "조적", "방수미장",
        "목문틀", "금속문틀 및 금속프레임", "P.L 창틀",
        "단열재 취부",
        "벽체 도장", "도배", "벽체 타일/석재", "무늬목 판넬/원목",
        "바닥미장", "타일/석재 (바닥)", "마루",
        "위생기구/액세서리", "큐비클/유리시공",
        "붙박이가구", "창호", "이동가구 설치", "각종기구 설치",
        "롤스크린 설치",
    ],
}


def get_all_trade_names() -> list[str]:
    """전체 공종명 리스트 반환"""
    names = []
    for grp in PROCESS_GROUPS:
        for item in grp["items"]:
            names.append(item["name"])
    return names


def get_trade_map() -> dict:
    """공종명 → (group, item_dict) 매핑 딕셔너리"""
    trade_map = {}
    for grp in PROCESS_GROUPS:
        for item in grp["items"]:
            trade_map[item["name"]] = {
                "group": grp["group"],
                "color": grp["color"],
                **item,
            }
    return trade_map


def get_preset_trades(project_type: str) -> list[str]:
    """공사 유형에 해당하는 기본 공종 리스트 반환"""
    return TYPE_PRESETS.get(project_type, TYPE_PRESETS["오피스"])
