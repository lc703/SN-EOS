"""The operations behind the REST API and the MCP server.

Each tool is registered once with a name, description, JSON schema and handler. REST routes and MCP
`tools/call` both go through `run()`, which checks the token's scope, runs the handler as the token's
owner (so the usual permission rules apply), and writes an AuditLog row.
"""

import datetime as dt
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import Quarter, Team, User, monday_of
from core.permissions import can_edit_owned, can_edit_team_item, can_edit_todo, is_admin, is_team_member
from issues.models import Issue
from meetings.models import Headline, Meeting, MeetingRating
from rocks.models import RAG_CHOICES, RED, Rock, RockUpdate
from scorecard.models import Measurable, ScoreEntry
from todos.models import Todo, default_due

from .models import AuditLog

TOOLS = {}


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Tool:
    def __init__(self, name, description, schema, handler, write=False):
        self.name, self.description, self.schema, self.handler, self.write = name, description, schema, handler, write

    def definition(self):
        return {
            "name": self.name,
            "title": self.name.replace("_", " ").capitalize(),
            "description": self.description,
            "inputSchema": self.schema,
            "annotations": {"readOnlyHint": not self.write, "destructiveHint": False, "idempotentHint": not self.write},
        }


def tool(name, description, properties=None, required=(), write=False):
    schema = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = list(required)

    def deco(fn):
        TOOLS[name] = Tool(name, description, schema, fn, write)
        return fn

    return deco


# ---------------------------------------------------------------- argument helpers

TEAM = {"type": "string", "description": "Team slug, name or id. Defaults to your first team."}
QUARTER = {"type": "string", "description": 'Quarter name (e.g. "Q3 2026") or id. Defaults to the current quarter.'}
PERSON = {"type": "string", "description": "Person: email, name or id."}
DATE = {"type": "string", "format": "date", "description": "YYYY-MM-DD"}


def _team(user, value, required=False):
    if value in (None, ""):
        if required:
            raise ApiError(400, "team is required")
        return user.teams.order_by("sort").first() or Team.objects.filter(is_leadership=True).first() or Team.objects.first()
    value = str(value).strip()
    q = Q(slug__iexact=value) | Q(name__iexact=value) | Q(short_code__iexact=value)
    if value.isdigit():
        q |= Q(pk=int(value))
    team = Team.objects.filter(q).first()
    if not team:
        raise ApiError(404, f"No team matches {value!r}")
    return team


def _quarter(value):
    if value in (None, ""):
        q = Quarter.objects.current()
    else:
        value = str(value).strip()
        q = Quarter.objects.filter(Q(pk=int(value)) if value.isdigit() else Q(name__iexact=value)).first()
    if not q:
        raise ApiError(404, f"No quarter matches {value!r}")
    return q


def _person(value, default=None):
    if value in (None, ""):
        return default
    value = str(value).strip()
    q = Q(email__iexact=value) | Q(name__iexact=value)
    if value.isdigit():
        q |= Q(pk=int(value))
    person = User.objects.filter(q, is_active=True).first() or User.objects.filter(name__icontains=value, is_active=True).first()
    if not person:
        raise ApiError(404, f"No person matches {value!r}")
    return person


def _date(value, field="date"):
    if value in (None, ""):
        return None
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ApiError(400, f"{field} must be YYYY-MM-DD") from exc


def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(value, field):
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, f"{field} must be a number") from exc


def _get(model, pk, label):
    obj = model.objects.filter(pk=_int(pk, f"{label}_id")).first()
    if not obj:
        raise ApiError(404, f"{label.capitalize()} {pk} not found")
    return obj


def _allow(ok, message="You don't have permission to change that."):
    if not ok:
        raise ApiError(403, message)


def _member_or_admin(user, team):
    _allow(is_admin(user) or is_team_member(user, team), f"You're not on the {team.name} team.")


def _num(v):
    if v is None:
        return None
    v = Decimal(v)
    return int(v) if v == v.to_integral_value() else float(v)


# ---------------------------------------------------------------- serializers

def person_json(u):
    return {"id": u.pk, "name": u.display_name, "email": u.email} if u else None


def team_json(t):
    return {"id": t.pk, "slug": t.slug, "name": t.name, "is_leadership": t.is_leadership}


