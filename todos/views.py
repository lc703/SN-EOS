import datetime as dt

from django import forms
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import asana_client
from core.forms import DateInput, PersonField, StyledForm, people_choices
from core.models import User
from core.scoping import company_items, for_team, is_rollup
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
    asana_client.maybe_sync()
    team, quarter = scope(request)
    user = request.user
    who = request.GET.get("owner", "")
    show = request.GET.get("show", "open")
    team_qs = for_team(Todo.objects.filter(is_private=False), team).select_related("owner", "rock", "issue", "team")
    if who.isdigit():
        team_qs = team_qs.filter(owner_id=int(who))
    if show == "open":
        listed = team_qs.filter(done=False)
    else:
        listed = team_qs.filter(Q(done=False) | Q(done_at__gte=timezone.now() - dt.timedelta(days=14)))
    company_listed = None
    if not is_rollup(team):
        company_qs = company_items(Todo.objects.filter(is_private=False), team).select_related("owner", "rock", "issue", "team")
        if who.isdigit():
            company_qs = company_qs.filter(owner_id=int(who))
        company_listed = company_qs.filter(done=False) if show == "open" else company_qs.filter(
            Q(done=False) | Q(done_at__gte=timezone.now() - dt.timedelta(days=14))
        )
    private = Todo.objects.filter(is_private=True).filter(Q(owner=user) | Q(created_by=user)).filter(done=False)

    base = for_team(Todo.objects.filter(is_private=False), team)
    weekly = weekly_completion(base, weeks=4)
    if is_rollup(team):
        members = User.objects.filter(is_active=True, teams__isnull=False).distinct().order_by("name", "email")
    else:
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
            "company_todos": list(company_listed) if company_listed is not None else [],
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
        send_if_asked(request, todo)
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


def _try_send(todo):
    """Send a to-do to Asana unless it is already there. Returns an error message or ''."""
    if todo.asana_task_gid:
        return ""
    if not asana_client.is_configured():
        return "Asana is not connected yet."
    try:
        asana_client.send_todo(todo)
    except asana_client.AsanaError as exc:
        return str(exc)
    return ""


def _notify_send(request, todo, error):
    if error:
        messages.error(request, f"Not sent to Asana: {error}")
    elif todo.asana_unassigned:
        messages.warning(request, f"Sent to Asana, but {todo.owner.first} was not found in Asana, so it is unassigned.")
    else:
        messages.success(request, "Sent to Asana.")


def send_if_asked(request, todo):
    """The add forms carry a 'Send to Asana' checkbox. Private to-dos never go."""
    if todo and request.POST.get("send_asana") and not todo.is_private and asana_client.is_configured():
        _notify_send(request, todo, _try_send(todo))


@require_POST
def todo_asana(request, pk):
    """Send this to-do to Asana. Safe to repeat: a to-do that is already there is never sent twice."""
    todo = get_object_or_404(Todo.objects.select_related("team", "owner", "rock", "issue"), pk=pk)
    require(can_edit_todo(request.user, todo))
    error = _try_send(todo)
    if is_htmx(request) and request.POST.get("partial"):
        return render(
            request, "todos/_todo.html",
            {"t": todo, "today": timezone.localdate(), "compact": request.POST.get("compact"), "asana_error": error},
        )
    _notify_send(request, todo, error)
    return go_back(request, "/todos/")


def todo_edit(request, pk):
    todo = get_object_or_404(Todo.objects.select_related("team", "rock", "issue"), pk=pk)
    require(can_view_todo(request.user, todo))
    editable = can_edit_todo(request.user, todo)
    old_notes = todo.notes
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
            problem = asana_client.push_notes_if_changed(todo, old_notes)
            if problem:
                messages.warning(request, f"Saved here, but Asana was not updated: {problem}")
            return go_back(request, "/todos/")
    return render(request, "todos/todo_form.html", {"form": form, "obj": todo, "editable": editable})
