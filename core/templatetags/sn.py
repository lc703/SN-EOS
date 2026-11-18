from decimal import Decimal

from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def num(value):
    """Decimal for an input box: 85.00 -> 85, 1.50 -> 1.5."""
    if value is None or value == "":
        return ""
    text = format(Decimal(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


@register.filter
def lines(value):
    return [x.strip() for x in (value or "").splitlines() if x.strip()]


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def relday(day):
    if not day:
        return ""
    delta = (day - timezone.localdate()).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    if -7 < delta < 0:
        return f"{-delta} days ago"
    if 0 < delta < 7:
        return day.strftime("%A")
    return day.strftime("%b %-d")


@register.filter
def ago(value):
    if not value:
        return ""
    from django.utils.timesince import timesince

    return f"{timesince(value, depth=1)} ago"


@register.filter
def pct_class(pct):
    if pct is None:
        return "text-neutral-400"
    if pct >= 90:
        return "text-green-700"
    if pct >= 70:
        return "text-amber-600"
    return "text-red-700"


@register.inclusion_tag("_avatar.html")
def avatar(user, size=""):
    return {"u": user, "size": size}


@register.inclusion_tag("_status_pill.html")
def status_pill(rock):
    return {"rock": rock}
