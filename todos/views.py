import datetime as dt

from django import forms
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.forms import DateInput, PersonField, StyledForm, people_choices
from core.models import User
from core.permissions import can_edit_todo, can_view_todo, is_admin, is_team_member
from core.utils import go_back, is_htmx, require, scope
from meetings.models import Meeting

from .models import Todo, default_due, weekly_completion


class TodoForm(StyledForm, forms.ModelForm):
    owner = PersonField(queryset=None)

    class Meta:
        model = Todo
        fields = ["title", "owner", "due_date", "is_private", "notes"]
        widgets = {"due_date": DateInput(), "notes": forms.Textarea(attrs={"rows": 2})}

    full_width = ["title"]

    def __init__(self, *args, team=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        team = team or (self.instance.team if self.instance.team_id else None)
        self.fields["owner"].queryset = people_choices(team, include=[self.instance.owner_id, getattr(user, "pk", None)])
        if user and not self.instance.pk:
            self.fields["owner"].initial = user.pk
            self.fields["due_date"].initial = default_due()


def create_todo(user, team, data, issue=None, rock=None, meeting=None):
    """Shared by the To-Do page, the IDS solve flow and the L10 meeting."""
    title = (data.get("title") or "").strip()
    if not title:
        return None
    owner = User.objects.filter(pk=data.get("owner") or user.pk).first() or user
    due = data.get("due_date") or default_due()
    is_private = str(data.get("is_private", "")).lower() in {"1", "on", "true"} and not (issue or meeting)
    return Todo.objects.create(
        team=team,
        title=title[:240],
        owner=owner,
        due_date=due,
        is_private=is_private,
        notes=data.get("notes", ""),
        issue=issue,
        rock=rock,
        meeting=meeting,
        created_by=user,
    )


def todos_list(request):
    team, quarter = scope(request)
    user = request.user
    who = request.GET.get("owner", "")
    show = request.GET.get("show", "open")
    team_qs = Todo.objects.filter(team=team, is_private=False).select_related("owner", "rock", "issue")
    if who.isdigit():
        team_qs = team_qs.filter(owner_id=int(who))
    if show == "open":
        listed = team_qs.filter(done=False)
    else:
        listed = team_qs.filter(Q(done=False) | Q(done_at__gte=timezone.now() - dt.timedelta(days=14)))
    private = Todo.objects.filter(is_private=True).filter(Q(owner=user) | Q(created_by=user)).filter(done=False)

    base = Todo.objects.filter(team=team, is_private=False)
    weekly = weekly_completion(base, weeks=4)
    members = team.members.filter(is_active=True) if team else User.objects.none()
    people = []
    for m in members:
        rows = weekly_completion(base.filter(owner=m), weeks=4)
        people.append({"user": m, "weeks": rows, "open": base.filter(owner=m, done=False).count()})
    can_add = is_admin(user) or is_team_member(user, team)
    return render(
        request,
        "todos/todos.html",
        {
            "todos": listed,
            "private": private,
            "weekly": weekly,
            "people": people,
            "members": members,
            "who": who,
            "show": show,
            "form": TodoForm(team=team, user=user),
            "can_add": can_add,
            "today": timezone.localdate(),
        },
    )


@require_POST
def todo_new(request):
    team, _ = scope(request)
    form = TodoForm(request.POST, team=team, user=request.user)
    if form.is_valid():
        if not form.cleaned_data["is_private"]:
            require(is_admin(request.user) or is_team_member(request.user, team))
        meeting = Meeting.objects.filter(pk=request.POST.get("meeting") or 0).first()
        todo = form.save(commit=False)
        todo.team = team
        todo.created_by = request.user
        todo.meeting = meeting
        if meeting:
            todo.is_private = False
        todo.save()
        if not is_htmx(request):
            messages.success(request, f"To-do added for {todo.owner.first}.")
    else:
        messages.error(request, "To-do needs a title and an owner.")
    return go_back(request, "/todos/")


@require_POST
def todo_toggle(request, pk):
    todo = get_object_or_404(Todo, pk=pk)
    require(can_edit_todo(request.user, todo))
    todo.set_done(request.POST.get("done") in {"1", "on", "true"})
    if is_htmx(request) and request.POST.get("partial"):
        return render(request, "todos/_todo.html", {"t": todo, "today": timezone.localdate(), "compact": request.POST.get("compact")})
    return go_back(request, "/todos/")


def todo_edit(request, pk):
    todo = get_object_or_404(Todo.objects.select_related("team", "rock", "issue"), pk=pk)
    require(can_view_todo(request.user, todo))
    editable = can_edit_todo(request.user, todo)
    form = TodoForm(request.POST or None, instance=todo, user=request.user)
    if request.method == "POST":
        require(editable)
        if "delete" in request.POST:
            todo.delete()
            messages.success(request, "To-do deleted.")
            return go_back(request, "/todos/")
        if form.is_valid():
            form.save()
            messages.success(request, "To-do saved.")
            return go_back(request, "/todos/")
    return render(request, "todos/todo_form.html", {"form": form, "obj": todo, "editable": editable})
