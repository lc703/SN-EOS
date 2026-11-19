"""EOS session agendas (Traction, chapter 9 "Traction: Bringing It All Together" and the Quarterly/Annual Pulse).

Keys are stored on Session.current_step and SessionItem.step, so keep them stable.
"""

QUARTERLY = [
    ("segue", "Segue", "Best business and personal news from the last 90 days, what's working and not working, and expectations for today."),
    ("review", "Review previous quarter", "Rocks done or not done (aim for 80%+), the Scorecard, to-do completion, and lessons learned."),
    ("vto", "Review the V/TO", "Read the V/TO top to bottom. Is everyone still on the same page? Anything that isn't goes to the Issues List."),
    ("rocks", "Establish next quarter's Rocks", "Brainstorm everything that could be a Rock, keep, kill or combine, then set 3 to 7 company Rocks and assign each one owner."),
    ("ids", "Tackle key issues", "Prioritize the Issues List and IDS the most important ones."),
    ("next", "Next steps", "Who does what by when. Cascading messages to the rest of the company."),
    ("conclude", "Conclude", "Feedback on the day, were expectations met, and rate the session 1 to 10."),
]

ANNUAL = [
    ("segue", "Segue", "Best news of the year, what's working and not working, and expectations for the two days."),
    ("review", "Review previous year", "Last year's goals and Rocks, the numbers, and lessons learned."),
    ("health", "Team health building", "Each person shares one thing every teammate does that helps the team, and one thing to improve."),
    ("swot", "SWOT / Issues List", "Strengths, weaknesses, opportunities and threats. Weaknesses and threats feed the Issues List."),
    ("vto", "V/TO through the 1-year plan", "Refresh core values, core focus, 10-year target, marketing strategy and the 3-year picture."),
    ("goals", "Establish 1-year goals", "3 to 7 goals for the year, with revenue, profit and measurables. These go on the V/TO."),
    ("rocks", "Establish Q1 Rocks", "Brainstorm, keep/kill/combine, then set 3 to 7 company Rocks, each with one owner."),
    ("ids", "Tackle key issues", "Prioritize the Issues List and IDS the most important ones."),
    ("next", "Next steps", "Who does what by when. Cascading messages to the rest of the company."),
    ("conclude", "Conclude", "Feedback on the two days, were expectations met, and rate the session 1 to 10."),
]

AGENDAS = {"quarterly": QUARTERLY, "annual": ANNUAL}

# Brainstorm buckets a step collects. (kind, label, placeholder)
STEP_ITEMS = {
    "segue": [
        ("news", "Best business and personal news", "One best business and one best personal…"),
        ("working", "What's working", "What's working…"),
        ("not_working", "What's not working", "What's not working…"),
        ("expectation", "Expectations for today", "I expect we'll…"),
    ],
    "review": [("lesson", "Lessons learned", "What did we learn…")],
    "health": [("health", "Team health notes", "One thing they do well / one to improve…")],
    "swot": [
        ("swot_strength", "Strengths", "Strength…"),
        ("swot_weakness", "Weaknesses", "Weakness…"),
        ("swot_opportunity", "Opportunities", "Opportunity…"),
        ("swot_threat", "Threats", "Threat…"),
    ],
    "vto": [("vto_note", "Not on the same page", "Something we don't agree on…")],
    "rocks": [("rock_idea", "Rock brainstorm", "Could be a Rock…")],
    "next": [("next_step", "Next steps", "Who does what by when…")],
    "conclude": [("feedback", "Feedback on the day", "Feedback…")],
}

ITEM_LABELS = {kind: label for items in STEP_ITEMS.values() for kind, label, _ in items} | {
    "reflection": "Reflection",
    "affirmation": "Affirmation",
    "vto_check": "V/TO check",
    "priority": "Priorities",
}
