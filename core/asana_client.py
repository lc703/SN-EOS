"""Asana adapter for to-dos. Same approach as the Battle Planner's, so one credential set serves both apps.

SN EOS stays the source of truth; Asana is where people who live there do the work. A to-do is sent as one
task in a private "Strategic Action" project (a section per plant), assigned to the owner by email.
Completing the task in Asana checks the to-do off here. Nothing is sent to Asana unless a person asks.

Uses the Asana REST API directly with the requests library (installed with allauth).
Config: ASANA_PAT, ASANA_WORKSPACE_GID, optional ASANA_TEAM_GID, optional ASANA_PROJECT_GID.
"""
import datetime as dt

import requests
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from todos.models import Todo

from .models import AppSetting, Quarter

API = "https://app.asana.com/api/1.0"
PROJECT_NAME = "Strategic Action"
PLANT_SECTIONS = ["Company", "Kentucky", "Le Roy", "Mabel"]
TIMEOUT = 15


class AsanaError(Exception):
    pass


def is_configured():
    return bool(settings.ASANA_PAT and settings.ASANA_WORKSPACE_GID)


def _headers():
    return {"Authorization": f"Bearer {settings.ASANA_PAT}", "Accept": "application/json"}


def _request(method, path, **kwargs):
    if not settings.ASANA_PAT:
        raise AsanaError("Asana is not connected yet. Add ASANA_PAT in Railway.")
    try:
        resp = requests.request(method, f"{API}{path}", timeout=TIMEOUT, headers=_headers(), **kwargs)
    except requests.RequestException as exc:
        raise AsanaError(f"Could not reach Asana: {exc.__class__.__name__}") from exc
    if resp.status_code >= 400:
        try:
            msg = resp.json()["errors"][0]["message"]
        except Exception:
            msg = resp.text[:200]
        raise AsanaError(f"Asana said: {msg}")
    return resp.json()


def _call(method, path, **kwargs):
    return _request(method, path, **kwargs).get("data")


def _pages(path, params):
    """Every row of a list endpoint, following Asana's pages."""
    params, rows = dict(params, limit=100), []
    while True:
        body = _request("GET", path, params=dict(params))
        rows.extend(body.get("data") or [])
        offset = (body.get("next_page") or {}).get("offset")
        if not offset:
            return rows
        params["offset"] = offset


def _find_project():
    """Reuse the Battle Planner's Strategic Action project when this token can see it, instead of making a twin."""
    for p in _pages("/projects", {"workspace": settings.ASANA_WORKSPACE_GID, "archived": "false", "opt_fields": "name"}):
        if p.get("name") == PROJECT_NAME:
            return p["gid"]
    return None


def project_gid(create=True):
    gid = settings.ASANA_PROJECT_GID or AppSetting.get("asana_project_gid")
    if gid:
        return gid
    gid = _find_project()
    if not gid and create:
        data = {"name": PROJECT_NAME, "workspace": settings.ASANA_WORKSPACE_GID, "default_view": "list",
                "notes": "Action items sent from SN EOS and the SN Strategy Battle Planner."}
        if settings.ASANA_TEAM_GID:
            data["team"] = settings.ASANA_TEAM_GID
        gid = _call("POST", "/projects", json={"data": data})["gid"]
    if gid:
        AppSetting.put("asana_project_gid", gid)
    return gid


def section_gid(plant_name):
    name = plant_name if plant_name in PLANT_SECTIONS else "Company"
    key = f"asana_section_{name}"
    gid = AppSetting.get(key)
    if gid:
        return gid
    proj = project_gid()
    existing = {s["name"]: s["gid"] for s in _call("GET", f"/projects/{proj}/sections") or []}
    for n in PLANT_SECTIONS:
        if n not in existing:
            existing[n] = _call("POST", f"/projects/{proj}/sections", json={"data": {"name": n}})["gid"]
        AppSetting.put(f"asana_section_{n}", existing[n])
    return existing[name]


def user_gid(email):
    """Match by email. None when the person is not in Asana. A miss is only remembered for an hour, so
    someone who joins Asana later starts getting their tasks assigned."""
    if not email:
        return None
    key = f"asana_user_{email.lower()}"
    cached = AppSetting.get(key)
    if cached and not cached.startswith("-"):
        return cached
    if cached.startswith("-|"):
        try:
            if timezone.now() - dt.datetime.fromisoformat(cached[2:]) < dt.timedelta(hours=1):
                return None
        except ValueError:
            pass
    users = _pages("/users", {"workspace": settings.ASANA_WORKSPACE_GID, "opt_fields": "email"})
    found = next((u["gid"] for u in users if (u.get("email") or "").lower() == email.lower()), None)
    AppSetting.put(key, found or f"-|{timezone.now().isoformat()}")
    return found


def assignee_for(user):
    return user_gid(user.asana_email or user.email)


def ensure_project_member(gid):
    """The project is private: add each assignee so their task links open without 'request access'.
    Remembered per person, so it is one API call each."""
    if not gid:
        return
    key = f"asana_member_{gid}"
    if AppSetting.get(key):
        return
    _call("POST", f"/projects/{project_gid()}/addMembers", json={"data": {"members": gid}})
    AppSetting.put(key, "1")


def task_name(todo):
    parent = (todo.rock.title if todo.rock_id else todo.issue.title if todo.issue_id else "")[:40]
    return f"[{parent}] {todo.title}" if parent else todo.title