def rock_json(r, detail=False):
    data = {
        "id": r.pk, "title": r.title, "team": r.team.slug, "quarter": r.quarter.name,
        "kind": "company" if r.is_company else "departmental", "owner": person_json(r.owner),
        "status": r.status, "rag": r.rag, "due_date": r.due_date.isoformat() if r.due_date else None,
        "milestones_done": (r.milestone_progress or (0, 0))[0], "milestones_total": (r.milestone_progress or (0, 0))[1],
        "goal": r.goal.title if r.goal_id else None,
    }
    if detail:
        data["description"] = r.description
        data["milestones"] = [
            {"id": m.pk, "title": m.title, "done": m.done, "due_date": m.due_date.isoformat() if m.due_date else None}
            for m in r.milestones.all()
        ]
        data["updates"] = [rock_update_json(u) for u in r.updates.all()[:13]]
    return data


def rock_update_json(u):
    return {
        "id": u.pk, "rock_id": u.rock_id, "week": u.week_start.isoformat(), "rag": u.rag, "note": u.note,
        "recovery_plan": u.recovery_plan, "author": person_json(u.author),
    }


def issue_json(i):
    return {
        "id": i.pk, "title": i.title, "description": i.description, "team": i.team.slug, "owner": person_json(i.owner),
        "list": i.horizon, "status": i.status, "priority": i.priority, "resolution": i.resolution,
        "created_at": i.created_at.isoformat(),
    }


def todo_json(t):
    return {
        "id": t.pk, "title": t.title, "notes": t.notes, "team": t.team.slug if t.team_id else None,
        "private": t.is_private, "owner": person_json(t.owner), "due_date": t.due_date.isoformat(), "done": t.done,
        "overdue": t.overdue,
    }


def headline_json(h):
    return {
        "id": h.pk, "text": h.text, "kind": h.kind, "team": h.team.slug, "author": person_json(h.author),
        "created_at": h.created_at.isoformat(), "meeting_id": h.meeting_id,
    }


def meeting_json(m, detail=False):
    data = {
        "id": m.pk, "team": m.team.slug, "date": m.date.isoformat(), "facilitator": person_json(m.facilitator),
        "concluded": m.is_concluded, "average_rating": m.average_rating, "current_section": m.current_section,
    }
    if detail:
        data.update(
            segue_notes=m.segue_notes, notes=m.notes,
            attendees=[person_json(u) for u in m.attendees.all()],
            ratings=[{"person": person_json(r.user), "rating": r.rating} for r in m.ratings.select_related("user")],
            headlines=[headline_json(h) for h in m.headlines.select_related("team", "author")],
            new_todos=[todo_json(t) for t in m.new_todos.select_related("team", "owner")],
            solved_issues=[issue_json(i) for i in m.solved_issues.select_related("team", "owner")],
            cascading_messages=[c.text for c in m.cascades.all()],
        )
    return data


# ---------------------------------------------------------------- read tools

@tool("whoami", "The person this token acts as, with their teams.")
def whoami(user):
    return {**person_json(user), "is_admin": is_admin(user), "teams": [team_json(t) for t in user.teams.all()]}


@tool("list_teams", "All teams. Use a team's slug as the `team` argument elsewhere.")
def list_teams(user):
    return {"teams": [team_json(t) for t in Team.objects.all()]}


@tool("list_quarters", "Quarters, newest first, marking the current one.")
def list_quarters(user):
    current = Quarter.objects.current()
    return {
        "quarters": [
            {"id": q.pk, "name": q.name, "start": q.start_date.isoformat(), "end": q.end_date.isoformat(), "current": q == current}
            for q in Quarter.objects.all()
        ]
    }


@tool(
    "get_scorecard",
    "A team's weekly Scorecard: each Measurable with its goal, owner and values for the quarter's 13 weeks.",
    {"team": TEAM, "quarter": QUARTER},
)
def get_scorecard(user, team=None, quarter=None):
    team, quarter = _team(user, team), _quarter(quarter)
    weeks = quarter.weeks()
    ms = list(Measurable.objects.filter(team=team, active=True).select_related("owner"))
    entries = {}
    for e in ScoreEntry.objects.filter(measurable__in=ms, week_start__in=weeks):
        entries[(e.measurable_id, e.week_start)] = e.value
    rows = []
    for m in ms:
        values = []
        for w in weeks:
            v = entries.get((m.pk, w))
            values.append({"week": w.isoformat(), "value": _num(v), "on_goal": m.is_on_goal(v)})
        rows.append({
            "id": m.pk, "title": m.title, "owner": person_json(m.owner), "unit": m.unit,
            "goal": {"compare": m.goal_compare, "value": _num(m.goal), "display": m.goal_display}, "weeks": values,
        })
    return {"team": team.slug, "quarter": quarter.name, "measurables": rows}


