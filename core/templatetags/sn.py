from decimal import Decimal

from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def get_item(mapping, key):
    return (mapping or {}).get(key)


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
def cellnum(value):
    """Like num, with thousands separators for big numbers: 476930 -> 476,930."""
    text = num(value)
    if not text:
        return text
    whole, _, frac = text.partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = f"{int(whole.lstrip('-') or 0):,}"
    return sign + whole + ("." + frac if frac else "")


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


@register.simple_tag
def icon(name, cls="h-4 w-4", stroke="2"):
    from django.utils.safestring import mark_safe

    from core.icons import svg

    return mark_safe(svg(name, cls, stroke))


@register.simple_tag
def sparkline(values, goal=None, states=None, width=96, height=26):
    from django.utils.safestring import mark_safe

    from core.charts import sparkline as draw

    return mark_safe(draw(values, goal=goal, states=states, width=width, height=height))


@register.simple_tag
def donut(segments, size=92, center="", sub=""):
    from django.utils.safestring import mark_safe

    from core.charts import donut as draw

    return mark_safe(draw(segments, size=size, center=str(center), sub=sub))


@register.simple_tag
def bars(items, goal=None, height=72):
    from django.utils.safestring import mark_safe

    from core.charts import bars as draw

    return mark_safe(draw(items, goal=goal, height=height))


@register.filter
def rag_label(rag):
    return {"green": "Green", "yellow": "Yellow", "red": "Red", "done": "Done"}.get(rag, "—")


@register.inclusion_tag("_empty.html")
def empty(title, body="", icon_name="sparkle", action_url="", action_label="", compact=False):
    return {"title": title, "body": body, "icon_name": icon_name, "action_url": action_url, "action_label": action_label, "compact": compact}


@register.inclusion_tag("rocks/_strip.html")
def rock_strip(rock):
    from core.models import monday_of

    return {"strip": rock.week_strip(), "now": monday_of(timezone.localdate())}


@register.filter
def can_edit_rock(rock, user):
    from core.permissions import can_edit_owned

    return can_edit_owned(user, rock)