def task_notes(todo):
    """The Asana task description: the to-do's own notes first, then where it lives in SN EOS."""
    quarter = (todo.rock.quarter if todo.rock_id else None) or Quarter.objects.for_date(todo.due_date) or Quarter.objects.current()
    link = f"{settings.SITE_URL.rstrip('/')}{reverse('todo_edit', args=[todo.pk])}"
    lines = [f"Team: {todo.team.name if todo.team_id else 'Company'}"]
    if quarter:
        lines.append(f"Quarter: {quarter}")
    lines += [f"Owner: {todo.owner.display_name}", "", f"Tracked in SN EOS: {link}"]
    details = "\n".join(lines)
    notes = (todo.notes or "").strip()
    return f"{notes}\n\n---\n{details}" if notes else details


def update_task_notes(todo):
    """Push edited notes to the task that is already in Asana."""
    if not todo.asana_task_gid:
        return
    _call("PUT", f"/tasks/{todo.asana_task_gid}", json={"data": {"notes": task_notes(todo)}})


def create_task(owner, name, notes, due_on, plant_name="Company"):
    """Create a task in Strategic Action, assigned to `owner` and shared with them. Returns (gid, assigned)."""
    assignee = assignee_for(owner)
    proj = project_gid()
    data = {
        "name": name,
        "notes": notes,
        "due_on": due_on.isoformat(),
        "projects": [proj],
        "memberships": [{"project": proj, "section": section_gid(plant_name or "Company")}],
    }
    if assignee:
        ensure_project_member(assignee)
        data["assignee"] = assignee
    task = _call("POST", "/tasks", json={"data": data})
    return task["gid"], bool(assignee)


def send_todo(todo):
    """Create one Asana task for a to-do and remember its link. Sending twice never makes a second task:
    the row is locked while the task is created, so a double click or two people at once see one send."""
    if todo.asana_task_gid:
        return todo.asana_task_gid
    if todo.is_private:
        raise AsanaError("Private to-dos stay in SN EOS. Make it a team to-do to send it to Asana.")
    if not is_configured():
        raise AsanaError("Asana is not connected yet.")
    with transaction.atomic():
        row = Todo.objects.select_for_update(of=("self",)).select_related("team", "owner", "rock", "issue").get(pk=todo.pk)
        if row.asana_task_gid:
            todo.asana_task_gid, todo.asana_sent_at, todo.asana_unassigned = row.asana_task_gid, row.asana_sent_at, row.asana_unassigned
            return row.asana_task_gid
        gid, assigned = create_task(
            row.owner, task_name(row), task_notes(row), row.due_date, row.team.name if row.team_id else "Company"
        )
        row.asana_task_gid, row.asana_sent_at, row.asana_unassigned = gid, timezone.now(), not assigned
        row.save(update_fields=["asana_task_gid", "asana_sent_at", "asana_unassigned"])
    todo.asana_task_gid, todo.asana_sent_at, todo.asana_unassigned = row.asana_task_gid, row.asana_sent_at, row.asana_unassigned
    return gid


def maybe_sync(every_minutes=10):
    """Pull completions back at most every few minutes, from page views. Never raises."""
    if not is_configured():
        return
    if not (settings.ASANA_PROJECT_GID or AppSetting.get("asana_project_gid")) and not Todo.objects.exclude(asana_task_gid="").exists():
        return
    try:
        last = AppSetting.get("asana_last_sync")
        now = timezone.now()
        if last and now - dt.datetime.fromisoformat(last) < dt.timedelta(minutes=every_minutes):
            return
        AppSetting.put("asana_last_sync", now.isoformat())
        sync_completed(last or None)
        fix_unassigned()
    except Exception:
        pass


def fix_unassigned():
    """Assign tasks that went out before their owner was found in Asana. Returns how many were fixed."""
    fixed = 0
    for todo in Todo.objects.filter(asana_unassigned=True).exclude(asana_task_gid="").select_related("owner"):
        gid = assignee_for(todo.owner)
        if not gid:
            continue
        ensure_project_member(gid)
        _call("PUT", f"/tasks/{todo.asana_task_gid}", json={"data": {"assignee": gid}})
        todo.asana_unassigned = False
        todo.save(update_fields=["asana_unassigned"])
        fixed += 1
    return fixed


def sync_completed(since=None):
    """Pull completion back: a to-do is checked off when its task is done in Asana. Returns how many changed."""
    proj = project_gid(create=False)
    if not proj:
        return 0
    params = {"project": proj, "opt_fields": "completed,completed_at"}
    if since:
        params["modified_since"] = since
    done = {t["gid"]: t.get("completed_at") for t in _pages("/tasks", params) if t.get("completed")}
    updated = 0
    for todo in Todo.objects.filter(asana_task_gid__in=list(done), asana_completed_at__isnull=True):
        when = parse_datetime(done[todo.asana_task_gid] or "") or timezone.now()
        todo.asana_completed_at = when
        fields = ["asana_completed_at"]
        if not todo.done:
            todo.done, todo.done_at = True, when
            fields += ["done", "done_at"]
        todo.save(update_fields=fields)
        updated += 1
    return updated


def push_notes_if_changed(todo, old_notes):
    """After an edit: keep the Asana description in step. Returns an error message or ''."""
    if not todo.asana_task_gid or todo.notes == old_notes or not is_configured():
        return ""
    try:
        update_task_notes(todo)
    except AsanaError as exc:
        return str(exc)
    return ""