@tool(
    "list_rocks",
    "Rocks (90-day priorities) for a team and quarter, with status, weekly G/Y/R and milestone progress.",
    {"team": TEAM, "quarter": QUARTER, "owner": PERSON, "mine": {"type": "boolean", "description": "Only your rocks."}},
)
def list_rocks(user, team=None, quarter=None, owner=None, mine=False):
    quarter = _quarter(quarter)
    qs = Rock.objects.filter(quarter=quarter).select_related("team", "quarter", "owner", "goal").prefetch_related("milestones", "updates")
    if _bool(mine):
        qs = qs.filter(owner=user)
    else:
        t = _team(user, team)
        qs = qs.filter(Q(team=t) | Q(is_company=True))
    if owner:
        qs = qs.filter(owner=_person(owner))
    return {"quarter": quarter.name, "rocks": [rock_json(r) for r in qs]}


@tool("get_rock", "One rock with description, milestones and its weekly updates.", {"rock_id": {"type": "integer"}}, ["rock_id"])
def get_rock(user, rock_id):
    return rock_json(_get(Rock, rock_id, "rock"), detail=True)


@tool(
    "list_issues",
    "A team's Issues List. Open issues by default, ranked by priority.",
    {"team": TEAM, "status": {"type": "string", "enum": ["open", "solved", "all"]}, "list": {"type": "string", "enum": ["short", "long"]}},
)
def list_issues(user, team=None, status="open", list=None):  # noqa: A002 - matches the public argument name
    team = _team(user, team)
    qs = Issue.objects.filter(team=team).select_related("team", "owner")
    if status in ("open", "solved"):
        qs = qs.filter(status=status)
    if list:
        qs = qs.filter(horizon=list)
    return {"team": team.slug, "issues": [issue_json(i) for i in qs[:200]]}


@tool(
    "list_todos",
    "To-Dos. Defaults to your own open to-dos; pass team for a team's list.",
    {"team": TEAM, "owner": PERSON, "include_done": {"type": "boolean"}},
)
def list_todos(user, team=None, owner=None, include_done=False):
    qs = Todo.objects.visible_to(user).select_related("team", "owner")
    if team:
        qs = qs.filter(team=_team(user, team), is_private=False)
    if owner:
        qs = qs.filter(owner=_person(owner))
    elif not team:
        qs = qs.filter(owner=user)
    if not _bool(include_done):
        qs = qs.filter(done=False)
    return {"todos": [todo_json(t) for t in qs[:200]]}


@tool("list_headlines", "Recent customer and employee headlines for a team.", {"team": TEAM, "limit": {"type": "integer"}})
def list_headlines(user, team=None, limit=20):
    team = _team(user, team)
    qs = Headline.objects.filter(team=team).select_related("team", "author")[: max(1, min(_int(limit, "limit"), 100))]
    return {"team": team.slug, "headlines": [headline_json(h) for h in qs]}


@tool("list_meetings", "Recent Level 10 meetings for a team.", {"team": TEAM, "limit": {"type": "integer"}})
def list_meetings(user, team=None, limit=10):
    team = _team(user, team)
    qs = Meeting.objects.filter(team=team).select_related("team", "facilitator").prefetch_related("ratings")
    return {"team": team.slug, "meetings": [meeting_json(m) for m in qs[: max(1, min(_int(limit, "limit"), 50))]]}


@tool("get_meeting", "One Level 10 meeting: attendees, ratings, headlines, new to-dos, solved issues and cascading messages.",
      {"meeting_id": {"type": "integer"}}, ["meeting_id"])
def get_meeting(user, meeting_id):
    return meeting_json(_get(Meeting, meeting_id, "meeting"), detail=True)


# ---------------------------------------------------------------- write tools

