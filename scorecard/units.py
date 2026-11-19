"""Reading a unit typed by a person ("$", "USD", "$M", "%", "yes/no") into one of our unit types."""

import re

PERCENT, CURRENCY, YESNO, NUMBER = "percent", "currency", "yesno", "number"

_PERCENT_WORDS = {"%", "percent", "percentage", "pct"}
_CURRENCY_WORDS = {"currency", "usd", "us$", "dollar", "dollars", "money"}
_YESNO_WORDS = {"yes/no", "yesno", "yes-no", "boolean", "y/n"}


def unit_from_text(text, default=NUMBER):
    """Dollars are anything with a $ sign or a dollar word, so "$", "USD", "$M" and "$k" all count."""
    low = (text or "").strip().lower()
    if not low:
        return default
    if low in _YESNO_WORDS:
        return YESNO
    if "%" in low or low in _PERCENT_WORDS:
        return PERCENT
    if "$" in low or low in _CURRENCY_WORDS or low.startswith("usd"):
        return CURRENCY
    return default


_MONEY = re.compile(
    r"\b(revenues?|dollars?|costs?|spend|profit|income|expenses?|cash|invoiced|invoices|payroll|budget|price|pipeline"
    r"|(?:deal|contract|order|proposal|sales|quote)\s+(?:value|amount|total))\b"
)
_NOT_MONEY = re.compile(
    r"%|#|\b(ratio|rate|percent|percentage|count|number|qty|quantity|per|score|"
    r"calls|visits|quotes|proposals|deals|leads|orders|meetings|samples|units|tons|days|hours)\b"
)


def title_is_money(title):
    """Titles like "Difference of Actual vs Expected Revenue" are dollars; "Labor to revenue ratio" is not."""
    low = (title or "").lower()
    return bool(_MONEY.search(low)) and not _NOT_MONEY.search(low)


def unit_for(unit_text, title="", goal_text=""):
    """The unit for an imported metric. A typed unit wins; a plain number is still dollars when the goal
    carries a $ sign or the name is clearly about money."""
    unit = unit_from_text(unit_text)
    if unit != NUMBER:
        return unit
    if "$" in str(goal_text or "") or title_is_money(title):
        return CURRENCY
    return NUMBER


# Rows Battle Planner filled by itself from iQuote or Attio. Here an assistant posts the numbers each week.
SOURCE_NOTES = {
    "iquote_quotes": "Filled weekly by assistant from iQuote",
    "iquote_rd": "Filled weekly by assistant from iQuote",
    "attio_prelim": "Filled weekly by assistant from Attio",
    "attio_rd": "Filled weekly by assistant from Attio",
    "attio_final": "Filled weekly by assistant from Attio",
}
