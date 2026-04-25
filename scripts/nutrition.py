#!/usr/bin/env python3
"""Nutrition tracker — natural-language meal logging.

Approach:
- User says: "chicken breast 200g, rice 1 cup, broccoli, olive oil"
- We match items against a compact food database (~80 common foods)
- Estimate calories, protein, fiber, sodium per portion (with sensible defaults)
- Aggregate daily and weekly
- Cross-correlate with energy/training data

This is a guide, not a precise tracker. We surface ranges, not single numbers.
"""

from __future__ import annotations

import json
import re
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .care_workspace import (
        atomic_write_text,
        load_profile,
        nutrition_path,
        nutrition_trends_path,
        save_profile,
        workspace_lock,
    )
except ImportError:
    from care_workspace import (  # type: ignore
        atomic_write_text,
        load_profile,
        nutrition_path,
        nutrition_trends_path,
        save_profile,
        workspace_lock,
    )


# Food database — calories per 100g, protein g per 100g, fiber g, sodium mg.
# Kept compact and commonly-eaten. Per 100g unless flagged "whole".
FOOD_DB: dict[str, dict[str, Any]] = {
    # Proteins
    "chicken breast":   {"kcal": 165, "protein": 31, "fiber": 0, "sodium": 75, "default_g": 150},
    "chicken thigh":    {"kcal": 209, "protein": 26, "fiber": 0, "sodium": 86, "default_g": 150},
    "salmon":           {"kcal": 208, "protein": 20, "fiber": 0, "sodium": 59, "default_g": 150},
    "tuna":             {"kcal": 132, "protein": 28, "fiber": 0, "sodium": 247, "default_g": 100},
    "egg":              {"kcal": 155, "protein": 13, "fiber": 0, "sodium": 124, "default_g": 50, "whole": True},
    "tofu":             {"kcal": 144, "protein": 17, "fiber": 2, "sodium": 14, "default_g": 150},
    "tempeh":           {"kcal": 192, "protein": 20, "fiber": 9, "sodium": 9, "default_g": 100},
    "ground beef":      {"kcal": 250, "protein": 26, "fiber": 0, "sodium": 75, "default_g": 150},
    "steak":            {"kcal": 271, "protein": 26, "fiber": 0, "sodium": 56, "default_g": 200},
    "pork":             {"kcal": 242, "protein": 27, "fiber": 0, "sodium": 62, "default_g": 150},
    "shrimp":           {"kcal": 99,  "protein": 24, "fiber": 0, "sodium": 111, "default_g": 100},
    "cottage cheese":   {"kcal": 98,  "protein": 11, "fiber": 0, "sodium": 364, "default_g": 200},
    "greek yogurt":     {"kcal": 59,  "protein": 10, "fiber": 0, "sodium": 36, "default_g": 200},
    "yogurt":           {"kcal": 61,  "protein": 3.5,"fiber": 0, "sodium": 46, "default_g": 200},
    "protein shake":    {"kcal": 120, "protein": 25, "fiber": 1, "sodium": 100, "default_g": 250},
    # Carbs
    "rice":             {"kcal": 130, "protein": 2.7,"fiber": 0.4,"sodium": 1, "default_g": 150},
    "white rice":       {"kcal": 130, "protein": 2.7,"fiber": 0.4,"sodium": 1, "default_g": 150},
    "brown rice":       {"kcal": 112, "protein": 2.6,"fiber": 1.8,"sodium": 5, "default_g": 150},
    "pasta":            {"kcal": 158, "protein": 5.8,"fiber": 1.8,"sodium": 6, "default_g": 200},
    "bread":            {"kcal": 265, "protein": 9,  "fiber": 2.7,"sodium": 491, "default_g": 60},
    "oats":             {"kcal": 379, "protein": 13, "fiber": 10, "sodium": 6, "default_g": 50},
    "potato":           {"kcal": 77,  "protein": 2,  "fiber": 2.2,"sodium": 6, "default_g": 200},
    "sweet potato":     {"kcal": 86,  "protein": 1.6,"fiber": 3,  "sodium": 55, "default_g": 200},
    "quinoa":           {"kcal": 120, "protein": 4.4,"fiber": 2.8,"sodium": 7, "default_g": 150},
    # Veg
    "broccoli":         {"kcal": 35,  "protein": 2.8,"fiber": 2.6,"sodium": 33, "default_g": 150},
    "spinach":          {"kcal": 23,  "protein": 2.9,"fiber": 2.2,"sodium": 79, "default_g": 100},
    "salad":            {"kcal": 20,  "protein": 1.4,"fiber": 1.6,"sodium": 28, "default_g": 200},
    "tomato":           {"kcal": 18,  "protein": 0.9,"fiber": 1.2,"sodium": 5, "default_g": 100},
    "cucumber":         {"kcal": 16,  "protein": 0.7,"fiber": 0.5,"sodium": 2, "default_g": 100},
    "carrot":           {"kcal": 41,  "protein": 0.9,"fiber": 2.8,"sodium": 69, "default_g": 100},
    "kale":             {"kcal": 49,  "protein": 4.3,"fiber": 4.1,"sodium": 38, "default_g": 100},
    "avocado":          {"kcal": 160, "protein": 2,  "fiber": 7,  "sodium": 7, "default_g": 100},
    "pepper":           {"kcal": 31,  "protein": 1,  "fiber": 2.1,"sodium": 4, "default_g": 100},
    "zucchini":         {"kcal": 17,  "protein": 1.2,"fiber": 1,  "sodium": 8, "default_g": 100},
    # Fruit
    "apple":            {"kcal": 52,  "protein": 0.3,"fiber": 2.4,"sodium": 1, "default_g": 150},
    "banana":           {"kcal": 89,  "protein": 1.1,"fiber": 2.6,"sodium": 1, "default_g": 120},
    "berries":          {"kcal": 57,  "protein": 0.7,"fiber": 2.4,"sodium": 1, "default_g": 100},
    "blueberries":      {"kcal": 57,  "protein": 0.7,"fiber": 2.4,"sodium": 1, "default_g": 100},
    "orange":           {"kcal": 47,  "protein": 0.9,"fiber": 2.4,"sodium": 0, "default_g": 150},
    # Fats
    "olive oil":        {"kcal": 884, "protein": 0,  "fiber": 0,  "sodium": 2, "default_g": 15},
    "butter":           {"kcal": 717, "protein": 0.9,"fiber": 0,  "sodium": 11, "default_g": 10},
    "almonds":          {"kcal": 579, "protein": 21, "fiber": 12, "sodium": 1, "default_g": 30},
    "peanut butter":    {"kcal": 588, "protein": 25, "fiber": 6,  "sodium": 459, "default_g": 30},
    "cheese":           {"kcal": 402, "protein": 25, "fiber": 0,  "sodium": 621, "default_g": 30},
    # Legumes
    "beans":            {"kcal": 127, "protein": 8.7,"fiber": 7.4,"sodium": 1, "default_g": 150},
    "lentils":          {"kcal": 116, "protein": 9,  "fiber": 7.9,"sodium": 2, "default_g": 150},
    "chickpeas":        {"kcal": 164, "protein": 8.9,"fiber": 7.6,"sodium": 7, "default_g": 150},
    # Drinks/snacks
    "milk":             {"kcal": 50,  "protein": 3.4,"fiber": 0,  "sodium": 44, "default_g": 250},
    "coffee":           {"kcal": 2,   "protein": 0.1,"fiber": 0,  "sodium": 5, "default_g": 250},
    "beer":             {"kcal": 43,  "protein": 0.5,"fiber": 0,  "sodium": 4, "default_g": 350},
    "wine":             {"kcal": 83,  "protein": 0.1,"fiber": 0,  "sodium": 4, "default_g": 150},
    "chocolate":        {"kcal": 546, "protein": 4.9,"fiber": 7,  "sodium": 24, "default_g": 30},
    "ice cream":        {"kcal": 207, "protein": 3.5,"fiber": 0.7,"sodium": 80, "default_g": 100},
    # Common composite meals (rough)
    "burrito":          {"kcal": 215, "protein": 9,  "fiber": 4,  "sodium": 480, "default_g": 350},
    "burger":           {"kcal": 295, "protein": 17, "fiber": 1.6,"sodium": 396, "default_g": 200},
    "pizza":            {"kcal": 266, "protein": 11, "fiber": 2.3,"sodium": 598, "default_g": 200},
    "sandwich":         {"kcal": 250, "protein": 12, "fiber": 2,  "sodium": 480, "default_g": 200},
    "salad bowl":       {"kcal": 90,  "protein": 5,  "fiber": 4,  "sodium": 400, "default_g": 350},
    "smoothie":         {"kcal": 80,  "protein": 4,  "fiber": 2,  "sodium": 50, "default_g": 350},
}