@tool(
    "set_measurable_value",
    "Enter or clear a weekly Scorecard value. The week can be any date in that week.",
    {"measurable_id": {"type": "integer"}, "week": DATE, "value": {"type": ["number", "string", "null"], "description": "Empty or null clears the cell. Yes/No measurables take yes/no."}},
    ["measurable_id", "week"],
    write=True,
)
def set_measurable_value(user, measurable_id, week, value=None):
    m = _get(Measurable, measurable_id, "measurable")
    _allow(can_edit_owned(user, m), "Only the measurable's owner (or an admin) can enter its numbers.")
    week = monday_of(_date(week, "week"))
    try:
        parsed = Measurable.parse("" if value is None else str(value), m.unit)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    if parsed is None:
        ScoreEntry.objects.filter(measurable=m, week_start=week).delete()
    else:
        ScoreEntry.objects.update_or_create(measurable=m, week_start=week, defaults={"value": parsed, "updated_by": user})
    return {"measurable_id": m.pk, "title": m.title, "week": week.isoformat(), "value": _num(parsed), "on_goal": m.is_on_goal(parsed)}


@tool(
    "create_rock",
    "Create a rock for a team and quarter.",
    {"team": TEAM, "title": {"type": "string"}, "owner": PERSON, "quarter": QUARTER, "description": {"type": "string"},
     "due_date": DATE, "company": {"type": "boolean", "description": "Company rock (leadership) rather than departmental."}},
    ["title"],
    write=True,
)
def create_rock(user, title, team=None, owner=None, quarter=None, description="", due_date=None, company=False):
    team = _team(user, team)
    _member_or_admin(user, team)
    if not str(title).strip():
        raise ApiError(400, "title is required")
    rock = Rock.objects.create(
        team=team, quarter=_quarter(quarter), title=str(title).strip()[:200], owner=_person(owner, user),
        description=description or "", due_date=_date(due_date, "due_date"), is_company=_bool(company) and team.is_leadership,
    )
    return rock_json(rock)


@tool(
    "update_rock",
    "Change a rock's title, description, owner, due date or status (on_track, off_track, done).",
    {"rock_id": {"type": "integer"}, "title": {"type": "string"}, "description": {"type": "string"}, "owner": PERSON,
     "due_date": DATE, "status": {"type": "string", "enum": ["on_track", "off_track", "done"]}},
    ["rock_id"],
    write=True,
)
def update_rock(user, rock_id, title=None, description=None, owner=None, due_date=None, status=None):
    rock = _get(Rock, rock_id, "rock")
    _allow(can_edit_owned(user, rock), "Only the rock's owner (or an admin) can change it.")
    if title is not None:
        rock.title = str(title).strip()[:200] or rock.title
    if description is not None:
        rock.description = description
    if owner:
        rock.owner = _person(owner)
    if due_date:
        rock.due_date = _date(due_date, "due_date")
    if status:
        if status not in dict(Rock.STATUS_CHOICES):
            raise ApiError(400, "status must be on_track, off_track or done")
        rock.status = status
    rock.save()
    return rock_json(rock)


@tool(
    "add_rock_update",
    "Post the weekly G/Y/R update on a rock. Red needs a recovery plan. Replaces an update already posted for that week.",
    {"rock_id": {"type": "integer"}, "rag": {"type": "string", "enum": ["green", "yellow", "red"]}, "note": {"type": "string"},
     "recovery_plan": {"type": "string"}, "week": {**DATE, "description": "Any date in the week. Defaults to this week."}},
    ["rock_id", "rag"],
    write=True,
)
def add_rock_update(user, rock_id, rag, note="", recovery_plan="", week=None):
    rock = _get(Rock, rock_id, "rock")
    _allow(can_edit_owned(user, rock), "Only the rock's owner (or an admin) can post its weekly update.")
    if rag not in dict(RAG_CHOICES):
        raise ApiError(400, "rag must be green, yellow or red")
    if rag == RED and not (recovery_plan or "").strip():
        raise ApiError(400, "A red rock needs a recovery plan.")
    week = monday_of(_date(week, "week") or timezone.localdate())
    update, _ = RockUpdate.objects.update_or_create(
        rock=rock, week_start=week,
        defaults={"rag": rag, "note": note or "", "recovery_plan": recovery_plan or "", "author": user},
    )
    return rock_update_json(update)


