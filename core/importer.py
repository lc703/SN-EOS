"""Import a Battle Planner `dumpdata` export into SN EOS.

Idempotent: every imported row remembers its old pk in `legacy_id`, so re-running updates
nothing (default) or refreshes fields from the file (`refresh=True`). Rows are never duplicated.
"""

import datetime as dt
from collections import Counter, OrderedDict, defaultdict

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from core.models import LegacyRecord, Quarter, Team, User
from issues.models import Issue
from meetings.models import Meeting, MeetingRating
from people.models import ConversationScore, OneOnOne, PeopleReview, SuccessStatement, ValueRating
from planning.models import ANNUAL, Session, SessionItem
from rocks.models import Milestone, Rock, RockUpdate
from scorecard.models import Measurable, ScoreEntry
from todos.models import Todo
from vision.models import VTO, CoreValue, Seat

SEAT_STATUS = {"green": Seat.FILLED, "yellow": Seat.FUTURE, "red": Seat.OPEN}
RAG_COLORS = {"green", "yellow", "red"}
RAG_TO_STATUS = {"green": Rock.ON_TRACK, "yellow": Rock.ON_TRACK, "red": Rock.OFF_TRACK, "complete": Rock.DONE}
RAG_TO_VALUE = {"green": ValueRating.PLUS, "yellow": ValueRating.MIXED, "red": ValueRating.MINUS}
# Old evaluations scored each criterion red/yellow/green; we average these into the 1-10 L10 rating.
RAG_TO_RATING = {"green": 10, "yellow": 7, "red": 4}
UNIT_MAP = {
    "%": Measurable.UNIT_PERCENT,
    "percent": Measurable.UNIT_PERCENT,
    "count": Measurable.UNIT_NUMBER,
    "number": Measurable.UNIT_NUMBER,
    "#": Measurable.UNIT_NUMBER,
    "$": Measurable.UNIT_CURRENCY,
    "currency": Measurable.UNIT_CURRENCY,
    "yes/no": Measurable.UNIT_YESNO,
    "yesno": Measurable.UNIT_YESNO,
}
DIRECTION_TO_COMPARE = {"up": Measurable.GTE, "down": Measurable.LTE}
GOAL_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
# Old metrics fed by an integration. SN EOS has no integrations yet, so these are typed in weekly.
AUTO_SOURCES = {"iquote_quotes", "iquote_rd", "attio_prelim", "attio_rd", "attio_final"}
STEP_TO_SECTION = {"open": "segue", "rocks": "rocks", "todos": "todos", "issues": "ids", "evaluate": "conclude"}

HANDLED = {
    "core.facility", "core.user", "core.quarter", "core.value", "core.valuestatement", "core.strategyhouse",
    "core.box", "core.visiondoc", "core.rock", "core.rockstatus", "core.milestone", "core.issue",
    "core.commitment", "core.scorecardmetric", "core.scorecardentry", "core.seat", "core.successstatement", "core.oneonone",
    "core.meeting", "core.meetingevaluation", "core.roundrobinanswer",
    "core.offsite", "core.offsitereflection", "core.offsitelesson", "core.swotitem", "core.fourwhatsitem",
    "core.priorityeval", "core.missioneval", "core.visioneval", "core.valueseval",
}
# Kept raw in LegacyRecord: no EOS equivalent.
ARCHIVED_NOTE = {
    "core.meetingcriterion": "L10 evaluation criteria",
    "core.roundrobinquestion": "round robin question bank",
}
SKIP_MODELS = {"sessions.session", "admin.logentry", "contenttypes.contenttype", "auth.permission"}


def _date(val):
    return parse_date(val) if val else None


def _dt(val):
    if not val:
        return None
    parsed = parse_datetime(val)
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _day_start(day):
    return timezone.make_aware(dt.datetime.combine(day, dt.time(9, 0)))


def _initials(name):
    """'Joel Senecal-Moseley' -> {'JSM', 'JS'}; 'Ben Steuart' -> {'BS'}."""
    words = [w for w in (name or "").replace("-", " ").split() if w[:1].isalpha()]
    out = {"".join(w[0] for w in words).upper()}
    spaced = [w for w in (name or "").split() if w[:1].isalpha()]
    if len(spaced) >= 2:
        out.add((spaced[0][0] + spaced[-1][0]).upper())
    return out if words else set()


def parse_goal(raw, unit):
    """'40%' -> 40, '$11M' -> 11000000, '' -> None. Raises ValueError if unreadable."""
    from decimal import Decimal

    text = (raw or "").strip().replace(" ", "")
    mult = 1
    if text[-1:].lower() in GOAL_SUFFIX and unit != Measurable.UNIT_YESNO:
        mult, text = GOAL_SUFFIX[text[-1].lower()], text[:-1]
    value = Measurable.parse(text, unit)
    return None if value is None else value * Decimal(mult)


