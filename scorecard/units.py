"""Reading a unit typed by a person ("$", "USD", "$M", "%", "yes/no") into one of our unit types."""

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


# Rows Battle Planner filled by itself from iQuote or Attio. Here an assistant posts the numbers each week.
SOURCE_NOTES = {
    "iquote_quotes": "Filled weekly by assistant from iQuote",
    "iquote_rd": "Filled weekly by assistant from iQuote",
    "attio_prelim": "Filled weekly by assistant from Attio",
    "attio_rd": "Filled weekly by assistant from Attio",
    "attio_final": "Filled weekly by assistant from Attio",
}
