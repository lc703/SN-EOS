from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import User
from core.permissions import can_review_person, can_view_private_people_notes, manages
from core.utils import require, scope
from rocks.models import Rock
from todos.models import Todo
from vision.models import CoreValue, Seat

from .models import OneOnOne, PeopleReview, ValueRating


def people_list(request):
    team, _ = scope(request)
    show_all = request.GET.get("all") == "1"
    users = User.objects.filter(is_active=True).prefetch_related("teams", "seats").order_by("name")
    if not show_all and team:
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
            "one_on_ones": OneOnOne.objects.filter(person=person).select_related("manager")[:20] if private else [],
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
