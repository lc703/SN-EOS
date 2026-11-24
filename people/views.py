from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import User
from core.permissions import can_review_person, can_view_private_people_notes, manages
from core.utils import go_back, require, scope
from core.scoping import is_rollup
from rocks.models import Rock
from todos.models import Todo
from vision.models import CoreValue, Seat

from .models import ConversationScore, OneOnOne, PeopleReview, SuccessStatement, ValueRating


def people_list(request):
    team, _ = scope(request)
    show_all = request.GET.get("all") == "1"
    users = User.objects.filter(is_active=True).prefetch_related("teams", "seats").order_by("name")
    if not show_all and team and not is_rollup(team):
        users = users.filter(teams=team) | users.filter(home_team=team)
        users = users.distinct().order_by("name")
    return render(request, "people/people.html", {"people": users, "show_all": show_all})


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
            person=person, manager=manager, date=request.POST.get("date") or timezone.localdate(), notes=notes, created_by=request.user
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


def _conversation_people(request, team, show_all):
    """Who the viewer runs or sees conversations for: admins see everyone (team-scoped), managers their reports."""
    from core.permissions import is_admin

    users = User.objects.filter(is_active=True)
    if is_admin(request.user):
        if not show_all and team and not is_rollup(team):
            users = (users.filter(teams=team) | users.filter(home_team=team))
    else:
        managed = Seat.objects.filter(parent__person=request.user).values_list("person_id", flat=True)
        users = users.filter(pk__in=[*managed, request.user.pk])
    return users.distinct().order_by("name")


def conversations(request):
    """Quarterly Conversation tracker: who's done, who's in progress, who's struggling."""
    team, quarter = scope(request)
    show_all = request.GET.get("all") == "1"
    people = list(_conversation_people(request, team, show_all))
    ids = [p.pk for p in people]
    convos = {}
    if quarter:
        for c in OneOnOne.objects.filter(person_id__in=ids, kind=OneOnOne.QUARTERLY, quarter=quarter).prefetch_related("scores").order_by("-date", "-id"):
            convos.setdefault(c.person_id, c)
    last_one = {}
    for c in OneOnOne.objects.filter(person_id__in=ids, kind=OneOnOne.ONE_ON_ONE).order_by("-date").values("person_id", "date"):
        last_one.setdefault(c["person_id"], c["date"])
    managers = {}
    for s in Seat.objects.filter(person_id__in=ids, parent__person__isnull=False).select_related("parent__person"):
        managers.setdefault(s.person_id, []).append(s.parent.person)
    rows = []
    for p in people:
        c = convos.get(p.pk)
        state = "done" if c and c.completed_at else "progress" if c else "todo"
        rows.append({"person": p, "convo": c, "state": state, "last_one": last_one.get(p.pk),
                     "managers": list(dict.fromkeys(managers.get(p.pk, []))), "can_run": can_review_person(request.user, p)})
    done = sum(r["state"] == "done" for r in rows)
    return render(request, "people/conversations.html", {
        "rows": rows, "done": done, "total": len(rows), "pct": round(100 * done / len(rows)) if rows else None,
        "in_progress": sum(r["state"] == "progress" for r in rows),
        "struggling": sum(1 for r in rows if r["convo"] and r["convo"].is_struggling),
        "show_all": show_all,
    })


@require_POST
def conversation_new(request, pk):
    person = get_object_or_404(User, pk=pk)
    require(can_review_person(request.user, person) or (request.POST.get("kind") == OneOnOne.ONE_ON_ONE and can_view_private_people_notes(request.user, person)))
    _, quarter = scope(request)
    kind = OneOnOne.QUARTERLY if request.POST.get("kind") == OneOnOne.QUARTERLY else OneOnOne.ONE_ON_ONE
    if kind == OneOnOne.QUARTERLY and quarter:
        existing = OneOnOne.objects.filter(person=person, kind=kind, quarter=quarter).first()
        if existing:
            return redirect("conversation", pk=existing.pk)
    manager = request.user if request.user.pk != person.pk else None
    convo = OneOnOne.objects.create(person=person, manager=manager, kind=kind, quarter=quarter, created_by=request.user)
    return redirect("conversation", pk=convo.pk)


