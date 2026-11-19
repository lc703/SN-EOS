from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import User
from core.permissions import can_review_person, can_view_private_people_notes, is_admin, manages
from core.utils import go_back, hx_trigger, is_htmx, require, scope
from rocks.models import Rock
from todos.models import Todo
from vision.models import CoreValue, Seat

from .models import OneOnOne, OneOnOneScore, PeopleReview, SuccessStatement, ValueRating


def people_list(request):
    team, quarter = scope(request)
    show_all = request.GET.get("all") == "1"
    users = User.objects.filter(is_active=True).prefetch_related("teams", "seats").order_by("name")
    if not show_all and team:
        users = users.filter(teams=team) | users.filter(home_team=team)
        users = users.distinct().order_by("name")
    tracker = qc_tracker(request.user, quarter, None if show_all else team)
    qc_by_person = {r["person"].pk: r for r in tracker["rows"]}
    users = list(users)
    for u in users:
        u.qc_row = qc_by_person.get(u.pk)
    return render(request, "people/people.html", {"people": users, "show_all": show_all, "tracker": tracker})


def person(request, pk):
    person = get_object_or_404(User.objects.prefetch_related("teams"), pk=pk)
    _, quarter = scope(request)
    private = can_view_private_people_notes(request.user, person)
    reviewer = can_review_person(request.user, person)
    reviews = []
    if private:
        reviews = list(PeopleReview.objects.filter(person=person).select_related("reviewer").prefetch_related("ratings__value")[:12])
    values = list(CoreValue.objects.filter(active=True))
    latest = reviews[0] if reviews else None
    latest_map = {r.value_id: r.rating for r in latest.ratings.all()} if latest else {}
    managers = [s.parent.person for s in Seat.objects.filter(person=person, parent__person__isnull=False).select_related("parent__person")]
    return render(
        request,
        "people/person.html",
        {
            "person": person,
            "seats": Seat.objects.filter(person=person).select_related("team", "parent"),
            "managers": list(dict.fromkeys(managers)),
            "reports": User.objects.filter(seats__parent__person=person).distinct().order_by("name"),
            "rocks": Rock.objects.filter(owner=person, quarter=quarter).select_related("team") if quarter else [],
            "open_todos": Todo.objects.filter(owner=person, done=False, is_private=False).count(),
            "statements": person.success_statements.all(),
            "private": private,
            "reviewer": reviewer,
            "one_on_ones": OneOnOne.objects.filter(person=person).select_related("manager").prefetch_related("scores")[:20] if private else [],
            "reviews": reviews,
            "latest": latest,
            "value_rows": [(v, latest_map.get(v.pk)) for v in values],
            "values": values,
            "rating_choices": ValueRating.CHOICES,
            "today": timezone.localdate(),
            "is_manager": manages(request.user, person),
        },
    )


@require_POST
def one_on_one_add(request, pk):
    person = get_object_or_404(User, pk=pk)
    require(can_view_private_people_notes(request.user, person))
    notes = request.POST.get("notes", "").strip()
    if notes:
        manager = request.user if request.user.pk != person.pk else None
        OneOnOne.objects.create(
            person=person, manager=manager, kind=OneOnOne.CHECKIN, date=request.POST.get("date") or timezone.localdate(), notes=notes, created_by=request.user
        )
        messages.success(request, "1:1 notes saved.")
    return redirect("person", pk=person.pk)


@require_POST
def review_add(request, pk):
    person = get_object_or_404(User, pk=pk)
    require(can_review_person(request.user, person))

    def yn(name):
        val = request.POST.get(name)
        return {"yes": True, "no": False}.get(val)

    review = PeopleReview.objects.create(
        person=person,
        reviewer=request.user,
        date=request.POST.get("date") or timezone.localdate(),
        gets_it=yn("gets_it"),
        wants_it=yn("wants_it"),
        capacity=yn("capacity"),
        notes=request.POST.get("notes", "").strip(),
    )
    for value in CoreValue.objects.filter(active=True):
        rating = request.POST.get(f"value_{value.pk}")
        if rating in dict(ValueRating.CHOICES):
            ValueRating.objects.create(review=review, value=value, rating=rating)
    messages.success(request, "People Analyzer saved.")
    return redirect("person", pk=person.pk)


# ---------------------------------------------------------------- Quarterly Conversations

def manager_pairs(viewer, team=None):
    """[(manager, report)] from the Accountability Chart that the viewer may see, ordered by manager then report."""
    seats = Seat.objects.filter(person__isnull=False, parent__person__isnull=False).select_related("person", "parent__person", "team")
    if team is not None and not team.is_leadership:
        seats = seats.filter(team=team)
    pairs = {}
    for s in seats:
        mgr, rep = s.parent.person, s.person
        if mgr.pk == rep.pk or not rep.is_active:
            continue
        if is_admin(viewer) or viewer.pk in (mgr.pk, rep.pk):
            pairs.setdefault((mgr.pk, rep.pk), (mgr, rep))
    return sorted(pairs.values(), key=lambda p: (p[0].name, p[1].name))


def qc_tracker(viewer, quarter, team=None):
    pairs = manager_pairs(viewer, team)
    convos = {}
    if quarter:
        qs = OneOnOne.objects.filter(
            kind=OneOnOne.QUARTERLY, person_id__in=[r.pk for _, r in pairs], date__gte=quarter.start_date, date__lte=quarter.end_date
        ).prefetch_related("scores").order_by("-date", "-id")
        for o in qs:
            convos.setdefault(o.person_id, o)
    rows = []
    for mgr, rep in pairs:
        o = convos.get(rep.pk)
        status = "done" if o and o.is_complete else "draft" if o else "todo"
        rows.append({"manager": mgr, "person": rep, "qc": o, "status": status, "red": o.red_count if o else 0})
    done = sum(1 for r in rows if r["status"] == "done")
    return {
        "rows": rows, "done": done, "total": len(rows),
        "draft": sum(1 for r in rows if r["status"] == "draft"),
        "todo": sum(1 for r in rows if r["status"] == "todo"),
        "struggling": sum(1 for r in rows if r["red"]),
        "pct": round(100 * done / len(rows)) if rows else 0,
    }


