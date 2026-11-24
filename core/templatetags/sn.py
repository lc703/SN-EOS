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


@register.simple_tag
def sparkline(values, goal=None, ok=None, width=96, height=26):
    from django.utils.safestring import mark_safe

    from core.charts import sparkline as draw

    return mark_safe(draw(values, goal=goal, ok=ok, width=width, height=height))


@register.simple_tag
def rock_strip(strip, today=None, large=False):
    """strip: [(week, RockUpdate|None)] -> 13 colored squares; the current week is outlined."""
    from django.utils.html import format_html_join
    from django.utils.safestring import mark_safe

    from core.models import monday_of

    now = monday_of(today or timezone.localdate())
    letters = {"green": "g", "yellow": "y", "red": "r"}
    labels = {"green": "On track", "yellow": "At risk", "red": "Off track"}
    cells = []
    for week, upd in strip:
        cls = letters.get(getattr(upd, "color", ""), "")
        if week == now:
            cls += " now"
        tip = f"Week of {week:%b %-d}: " + (labels.get(upd.color, "") if upd else "no update")
        cells.append((cls.strip(), tip))
    inner = format_html_join("", '<span class="{}" title="{}"></span>', cells)
    return mark_safe(f'<span class="strip{" strip-lg" if large else ""}" aria-label="13-week status">{inner}</span>')


@register.filter
def color_dot(color):
    return {"green": "dot-green", "yellow": "dot-yellow", "red": "dot-red"}.get(color or "", "dot-none")


@register.filter
def color_badge(color):
    return {"green": "badge-green", "yellow": "badge-yellow", "red": "badge-red"}.get(color or "", "")


@register.filter
def editable_by(todo, user):
    """True when this viewer may check off the to-do. Private to-dos stay with their owner."""
    from core.permissions import can_edit_todo

    return can_edit_todo(user, todo)


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.simple_tag(takes_context=True)
def form_errors(context, key):
    """Errors (and typed values) left by `stash_form_errors` for this form, shown once."""
    request = context.get("request")
    session = getattr(request, "session", None)
    return (session.pop(f"form_errors:{key}", None) if session is not None else None) or {}


@register.simple_tag(takes_context=True)
def l10_from(context, section, prefix="?"):
    """`?from=<this L10 section>` for links out of an L10 section, or "" when not inside a meeting."""
    from urllib.parse import quote

    from core.l10 import l10_path

    mid = context.get("meeting_id")
    if not mid:
        meeting = context.get("meeting")
        mid = getattr(meeting, "pk", None)
    if not str(mid or "").isdigit():
        return ""
    from meetings.models import SECTION_KEYS

    current = context.get("section") or context.get("l10_section")
    if current in SECTION_KEYS:
        section = current
    roster = context.get("roster")
    request = context.get("request")
    show_all = bool(getattr(roster, "show_all", False)) or bool(request and request.GET.get("all") == "1")
    return prefix + "from=" + quote(l10_path(int(mid), section, show_all), safe="")