@tool(
    "create_issue",
    "Add an issue to a team's Issues List.",
    {"team": TEAM, "title": {"type": "string"}, "description": {"type": "string"}, "owner": PERSON,
     "list": {"type": "string", "enum": ["short", "long"], "description": "short = weekly L10 list, long = quarterly."}},
    ["title"],
    write=True,
)
def create_issue(user, title, team=None, description="", owner=None, list="short"):  # noqa: A002
    team = _team(user, team)
    _member_or_admin(user, team)
    if not str(title).strip():
        raise ApiError(400, "title is required")
    issue = Issue.objects.create(
        team=team, title=str(title).strip()[:240], description=description or "", owner=_person(owner, user),
        horizon=list if list in (Issue.SHORT, Issue.LONG) else Issue.SHORT, created_by=user,
    )
    return issue_json(issue)


@tool(
    "update_issue",
    "Edit an issue, set its priority (1-3, 0 clears), solve it with a resolution, or reopen it.",
    {"issue_id": {"type": "integer"}, "title": {"type": "string"}, "description": {"type": "string"}, "owner": PERSON,
     "priority": {"type": "integer", "minimum": 0, "maximum": 3}, "solve": {"type": "boolean"}, "resolution": {"type": "string"},
     "reopen": {"type": "boolean"}},
    ["issue_id"],
    write=True,
)
def update_issue(user, issue_id, title=None, description=None, owner=None, priority=None, solve=False, resolution=None, reopen=False):
    issue = _get(Issue, issue_id, "issue")
    _allow(can_edit_team_item(user, issue))
    fields = []
    if title is not None:
        issue.title = str(title).strip()[:240] or issue.title
        fields.append("title")
    if description is not None:
        issue.description = description
        fields.append("description")
    if owner:
        issue.owner = _person(owner)
        fields.append("owner")
    if fields:
        issue.save(update_fields=fields)
    if priority is not None:
        p = _int(priority, "priority")
        if p not in (0, 1, 2, 3):
            raise ApiError(400, "priority must be 0-3")
        issue.set_priority(p)
    if _bool(solve):
        issue.solve(resolution=resolution)
    elif _bool(reopen):
        issue.reopen()
    elif resolution is not None:
        issue.resolution = resolution
        issue.save(update_fields=["resolution"])
    return issue_json(issue)


@tool(
    "create_todo",
    "Create a 7-day To-Do. Without a team it's a private to-do for the owner.",
    {"title": {"type": "string"}, "team": TEAM, "owner": PERSON, "due_date": DATE, "notes": {"type": "string"},
     "private": {"type": "boolean"}},
    ["title"],
    write=True,
)
def create_todo(user, title, team=None, owner=None, due_date=None, notes="", private=None):
    if not str(title).strip():
        raise ApiError(400, "title is required")
    private = _bool(private) if private is not None else not team
    team_obj = _team(user, team) if team else None
    if team_obj:
        _member_or_admin(user, team_obj)
    who = _person(owner, user)
    if private and who != user:
        raise ApiError(400, "A private to-do can only be for yourself.")
    todo = Todo.objects.create(
        team=team_obj, title=str(title).strip()[:240], owner=who, due_date=_date(due_date, "due_date") or default_due(),
        notes=notes or "", is_private=private, created_by=user,
    )
    return todo_json(todo)


@tool(
    "update_todo",
    "Mark a to-do done or not done, or change its title, owner, due date or notes.",
    {"todo_id": {"type": "integer"}, "done": {"type": "boolean"}, "title": {"type": "string"}, "owner": PERSON,
     "due_date": DATE, "notes": {"type": "string"}},
    ["todo_id"],
    write=True,
)
def update_todo(user, todo_id, done=None, title=None, owner=None, due_date=None, notes=None):
    todo = _get(Todo, todo_id, "to-do")
    _allow(can_edit_todo(user, todo))
    fields = []
    if title is not None:
        todo.title = str(title).strip()[:240] or todo.title
        fields.append("title")
    if owner:
        todo.owner = _person(owner)
        fields.append("owner")
    if due_date:
        todo.due_date = _date(due_date, "due_date")
        fields.append("due_date")
    if notes is not None:
        todo.notes = notes
        fields.append("notes")
    if fields:
        todo.save(update_fields=fields)
    if done is not None:
        todo.set_done(_bool(done))
    return todo_json(todo)


