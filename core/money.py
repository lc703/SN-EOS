from decimal import ROUND_HALF_UP, Decimal


def format_dollars(value):
    """$48,213 or -$1,200: whole dollars, thousands separators, halves rounded away from zero."""
    if value is None or value == "":
        return ""
    amount = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    whole = amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return f"{'-' if whole < 0 else ''}${abs(whole):,}"
