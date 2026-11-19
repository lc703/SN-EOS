"""Battle Planner -> EOS mapping rules shared by the importer and the data migrations.

Pure functions over plain dicts, so historical models in migrations can use them too.
"""

SEAT_STATUS = {"green": "filled", "yellow": "future", "red": "open"}
RAGS = {"green", "yellow", "red"}

# Battle Planner offsite steps -> EOS quarterly session steps.
OFFSITE_STEP = {
    "prayer": "segue", "chapter": "segue", "reflection": "review", "lessons": "review", "affirmation": "review",
    "values": "vto", "mission": "vto", "vision": "vto", "whats": "segue", "swot": "ids", "priority": "rocks",
    "rocks": "rocks", "done": "conclude",
}

MISSION_STATEMENTS = {
    "why": 'Our purpose answers the question "why do we exist?"',
    "visible": "Our purpose is visible at every level of the organization.",
    "decisions": "Decisions are being made in light of our purpose.",
    "daily": "The team is using our purpose in day-to-day communication.",
}
VISION_STATEMENTS = {
    "clear": "Our vision is clear and specific enough to measure.",
    "memory": "Every leader can state the vision from memory.",
    "rocks": "This quarter's rocks move us toward the vision.",
    "believe": "The team believes the vision is achievable.",
}
FOUR_WHATS = {"working": "working", "broken": "not_working", "missing": "not_working", "confusing": "not_working"}
FOUR_WHATS_PREFIX = {"broken": "Broken: ", "missing": "Missing: ", "confusing": "Confusing: "}

OFFSITE_ITEM_MODELS = {
    "core.swotitem", "core.fourwhatsitem", "core.offsitelesson", "core.offsitereflection", "core.affirmation",
    "core.priorityeval", "core.missioneval", "core.visioneval", "core.valueseval",
}


def seat_status(bp_status):
    return SEAT_STATUS.get((bp_status or "").lower(), "filled")


def _join(*parts):
    return "\n".join(p for p in parts if p)


def offsite_item(model, f):
    """One Battle Planner offsite row -> a session item dict, or None.

    Keys: step, kind, text, rag, author (old user pk), about (old user pk), sort.
    """
    if model == "core.swotitem":
        return {"step": "swot", "kind": f"swot_{f.get('kind', 'strength')}", "text": f.get("text", ""), "author": f.get("author")}
    if model == "core.fourwhatsitem":
        kind = f.get("kind", "working")
        return {"step": "segue", "kind": FOUR_WHATS.get(kind, "not_working"),
                "text": FOUR_WHATS_PREFIX.get(kind, "") + f.get("text", ""), "author": f.get("author")}
    if model == "core.offsitelesson":
        text = f.get("title", "") + (f" — {f['body']}" if f.get("body") else "")
        return {"step": "review", "kind": "lesson", "text": text, "author": f.get("author"), "sort": f.get("sort", 0)}
    if model == "core.offsitereflection":
        text = _join(
            f"Chapter title: {f['chapter_title']}" + (f" ({f['chapter_why']})" if f.get("chapter_why") else "") if f.get("chapter_title") else "",
            f"Wins: {f['wins']}" if f.get("wins") else "",
            f"Team growth: {f['team_growth']}" if f.get("team_growth") else "",
            f"Personal growth: {f['personal_growth']}" if f.get("personal_growth") else "",
        )
        return {"step": "review", "kind": "reflection", "text": text, "author": f.get("user"), "about": f.get("user")} if text else None
    if model == "core.affirmation":
        text = _join(
            f"Qualities: {f['qualities']}" if f.get("qualities") else "",
            f"Growth seen: {f['growth_seen']}" if f.get("growth_seen") else "",
            f"Where I see God working: {f['lord_working']}" if f.get("lord_working") else "",
            f"One opportunity: {f['one_opportunity']}" if f.get("one_opportunity") else "",
        )
        return {"step": "review", "kind": "affirmation", "text": text, "author": f.get("author"), "about": f.get("recipient")} if text else None
    if model == "core.priorityeval":
        top = f.get("top_three_to_five") or []
        text = _join(
            f"#1 priority: {f['number_one']}" if f.get("number_one") else "",
            ("Top priorities: " + "; ".join(str(t) for t in top)) if top else "",
            f.get("notes", ""),
        )
        return {"step": "rocks", "kind": "priority", "text": text} if text else None
    if model in ("core.missioneval", "core.visioneval"):
        table = MISSION_STATEMENTS if model == "core.missioneval" else VISION_STATEMENTS
        label = table.get(f.get("statement_key"), f.get("statement_key", ""))
        prefix = "Purpose" if model == "core.missioneval" else "Vision"
        text = f"{prefix}: {label}" + (f" — {f['note']}" if f.get("note") else "")
        return {"step": "vto", "kind": "vto_check", "text": text, "rag": f.get("rag", "")}
    if model == "core.valueseval":
        text = "Core values" + (f": {f['note']}" if f.get("note") else "")
        return {"step": "vto", "kind": "vto_check", "text": text, "rag": f.get("rag", "")}
    return None


def box_goal(f):
    """A Strategy House box -> 1-year goal fields (owner and pk resolved by the caller)."""
    tactics = f.get("tactics") or []
    if isinstance(tactics, str):
        tactics = [tactics]
    return {
        "title": (f.get("statement") or "Goal")[:240],
        "strategy": f.get("strategy") or "",
        "tactics": "\n".join(str(t) for t in tactics if t),
        "due_date": f.get("due_date") or None,
        "sort": f.get("sort") or 0,
    }


def targets_text(targets):
    """Strategy House targets [{label, value, sub}] -> V/TO measurables lines."""
    out = []
    for t in targets or []:
        if not isinstance(t, dict):
            continue
        line = " ".join(x for x in [str(t.get("value") or ""), str(t.get("label") or "")] if x).strip()
        if t.get("sub"):
            line += f" ({t['sub']})"
        if line:
            out.append(line)
    return "\n".join(out)
