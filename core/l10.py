"""Getting back to the exact L10 section after opening a rock, issue, to-do or measurable.

Links inside an L10 section carry `?from=/meetings/<id>/?s=<section>[&all=1]`. The detail page validates it
and shows a "Back to L10 – <Section>" link. Only a rebuilt path to an existing meeting is ever used, never
the raw value, so it cannot become an open redirect.
"""

from urllib.parse import quote, urlsplit, parse_qs

from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

MAX_LEN = 200


def l10_path(meeting_id, section, show_all=False):
    return f"{reverse('meeting', args=[meeting_id])}?s={section}" + ("&all=1" if show_all else "")


def l10_return(request):
    """Validated `?from=` as {"url", "label", "qs", "section"}, or None for anything unsafe or unknown."""
    from meetings.models import SECTIONS, SECTION_KEYS, Meeting

    raw = request.GET.get("from")
    if not raw or not isinstance(raw, str) or len(raw) > MAX_LEN:
        return None
    if not raw.startswith("/") or raw.startswith("//") or "\\" in raw or any(c in raw for c in "\r\n\t "):
        return None
    if not url_has_allowed_host_and_scheme(raw, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return None
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc or parts.fragment:
        return None
    path = parts.path.rstrip("/")
    prefix, _, tail = path.rpartition("/")
    if prefix != "/meetings" or not tail.isdigit():
        return None
    meeting_id = int(tail)
    if reverse("meeting", args=[meeting_id]) != parts.path:
        return None
    if not Meeting.objects.filter(pk=meeting_id).exists():
        return None
    query = parse_qs(parts.query)
    section = (query.get("s") or [""])[0]
    if section not in SECTION_KEYS:
        return None
    url = l10_path(meeting_id, section, show_all=(query.get("all") or [""])[0] == "1")
    return {
        "url": url,
        "label": f"Back to L10 – {dict(SECTIONS)[section]}",
        "qs": "?from=" + quote(url, safe=""),
        "section": section,
    }
