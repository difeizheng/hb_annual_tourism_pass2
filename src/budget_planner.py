"""Budget planner: generate optimal spending plans within a given budget."""
from __future__ import annotations

from src.seasonal_recommender import (
    MONTH_TO_SEASON,
    calculate_seasonal_score,
)
from src.trip_planner.play_duration import estimate_play_duration
from src.trip_planner.cost_estimator import (
    estimate_trip_cost,
    FUEL_RATE_PER_KM,
    TOLL_RATE_PER_KM,
    ACCOMODATION_COSTS,
    FOOD_DAILY_COSTS,
)


# Budget allocation ratios
TICKET_RATIO = 0.30
TRANSPORT_RATIO = 0.30
FOOD_RATIO = 0.20
ACCOMMODATION_RATIO = 0.20


def plan_budget(
    budget: float,
    spots: list[dict],
    pass_info: dict[str, dict],
    origin: dict,
    num_days: int,
    people: int,
    travel_month: int,
) -> dict:
    """Generate 3 budget plans within the given budget.

    Args:
        budget: total budget in yuan
        spots: list of spot dicts
        pass_info: pass info from build_pass_info
        origin: {name, lng, lat}
        num_days: 1-3
        people: 1-5
        travel_month: 1-12

    Returns:
        {plans: [...], best_plan_idx: int, budget_left: float}
    """
    season = MONTH_TO_SEASON[travel_month]
    travel_style = "midrange"

    # Score all spots for current season
    scored = []
    for spot in spots:
        if not spot.get("lng") or not spot.get("lat"):
            continue
        score, reason = calculate_seasonal_score(spot, season)
        if score == 0:
            continue
        play_hours = estimate_play_duration(
            spot.get("category", ""),
            spot.get("sub_category", ""),
            spot.get("level", ""),
            spot.get("price", 0),
        )
        scored.append({
            **spot,
            "_score": score,
            "_reason": reason,
            "_play_hours": play_hours,
        })

    scored.sort(key=lambda x: -x["_score"])

    # Compute non-ticket costs
    nights = max(num_days - 1, 0)
    transport_per_person = 200 * num_days  # rough estimate
    food_total = FOOD_DAILY_COSTS[travel_style] * num_days * people
    accom_total = ACCOMODATION_COSTS[travel_style] * nights

    fixed_costs = accom_total + food_total

    # ============ Plan A: Buy pass ============
    pass_plans = []
    for pid, pi in pass_info.items():
        # Spots covered by this pass with good seasonal score
        pass_spot_names = {s["name"] for s in pi["spots_detail"]}
        covered = [s for s in scored if s["name"] in pass_spot_names]
        covered_value = sum(s["price"] for s in covered)
        pass_savings = covered_value - pi["price"]

        if pass_savings <= 0:
            continue  # pass not worth it

        total_cost = pi["price"] + fixed_costs + transport_per_person * people
        if total_cost > budget:
            continue

        pass_plans.append({
            "pid": pid,
            "display": pi["display"],
            "pass_price": pi["price"],
            "spots_count": len(covered),
            "a5_count": sum(1 for s in covered if s.get("level") == "A5"),
            "total_cost": total_cost,
            "per_person": total_cost / people,
            "savings": pass_savings,
            "covered_spots": covered[:10],  # top 10
        })

    pass_plans.sort(key=lambda x: -x["savings"])
    best_pass = pass_plans[0] if pass_plans else None

    plan_a = {
        "type": "pass",
        "name": f"🎫 买年卡最省",
        "description": f"购买{best_pass['display'] if best_pass else '推荐年卡'}，覆盖景点最多最省",
        "total_cost": best_pass["total_cost"] if best_pass else budget + 1,
        "per_person": best_pass["per_person"] / people if best_pass and people > 0 else budget,
        "spots_count": best_pass["spots_count"] if best_pass else 0,
        "a5_count": best_pass["a5_count"] if best_pass else 0,
        "pass_id": best_pass["pid"] if best_pass else None,
        "pass_display": best_pass["display"] if best_pass else None,
        "pass_price": best_pass["pass_price"] if best_pass else 0,
        "savings": best_pass["savings"] if best_pass else 0,
        "spots": best_pass["covered_spots"] if best_pass else [],
        "feasible": best_pass is not None and best_pass["total_cost"] <= budget if best_pass else False,
        "breakdown": {
            "年卡": best_pass["pass_price"] if best_pass else 0,
            "交通": transport_per_person * people,
            "餐饮": food_total,
            "住宿": accom_total,
        } if best_pass else {},
    }

    # ============ Plan B: Self-pay flexible ============
    ticket_budget = (budget - fixed_costs) * TICKET_RATIO  # portion for tickets
    self_pay_spots = []
    self_pay_total = 0
    for s in scored:
        if self_pay_total + s["price"] > ticket_budget:
            break
        self_pay_spots.append(s)
        self_pay_total += s["price"]

    plan_b_total = self_pay_total + fixed_costs + transport_per_person * people

    plan_b = {
        "type": "self_pay",
        "name": f"🎟️ 自费灵活",
        "description": "按季节评分选景点，自费购票，灵活自由",
        "total_cost": plan_b_total,
        "per_person": plan_b_total / people if people > 0 else budget,
        "spots_count": len(self_pay_spots),
        "a5_count": sum(1 for s in self_pay_spots if s.get("level") == "A5"),
        "pass_id": None,
        "pass_display": None,
        "pass_price": 0,
        "savings": 0,
        "spots": self_pay_spots[:10],
        "feasible": plan_b_total <= budget,
        "breakdown": {
            "门票": self_pay_total,
            "交通": transport_per_person * people,
            "餐饮": food_total,
            "住宿": accom_total,
        },
    }

    # ============ Plan C: Mixed (pass + supplement) ============
    # Pick cheapest pass that covers good spots, then self-pay rest
    mixed_plan = None
    if pass_plans:
        # Try a mid-range pass
        mid_pass = pass_plans[min(len(pass_plans) - 1, len(pass_plans) // 2)]
        remaining_ticket_budget = (budget - fixed_costs - transport_per_person * people) - mid_pass["pass_price"]
        if remaining_ticket_budget > 0:
            # Self-pay for uncovered high-value spots
            mixed_spots = list(mid_pass.get("covered_spots", [])[:5])
            mixed_names = {s["name"] for s in mixed_spots}
            mixed_extra = 0
            for s in scored:
                if s["name"] in mixed_names:
                    continue
                if mixed_extra + s["price"] > remaining_ticket_budget:
                    break
                mixed_spots.append(s)
                mixed_extra += s["price"]
                mixed_names.add(s["name"])

            mixed_total = mid_pass["pass_price"] + mixed_extra + fixed_costs + transport_per_person * people
            mixed_plan = {
                "type": "mixed",
                "name": f"🔀 年卡+补差",
                "description": f"购买{mid_pass['display']} + 自费补充高价值景点",
                "total_cost": mixed_total,
                "per_person": mixed_total / people if people > 0 else budget,
                "spots_count": len(mixed_spots),
                "a5_count": sum(1 for s in mixed_spots if s.get("level") == "A5"),
                "pass_id": mid_pass["pid"],
                "pass_display": mid_pass["display"],
                "pass_price": mid_pass["pass_price"],
                "savings": mid_pass["savings"],
                "spots": mixed_spots[:10],
                "feasible": mixed_total <= budget,
                "breakdown": {
                    "年卡": mid_pass["pass_price"],
                    "补差门票": mixed_extra,
                    "交通": transport_per_person * people,
                    "餐饮": food_total,
                    "住宿": accom_total,
                },
            }

    plans = [plan_a, plan_b]
    if mixed_plan:
        plans.append(mixed_plan)

    # Find best feasible plan (most spots within budget)
    feasible = [p for p in plans if p["feasible"]]
    if feasible:
        best_idx = max(range(len(plans)), key=lambda i: (plans[i]["feasible"], plans[i]["spots_count"]))
        budget_left = budget - plans[best_idx]["total_cost"]
    else:
        best_idx = 0
        budget_left = 0

    return {
        "plans": plans,
        "best_plan_idx": best_idx,
        "budget_left": round(budget_left, 0),
    }
