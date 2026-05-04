"""Estimate total trip cost: driving, accommodation, tickets, food."""
from __future__ import annotations

# Cost rates
FUEL_RATE_PER_KM = 0.08  # ~8L/100km at ¥1/L
TOLL_RATE_PER_KM = 0.45  # Highway toll per km
ACCOMODATION_COSTS = {
    "economy": 200,
    "midrange": 400,
    "luxury": 800,
}
FOOD_DAILY_COSTS = {
    "economy": 80,
    "midrange": 150,
    "luxury": 300,
}


def estimate_trip_cost(
    total_distance_km: float,
    num_days: int,
    ticket_cost: float,
    pass_savings: float = 0,
    travel_style: str = "midrange",
) -> dict:
    """Calculate complete trip cost breakdown.

    Args:
        total_distance_km: total driving distance for the trip
        num_days: number of travel days
        ticket_cost: sum of all ticket prices (without pass)
        pass_savings: amount saved by using annual passes
        travel_style: "economy", "midrange", or "luxury"

    Returns:
        {
            "driving": {fuel, tolls, total},
            "accommodation": {per_night, nights, total},
            "tickets": {raw, savings, net},
            "food": {daily, total},
            "grand_total": float,
        }
    """
    if travel_style not in ACCOMODATION_COSTS:
        travel_style = "midrange"

    fuel_cost = round(total_distance_km * FUEL_RATE_PER_KM, 1)
    toll_cost = round(total_distance_km * TOLL_RATE_PER_KM, 1)
    driving_total = fuel_cost + toll_cost

    nights = max(num_days - 1, 0)
    per_night = ACCOMODATION_COSTS[travel_style]
    accommodation_total = nights * per_night

    daily_food = FOOD_DAILY_COSTS[travel_style]
    food_total = num_days * daily_food

    net_tickets = max(ticket_cost - pass_savings, 0)

    grand_total = driving_total + accommodation_total + net_tickets + food_total

    return {
        "driving": {
            "fuel": fuel_cost,
            "tolls": toll_cost,
            "total": round(driving_total, 1),
        },
        "accommodation": {
            "per_night": per_night,
            "nights": nights,
            "total": accommodation_total,
        },
        "tickets": {
            "raw": ticket_cost,
            "savings": pass_savings,
            "net": net_tickets,
        },
        "food": {
            "daily": daily_food,
            "total": food_total,
        },
        "grand_total": round(grand_total, 1),
    }
