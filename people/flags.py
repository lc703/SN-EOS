"""People signals for the Accountability Chart: GWC, People Analyzer and Quarterly Conversation flags.

These come from private people data, so they're only computed for people the viewer may see
(themselves, their direct reports, or everyone for admins).
"""

import datetime as dt

from django.utils import timezone

from core.permissions import is_admin

from .models import OneOnOne, PeopleReview

RECENT_DAYS = 120


def visible_people(viewer, person_ids):
    from vision.models import Seat

    person_ids = {p for p in person_ids if p}
    if is_admin(viewer):
        return person_ids
    managed = set(Seat.objects.filter(parent__person=viewer, person_id__in=person_ids).values_list("person_id", flat=True))
    return managed | ({viewer.pk} & person_ids)


def people_flags(viewer, person_ids):
    """{person_id: {"gwc": {"g","w","c"}, "pa": "ok|watch|below|None", "struggling": bool, "reds": n, "qc_date": date}}"""
    ids = visible_people(viewer, person_ids)
    if not ids:
        return {}
    since = timezone.localdate() - dt.timedelta(days=RECENT_DAYS)
    reviews, convos = {}, {}
    for r in PeopleReview.objects.filter(person_id__in=ids).prefetch_related("ratings").order_by("person_id", "-date", "-id"):
        reviews.setdefault(r.person_id, r)
    for c in OneOnOne.objects.filter(person_id__in=ids, date__gte=since).prefetch_related("scores").order_by("person_id", "-date", "-id"):
        convos.setdefault(c.person_id, c)
    out = {}
    for pid in ids:
        review, convo = reviews.get(pid), convos.get(pid)
        flags = {"gwc": None, "pa": None, "struggling": False, "reds": 0, "qc_date": None, "convo": convo}
        gwc_src = None
        if convo and None not in (convo.gets_it, convo.wants_it, convo.capacity):
            gwc_src = convo
        if review and (gwc_src is None or review.date >= gwc_src.date) and not (review.gets_it is None and review.wants_it is None and review.capacity is None):
            gwc_src = review
        if gwc_src is not None:
            flags["gwc"] = {"g": gwc_src.gets_it, "w": gwc_src.wants_it, "c": gwc_src.capacity}
        if review is not None:
            ratings = [x.rating for x in review.ratings.all()]
            if ratings:
                flags["pa"] = "below" if "-" in ratings else "watch" if "+/-" in ratings else "ok"
        if convo is not None:
            counts = convo.color_counts
            flags["reds"] = counts["red"]
            flags["struggling"] = convo.is_struggling
            flags["qc_date"] = convo.date
        if flags["gwc"] and False in flags["gwc"].values():
            flags["struggling"] = True
        out[pid] = flags
    return out
