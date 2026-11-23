"""Tools shared by the REST API and the MCP server.

Every call runs as one person (the token owner) with that person's permissions on the site. Writes are
recorded in the audit log. 1:1s, Quarterly Conversations and People Analyzer data are never exposed.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from core import asana_client
from core.models import Quarter, Team, User, monday_of
from core.permissions import can_edit_owned, can_edit_team_item, can_edit_todo, is_admin, is_team_member
from issues.models import Issue
from meetings.models import Headline, Meeting, MeetingRating
from rocks.models import Milestone, Rock
from rocks.services import record_update, set_done
from scorecard.models import Measurable, Plant, ScoreEntry
from scorecard.plants import layout
from todos.models import Todo

from .models import AuditLog

TOOLS = {}


class ToolError(Exception):
    """A problem the caller can fix (bad input, not found)."""


class ToolForbidden(ToolError):
    """Not allowed for this person or token."""


@dataclass
class Actor:
    user: User
    source: str = AuditLog.API
    token: object = None

    @property
    def can_write(self):
        return self.token is None or self.token.can_write

    def log(self, action, obj=None, summary="", **data):
        AuditLog.objects.create(
            user=self.user, token=self.token, source=self.source, action=action,
            object_type=obj._meta.model_name if obj is not None else "", object_id=str(obj.pk) if obj is not None else "",
            summary=summary[:300], data=_jsonable(data),
        )


def tool(name, description, properties=None, required=(), write=False):
    def register(fn):
        TOOLS[name] = {
            "name": name, "fn": fn, "write": write, "description": description,
            "schema": {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False},
        }
        return fn
    return register


def call(actor, name, args):
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolError(f"Unknown tool '{name}'.")
    if spec["write"] and not actor.can_write:
        raise ToolForbidden("This token is read-only.")
    args = dict(args or {})
    unknown = set(args) - set(spec["schema"]["properties"])
    if unknown:
        raise ToolError(f"Unknown argument(s): {', '.join(sorted(unknown))}.")
    missing = [k for k in spec["schema"]["required"] if args.get(k) in (None, "")]
    if missing:
        raise ToolError(f"Missing required argument(s): {', '.join(missing)}.")
    try:
        return spec["fn"](actor, **args)
    except PermissionDenied as exc:
        raise ToolForbidden(str(exc) or "You don't have permission to do that.") from exc
    except ValidationError as exc:
        raise ToolError(" ".join(exc.messages)) from exc


# ---- helpers -------------------------------------------------------------------------------

def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


def _allow(ok, msg="You don't have permission to do that."):
    if not ok:
        raise PermissionDenied(msg)


def _get(model, pk, label):
    try:
        return model.objects.get(pk=int(pk))
    except (model.DoesNotExist, ValueError, TypeError):
        raise ToolError(f"No {label} with id {pk}.")


def _team(actor, ref=None):
    if ref in (None, ""):
        team = actor.user.home_team or actor.user.teams.first() or Team.objects.filter(is_leadership=True).first()
        if team is None:
            raise ToolError("No team given and you don't belong to one.")
        return team
    ref = str(ref).strip()
    q = Q(slug__iexact=ref) | Q(name__iexact=ref) | Q(short_code__iexact=ref)
    if ref.isdigit():
        q |= Q(pk=int(ref))
    team = Team.objects.filter(q).first()
    if team is None:
        raise ToolError(f"No team '{ref}'. Teams: {', '.join(Team.objects.values_list('slug', flat=True))}.")
    return team


def _person(ref, default=None):
    if ref in (None, ""):
        return default
    ref = str(ref).strip()
    if ref.lower() == "me":
        return default
    q = Q(email__iexact=ref) | Q(name__iexact=ref)
    if ref.isdigit():
        q |= Q(pk=int(ref))
    found = list(User.objects.filter(q, is_active=True)[:2])
    if len(found) != 1:
        raise ToolError(f"No single active person matches '{ref}'. Use an email address.")
    return found[0]


def _date(raw, field="date"):
    if raw in (None, ""):
        return None
    d = parse_date(str(raw))
    if d is None:
        raise ToolError(f"{field} must be YYYY-MM-DD.")
    return d


def _quarter(ref=None):
    if ref:
        cond = Q(name__iexact=str(ref))
        if str(ref).isdigit():
            cond |= Q(pk=int(ref))
        q = Quarter.objects.filter(cond).first()
        if q is None:
            raise ToolError(f"No quarter '{ref}'.")
        return q
    q = Quarter.objects.current()
    if q is None:
        raise ToolError("No quarter set up yet.")
    return q


def _user(u):
    return {"id": u.pk, "name": u.display_name, "email": u.email} if u else None


def _measurable(m, weeks=None):
    out = {
        "id": m.pk, "title": m.title, "plant": m.plant_name, "team": m.team.slug, "owner": _user(m.owner), "unit": m.unit,
        "source": m.source,
        "goal": {"compare": m.goal_compare, "value": m.goal, "display": m.goal_display},
    }
    if weeks is not None:
        entries = {e.week_start: e for e in m.entries.filter(week_start__in=weeks)}
        out["weeks"] = [
            {"week": w, "value": entries[w].value if w in entries else None,
             "display": m.format_value(entries[w].value) if w in entries else "",
             "on_goal": m.is_on_goal(entries[w].value) if w in entries else None}
            for w in weeks
        ]
    return out


def _rock(r, detail=False):
    out = {
        "id": r.pk, "title": r.title, "team": r.team.slug, "kind": r.kind_label.lower(), "owner": _user(r.owner),
        "status": r.status, "due_date": r.due_date, "quarter": r.quarter.name,
        "milestones": {"done": sum(m.done for m in r.milestones.all()), "total": len(r.milestones.all())},
    }
    latest = r.updates.first()
    out["latest_update"] = _update(latest) if latest else None
    if detail:
        out["description"] = r.description
        out["milestone_list"] = [{"id": m.pk, "title": m.title, "due_date": m.due_date, "done": m.done} for m in r.milestones.all()]
        out["updates"] = [_update(u) for u in r.updates.all()[:13]]
    return out


def _update(u):
    return {"week": u.week_start, "color": u.color, "note": u.note, "recovery_plan": u.recovery_plan, "author": _user(u.author)}


def _issue(i):
    return {
        "id": i.pk, "title": i.title, "description": i.description, "team": i.team.slug, "owner": _user(i.owner),
        "list": "long_term" if i.horizon == Issue.LONG else "short_term", "status": i.status, "priority": i.priority,
        "resolution": i.resolution, "created_at": i.created_at,
    }


def _todo(t):
    return {
        "id": t.pk, "title": t.title, "notes": t.notes, "team": t.team.slug if t.team else None, "owner": _user(t.owner),
        "due_date": t.due_date, "done": t.done, "private": t.is_private, "overdue": t.overdue,
        "rock_id": t.rock_id, "issue_id": t.issue_id,
        "in_asana": bool(t.asana_task_gid), "asana_url": t.asana_url or None, "asana_state": t.asana_state,
        "asana_unassigned": t.asana_unassigned if t.asana_task_gid else None,
    }


def _can_post_to_team(actor, team):
    return is_admin(actor.user) or is_team_member(actor.user, team)


# ---- read tools ----------------------------------------------------------------------------

@tool("whoami", "Who this token acts as: your name, role, teams and the current quarter.")
def whoami(actor):
    q = Quarter.objects.current()
    return {
        "user": _user(actor.user), "role": actor.user.role, "can_write": actor.can_write,
        "teams": [{"slug": t.slug, "name": t.name, "leadership": t.is_leadership} for t in actor.user.teams.all()],
        "home_team": actor.user.home_team.slug if actor.user.home_team else None,
        "quarter": {"name": q.name, "start": q.start_date, "end": q.end_date} if q else None,
        "this_week": monday_of(timezone.localdate()),
    }


@tool("list_teams", "All teams with their slug (use the slug as `team` in other tools).")
def list_teams(actor):
    return [{"slug": t.slug, "name": t.name, "leadership": t.is_leadership, "members": t.members.count()} for t in Team.objects.all()]


@tool(
    "my_90",
    "Open to-dos, this quarter's rocks, measurables, open issues, seats and upcoming meetings. "
    "Defaults to you. Pass person (email, name, or id) for someone else's 90. "
    "Private to-dos are included only when you can already see them. "
    "1:1s, Quarterly Conversations, GWC and People Analyzer are never included.",
    {"person": {"type": "string", "description": "Optional email, name, or id. Omit for yourself."}},
)
def my_90(actor, person=None):
    q = Quarter.objects.current()
    subject = _person(person, actor.user) if person else actor.user
    weeks = q.weeks() if q else []
    this = monday_of(timezone.localdate())
    weeks = [w for w in weeks if w <= this][-4:]
    todos = Todo.objects.visible_to(actor.user).filter(owner=subject, done=False).select_related("team", "owner")
    meetings = Meeting.objects.filter(
        team__in=subject.teams.all(),
        concluded_at__isnull=True,
        date__gte=timezone.localdate() - dt.timedelta(days=1),
    ).select_related("team").order_by("date", "id").distinct()[:5]
    return {
        "person": _user(subject),
        "todos": [_todo(t) for t in todos[:50]],
        "rocks": [_rock(r) for r in Rock.objects.filter(owner=subject, quarter=q).select_related("team", "owner", "quarter").prefetch_related("milestones", "updates")] if q else [],
        "measurables": [_measurable(m, weeks) for m in subject.measurables.filter(active=True).select_related("team", "owner", "plant")],
        "issues": [_issue(i) for i in Issue.objects.filter(owner=subject, status=Issue.OPEN).select_related("team", "owner")[:50]],
        "seats": [
            {"id": s.pk, "title": s.title, "team": s.team.slug if s.team_id else None}
            for s in subject.seats.select_related("team")
        ],
        "meetings": [{"id": m.pk, "team": m.team.slug, "date": m.date.isoformat()} for m in meetings],
    }


def _plant_filter(ref):
    """(is_filtering, plant). "company" means Company measurables (no plant)."""
    text = (ref or "").strip() if isinstance(ref, str) else ref
    if not text:
        return False, None
    if str(text).strip().lower() == "company":
        return True, None
    plant = Plant.find(str(text))
    if plant is None:
        names = ", ".join(["company"] + [p.slug for p in Plant.objects.all()])
        raise ToolError(f"Unknown plant '{text}'. Use one of: {names}.")
    return True, plant


@tool("get_scorecard",
      "The company Scorecard: Company measurables first, then each plant's measurables (Kentucky, Le Roy, Mabel) "
      "grouped by name. Each has goal, owner, plant and weekly values for the quarter (13 weeks).",
      {"plant": {"type": "string", "description": "Only this plant's rows: 'company', 'kentucky', 'le-roy' or 'mabel'. Omit for everything."},
       "team": {"type": "string", "description": "Optional: only measurables on this team (rarely needed)."},
       "quarter": {"type": "string", "description": "e.g. 'Q4 2026'. Defaults to the current quarter."}})
def get_scorecard(actor, team=None, quarter=None, plant=None):
    q = _quarter(quarter)
    weeks = q.weeks()
    ms = Measurable.objects.filter(active=True).select_related("team", "owner", "plant")
    filtering, p = _plant_filter(plant)
    if filtering:
        ms = ms.filter(plant=p)
    if team not in (None, ""):
        ms = ms.filter(team=_team(actor, team))
    ordered, _ = layout(ms)
    return {"quarter": q.name, "weeks": weeks, "measurables": [_measurable(m, weeks) for m in ordered]}


@tool("list_rocks", "Rocks for a quarter. Filter by team and/or owner.",
      {"team": {"type": "string", "description": "Team slug. Omit for all teams."},
       "owner": {"type": "string", "description": "'me', an email, or a name."},
       "quarter": {"type": "string"}})
def list_rocks(actor, team=None, owner=None, quarter=None):
    q = _quarter(quarter)
    qs = Rock.objects.filter(quarter=q).select_related("team", "owner", "quarter").prefetch_related("milestones", "updates")
    if team:
        t = _team(actor, team)
        qs = qs.filter(Q(team=t) | Q(is_company=True))
    if owner:
        qs = qs.filter(owner=_person(owner, actor.user))
    return [_rock(r) for r in qs]


@tool("get_rock", "One rock with its milestones and weekly status history.", {"rock_id": {"type": "integer"}}, required=["rock_id"])
def get_rock(actor, rock_id):
    return _rock(_get(Rock, rock_id, "rock"), detail=True)


@tool("list_issues", "A team's Issues List (open by default).",
      {"team": {"type": "string"}, "list": {"type": "string", "enum": ["short_term", "long_term", "all"], "default": "short_term"},
       "status": {"type": "string", "enum": ["open", "solved"], "default": "open"}})
def list_issues(actor, team=None, list="short_term", status="open"):
    t = _team(actor, team)
    qs = Issue.objects.filter(team=t, status=status).select_related("team", "owner")
    if list != "all":
        qs = qs.filter(horizon=Issue.LONG if list == "long_term" else Issue.SHORT)
    return [_issue(i) for i in qs[:200]]


@tool("list_todos", "To-Dos. Defaults to your own open to-dos. Private to-dos are only visible to their owner. "
      "Each to-do shows whether it is in Asana (in_asana, asana_url, asana_state: none/sent/done). Sending to Asana is done in the app.",
      {"team": {"type": "string"}, "owner": {"type": "string", "description": "'me' (default), email, name, or 'all'."},
       "include_done": {"type": "boolean", "default": False}})
def list_todos(actor, team=None, owner="me", include_done=False):
    qs = Todo.objects.visible_to(actor.user).select_related("team", "owner")
    if team:
        qs = qs.filter(team=_team(actor, team))
    if owner != "all":
        qs = qs.filter(owner=_person(owner, actor.user))
    if not include_done:
        qs = qs.filter(done=False)
    return [_todo(t) for t in qs[:200]]


@tool("list_headlines", "Recent customer and employee headlines for a team.",
      {"team": {"type": "string"}, "days": {"type": "integer", "default": 14}})
def list_headlines(actor, team=None, days=14):
    t = _team(actor, team)
    since = timezone.now() - dt.timedelta(days=int(days))
    qs = Headline.objects.filter(team=t, created_at__gte=since).select_related("author")
    return [{"id": h.pk, "kind": h.kind, "text": h.text, "author": _user(h.author), "created_at": h.created_at} for h in qs]


@tool("get_l10", "The team's current (or most recent) Level 10 Meeting: section, attendees, headlines, ratings.",
      {"team": {"type": "string"}})
def get_l10(actor, team=None):
    t = _team(actor, team)
    m = Meeting.objects.filter(team=t).prefetch_related("attendees", "ratings__user", "headlines").first()
    if m is None:
        return {"team": t.slug, "meeting": None}
    return {"team": t.slug, "meeting": {
        "id": m.pk, "date": m.date, "concluded": m.is_concluded, "section": m.current_section,
        "attendees": [_user(u) for u in m.attendees.all()],
        "headlines": [{"kind": h.kind, "text": h.text} for h in m.headlines.all()],
        "ratings": [{"user": _user(r.user), "rating": r.rating} for r in m.ratings.all()],
        "average_rating": m.average_rating, "cascading_messages": m.cascading_messages,
    }}


# ---- write tools ---------------------------------------------------------------------------

def _find_measurable(actor, measurable_id=None, measurable=None, team=None, plant=None):
    """A measurable by id, or by name (optionally within one plant or team). Names must match exactly one."""
    if measurable_id not in (None, ""):
        return _get(Measurable, measurable_id, "measurable")
    ref = "" if measurable is None else str(measurable).strip()
    if not ref:
        raise ToolError("Say which measurable: measurable_id, or measurable (its name or id).")
    qs = Measurable.objects.filter(active=True).select_related("team", "owner", "plant")
    filtering, p = _plant_filter(plant)
    if filtering:
        qs = qs.filter(plant=p)
    if team not in (None, ""):
        qs = qs.filter(team=_team(actor, team))
    if ref.isdigit():
        by_id = qs.filter(pk=int(ref)).first()
        if by_id:
            return by_id
    found = list(qs.filter(title__iexact=ref)[:6])
    if not found:
        raise ToolError(f"No active measurable named '{ref}'. Use get_scorecard to see the names.")
    if len(found) > 1:
        plants = ", ".join(sorted({m.plant.slug if m.plant_id else "company" for m in found}))
        raise ToolError(f"More than one measurable is named '{ref}' (plants: {plants}). Pass plant, or use measurable_id.")
    return found[0]


@tool("set_measurable_value",
      "Enter or replace a weekly Scorecard number (an upsert: the same week again updates it). Name the measurable by "
      "`measurable` (its name or id; add `plant` if the name is on several plants, e.g. OEE) or by `measurable_id`. `week` is any "
      "date in the week (defaults to this week). An empty value clears the week.",
      {"measurable_id": {"type": "integer"},
       "measurable": {"type": ["string", "integer"], "description": "Name or id, e.g. 'Prelim Proposal Deal Value'."},
       "plant": {"type": "string", "description": "'company', 'kentucky', 'le-roy' or 'mabel'. Only needed when several plants share a measurable name."},
       "team": {"type": "string", "description": "Team slug (optional narrowing; plant is usually what you want)."},
       "value": {"type": ["string", "number", "null"], "description": "Number, or yes/no for Yes/No measurables. Dollars may be sent as 11000000 or $11,000,000."},
       "week": {"type": "string", "description": "YYYY-MM-DD"}}, write=True)
def set_measurable_value(actor, measurable_id=None, value=None, week=None, measurable=None, team=None, plant=None):
    m = _find_measurable(actor, measurable_id, measurable, team, plant)
    _allow(can_edit_owned(actor.user, m), "Only the measurable's owner (or an admin) can enter its numbers.")
    monday = monday_of(_date(week, "week") or timezone.localdate())
    try:
        parsed = Measurable.parse("" if value is None else str(value), m.unit)
    except ValueError as exc:
        raise ToolError(str(exc))
    if parsed is None:
        created = False
        ScoreEntry.objects.filter(measurable=m, week_start=monday).delete()
    else:
        _, created = ScoreEntry.objects.update_or_create(measurable=m, week_start=monday, defaults={"value": parsed, "updated_by": actor.user})
    actor.log("scorecard.set_value", m, f"{m.title} week of {monday:%b %-d}: {m.format_value(parsed) or 'cleared'}", week=monday, value=parsed)
    return {
        "measurable_id": m.pk, "measurable": m.title, "plant": m.plant_name, "team": m.team.slug, "week": monday, "value": parsed,
        "display": m.format_value(parsed), "on_goal": m.is_on_goal(parsed), "created": created,
    }


@tool("update_rock_status", "Weekly rock check-in: green (on track), yellow (at risk) or red (off track). Red requires a recovery_plan.",
      {"rock_id": {"type": "integer"}, "color": {"type": "string", "enum": ["green", "yellow", "red"]},
       "note": {"type": "string"}, "recovery_plan": {"type": "string"}, "week": {"type": "string", "description": "YYYY-MM-DD, defaults to this week"}},
      required=["rock_id", "color"], write=True)
def update_rock_status(actor, rock_id, color, note="", recovery_plan="", week=None):
    r = _get(Rock, rock_id, "rock")
    _allow(can_edit_owned(actor.user, r), "Only the rock's owner (or an admin) can update it.")
    u = record_update(r, actor.user, color, note, recovery_plan, _date(week, "week"))
    actor.log("rock.update", r, f"{r.title}: {u.get_color_display()}", color=color, week=u.week_start, note=note, recovery_plan=recovery_plan)
    r.refresh_from_db()
    return _rock(r, detail=True)


@tool("set_rock_done", "Mark a rock done (or not done).", {"rock_id": {"type": "integer"}, "done": {"type": "boolean", "default": True}},
      required=["rock_id"], write=True)
def set_rock_done(actor, rock_id, done=True):
    r = _get(Rock, rock_id, "rock")
    _allow(can_edit_owned(actor.user, r), "Only the rock's owner (or an admin) can update it.")
    set_done(r, bool(done))
    actor.log("rock.done" if done else "rock.reopen", r, r.title)
    return _rock(r)


@tool("set_milestone", "Add a milestone to a rock, or mark one done. Give milestone_id to update, or title (+ due_date) to add.",
      {"rock_id": {"type": "integer"}, "milestone_id": {"type": "integer"}, "title": {"type": "string"},
       "due_date": {"type": "string"}, "done": {"type": "boolean"}}, required=["rock_id"], write=True)
def set_milestone(actor, rock_id, milestone_id=None, title=None, due_date=None, done=None):
    r = _get(Rock, rock_id, "rock")
    _allow(can_edit_owned(actor.user, r), "Only the rock's owner (or an admin) can change its milestones.")
    if milestone_id:
        ms = Milestone.objects.filter(rock=r, pk=milestone_id).first()
        if ms is None:
            raise ToolError(f"Rock {r.pk} has no milestone {milestone_id}.")
        if title:
            ms.title = title[:200]
        if due_date:
            ms.due_date = _date(due_date, "due_date")
        if done is not None:
            ms.done = bool(done)
        ms.save()
    else:
        if not title:
            raise ToolError("Give a title to add a milestone.")
        ms = Milestone.objects.create(rock=r, title=title[:200], due_date=_date(due_date, "due_date"), done=bool(done))
    actor.log("rock.milestone", r, f"{r.title}: {ms.title}{' (done)' if ms.done else ''}")
    return {"rock_id": r.pk, "milestone": {"id": ms.pk, "title": ms.title, "due_date": ms.due_date, "done": ms.done}}


@tool("create_issue", "Add an issue to a team's Issues List.",
      {"title": {"type": "string"}, "team": {"type": "string"}, "description": {"type": "string"},
       "list": {"type": "string", "enum": ["short_term", "long_term"], "default": "short_term"},
       "owner": {"type": "string", "description": "'me' (default), email or name"}}, required=["title"], write=True)
def create_issue(actor, title, team=None, description="", list="short_term", owner="me"):
    t = _team(actor, team)
    _allow(_can_post_to_team(actor, t), f"You're not on the {t.name} team.")
    i = Issue.objects.create(
        team=t, title=title.strip()[:240], description=description or "", owner=_person(owner, actor.user), created_by=actor.user,
        horizon=Issue.LONG if list == "long_term" else Issue.SHORT,
    )
    actor.log("issue.create", i, i.title, team=t.slug)
    return _issue(i)


@tool("update_issue", "Edit an issue: title, description, owner, list, or priority (1-3, 0 clears).",
      {"issue_id": {"type": "integer"}, "title": {"type": "string"}, "description": {"type": "string"}, "owner": {"type": "string"},
       "list": {"type": "string", "enum": ["short_term", "long_term"]}, "priority": {"type": "integer", "minimum": 0, "maximum": 3}},
      required=["issue_id"], write=True)
def update_issue(actor, issue_id, title=None, description=None, owner=None, list=None, priority=None):
    i = _get(Issue, issue_id, "issue")
    _allow(can_edit_team_item(actor.user, i))
    if title:
        i.title = title.strip()[:240]
    if description is not None:
        i.description = description
    if owner:
        i.owner = _person(owner, actor.user)
    if list:
        i.horizon = Issue.LONG if list == "long_term" else Issue.SHORT
    i.save()
    if priority is not None:
        i.set_priority(int(priority) or None)
    actor.log("issue.update", i, i.title)
    return _issue(i)


@tool("solve_issue", "IDS: mark an issue solved with the solution, optionally creating to-dos (title, owner, due_date).",
      {"issue_id": {"type": "integer"}, "resolution": {"type": "string"},
       "todos": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "owner": {"type": "string"}, "due_date": {"type": "string"}}, "required": ["title"]}}},
      required=["issue_id"], write=True)
def solve_issue(actor, issue_id, resolution="", todos=None):
    i = _get(Issue, issue_id, "issue")
    _allow(can_edit_team_item(actor.user, i))
    made = []
    for spec in todos or []:
        if not (spec or {}).get("title"):
            continue
        made.append(Todo.objects.create(
            team=i.team, title=spec["title"][:240], owner=_person(spec.get("owner"), actor.user),
            due_date=_date(spec.get("due_date"), "due_date") or timezone.localdate() + dt.timedelta(days=7),
            issue=i, created_by=actor.user,
        ))
    i.solve(resolution=resolution or None)
    actor.log("issue.solve", i, i.title, resolution=resolution, todos=[t.pk for t in made])
    return {"issue": _issue(i), "todos": [_todo(t) for t in made]}


@tool("create_todo", "Add a to-do (7-day action item). Defaults: owner you, due in 7 days, your home team.",
      {"title": {"type": "string"}, "team": {"type": "string"}, "owner": {"type": "string"}, "due_date": {"type": "string"},
       "notes": {"type": "string"}, "private": {"type": "boolean", "default": False},
       "rock_id": {"type": "integer"}, "issue_id": {"type": "integer"}}, required=["title"], write=True)
def create_todo(actor, title, team=None, owner="me", due_date=None, notes="", private=False, rock_id=None, issue_id=None):
    t = _team(actor, team)
    who = _person(owner, actor.user)
    if private:
        _allow(who.pk == actor.user.pk, "Private to-dos can only be for yourself.")
    else:
        _allow(_can_post_to_team(actor, t), f"You're not on the {t.name} team.")
    todo = Todo.objects.create(
        team=t, title=title.strip()[:240], owner=who, notes=notes or "", is_private=bool(private), created_by=actor.user,
        due_date=_date(due_date, "due_date") or timezone.localdate() + dt.timedelta(days=7),
        rock=_get(Rock, rock_id, "rock") if rock_id else None, issue=_get(Issue, issue_id, "issue") if issue_id else None,
    )
    actor.log("todo.create", todo, todo.title, team=t.slug, owner=who.email)
    return _todo(todo)


@tool("update_todo", "Complete, reopen or edit a to-do. Edited notes are pushed to its Asana task if it has one.",
      {"todo_id": {"type": "integer"}, "done": {"type": "boolean"}, "title": {"type": "string"}, "due_date": {"type": "string"},
       "notes": {"type": "string"}, "owner": {"type": "string"}}, required=["todo_id"], write=True)
def update_todo(actor, todo_id, done=None, title=None, due_date=None, notes=None, owner=None):
    todo = _get(Todo, todo_id, "to-do")
    if not Todo.objects.visible_to(actor.user).filter(pk=todo.pk).exists():
        raise ToolError(f"No to-do with id {todo_id}.")
    _allow(can_edit_todo(actor.user, todo))
    old_notes = todo.notes
    if title:
        todo.title = title.strip()[:240]
    if due_date:
        todo.due_date = _date(due_date, "due_date")
    if notes is not None:
        todo.notes = notes
    if owner:
        todo.owner = _person(owner, actor.user)
    todo.save()
    if done is not None:
        todo.set_done(done)
    actor.log("todo.update", todo, f"{todo.title}{' (done)' if todo.done else ''}")
    out = _todo(todo)
    problem = asana_client.push_notes_if_changed(todo, old_notes)
    if problem:
        out["asana_warning"] = f"Saved, but the Asana task was not updated: {problem}"
    return out


@tool("add_headline", "Share a customer or employee headline with a team. It shows up in the team's next L10.",
      {"text": {"type": "string"}, "team": {"type": "string"}, "kind": {"type": "string", "enum": ["customer", "employee"], "default": "customer"}},
      required=["text"], write=True)
def add_headline(actor, text, team=None, kind="customer"):
    t = _team(actor, team)
    _allow(_can_post_to_team(actor, t), f"You're not on the {t.name} team.")
    meeting = Meeting.objects.filter(team=t, concluded_at__isnull=True).first()
    h = Headline.objects.create(team=t, meeting=meeting, kind=kind if kind in ("customer", "employee") else "customer", text=text.strip()[:300], author=actor.user)
    actor.log("headline.create", h, h.text, team=t.slug)
    return {"id": h.pk, "team": t.slug, "kind": h.kind, "text": h.text, "meeting_id": meeting.pk if meeting else None}


@tool("rate_l10", "Give your 1-10 rating for an L10 meeting you attended.",
      {"meeting_id": {"type": "integer"}, "rating": {"type": "integer", "minimum": 1, "maximum": 10}}, required=["meeting_id", "rating"], write=True)
def rate_l10(actor, meeting_id, rating):
    m = _get(Meeting, meeting_id, "meeting")
    rating = int(rating)
    if not 1 <= rating <= 10:
        raise ToolError("Rating must be 1-10.")
    _allow(m.attendees.filter(pk=actor.user.pk).exists() or is_team_member(actor.user, m.team), "You weren't in this meeting.")
    m.attendees.add(actor.user)
    MeetingRating.objects.update_or_create(meeting=m, user=actor.user, defaults={"rating": rating})
    actor.log("l10.rate", m, f"{m}: {rating}")
    return {"meeting_id": m.pk, "rating": rating, "average": m.average_rating}


@tool("add_cascading_message", "Add a cascading message to an L10 (what to communicate to the rest of the company, and who tells them).",
      {"meeting_id": {"type": "integer"}, "message": {"type": "string"}}, required=["meeting_id", "message"], write=True)
def add_cascading_message(actor, meeting_id, message):
    m = _get(Meeting, meeting_id, "meeting")
    _allow(is_admin(actor.user) or is_team_member(actor.user, m.team), f"You're not on the {m.team.name} team.")
    m.cascading_messages = "\n".join(x for x in [m.cascading_messages.strip(), f"- {message.strip()}"] if x)
    m.save(update_fields=["cascading_messages"])
    actor.log("l10.cascade", m, message)
    return {"meeting_id": m.pk, "cascading_messages": m.cascading_messages}