# Quantity parsers
_PORTION_PATTERNS = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*g\b"), 1.0),         # grams
    (re.compile(r"(\d+(?:\.\d+)?)\s*kg\b"), 1000.0),
    (re.compile(r"(\d+(?:\.\d+)?)\s*oz\b"), 28.35),       # ounces
    (re.compile(r"(\d+(?:\.\d+)?)\s*lb\b"), 453.6),
    (re.compile(r"(\d+(?:\.\d+)?)\s*cups?\b"), 240.0),    # cups
    (re.compile(r"(\d+(?:\.\d+)?)\s*tbsp\b"), 15.0),
    (re.compile(r"(\d+(?:\.\d+)?)\s*tsp\b"), 5.0),
    (re.compile(r"(\d+(?:\.\d+)?)\s*ml\b"), 1.0),
]


def _grams_for(item: str, food: dict[str, Any]) -> float:
    """Extract grams from item text, falling back to food default."""
    for pattern, multiplier in _PORTION_PATTERNS:
        m = pattern.search(item)
        if m:
            return float(m.group(1)) * multiplier
    # Number alone with no unit — assume default
    if food.get("whole"):
        m = re.search(r"^(\d+(?:\.\d+)?)\s+", item.strip())
        if m:
            return float(m.group(1)) * float(food["default_g"])
    return float(food.get("default_g", 100))


