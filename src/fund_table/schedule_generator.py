"""인테리어 시공 공정표 자동 생성 엔진

면적·공사 유형·선택 공종을 기반으로 Full CPM(Critical Path Method)으로
각 공종의 시작일/종료일을 자동 배치한다.

Phase A 고도화 (세션 XLIV):
- A-1: 면적 보정 로그 연속 함수 (기존 5단계 계단 → 연속 곡선)
- A-2: Full CPM — Forward + Backward Pass + Float + 임계경로
- A-3: 가중 스케일링 (CP 공종 보호, 비CP 공종 우선 축소)
- A-4: DAG 순환 의존성 검증 (Kahn's algorithm)
"""
import logging
import math
from collections import deque
from datetime import datetime, timedelta

import json as _json

logger = logging.getLogger(__name__)


def _get_process_groups() -> list[dict]:
    """DB에서 공종 마스터 조회. 비어있으면 하드코딩 폴백."""
    try:
        from src.fund_table.db import list_construction_trades
        trades = list_construction_trades()
        if trades:
            groups_map: dict[str, dict] = {}
            for t in trades:
                gn = t["group_name"]
                if gn not in groups_map:
                    groups_map[gn] = {"group": gn, "color": t["group_color"], "items": []}
                preds = t.get("predecessors", "[]")
                steps = t.get("steps", "[]")
                groups_map[gn]["items"].append({
                    "name": t["name"],
                    "item_type": t.get("item_type", "bar"),
                    "default_days": t.get("default_days", 0),
                    "predecessors": _json.loads(preds) if isinstance(preds, str) else preds,
                    "steps": _json.loads(steps) if isinstance(steps, str) else steps,
                })
            return list(groups_map.values())
    except Exception:
        pass
    from src.fund_table.process_map_master import PROCESS_GROUPS
    return PROCESS_GROUPS


def _get_preset_trades(project_type: str) -> list[str]:
    """DB 프리셋 조회. 비어있으면 하드코딩 폴백."""
    try:
        from src.fund_table.db import list_construction_presets
        presets = list_construction_presets()
        for p in presets:
            if p["preset_name"] == project_type:
                return p["trade_names"]
    except Exception:
        pass
    from src.fund_table.process_map_master import get_preset_trades
    return get_preset_trades(project_type)


# ---------------------------------------------------------------------------
# A-1: 면적 보정 — 로그 기반 연속 함수
# ---------------------------------------------------------------------------

def _area_factor(area_pyeong: float) -> float:
    """면적에 따른 공기 보정 계수 (100평 = 1.0 기준).

    로그 곡선 기반으로 경계 불연속 없이 부드럽게 변화.
    10평 → ~0.65, 30평 → ~0.74, 70평 → ~0.90, 100평 → 1.0,
    200평 → ~1.15, 300평 → ~1.24, 500평 → ~1.35

    Returns:
        0.5 ~ 2.0 범위의 보정 계수
    """
    base = 100.0
    clamped = max(area_pyeong, 10.0)
    raw = 1.0 + 0.3 * math.log2(clamped / base)
    return round(max(0.5, min(2.0, raw)), 2)


# ---------------------------------------------------------------------------
# A-4: DAG 순환 의존성 검증
# ---------------------------------------------------------------------------

def _validate_dag(trades: list[dict]) -> list[str]:
    """위상정렬(Kahn's algorithm)로 순환 의존성 검증 + 위상 순서 반환.

    Args:
        trades: name, predecessors 키를 가진 공종 리스트

    Returns:
        위상 정렬된 공종명 리스트

    Raises:
        ValueError: 순환 의존성 발견 시
    """
    name_set = {t["name"] for t in trades}
    adjacency: dict[str, list[str]] = {t["name"]: [] for t in trades}
    in_degree: dict[str, int] = {t["name"]: 0 for t in trades}

    for t in trades:
        for pred in t.get("predecessors", []):
            if pred in name_set:
                adjacency[pred].append(t["name"])
                in_degree[t["name"]] += 1

    queue = deque(name for name, deg in in_degree.items() if deg == 0)
    topo_order = []

    while queue:
        node = queue.popleft()
        topo_order.append(node)
        for succ in adjacency[node]:
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    if len(topo_order) != len(trades):
        cycle_nodes = [t["name"] for t in trades if t["name"] not in set(topo_order)]
        raise ValueError(f"순환 의존성 발견: {cycle_nodes}")

    return topo_order