@tool(
    "create_headline",
    "Share a customer or employee headline with a team. It shows in their next L10.",
    {"team": TEAM, "text": {"type": "string"}, "kind": {"type": "string", "enum": ["customer", "employee"]}},
    ["text"],
    write=True,
)
def create_headline(user, text, team=None, kind="customer"):
    team = _team(user, team)
    _member_or_admin(user, team)
    if not str(text).strip():
        raise ApiError(400, "text is required")
    meeting = Meeting.objects.filter(team=team, concluded_at__isnull=True).first()
    h = Headline.objects.create(
        team=team, meeting=meeting, text=str(text).strip()[:300], author=user,
        kind=kind if kind in (Headline.CUSTOMER, Headline.EMPLOYEE) else Headline.CUSTOMER,
    )
    return headline_json(h)


@tool(
    "rate_meeting",
    "Give your 1-10 rating for a Level 10 meeting.",
    {"meeting_id": {"type": "integer"}, "rating": {"type": "integer", "minimum": 1, "maximum": 10}},
    ["meeting_id", "rating"],
    write=True,
)
def rate_meeting(user, meeting_id, rating):
    meeting = _get(Meeting, meeting_id, "meeting")
    _member_or_admin(user, meeting.team)
    r = _int(rating, "rating")
    if not 1 <= r <= 10:
        raise ApiError(400, "rating must be 1-10")
    MeetingRating.objects.update_or_create(meeting=meeting, user=user, defaults={"rating": r})
    return meeting_json(meeting)


@tool(
    "add_meeting_notes",
    "Append text to a Level 10 meeting's segue (good news) or general notes.",
    {"meeting_id": {"type": "integer"}, "text": {"type": "string"}, "field": {"type": "string", "enum": ["notes", "segue"]}},
    ["meeting_id", "text"],
    write=True,
)
def add_meeting_notes(user, meeting_id, text, field="notes"):
    meeting = _get(Meeting, meeting_id, "meeting")
    _member_or_admin(user, meeting.team)
    attr = "segue_notes" if field == "segue" else "notes"
    current = getattr(meeting, attr)
    setattr(meeting, attr, (current + "\n" if current else "") + str(text).strip())
    meeting.save(update_fields=[attr])
    return meeting_json(meeting, detail=True)


# ---------------------------------------------------------------- runner

OBJECT_ID_KEYS = ("rock_id", "issue_id", "todo_id", "measurable_id", "meeting_id")


def run(token, name, args, channel, ip=None, action=None):
    """Run a tool as the token's owner. Returns (status, result-or-error-dict) and records an AuditLog row."""
    t = TOOLS.get(name)
    user = token.user
    args = {k: v for k, v in (args or {}).items() if v is not None}
    log = AuditLog(token=token, user=user, channel=channel, action=(action or name)[:80], is_write=bool(t and t.write), ip=ip)
    try:
        if not t:
            raise ApiError(404, f"Unknown tool {name!r}")
        if t.write and not token.can_write:
            raise ApiError(403, "This token is read only.")
        allowed = set(t.schema["properties"])
        unknown = set(args) - allowed
        if unknown:
            raise ApiError(400, f"Unknown argument(s): {', '.join(sorted(unknown))}")
        missing = [k for k in t.schema.get("required", []) if args.get(k) in (None, "")]
        if missing:
            raise ApiError(400, f"Missing argument(s): {', '.join(missing)}")
        with transaction.atomic():
            result = t.handler(user, **args)
        status = 201 if t.write and name.startswith("create_") else 200
        log.ok, log.status = True, status
    except ApiError as exc:
        status, result = exc.status, {"error": exc.message}
        log.ok, log.status, log.message = False, exc.status, exc.message[:255]
    except ValidationError as exc:
        msg = "; ".join(exc.messages)
        status, result = 400, {"error": msg}
        log.ok, log.status, log.message = False, 400, msg[:255]
    if t and t.write:
        log.payload = {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in args.items()}
        obj_key = next((k for k in OBJECT_ID_KEYS if k in args), None)
        if obj_key:
            log.object_type, log.object_id = obj_key[:-3], str(args[obj_key])
        elif isinstance(result, dict) and "id" in result:
            log.object_type, log.object_id = name.split("_", 1)[-1], str(result["id"])
    log.save()
    token.last_used_at = timezone.now()
    token.save(update_fields=["last_used_at"])
    return status, result