def _split_title(text, limit=240):
    text = (text or "").strip()
    if len(text) <= limit:
        return text, ""
    return text[: limit - 1].rstrip() + "…", text


class BattlePlannerImporter:
    def __init__(self, rows, refresh=False, log=None):
        self.rows = rows
        self.refresh = refresh
        self.log = log or (lambda msg: None)
        self.by = defaultdict(list)
        for row in rows:
            self.by[row["model"]].append(row)
        self.stats = OrderedDict()
        self.notes = []
        self.users, self.teams, self.quarters = {}, {}, {}
        self.rocks, self.issues, self.values, self.seats, self.meetings = {}, {}, {}, {}, {}
        self.statements = {}

    # -- helpers -------------------------------------------------------------------------
    def _count(self, label, result):
        self.stats.setdefault(label, Counter())[result] += 1

    def upsert(self, model, legacy_id, fields, label=None):
        """Create by legacy_id, or update (refresh) / leave alone. Returns (obj, created)."""
        label = label or model._meta.verbose_name_plural.title()
        obj = model.objects.filter(legacy_id=legacy_id).first()
        if obj is None:
            obj = model(legacy_id=legacy_id, **fields)
            obj.save()
            self._count(label, "created")
            return obj, True
        if self.refresh:
            for k, v in fields.items():
                setattr(obj, k, v)
            obj.save()
            self._count(label, "updated")
        else:
            self._count(label, "unchanged")
        return obj, False

    def fields(self, model):
        return [(r["pk"], r["fields"]) for r in sorted(self.by.get(model, []), key=lambda r: r["pk"])]

    # -- run -----------------------------------------------------------------------------
    @transaction.atomic
    def run(self):
        self.import_teams()
        self.import_users()
        self.import_team_members()
        self.import_quarters()
        self.import_values()
        self.import_vto()
        self.import_rocks()
        self.import_milestones()
        self.import_issues()
        self.import_measurables()
        self.import_todos()
        self.import_seats()
        self.import_success_statements()
        self.import_one_on_ones()
        self.import_meetings()
        self.import_ratings()
        self.import_offsites()
        self.archive_rest()
        return self.stats

    def import_teams(self):
        for pk, f in self.fields("core.facility"):
            team = Team.objects.filter(legacy_id=pk).first() or Team.objects.filter(name__iexact=f["name"]).first()
            is_lead = f["name"].lower() in {"company", "leadership"} or f.get("sort") == 0
            data = {"short_code": f.get("short_code", ""), "sort": f.get("sort", 0), "is_leadership": is_lead}
            if team is None:
                team = Team.objects.create(name=f["name"], legacy_id=pk, legacy={"meeting_weekday": f.get("meeting_weekday")}, **data)
                self._count("Teams", "created")
            else:
                changed = team.legacy_id != pk
                team.legacy_id = pk
                if self.refresh:
                    for k, v in data.items():
                        setattr(team, k, v)
                    changed = True
                team.save()
                self._count("Teams", "updated" if changed else "unchanged")
            self.teams[pk] = team

    def import_users(self):
        for pk, f in self.fields("core.user"):
            email = (f.get("email") or f.get("username") or "").strip().lower()
            if not email:
                self.notes.append(f"user #{pk}: no email, skipped")
                continue
            user = User.objects.filter(legacy_id=pk).first() or User.objects.filter(email=email).first()
            role = User.ROLE_ADMIN if f.get("role") == "admin" else User.ROLE_MEMBER
            data = {
                "name": f.get("name") or " ".join(x for x in [f.get("first_name"), f.get("last_name")] if x),
                "role": role,
                "is_active": f.get("is_active", True),
                "home_team": self.teams.get(f.get("facility")),
            }
            legacy = {k: f.get(k) for k in ("asana_email", "date_joined", "last_login") if f.get(k)}
            if user is None:
                user = User(email=email, username=email, legacy_id=pk, legacy=legacy, **data)
                user.set_unusable_password()
                user.save()
                self._count("Users", "created")
            else:
                changed = user.legacy_id != pk
                user.legacy_id = pk
                if self.refresh:
                    for k, v in data.items():
                        setattr(user, k, v)
                    user.legacy = legacy
                    changed = True
                elif not user.name and data["name"]:
                    user.name, changed = data["name"], True
                user.save()
                self._count("Users", "updated" if changed else "unchanged")
            self.users[pk] = user

    def import_team_members(self):
        for pk, f in self.fields("core.facility"):
            team = self.teams[pk]
            members = [self.users[u] for u in f.get("team", []) if u in self.users]
            team.members.add(*members)

    def import_quarters(self):
        for pk, f in self.fields("core.quarter"):
            q = Quarter.objects.filter(legacy_id=pk).first() or Quarter.objects.filter(name=f["name"]).first()
            data = {"start_date": _date(f["start_date"]), "end_date": _date(f["end_date"]), "is_current": f.get("is_active", False)}
            if q is None:
                q = Quarter.objects.create(name=f["name"], legacy_id=pk, **data)
                self._count("Quarters", "created")
            else:
                q.legacy_id = pk
                if self.refresh:
                    for k, v in data.items():
                        setattr(q, k, v)
                q.save()
                self._count("Quarters", "updated" if self.refresh else "unchanged")
            self.quarters[pk] = q

    def import_values(self):
        statements = defaultdict(list)
        for pk, f in self.fields("core.valuestatement"):
            statements[f["value"]].append((f.get("sort", 0), f["text"]))
        for pk, f in self.fields("core.value"):
            # Old value statements were generic offsite evaluation prompts, not descriptions of the value.
            evals = [t for _, t in sorted(statements.get(pk, []))]
            obj, _ = self.upsert(
                CoreValue, pk,
                {"name": f["name"], "sort": f.get("sort", 0), "active": f.get("active", True), "legacy": {"evaluation_statements": evals}},
                label="Core values",
            )
            self.values[pk] = obj

    def import_vto(self):
        houses = self.fields("core.strategyhouse")
        docs = self.fields("core.visiondoc")
        if not houses and not docs:
            return
        vto = VTO.load()
        house = houses[-1][1] if houses else {}
        doc = docs[-1][1] if docs else {}
        three_measurables = "\n".join(x for x in [doc.get("three_year_target", ""), doc.get("three_year_measurables", "")] if x)
        mapped = {
            "purpose": house.get("purpose", ""),
            "ten_year_target": doc.get("ten_year_target") or house.get("vision", ""),
            "target_market": doc.get("target_market", ""),
            "uniques": doc.get("uniques", ""),
            "proven_process": doc.get("proven_process", ""),
            "guarantee": doc.get("guarantee", ""),
            "three_year_date": doc.get("three_year_date", ""),
            "three_year_revenue": doc.get("three_year_revenue", ""),
            "three_year_profit": doc.get("three_year_profit", ""),
            "three_year_measurables": three_measurables,
            "three_year_picture": doc.get("three_year_picture", ""),
            "one_year_date": doc.get("one_year_date", ""),
            "one_year_revenue": doc.get("one_year_revenue", ""),
            "one_year_profit": doc.get("one_year_profit", ""),
            "one_year_measurables": doc.get("one_year_measurables", ""),
            "one_year_goals": doc.get("one_year_goals", ""),
        }
        changed = 0
        for k, v in mapped.items():
            v = (v or "").replace("\u00a0", " ").strip()
            if v and (self.refresh or not getattr(vto, k)):
                if getattr(vto, k) != v:
                    setattr(vto, k, v)
                    changed += 1
        targets = [t for t in house.get("targets") or [] if isinstance(t, dict) and (t.get("label") or t.get("value"))]
        target_lines = [
            ": ".join(x for x in [t.get("label", "").strip(), " ".join(x for x in [t.get("value", ""), t.get("sub", "")] if x).strip()] if x)
            for t in targets
        ]
        if target_lines:
            current = [x for x in vto.one_year_measurables.splitlines() if x.strip()]
            missing = [x for x in target_lines if x not in current]
            if missing and (self.refresh or not any(x in current for x in target_lines)):
                vto.one_year_measurables = "\n".join(current + missing)
                changed += 1
        legacy = {
            "strategy_house": {k: house.get(k) for k in ("lessons", "rudder_note") if house.get(k)},
            "targets": targets,
        }
        if self.refresh or not vto.legacy or "boxes" in vto.legacy:
            vto.legacy = legacy
            changed += 1
        vto.save()
        self._count("V/TO", "updated" if changed else "unchanged")
        self.import_strategy_issues(house, houses[-1][0] if houses else None)

    def upsert_source(self, model, source, fields, label):
        """Upsert keyed on legacy['source'] for rows that come from a different old model."""
        obj = model.objects.filter(legacy__source=source).first()
        fields = fields | {"legacy": fields.get("legacy", {}) | {"source": source}}
        if obj is None:
            obj = model.objects.create(**fields)
            self._count(label, "created")
        elif self.refresh:
            for k, v in fields.items():
                setattr(obj, k, v)
            obj.save()
            self._count(label, "updated")
        else:
            self._count(label, "unchanged")
        return obj

    def import_strategy_issues(self, house, house_pk):
        """Strategy House challenge, issue/opportunity boxes and parked items -> the V/TO Issues List (long-term)."""
        lead = Team.objects.filter(is_leadership=True).first()
        if lead is None:
            return
        label = "Long-term issues (from Strategy House)"
        base = {"team": lead, "horizon": Issue.LONG, "status": Issue.OPEN}
        challenge = (house.get("major_business_challenge") or "").strip()
        if challenge and house_pk:
            title, desc = _split_title(challenge)
            self.upsert_source(Issue, f"strategyhouse:{house_pk}:challenge", base | {
                "title": title, "description": "\n\n".join(x for x in [desc, "Major business challenge (Strategy House)."] if x),
            }, label)
        for pk, f in self.fields("core.box"):
            statement = (f.get("statement") or "").strip() or f"{(f.get('kind') or 'Box').title()} #{pk}"
            title, long_text = _split_title(statement)
            parts = [long_text] if long_text else []
            if f.get("strategy"):
                parts.append(f"Strategy: {f['strategy'].strip()}")
            tactics = [t.strip() for t in (f.get("tactics") or []) if isinstance(t, str) and t.strip()]
            if tactics:
                parts.append("Tactics:\n" + "\n".join(f"- {t}" for t in tactics))
            if f.get("due_date"):
                parts.append(f"Due {f['due_date']}")
            owner = self.users.get(f.get("dri"))
            self.upsert_source(Issue, f"core.box:{pk}", base | {
                "title": title, "description": "\n\n".join(parts), "owner": owner, "created_by": owner,
                "legacy": {"kind": f.get("kind"), "strategy": f.get("strategy"), "tactics": tactics, "due_date": f.get("due_date")},
            }, label)
        for i, item in enumerate(house.get("parked") or []):
            text = item if isinstance(item, str) else (item or {}).get("text", "")
            if text.strip() and house_pk:
                title, desc = _split_title(text)
                self.upsert_source(Issue, f"strategyhouse:{house_pk}:parked:{i}", base | {"title": title, "description": desc}, label)

    def import_rocks(self):
        history = defaultdict(list)
        for pk, f in self.fields("core.rockstatus"):
            history[f["rock"]].append(f | {"_pk": pk})
        for pk, f in self.fields("core.rock"):
            team = self.teams.get(f["facility"])
            quarter = self.quarters.get(f["quarter"])
            if not team or not quarter:
                self.notes.append(f"rock #{pk}: missing team or quarter, skipped")
                continue
            hist = sorted(history.get(pk, []), key=lambda h: (h["week_start"], h["created_at"]))
            rag = hist[-1]["rag"] if hist else f.get("current_rag")
            status = Rock.DONE if f.get("is_complete") else RAG_TO_STATUS.get(rag, Rock.ON_TRACK)
            legacy = {
                "current_rag": f.get("current_rag"),
                "box": f.get("box"),
                "asana_task_gid": f.get("asana_task_gid"),
                "contributors": [self.users[u].display_name for u in f.get("contributors", []) if u in self.users],
            }
            obj, _ = self.upsert(
                Rock, pk,
                {
                    "quarter": quarter, "team": team, "is_company": team.is_leadership, "title": f["title"][:200],
                    "description": f.get("description", ""), "owner": self.users.get(f.get("owner")),
                    "due_date": _date(f.get("due_date")) or quarter.end_date, "status": status,
                    "sort": f.get("sort", 0), "legacy": legacy,
                },
                label="Rocks",
            )
            self.rocks[pk] = obj
            self.import_rock_updates(obj, hist)

    def import_rock_updates(self, rock, hist):
        """Weekly G/Y/R history -> RockUpdate, one per (rock, Monday). Later rows in the same week win."""
        from core.models import monday_of

        by_week = OrderedDict()
        for h in hist:
            week = _date(h.get("week_start"))
            if week and h.get("rag") in RAG_COLORS:
                by_week[monday_of(week)] = h
        for week, h in by_week.items():
            fields = {
                "rock": rock, "week_start": week, "color": h["rag"], "note": h.get("note") or "",
                "recovery_plan": h.get("recovery_plan") or "", "author": self.users.get(h.get("author")),
            }
            existing = RockUpdate.objects.filter(rock=rock, week_start=week).first()
            if existing and existing.legacy_id is None and not self.refresh:
                self._count("Rock weekly updates", "unchanged")
                continue
            if existing and existing.legacy_id != h["_pk"]:
                existing.legacy_id = h["_pk"]
                existing.save(update_fields=["legacy_id"])
            self.upsert(RockUpdate, h["_pk"], fields, label="Rock weekly updates")

    def import_milestones(self):
        for pk, f in self.fields("core.milestone"):
            rock = self.rocks.get(f["rock"])
            if not rock:
                self.notes.append(f"milestone #{pk}: rock #{f['rock']} not imported, skipped")
                continue
            people = [self.users[u].display_name for u in f.get("people", []) if u in self.users]
            self.upsert(
                Milestone, pk,
                {"rock": rock, "title": f["title"][:200], "due_date": _date(f.get("due_date")), "done": f.get("is_done", False),
                 "legacy": {"people": people, "completed_at": f.get("completed_at")}},
                label="Milestones",
            )

    def import_issues(self):
        ranks = defaultdict(int)
        for pk, f in self.fields("core.issue"):
            team = self.teams.get(f["facility"]) or Team.objects.filter(is_leadership=True).first()
            title, desc = _split_title(f["text"])
            status = Issue.SOLVED if f.get("status") == "resolved" else Issue.OPEN
            horizon = Issue.LONG if f.get("status") == "parked" else Issue.SHORT
            priority = None
            if status == Issue.OPEN and f.get("high_priority") and ranks[(team.pk, horizon)] < 3:
                ranks[(team.pk, horizon)] += 1
                priority = ranks[(team.pk, horizon)]
            owner = self.users.get(f.get("raised_by"))
            obj, _ = self.upsert(
                Issue, pk,
                {
                    "team": team, "title": title, "description": desc, "owner": owner, "created_by": owner,
                    "horizon": horizon, "status": status, "priority": priority,
                    "created_at": _dt(f.get("created_at")) or timezone.now(),
                    "legacy": {"status": f.get("status"), "high_priority": f.get("high_priority"), "quarter": f.get("quarter")},
                },
                label="Issues",
            )
            self.issues[pk] = obj

    def _owner_from_initials(self, initials, team):
        """Old metrics name owners by initials. Match one imported user, preferring the metric's team."""
        code = (initials or "").strip().upper()
        if not code:
            return None
        matches = [u for u in self.users.values() if code in _initials(u.name)]
        if len(matches) > 1 and team is not None:
            local = [u for u in matches if u.home_team_id == team.pk]
            matches = local or matches
        return matches[0] if len(matches) == 1 else None

    def import_measurables(self):
        lead = Team.objects.filter(is_leadership=True).first()
        self.measurables = {}
        unmatched, bad_goals, auto = set(), [], []
        for pk, f in self.fields("core.scorecardmetric"):
            team = self.teams.get(f.get("facility")) or lead
            unit = UNIT_MAP.get((f.get("unit") or "").strip().lower(), Measurable.UNIT_NUMBER)
            direction = (f.get("direction") or "").strip().lower()
            goal_compare = Measurable.EQ if unit == Measurable.UNIT_YESNO else DIRECTION_TO_COMPARE.get(direction, Measurable.GTE)
            goal = None
            # No direction in the old app meant "no color", so leave the goal empty to match.
            if f.get("goal") and (direction or unit == Measurable.UNIT_YESNO):
                try:
                    goal = parse_goal(f["goal"], unit)
                except ValueError:
                    bad_goals.append(f"{f['name']} ({f['goal']})")
            owner = self._owner_from_initials(f.get("owner"), team)
            if f.get("owner") and owner is None:
                unmatched.add(f["owner"].strip())
            source = f.get("source") or "manual"
            if source in AUTO_SOURCES and f.get("active", True):
                auto.append(f["name"])
            legacy = {k: f.get(k) for k in ("unit", "facility", "owner", "goal", "direction", "source") if k in f}
            obj, _ = self.upsert(
                Measurable, pk,
                {"team": team, "title": f["name"][:160], "unit": unit, "goal_compare": goal_compare, "goal": goal,
                 "owner": owner, "sort": f.get("sort", 0), "active": f.get("active", True), "legacy": legacy},
                label="Measurables",
            )
            self.measurables[pk] = obj
        if unmatched:
            self.notes.append(f"measurables: no unique user for owner initials {', '.join(sorted(unmatched))}; owner left blank")
        if bad_goals:
            self.notes.append(f"measurables: could not read goal for {'; '.join(bad_goals)}; goal left blank")
        if auto:
            self.notes.append(f"measurables: {', '.join(auto)} were auto-filled by iQuote/Attio in the old app; type them in weekly for now")
        self.import_score_entries()

    def import_score_entries(self):
        """Weekly values. Keyed by (measurable, Monday), so re-runs never duplicate a week."""
        from core.models import monday_of

        bad = []
        for pk, f in self.fields("core.scorecardentry"):
            m = self.measurables.get(f.get("metric"))
            week = _date(f.get("week_start"))
            if m is None or week is None:
                self._count("Scorecard values", "skipped")
                continue
            week = monday_of(week)
            try:
                value = Measurable.parse(f.get("value"), m.unit)
            except ValueError:
                bad.append(f"{m.title} {week.isoformat()} ({f.get('value')})")
                self._count("Scorecard values", "skipped")
                continue
            entry = ScoreEntry.objects.filter(measurable=m, week_start=week).first()
            by = self.users.get(f.get("entered_by"))
            if entry is None:
                ScoreEntry.objects.create(measurable=m, week_start=week, value=value, updated_by=by)
                self._count("Scorecard values", "created")
            elif self.refresh and entry.value != value:
                entry.value, entry.updated_by = value, by
                entry.save()
                self._count("Scorecard values", "updated")
            else:
                self._count("Scorecard values", "unchanged")
        if bad:
            self.notes.append(f"scorecard: skipped unreadable values: {'; '.join(bad)}")

    def _todo_team(self, f, owner):
        rock = self.rocks.get(f.get("rock"))
        issue = self.issues.get(f.get("issue"))
        if rock:
            return rock.team
        if issue:
            return issue.team
        if owner.home_team_id:
            return owner.home_team
        return owner.teams.first() or Team.objects.filter(is_leadership=True).first()

    def import_todos(self):
        for pk, f in self.fields("core.commitment"):
            owner = self.users.get(f.get("owner")) or self.users.get(f.get("created_by"))
            if not owner:
                self.notes.append(f"commitment #{pk}: no owner, skipped")
                continue
            title, long_text = _split_title(f["text"])
            notes = [x for x in [long_text, f.get("description", "")] if x]
            result = f.get("result") or "open"
            if result == "miss" and f.get("why_not"):
                notes.append(f"Missed: {f['why_not']}")
            due = _date(f.get("due_date")) or (_date(f.get("week_start")) or timezone.localdate()) + dt.timedelta(days=7)
            done = result == "hit"
            done_at = (_dt(f.get("asana_completed_at")) or _day_start(due)) if done else None
            self.upsert(
                Todo, pk,
                {
                    "team": self._todo_team(f, owner), "title": title, "notes": "\n\n".join(notes), "owner": owner,
                    "due_date": due, "done": done, "done_at": done_at, "rock": self.rocks.get(f.get("rock")),
                    "issue": self.issues.get(f.get("issue")), "created_by": self.users.get(f.get("created_by")),
                    "created_at": _dt(f.get("created_at")) or timezone.now(),
                    "legacy": {k: f.get(k) for k in ("result", "why_not", "week_start", "asana_task_gid", "asana_completed_at") if f.get(k)},
                },
                label="To-dos",
            )

    def import_seats(self):
        by_name = {u.display_name.lower(): u for u in self.users.values()}
        rows = self.fields("core.seat")
        for pk, f in rows:
            person = self.users.get(f.get("person")) or by_name.get((f.get("person_name") or "").strip().lower())
            obj, _ = self.upsert(
                Seat, pk,
                {"team": self.teams.get(f.get("facility")), "title": f["title"][:120], "person": person,
                 "person_name": "" if person else (f.get("person_name") or "")[:120], "roles": f.get("responsibilities", ""),
                 "status": SEAT_STATUS.get(f.get("status"), Seat.FILLED), "agency": bool(f.get("agency")),
                 "sort": f.get("sort", 0), "legacy": {"status": f.get("status"), "agency": f.get("agency")}},
                label="Seats",
            )
            self.seats[pk] = obj
        for pk, f in rows:
            seat = self.seats[pk]
            parent = self.seats.get(f.get("parent"))
            if seat.parent_id != (parent.pk if parent else None) and (self.refresh or seat.parent_id is None):
                seat.parent = parent
                seat.save(update_fields=["parent"])

    def import_success_statements(self):
        for pk, f in self.fields("core.successstatement"):
            person = self.users.get(f["user"])
            if not person:
                continue
            obj, _ = self.upsert(
                SuccessStatement, pk, {"person": person, "text": f["text"], "standard": f.get("standard", ""), "sort": f.get("sort", 0)},
                label="Success statements",
            )
            self.statements[pk] = obj

    def _manager_of(self, person):
        seat = Seat.objects.filter(person=person, parent__person__isnull=False).select_related("parent__person").first()
        return seat.parent.person if seat else None

    def import_one_on_ones(self):
        for pk, f in self.fields("core.oneonone"):
            person = self.users.get(f["user"])
            if not person:
                continue
            scores = f.get("scores") or {}
            manager = self.users.get(f.get("created_by")) or self._manager_of(person)
            date = _date(f.get("date")) or timezone.localdate()
            completed = _dt(f.get("completed_at"))
            obj, created = self.upsert(
                OneOnOne, pk,
                {"person": person, "manager": manager, "date": date, "kind": OneOnOne.ONE_ON_ONE,
                 "quarter": Quarter.objects.for_date(date), "highlight": (f.get("highlight") or "").strip(), "notes": "",
                 "completed_at": completed, "created_by": self.users.get(f.get("created_by")),
                 "created_at": completed or _day_start(date),
                 "legacy": {"scores": scores, "completed_at": f.get("completed_at")}},
                label="1:1s",
            )
            if created or self.refresh or not obj.scores.exists():
                self._scores_from_one_on_one(obj, scores)
            self._review_from_one_on_one(obj, scores, created)

    def _scores_from_one_on_one(self, one, scores):
        """'ss<pk>' / 'cv<pk>' keys -> one G/Y/R cell per success statement / core value."""
        one.scores.all().delete()
        cells = []
        for key, score in scores.items():
            ref = int(key[2:]) if key[2:].isdigit() else None
            target = {"ss": ("statement", self.statements), "cv": ("value", self.values)}.get(key[:2])
            if target is None or ref not in target[1]:
                self._count("1:1 grid cells", "skipped")
                continue
            color = (score or {}).get("rag") or ""
            cells.append(ConversationScore(
                conversation=one, color=color if color in RAG_COLORS else "", note=(score or {}).get("note") or "",
                **{target[0]: target[1][ref]},
            ))
        ConversationScore.objects.bulk_create(cells)
        if cells:
            self.stats.setdefault("1:1 grid cells", Counter())["mapped"] += len(cells)

    def _review_from_one_on_one(self, one, scores, created):
        cv = {int(k[2:]): v.get("rag") for k, v in scores.items() if k.startswith("cv") and k[2:].isdigit()}
        cv = {k: RAG_TO_VALUE[r] for k, r in cv.items() if r in RAG_TO_VALUE and k in self.values}
        if not cv:
            return
        review = PeopleReview.objects.filter(person=one.person, date=one.date, notes__startswith=f"From 1:1 #{one.legacy_id}").first()
        if review and not (created or self.refresh):
            self._count("People Analyzer reviews (from 1:1 core values)", "unchanged")
            return
        if review is None:
            review = PeopleReview.objects.create(
                person=one.person, reviewer=one.manager, date=one.date, notes=f"From 1:1 #{one.legacy_id} (Battle Planner)"
            )
            self._count("People Analyzer reviews (from 1:1 core values)", "created")
        else:
            self._count("People Analyzer reviews (from 1:1 core values)", "updated")
        for value_pk, rating in cv.items():
            ValueRating.objects.update_or_create(review=review, value=self.values[value_pk], defaults={"rating": rating})

    def import_meetings(self):
        answers = defaultdict(list)
        for pk, f in self.fields("core.roundrobinanswer"):
            answers[f["meeting"]].append(f)
        for pk, f in self.fields("core.meeting"):
            team = self.teams.get(f["facility"])
            if not team:
                continue
            date = _date(f["date"])
            segue = []
            if answers.get(pk):
                segue.append(f"Round robin: {f.get('round_robin_question', '')}".strip())
                for a in answers[pk]:
                    who = self.users[a["user"]].display_name if a["user"] in self.users else "?"
                    segue.append(f"- {who}: {a['answer']}")
            obj, created = self.upsert(
                Meeting, pk,
                {"team": team, "quarter": self.quarters.get(f.get("quarter")), "date": date,
                 "current_section": STEP_TO_SECTION.get(f.get("current_step"), "segue"), "segue_notes": "\n".join(segue),
                 "notes": f.get("notes", ""), "started_at": _day_start(date),
                 "concluded_at": _day_start(date),
                 "legacy": {k: f.get(k) for k in ("round_robin_question", "current_step", "is_closed", "summary_sent_at")}},
                label="L10 meetings",
            )
            if created or self.refresh:
                obj.attendees.set([self.users[u] for u in f.get("attendees", []) if u in self.users])
            self.meetings[pk] = obj
        if answers:
            self.stats["Round robin answers (-> segue notes)"] = Counter(mapped=sum(len(v) for v in answers.values()))

    def import_ratings(self):
        for pk, f in self.fields("core.meetingevaluation"):
            meeting = self.meetings.get(f["meeting"])
            user = self.users.get(f["user"])
            if not meeting or not user:
                continue
            points = [RAG_TO_RATING[r] for r in (f.get("scores") or {}).values() if r in RAG_TO_RATING]
            rating = round(sum(points) / len(points)) if points else None
            existing = MeetingRating.objects.filter(meeting=meeting, user=user).first()
            if existing and existing.legacy_id is None:
                existing.legacy_id = pk
                existing.save(update_fields=["legacy_id"])
            self.upsert(MeetingRating, pk, {"meeting": meeting, "user": user, "rating": rating, "legacy": {"scores": f.get("scores")}}, label="Meeting ratings")

    def import_offsites(self):
        """Battle Planner offsites -> EOS planning sessions. They covered SWOT and the V/TO, so they land as Annual Planning."""
        sessions = {}
        for pk, f in self.fields("core.offsite"):
            team = self.teams.get(f.get("facility")) or Team.objects.filter(is_leadership=True).first()
            date = _date(f.get("date")) or timezone.localdate()
            done = f.get("status") in {"complete", "done", "closed"}
            obj, _ = self.upsert(
                Session, pk,
                {"kind": ANNUAL, "team": team, "quarter": self.quarters.get(f.get("quarter")) or Quarter.objects.for_date(date),
                 "date": date, "notes": f.get("agenda_notes") or "", "started_at": _day_start(date),
                 "concluded_at": _day_start(date) if done else None, "current_section": "conclude" if done else "segue",
                 "legacy": {"status": f.get("status"), "current_step": f.get("current_step")}},
                label="Planning sessions (from offsites)",
            )
            sessions[pk] = obj
        if not sessions:
            return
        value_statements = {pk: f for pk, f in self.fields("core.valuestatement")}
        people = defaultdict(set)

        def item(model, pk, f, section, kind, text, color="", author=None, sort=0):
            session = sessions.get(f.get("offsite"))
            text = (text or "").strip()
            if session is None or not text:
                self._count("Planning session items", "skipped")
                return
            author = author if author is not None else self.users.get(f.get("author") or f.get("user"))
            if author:
                people[session.pk].add(author)
            key = f"{model}:{pk}"
            fields = {"session": session, "section": section, "kind": kind, "text": text, "color": color if color in RAG_COLORS else "",
                      "author": author, "sort": sort, "created_at": _dt(f.get("created_at")) or session.started_at,
                      "legacy": {"model": model}}
            obj = SessionItem.objects.filter(legacy_key=key).first()
            if obj is None:
                SessionItem.objects.create(legacy_key=key, **fields)
                self._count("Planning session items", "created")
            elif self.refresh:
                for k, v in fields.items():
                    setattr(obj, k, v)
                obj.save()
                self._count("Planning session items", "updated")
            else:
                self._count("Planning session items", "unchanged")

        for pk, f in self.fields("core.swotitem"):
            item("swotitem", pk, f, "swot", f.get("kind") if f.get("kind") in {"strength", "weakness", "opportunity", "threat"} else "note", f.get("text"))
        for pk, f in self.fields("core.fourwhatsitem"):
            kind = f.get("kind")
            text = f.get("text") if kind == "working" else f"{(kind or '').title()}: {f.get('text', '')}"
            item("fourwhatsitem", pk, f, "segue", "working" if kind == "working" else "not_working", text)
        for pk, f in self.fields("core.offsitereflection"):
            lines = [f"{label}: {f[k].strip()}" for k, label in
                     [("wins", "Wins"), ("team_growth", "Team growth"), ("personal_growth", "Personal growth")] if (f.get(k) or "").strip()]
            if (f.get("chapter_title") or "").strip():
                lines.append(f"Chapter title: {f['chapter_title'].strip()}" + (f" ({f['chapter_why'].strip()})" if (f.get("chapter_why") or "").strip() else ""))
            item("offsitereflection", pk, f, "segue", "best_news", "\n".join(lines))
        for pk, f in self.fields("core.offsitelesson"):
            text = ": ".join(x for x in [(f.get("title") or "").strip(), (f.get("body") or "").strip()] if x)
            item("offsitelesson", pk, f, "review", "lesson", text, sort=f.get("sort", 0))
        for pk, f in self.fields("core.priorityeval"):
            top = [t for t in (f.get("top_three_to_five") or []) if isinstance(t, str) and t.strip()]
            text = "\n".join(x for x in [f"#1: {f['number_one'].strip()}" if (f.get("number_one") or "").strip() else "",
                                         *[f"- {t.strip()}" for t in top], (f.get("notes") or "").strip()] if x)
            item("priorityeval", pk, f, "ids", "priority", text)
        for model, label in (("missioneval", "Mission"), ("visioneval", "Vision")):
            for pk, f in self.fields(f"core.{model}"):
                text = f"{label} · {(f.get('statement_key') or '').replace('_', ' ')}" + (f": {f['note'].strip()}" if (f.get("note") or "").strip() else "")
                item(model, pk, f, "vto", "vto_check", text, color=f.get("rag") or "")
        for pk, f in self.fields("core.valueseval"):
            vs = value_statements.get(f.get("value_statement")) or {}
            value = self.values.get(vs.get("value"))
            text = f"Core value · {value.name if value else 'value'}: {vs.get('text', '').strip()}" + (
                f" ({f['note'].strip()})" if (f.get("note") or "").strip() else "")
            item("valueseval", pk, f, "vto", "vto_check", text, color=f.get("rag") or "")
        for session in sessions.values():
            if people.get(session.pk):
                session.attendees.add(*people[session.pk])

    def archive_rest(self):
        LegacyRecord.objects.filter(model__in=HANDLED).delete()
        for model, rows in sorted(self.by.items()):
            if model in HANDLED or model in SKIP_MODELS:
                continue
            for row in rows:
                LegacyRecord.objects.update_or_create(model=model, legacy_id=row["pk"], defaults={"data": row["fields"]})
            self.stats[f"{model} ({ARCHIVED_NOTE.get(model, 'no EOS equivalent')})"] = Counter(archived=len(rows))

    def skipped_models(self):
        return [m for m in self.by if m not in HANDLED]