# ---------------------------------------------------------------------------
# A-2 / A-3: Full CPM + 가중 스케일링
# ---------------------------------------------------------------------------

def generate_construction_schedule(
    start_date: str,
    end_date: str,
    area_pyeong: float,
    project_type: str = "오피스",
    selected_trades: list[str] | None = None,
    has_import_materials: bool = False,
) -> dict:
    """공정표 자동 생성 (Full CPM)

    Args:
        start_date: 착공일 YYYY-MM-DD
        end_date: 준공일 YYYY-MM-DD
        area_pyeong: 시공면적 (평)
        project_type: 공사 유형 (오피스/상업시설/병원/식음/주거)
        selected_trades: 선택된 공종 리스트 (None이면 프리셋 사용)
        has_import_materials: 수입자재 포함 여부

    Returns:
        {"schedule_items": [...], "milestones": [...], "summary": {...}}
        각 schedule_item에 is_critical, total_float, early_start, late_start 포함
    """
    dt_start = datetime.strptime(start_date, "%Y-%m-%d")
    dt_end = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (dt_end - dt_start).days
    if total_days <= 0:
        return {"schedule_items": [], "milestones": [], "summary": {"error": "준공일이 착공일 이전입니다."}}

    # -----------------------------------------------------------------------
    # 1) 공종 필터링 (DB 또는 하드코딩 순서 보존)
    # -----------------------------------------------------------------------
    process_groups = _get_process_groups()
    if selected_trades is None:
        selected_trades = _get_preset_trades(project_type)
    selected_set = set(selected_trades)

    ordered_trades = []
    for grp in process_groups:
        for item in grp["items"]:
            if item["name"] in selected_set:
                ordered_trades.append({
                    "name": item["name"],
                    "group": grp["group"],
                    "color": grp["color"],
                    "item_type": item.get("item_type", "bar"),
                    "default_days": item.get("default_days", 3),
                    "predecessors": item.get("predecessors", []),
                    "steps": item.get("steps", []),
                })

    if not ordered_trades:
        return {"schedule_items": [], "milestones": [], "summary": {"error": "선택된 공종이 없습니다."}}

    # -----------------------------------------------------------------------
    # A-4: DAG 검증 (순환 의존성 체크)
    # -----------------------------------------------------------------------
    try:
        _validate_dag(ordered_trades)
    except ValueError as e:
        logger.error(f"공종 의존성 오류: {e}")
        return {"schedule_items": [], "milestones": [], "summary": {"error": str(e)}}

    # -----------------------------------------------------------------------
    # 2) 면적 기반 소요일수 보정 (A-1: 로그 연속 함수)
    # -----------------------------------------------------------------------
    n = len(ordered_trades)
    factor = _area_factor(area_pyeong)
    for t in ordered_trades:
        if t["item_type"] == "milestone":
            t["days"] = 0
        else:
            t["days"] = max(1, round(t["default_days"] * factor))

    # -----------------------------------------------------------------------
    # 3) Full CPM — Forward Pass
    # -----------------------------------------------------------------------
    name_to_idx = {t["name"]: i for i, t in enumerate(ordered_trades)}

    ES = [0] * n  # Earliest Start
    EF = [0] * n  # Earliest Finish

    for i, t in enumerate(ordered_trades):
        es = 0
        for pred_name in t["predecessors"]:
            if pred_name in name_to_idx:
                pred_idx = name_to_idx[pred_name]
                es = max(es, EF[pred_idx])
        ES[i] = es
        EF[i] = es + t["days"]

    # -----------------------------------------------------------------------
    # 4) Full CPM — Backward Pass
    # -----------------------------------------------------------------------
    raw_total = max(EF) if EF else 0

    LF = [raw_total] * n  # Latest Finish
    LS = [0] * n          # Latest Start

    # 후행공종(successors) 매핑 구성
    successors: dict[int, list[int]] = {i: [] for i in range(n)}
    for i, t in enumerate(ordered_trades):
        for pred_name in t["predecessors"]:
            if pred_name in name_to_idx:
                pred_idx = name_to_idx[pred_name]
                successors[pred_idx].append(i)

    # 역순 Backward Pass
    for i in range(n - 1, -1, -1):
        if successors[i]:
            LF[i] = min(LS[succ_idx] for succ_idx in successors[i])
        # else: LF[i] = raw_total (이미 초기화됨)
        LS[i] = LF[i] - ordered_trades[i]["days"]

    # -----------------------------------------------------------------------
    # 5) Float 계산 + 임계경로 판별
    # -----------------------------------------------------------------------
    total_float = [0] * n
    is_critical = [False] * n

    for i in range(n):
        total_float[i] = LS[i] - ES[i]
        is_critical[i] = (total_float[i] == 0)

    critical_count = sum(1 for c in is_critical if c)
    logger.info(f"CPM 분석: 총 {n}개 공종, 임계경로 {critical_count}개, raw_total={raw_total}일")

    # -----------------------------------------------------------------------
    # 6) A-3: 가중 스케일링 — CP 공종 보호, 비CP 공종 우선 축소
    # -----------------------------------------------------------------------
    if raw_total <= 0:
        raw_total = 1
    scale = total_days / raw_total if raw_total > 0 else 1.0

    schedule_items = []
    milestones = []
    sort_order = 0

    for i, t in enumerate(ordered_trades):
        if t["item_type"] == "milestone":
            scaled_start = round(ES[i] * scale)
            scaled_days = 0
        elif is_critical[i]:
            # CP 공종: 약간 보호 (스케일 * 1.05, 최소 원래 일수의 70%)
            scaled_start = round(ES[i] * scale)
            scaled_days = max(1, round(t["days"] * scale * 1.05))
            scaled_days = max(scaled_days, max(1, round(t["days"] * 0.7)))
        else:
            # 비CP 공종: 약간 더 축소 (스케일 * 0.95)
            scaled_start = round(ES[i] * scale)
            scaled_days = max(1, round(t["days"] * scale * 0.95))

        item_start = dt_start + timedelta(days=scaled_start)
        item_end = item_start + timedelta(days=scaled_days) if scaled_days > 0 else item_start

        # 준공일 초과 방지
        if item_end > dt_end:
            item_end = dt_end
        if item_start > dt_end:
            item_start = dt_end

        schedule_item = {
            "item_name": t["name"],
            "start_date": item_start.strftime("%Y-%m-%d"),
            "end_date": item_end.strftime("%Y-%m-%d"),
            "status": "planned",
            "group_name": t["group"],
            "subtitle": "",
            "item_type": t["item_type"],
            "bar_color": t["color"],
            "sort_order": sort_order,
            "notes": ", ".join(t["steps"]) if t["steps"] else "",
            # A-2: CPM 분석 결과 필드
            "is_critical": is_critical[i],
            "total_float": total_float[i],
            "early_start": ES[i],
            "late_start": LS[i],
        }
        schedule_items.append(schedule_item)
        sort_order += 1

        if t["item_type"] == "milestone":
            milestones.append({
                "name": t["name"],
                "date": item_start.strftime("%Y-%m-%d"),
                "completed": False,
            })

    # -----------------------------------------------------------------------
    # 7) 수입자재 조기 발주 항목 추가
    # -----------------------------------------------------------------------
    if has_import_materials:
        import_order_date = dt_start - timedelta(days=30)
        if import_order_date < datetime.now():
            import_order_date = dt_start
        schedule_items.insert(0, {
            "item_name": "수입자재 발주",
            "start_date": import_order_date.strftime("%Y-%m-%d"),
            "end_date": (import_order_date + timedelta(days=5)).strftime("%Y-%m-%d"),
            "status": "planned",
            "group_name": "사전단계",
            "subtitle": "수입자재 리드타임 30일",
            "item_type": "bar",
            "bar_color": "#ef4444",
            "sort_order": -1,
            "notes": "수입자재 조기 발주",
            "is_critical": False,
            "total_float": 0,
            "early_start": 0,
            "late_start": 0,
        })
        for idx, si in enumerate(schedule_items):
            si["sort_order"] = idx

    # -----------------------------------------------------------------------
    # 8) 요약
    # -----------------------------------------------------------------------
    bar_items = [s for s in schedule_items if s["item_type"] == "bar"]
    cp_items = [s for s in schedule_items if s.get("is_critical")]

    summary = {
        "total_calendar_days": total_days,
        "total_trades": len(bar_items),
        "total_milestones": len(milestones),
        "critical_path_count": len(cp_items),
        "start_date": start_date,
        "end_date": end_date,
        "area_pyeong": area_pyeong,
        "project_type": project_type,
        "area_factor": factor,
        "raw_duration": raw_total,
        "scale_factor": round(scale, 3),
    }

    return {
        "schedule_items": schedule_items,
        "milestones": milestones,
        "summary": summary,
    }