def conversations(request):
    team, quarter = scope(request)
    tracker = qc_tracker(request.user, quarter, None if request.GET.get("all") == "1" else team)
    by_manager = {}
    for r in tracker["rows"]:
        by_manager.setdefault(r["manager"], []).append(r)
    return render(request, "people/conversations.html", {
        "tracker": tracker, "by_manager": list(by_manager.items()), "show_all": request.GET.get("all") == "1",
    })


@require_POST
def qc_start(request, pk):
    person = get_object_or_404(User, pk=pk)
    require(can_view_private_people_notes(request.user, person))
    _, quarter = scope(request)
    existing = None
    if quarter:
        existing = OneOnOne.objects.filter(
            person=person, kind=OneOnOne.QUARTERLY, date__gte=quarter.start_date, date__lte=quarter.end_date
        ).first()
    if existing:
        return redirect("qc_detail", pk=existing.pk)
    manager = request.user if request.user.pk != person.pk else next(
        (s.parent.person for s in Seat.objects.filter(person=person, parent__person__isnull=False).select_related("parent__person")), None
    )
    o = OneOnOne.objects.create(person=person, manager=manager, kind=OneOnOne.QUARTERLY, created_by=request.user)
    return redirect("qc_detail", pk=o.pk)


def _qc_rows(o):
    scores = o.score_map()
    prev = (
        OneOnOne.objects.filter(person=o.person, kind=OneOnOne.QUARTERLY, date__lt=o.date).exclude(pk=o.pk)
        .prefetch_related("scores").order_by("-date", "-id").first()
    )
    prev_scores = prev.score_map() if prev else {}
    statements = [("ss", s, scores.get(("ss", s.pk)), prev_scores.get(("ss", s.pk))) for s in o.person.success_statements.all()]
    values = [("cv", v, scores.get(("cv", v.pk)), prev_scores.get(("cv", v.pk))) for v in CoreValue.objects.filter(active=True)]
    return statements, values, prev


def qc_detail(request, pk):
    o = get_object_or_404(OneOnOne.objects.select_related("person", "manager"), pk=pk)
    require(can_view_private_people_notes(request.user, o.person))
    if request.method == "POST":
        fields = [f for f in ("highlight", "notes") if f in request.POST]
        for f in fields:
            setattr(o, f, request.POST[f])
        if "date" in request.POST and request.POST["date"]:
            o.date = request.POST["date"]
            fields.append("date")
        if "complete" in request.POST:
            o.completed_at = None if request.POST["complete"] == "0" else timezone.now()
            fields.append("completed_at")
        o.save(update_fields=fields or None)
        if is_htmx(request) and "complete" not in request.POST:
            return HttpResponse(status=204)
        if "complete" in request.POST:
            messages.success(request, "Quarterly Conversation complete." if o.completed_at else "Reopened.")
        return redirect("qc_detail", pk=o.pk)
    statements, values, prev = _qc_rows(o)
    rags = [s.rag for s in o.scores.all() if s.rag]
    return render(request, "people/qc.html", {
        "o": o, "person": o.person, "statements": statements, "values": values, "prev": prev,
        "counts": {"green": rags.count("green"), "yellow": rags.count("yellow"), "red": rags.count("red"),
                   "open": len(statements) + len(values) - len(rags)},
        "can_edit_statements": can_review_person(request.user, o.person),
        "rag_choices": [("green", "G"), ("yellow", "Y"), ("red", "R")],
    })


@require_POST
def qc_score(request, pk):
    o = get_object_or_404(OneOnOne.objects.select_related("person"), pk=pk)
    require(can_view_private_people_notes(request.user, o.person))
    kind, ref = request.POST.get("kind"), request.POST.get("ref", "")
    if kind not in ("ss", "cv") or not ref.isdigit():
        return HttpResponse(status=400)
    target = (
        get_object_or_404(SuccessStatement, pk=ref, person=o.person) if kind == "ss" else get_object_or_404(CoreValue, pk=ref)
    )
    lookup = {"statement": target} if kind == "ss" else {"value": target}
    score, _ = OneOnOneScore.objects.get_or_create(one_on_one=o, **lookup)
    if "rag" in request.POST:
        rag = request.POST["rag"]
        score.rag = "" if rag == score.rag else rag if rag in ("green", "yellow", "red") else ""
    if "note" in request.POST:
        score.note = request.POST["note"].strip()
    score.save()
    if is_htmx(request):
        return hx_trigger(HttpResponse(status=204), qcChanged=True)
    return redirect("qc_detail", pk=o.pk)


@require_POST
def statement_add(request, pk):
    person = get_object_or_404(User, pk=pk)
    require(can_review_person(request.user, person))
    text = request.POST.get("text", "").strip()
    if text:
        SuccessStatement.objects.create(person=person, text=text, sort=person.success_statements.count())
    if is_htmx(request):
        return hx_trigger(HttpResponse(status=204), qcChanged=True)
    return go_back(request, f"/people/{person.pk}/")


@require_POST
def statement_delete(request, pk):
    s = get_object_or_404(SuccessStatement.objects.select_related("person"), pk=pk)
    require(can_review_person(request.user, s.person))
    person_pk = s.person_id
    s.delete()
    if is_htmx(request):
        return hx_trigger(HttpResponse(status=204), qcChanged=True)
    return go_back(request, f"/people/{person_pk}/")