def parse_meal(text: str) -> dict[str, Any]:
    """Parse 'chicken 200g, rice 1 cup, broccoli, olive oil' into structured nutrition."""
    if not text:
        return {"items": [], "kcal": 0, "protein": 0, "fiber": 0, "sodium": 0}
    items_out = []
    total = {"kcal": 0.0, "protein": 0.0, "fiber": 0.0, "sodium": 0.0}
    for raw in re.split(r"[,;]|\bplus\b|\band\b", text.lower()):
        raw = raw.strip()
        if not raw:
            continue
        match_food = None
        match_name = None
        # Longest match wins (so "chicken breast" beats "chicken")
        for food_name in sorted(FOOD_DB, key=len, reverse=True):
            if food_name in raw:
                match_food = FOOD_DB[food_name]
                match_name = food_name
                break
        if not match_food:
            items_out.append({"raw": raw, "matched": False})
            continue
        grams = _grams_for(raw, match_food)
        scale = grams / 100.0
        item_kcal = match_food["kcal"] * scale
        item_protein = match_food["protein"] * scale
        item_fiber = match_food["fiber"] * scale
        item_sodium = match_food["sodium"] * scale
        items_out.append({
            "name": match_name,
            "raw": raw,
            "grams": round(grams, 1),
            "kcal": round(item_kcal),
            "protein": round(item_protein, 1),
            "fiber": round(item_fiber, 1),
            "sodium": round(item_sodium),
            "matched": True,
        })
        total["kcal"] += item_kcal
        total["protein"] += item_protein
        total["fiber"] += item_fiber
        total["sodium"] += item_sodium

    return {
        "items": items_out,
        "kcal": round(total["kcal"]),
        "protein": round(total["protein"], 1),
        "fiber": round(total["fiber"], 1),
        "sodium": round(total["sodium"]),
        "matched_count": sum(1 for i in items_out if i.get("matched")),
        "unmatched_count": sum(1 for i in items_out if not i.get("matched")),
    }


def log_meal(root: Path, person_id: str, text: str, when: str = "") -> dict[str, Any]:
    """Parse and persist a meal entry into profile.meals."""
    parsed = parse_meal(text)
    when = when or date.today().isoformat()
    entry = {
        "date": when,
        "raw": text,
        "kcal": parsed["kcal"],
        "protein": parsed["protein"],
        "fiber": parsed["fiber"],
        "sodium": parsed["sodium"],
        "items": parsed["items"],
        "logged_at": datetime.utcnow().isoformat(),
    }
    with workspace_lock(root, person_id):
        profile = load_profile(root, person_id)
        meals = list(profile.get("meals", []))
        meals.append(entry)
        profile["meals"] = meals
        save_profile(root, person_id, profile)
    return entry