def _grid(convo):
    scores = list(convo.scores.all())
    by = {}
    for sc in scores:
        key = f"value:{sc.value_id}" if sc.value_id else f"statement:{sc.statement_id}" if sc.statement_id else f"rock:{sc.rock_id}"
        by[key] = sc
    values = CoreValue.objects.filter(active=True)
    statements = convo.person.success_statements.all()
    rocks = Rock.objects.filter(owner=convo.person, quarter=convo.quarter).select_related("team") if convo.quarter else Rock.objects.none()
    groups = [
        ("Core values", "Do they live our core values?", [(f"value:{v.pk}", v.name, "", by.get(f"value:{v.pk}")) for v in values]),
        ("Roles", "Are they doing what the seat needs (their five roles / success statements)?",
         [(f"statement:{s.pk}", s.text, s.standard, by.get(f"statement:{s.pk}")) for s in statements]),
        ("Rocks", "Are this quarter's rocks getting done?", [(f"rock:{r.pk}", r.title, r.get_status_display(), by.get(f"rock:{r.pk}")) for r in rocks]),
    ]
    return groups


def conversation(request, pk):
    convo = get_object_or_404(OneOnOne.objects.select_related("person", "manager", "quarter"), pk=pk)
    require(can_view_private_people_notes(request.user, convo.person))
    editable = can_review_person(request.user, convo.person) or convo.manager_id == request.user.pk
    if request.method == "POST":
        require(editable)
        fields = []
        for f in ("highlight", "notes"):
            if f in request.POST:
                setattr(convo, f, request.POST[f].strip())
                fields.append(f)
        for f in ("gets_it", "wants_it", "capacity"):
            if f in request.POST:
                setattr(convo, f, {"yes": True, "no": False}.get(request.POST[f]))
                fields.append(f)
        if "date" in request.POST and request.POST["date"]:
            convo.date = request.POST["date"]
            fields.append("date")
        if request.POST.get("complete") == "1":
            convo.completed_at = timezone.now()
            fields.append("completed_at")
        elif request.POST.get("complete") == "0":
            convo.completed_at = None
            fields.append("completed_at")
        if fields:
            convo.save(update_fields=fields)
        if request.headers.get("HX-Request") and "complete" not in request.POST:
            return HttpResponse(status=204)
        if request.POST.get("complete") == "1":
            messages.success(request, f"{convo.get_kind_display()} with {convo.person.first} marked complete.")
        return redirect("conversation", pk=convo.pk)
    groups = _grid(convo)
    cells = [c for _, _, rows in groups for c in rows]
    counts = {k: sum(1 for c in cells if c[3] and c[3].color == k) for k in ("green", "yellow", "red")}
    history = OneOnOne.objects.filter(person=convo.person).exclude(pk=convo.pk).prefetch_related("scores")[:8]
    return render(request, "people/conversation.html", {
        "c": convo, "groups": groups, "editable": editable, "counts": counts, "unrated": sum(1 for c in cells if not (c[3] and c[3].color)),
        "history": history, "colors": [("green", "Green"), ("yellow", "Yellow"), ("red", "Red")],
    })


@require_POST
def conversation_score(request, pk):
    convo = get_object_or_404(OneOnOne.objects.select_related("person"), pk=pk)
    require(can_review_person(request.user, convo.person) or convo.manager_id == request.user.pk)
    kind, _, ref = (request.POST.get("subject") or "").partition(":")
    targets = {"value": ("value", CoreValue), "statement": ("statement", SuccessStatement), "rock": ("rock", Rock)}
    if kind not in targets or not ref.isdigit():
        return HttpResponse("Bad subject", status=400)
    field, model = targets[kind]
    obj = get_object_or_404(model, pk=int(ref))
    if kind == "statement":
        require(obj.person_id == convo.person_id)
    score, _ = ConversationScore.objects.get_or_create(conversation=convo, **{field: obj})
    if "color" in request.POST:
        color = request.POST["color"]
        score.color = color if color in dict(ConversationScore.COLOR_CHOICES) else ""
    if "note" in request.POST:
        score.note = request.POST["note"].strip()
    score.save()
    if "color" in request.POST:
        return render(request, "people/_score_cell.html", {"c": convo, "key": f"{kind}:{ref}", "score": score, "editable": True,
                                                            "colors": [("green", "Green"), ("yellow", "Yellow"), ("red", "Red")]})
    return HttpResponse(status=204)


@require_POST
def statement_add(request, pk):
    person = get_object_or_404(User, pk=pk)
    require(can_review_person(request.user, person))
    text = (request.POST.get("text") or "").strip()
    if text:
        SuccessStatement.objects.create(person=person, text=text, sort=person.success_statements.count())
    return go_back(request, f"/people/{person.pk}/")