def daily_aggregate(profile: dict[str, Any], days: int = 14) -> list[dict[str, Any]]:
    today = date.today()
    cutoff = today - timedelta(days=days)
    by_day: dict[str, dict[str, float]] = {}
    for m in profile.get("meals", []):
        d = str(m.get("date", ""))[:10]
        try:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        if dt < cutoff:
            continue
        bucket = by_day.setdefault(d, {"kcal": 0, "protein": 0, "fiber": 0, "sodium": 0})
        bucket["kcal"] += float(m.get("kcal") or 0)
        bucket["protein"] += float(m.get("protein") or 0)
        bucket["fiber"] += float(m.get("fiber") or 0)
        bucket["sodium"] += float(m.get("sodium") or 0)
    return [{"date": d, **vals} for d, vals in sorted(by_day.items())]


def render_nutrition_md(profile: dict[str, Any]) -> str:
    today = date.today()
    daily = daily_aggregate(profile, days=14)
    name = profile.get("name") or "You"
    weight_kg = None
    # Try to fetch from latest weight entry — use baseline target of 1.2 g/kg
    # if user has weight, otherwise omit target.
    lines = [f"# Nutrition — {name}", "",
             f"_Generated {today.isoformat()}_", ""]
    if not daily:
        lines.append("No meals logged in the last 14 days.")
        lines.append("")
        lines.append("Log one with:")
        lines.append("```")
        lines.append('scripts/care_workspace.py log-meal --root . --text "chicken breast 200g, rice 1 cup, broccoli"')
        lines.append("```")
        return "\n".join(lines) + "\n"

    avg_kcal = statistics.mean([d["kcal"] for d in daily])
    avg_protein = statistics.mean([d["protein"] for d in daily])
    avg_fiber = statistics.mean([d["fiber"] for d in daily])
    avg_sodium = statistics.mean([d["sodium"] for d in daily])

    lines.append("## Last 14 days — daily averages")
    lines.append("")
    lines.append(f"- **Calories:** {avg_kcal:.0f} kcal/day")
    lines.append(f"- **Protein:** {avg_protein:.0f} g/day")
    lines.append(f"- **Fiber:** {avg_fiber:.0f} g/day (target: 25–35 g)")
    lines.append(f"- **Sodium:** {avg_sodium:.0f} mg/day (cap: ~2300 mg)")
    lines.append("")

    lines.append("## Daily breakdown")
    lines.append("")
    lines.append("| Date | kcal | Protein | Fiber | Sodium |")
    lines.append("|---|---:|---:|---:|---:|")
    for d in daily[-7:]:
        lines.append(f"| {d['date']} | {d['kcal']:.0f} | {d['protein']:.0f}g | {d['fiber']:.0f}g | {d['sodium']:.0f}mg |")
    lines.append("")

    # Coaching
    lines.append("## Notes")
    lines.append("")
    if avg_protein < 80:
        lines.append("- Protein is on the low side. Aim for ~1.2 g/kg body weight (post-menopause: ~1.4 g/kg).")
    if avg_fiber < 25:
        lines.append("- Fiber below target — beans, oats, berries, broccoli are easy adds.")
    if avg_sodium > 2300:
        lines.append("- Sodium running high. Common drivers: bread, cheese, sandwiches, processed meats, restaurant meals.")
    if avg_protein >= 80 and avg_fiber >= 25 and avg_sodium <= 2300:
        lines.append("- All major markers in range. Keep going.")
    lines.append("")
    lines.append("_Estimates only. Calorie/macro values are approximate; precision tools (Cronometer, MyFitnessPal) are better for tight tracking._")
    return "\n".join(lines) + "\n"


def write_nutrition(root: Path, person_id: str) -> Path:
    profile = load_profile(root, person_id)
    text = render_nutrition_md(profile)
    path = nutrition_path(root, person_id)
    atomic_write_text(path, text)
    return path
