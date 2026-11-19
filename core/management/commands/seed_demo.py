"""Fill an empty database with a fictional company for demos and screenshots.

    DATABASE_URL=sqlite:////tmp/demo.sqlite3 python manage.py migrate
    DATABASE_URL=sqlite:////tmp/demo.sqlite3 python manage.py seed_demo

Everything here is made up. Refuses to run on a database that already has people in it.
"""

import datetime as dt
import random
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Quarter, Team, User, monday_of
from issues.models import Issue
from meetings.models import Headline, Meeting, MeetingRating
from people.models import ConversationScore, OneOnOne, SuccessStatement
from planning.models import ANNUAL, QUARTERLY, Session, SessionItem, SessionRating
from rocks.models import Milestone, Rock, RockUpdate
from scorecard.models import Measurable, ScoreEntry
from todos.models import Todo
from vision.models import VTO, CoreProcess, CoreValue, Seat

PEOPLE = [
    # key, name, title, role, home
    ("ava", "Ava Mercer", "Visionary", "admin", "lead"),
    ("noah", "Noah Bennett", "Integrator", "admin", "lead"),
    ("mia", "Mia Okafor", "Head of Sales", "member", "lead"),
    ("leo", "Leo Hartmann", "Head of Operations", "member", "lead"),
    ("zoe", "Zoe Lindqvist", "Finance Lead", "member", "lead"),
    ("eli", "Eli Navarro", "Plant Manager", "member", "ops"),
    ("ivy", "Ivy Castellano", "Quality Lead", "member", "ops"),
    ("sam", "Sam Whitfield", "Shift Supervisor", "member", "ops"),
    ("ruby", "Ruby Tanaka", "Account Manager", "member", "sales"),
    ("owen", "Owen Pryce", "Inside Sales", "member", "sales"),
]


class Command(BaseCommand):
    help = "Seed a fictional demo company (for screenshots and local demos). Only runs on an empty database."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, seed, **opts):
        if User.objects.exists():
            raise CommandError("This database already has people in it. seed_demo only runs on an empty database.")
        random.seed(seed)
        with transaction.atomic():
            self.build()
        self.stdout.write(self.style.SUCCESS("Demo data ready. Sign in with the dev login as Ava Mercer (admin) or Noah Bennett."))

    def build(self):
        today = timezone.localdate()
        this_monday = monday_of(today)
        q = Quarter.for_calendar(today)
        Quarter.objects.update(is_current=False)
        q.is_current = True
        q.save()
        prev_q = Quarter.for_calendar(q.start_date - dt.timedelta(days=1))
        next_q = Quarter.for_calendar(q.end_date + dt.timedelta(days=1))
        weeks = [w for w in q.weeks() if w <= this_monday]

        lead = Team.objects.create(name="Company", short_code="CO", is_leadership=True, sort=0)
        ops = Team.objects.create(name="Operations", short_code="OPS", sort=1)
        sales = Team.objects.create(name="Sales", short_code="SLS", sort=2)
        teams = {"lead": lead, "ops": ops, "sales": sales}

        u = {}
        for key, name, title, role, home in PEOPLE:
            first, last = name.split()
            u[key] = User.objects.create_user(
                username=key, email=f"{key}@example.com", name=name, first_name=first, last_name=last,
                title=title, role=role, home_team=teams[home], password=None,
            )
        lead.members.set([u[k] for k in ("ava", "noah", "mia", "leo", "zoe")])
        ops.members.set([u[k] for k in ("leo", "eli", "ivy", "sam")])
        sales.members.set([u[k] for k in ("mia", "ruby", "owen")])

        # ---------------- V/TO ----------------
        values = [CoreValue.objects.create(name=n, description=d, sort=i) for i, (n, d) in enumerate([
            ("Do the right thing", "Even when no one is watching."),
            ("Own it", "Say what you'll do, do what you say."),
            ("Better every day", "Small improvements, every week."),
            ("Serve the customer", "Their success is our success."),
        ])]
        vto = VTO.load()
        vto.purpose = "Help farmers raise healthier animals"
        vto.niche = "Custom feed supplements for mid-size farms"
        vto.ten_year_target = "Feed one million animals a day"
        vto.target_market = "Mid-size dairy and beef operations within 400 miles"
        vto.uniques = "Formulated per farm\nNext-day delivery\nNutritionist on call"
        vto.proven_process = "Visit · Test · Formulate · Deliver · Review"
        vto.guarantee = "On spec or it's free"
        vto.three_year_date = f"Dec 31, {today.year + 3}"
        vto.three_year_revenue, vto.three_year_profit = "$40M", "12%"
        vto.three_year_measurables = "1,200 active farms\n98% on-time delivery"
        vto.three_year_picture = "Second plant running\nNutrition team of 8\nCustomer portal live"
        vto.one_year_date = f"Dec 31, {today.year}"
        vto.one_year_revenue, vto.one_year_profit = "$22M", "9%"
        vto.one_year_measurables = "700 active farms\n96% on-time delivery"
        vto.one_year_goals = "Hire a second nutritionist\nLaunch the reorder portal\nCut changeover time 30%\nISO audit passed"
        vto.save()
        for i, (name, owner, steps, doc, fba) in enumerate([
            ("Sales: lead to first order", "mia", "Qualify\nFarm visit\nSample formula\nProposal\nFirst order", True, True),
            ("Order to delivery", "leo", "Order entry\nSchedule batch\nMix and QA\nLoad\nDeliver and confirm", True, False),
            ("Hiring and onboarding", "noah", "Seat defined\nPost\nInterview with values\nOffer\n30/60/90", True, True),
            ("Accounting", "zoe", "Invoice\nCollect\nClose month", False, False),
        ]):
            CoreProcess.objects.create(name=name, owner=u[owner], steps=steps, documented=doc, followed_by_all=fba, sort=i)

        # ---------------- Accountability Chart ----------------
        def seat(title, person=None, parent=None, team=lead, status=Seat.FILLED, roles="", agency=False, name=""):
            return Seat.objects.create(title=title, person=person, person_name=name, parent=parent, team=team, status=status,
                                       roles=roles, agency=agency, sort=Seat.objects.count())

        v = seat("Visionary", u["ava"], roles="Ideas and innovation\nBig relationships\nCulture\nCreative problem solving\nR&D")
        integ = seat("Integrator", u["noah"], v, roles="Lead, manage, hold accountable\nRun the L10\nP&L results\nExecute the business plan\nResolve cross-functional issues")
        s_sales = seat("Sales & Marketing", u["mia"], integ, roles="Revenue goal\nSales process\nMarketing plan\nCustomer retention\nPricing")
        s_ops = seat("Operations", u["leo"], integ, roles="Make the product\nDeliver on time\nQuality\nInventory\nSafety")
        s_fin = seat("Finance", u["zoe"], integ, roles="AR / AP\nBudgeting\nReporting\nPayroll\nIT")
        seat("Account Manager", u["ruby"], s_sales, sales, roles="Grow accounts\nReorders\nFarm visits")
        seat("Inside Sales", u["owen"], s_sales, sales, roles="Inbound leads\nQuotes\nCRM hygiene")
        seat("Marketing", None, s_sales, sales, Seat.OPEN, roles="Campaigns\nWebsite\nTrade shows", agency=True)
        plant = seat("Plant Manager", u["eli"], s_ops, ops, roles="Production schedule\nCrew\nMaintenance")
        seat("Quality", u["ivy"], s_ops, ops, roles="QA checks\nISO\nComplaints")
        seat("Logistics", None, s_ops, ops, Seat.FUTURE, roles="Routing\nFleet\n3PL partners")
        seat("Shift Supervisor", u["sam"], plant, ops, roles="Run the shift\nSafety huddle\nHandoffs")
        seat("Shift Supervisor (nights)", None, plant, ops, Seat.OPEN, roles="Run the night shift")
        seat("Controller", None, s_fin, lead, Seat.FUTURE, roles="Month-end close\nAudit")

        for key, lines in {
            "eli": ["Hit the weekly production plan", "Crew fully staffed and trained", "Zero lost-time incidents", "Maintenance on schedule", "Changeovers under 40 min"],
            "ruby": ["Grow top 20 accounts 10%", "Every account visited quarterly", "Reorders on time", "Pipeline in CRM", "Customer NPS 60+"],
            "sam": ["Shift hits plan", "Safety huddle every shift", "Clean handoffs", "Overtime under 5%", "Train one new operator a month"],
        }.items():
            for i, text in enumerate(lines):
                SuccessStatement.objects.create(person=u[key], text=text, sort=i)

        # ---------------- Scorecard ----------------
        sc = [
            (lead, "Weekly revenue", "zoe", Measurable.UNIT_CURRENCY, Measurable.GTE, 420000, "total", (380000, 470000)),
            (lead, "New farms signed", "mia", Measurable.UNIT_NUMBER, Measurable.GTE, 6, "total", (3, 9)),
            (lead, "On-time delivery", "leo", Measurable.UNIT_PERCENT, Measurable.GTE, 96, "avg", (91, 99)),
            (lead, "Cash on hand ($k)", "zoe", Measurable.UNIT_NUMBER, Measurable.GTE, 1500, "", (1300, 1800)),
            (lead, "Customer complaints", "ivy", Measurable.UNIT_NUMBER, Measurable.LTE, 2, "total", (0, 5)),
            (lead, "Open seats filled", "noah", Measurable.UNIT_YESNO, Measurable.EQ, 1, "", (0, 1)),
            (lead, "Employee pulse score", "noah", Measurable.UNIT_NUMBER, Measurable.GTE, 8, "avg", (6.8, 9.2)),
            (ops, "Tons produced", "eli", Measurable.UNIT_NUMBER, Measurable.GTE, 900, "total", (820, 980)),
            (ops, "Changeover minutes (avg)", "sam", Measurable.UNIT_NUMBER, Measurable.LTE, 40, "avg", (32, 55)),
            (ops, "QA pass rate", "ivy", Measurable.UNIT_PERCENT, Measurable.GTE, 99, "avg", (97, 100)),
            (ops, "Safety incidents", "sam", Measurable.UNIT_NUMBER, Measurable.LTE, 0, "total", (0, 1)),
            (sales, "Farm visits", "ruby", Measurable.UNIT_NUMBER, Measurable.GTE, 12, "total", (8, 16)),
            (sales, "Quotes sent", "owen", Measurable.UNIT_NUMBER, Measurable.GTE, 20, "total", (14, 28)),
            (sales, "Quote win rate", "owen", Measurable.UNIT_PERCENT, Measurable.GTE, 35, "avg", (24, 46)),
        ]
        for i, (team, title, owner, unit, cmp, goal, trail, (lo, hi)) in enumerate(sc):
            m = Measurable.objects.create(team=team, title=title, owner=u[owner], unit=unit, goal_compare=cmp, goal=Decimal(goal), trailing=trail, sort=i)
            base = random.uniform(lo, hi)
            for wi, w in enumerate(weeks):
                if w == this_monday and random.random() < 0.5:
                    continue
                if unit == Measurable.UNIT_YESNO:
                    val = Decimal(1 if random.random() < 0.7 else 0)
                else:
                    drift = (hi - lo) * 0.06 * wi * (1 if cmp != Measurable.LTE else -1)
                    raw = min(hi, max(lo, base + random.uniform(-(hi - lo) / 3, (hi - lo) / 3) + drift * 0.5))
                    val = Decimal(str(round(raw, 0 if hi > 50 else 1)))
                ScoreEntry.objects.create(measurable=m, week_start=w, value=val, updated_by=u[owner])

        # ---------------- Rocks ----------------
        rock_specs = [
            (lead, True, "Launch the reorder portal to 50 pilot farms", "mia", ["green", "green", "yellow", "green", "green", "green", "green", "green"], 4),
            (lead, True, "Hire and onboard a second nutritionist", "noah", ["green", "yellow", "yellow", "red", "yellow", "green", "green", "green"], 3),
            (lead, True, "Cut average changeover time to 40 minutes", "leo", ["yellow", "yellow", "red", "red", "red", "yellow", "red", "red"], 3),
            (lead, True, "Close the books in 5 business days", "zoe", ["green"] * 8, 2),
            (lead, True, "Roll out the new safety huddle format company-wide", "noah", ["green", "green", "green", "yellow", "green", "green", "green", "green"], 3),
            (lead, True, "Pass the ISO 22000 pre-audit", "ivy", ["green", "green", "green", "yellow", "green", "green", "green", "green"], 4),
            (ops, False, "Cross-train 6 operators on the new mixer", "eli", ["green", "green", "green", "green", "yellow", "green", "green", "green"], 3),
            (ops, False, "Preventive maintenance plan for all lines", "sam", ["yellow", "green", "green", "green", "green", "green", "green", "green"], 2),
            (sales, False, "Sign 10 farms in the new northern territory", "ruby", ["green", "yellow", "yellow", "yellow", "red", "yellow", "yellow", "green"], 3),
            (sales, False, "Every quote out within 24 hours", "owen", ["green"] * 8, 0),
        ]
        rocks = []
        for i, (team, company, title, owner, colors, n_ms) in enumerate(rock_specs):
            r = Rock.objects.create(quarter=q, team=team, is_company=company, title=title, owner=u[owner], sort=i)
            for wi, w in enumerate(weeks):
                if w == this_monday and i % 3 == 0:
                    continue
                c = colors[min(wi, len(colors) - 1)]
                RockUpdate.objects.create(
                    rock=r, week_start=w, color=c, author=u[owner],
                    note={"green": "On plan this week.", "yellow": "Slipped a few days; catching up.", "red": "Blocked."}[c],
                    recovery_plan="Bring in the vendor tech Tuesday; Leo reviews the SMED plan Friday." if c == "red" else "",
                )
            for m in range(n_ms):
                Milestone.objects.create(rock=r, title=["Scope agreed", "Pilot group picked", "Build done", "Train the team", "Go live"][m],
                                         due_date=q.start_date + dt.timedelta(days=18 * (m + 1)), done=m < n_ms // 2 + (1 if i % 2 else 0), sort=m)
            last = r.updates.order_by("-week_start").first()
            if last:
                r.apply_update(last)
            rocks.append(r)
        rocks[3].status = Rock.DONE
        rocks[3].save()
        done_update = rocks[3].updates.order_by("-week_start").first()
        if done_update:
            done_update.note = "Closed October in 4 days. Done."
            done_update.save()
        for i, (title, owner, done) in enumerate([
            ("Move to the new ERP", "zoe", True), ("Ship the spring catalog", "mia", True), ("Second mixer installed", "leo", False),
        ]):
            Rock.objects.create(quarter=prev_q, team=lead, is_company=True, title=title, owner=u[owner], status=Rock.DONE if done else Rock.OFF_TRACK, sort=i)

        # ---------------- Issues, to-dos, headlines ----------------
        for team, title, owner, horizon, prio in [
            (lead, "Changeover time keeps creeping up", "leo", Issue.SHORT, 1),
            (lead, "Northern territory pricing is unclear", "mia", Issue.SHORT, 2),
            (lead, "Night shift supervisor seat is still open", "noah", Issue.SHORT, 3),
            (lead, "Freight costs up 8% since August", "zoe", Issue.SHORT, None),
            (lead, "Do we build or lease the second plant?", "ava", Issue.LONG, None),
            (lead, "Customer portal: in-house or vendor?", "mia", Issue.LONG, None),
            (lead, "Succession plan for the plant manager seat", "noah", Issue.LONG, None),
            (ops, "Mixer 2 vibration alarm", "eli", Issue.SHORT, 1),
            (ops, "Pallet wrap supplier late twice", "sam", Issue.SHORT, None),
            (sales, "CRM duplicates", "owen", Issue.SHORT, None),
        ]:
            Issue.objects.create(team=team, title=title, owner=u[owner], horizon=horizon, priority=prio, created_by=u[owner])
        Issue.objects.create(team=lead, title="Weekly revenue report is late", owner=u["zoe"], status=Issue.SOLVED,
                             resolution="Report runs automatically Monday 7am.", solved_at=timezone.now() - dt.timedelta(days=6), created_by=u["zoe"])

        todo_specs = [
            (lead, "Send portal pilot invite to 50 farms", "mia", 2, False), (lead, "Book vendor tech for changeover study", "leo", 1, False),
            (lead, "Post the night shift supervisor job", "noah", -1, True), (lead, "Draft Q1 budget", "zoe", 5, False),
            (lead, "Call the ISO auditor about dates", "ivy", 0, True), (lead, "Northern pricing proposal", "mia", 4, False),
            (ops, "Order spare bearings for mixer 2", "eli", 1, False), (ops, "Train two operators on SMED", "sam", 6, False),
            (sales, "Visit Hillcrest Dairy", "ruby", 3, False), (sales, "Clean CRM duplicates", "owen", -2, True),
        ]
        for team, title, owner, due, done in todo_specs:
            Todo.objects.create(team=team, title=title, owner=u[owner], due_date=today + dt.timedelta(days=due), done=done,
                                done_at=timezone.now() if done else None, created_by=u[owner])
        past = ["Follow up with the feed mill", "Update the pricing sheet", "Review the QA log", "Call back Hillcrest Dairy",
                "Approve the overtime report", "Send the board update", "Check fleet maintenance", "Confirm the trade show booth"]
        for w_back in range(1, 7):
            monday = this_monday - dt.timedelta(weeks=w_back)
            for k in ("ava", "noah", "mia", "leo", "zoe", "eli", "ruby"):
                for j in range(4):
                    done = w_back > 3 or random.random() < 0.85
                    Todo.objects.create(team=u[k].home_team, title=random.choice(past), owner=u[k], due_date=monday + dt.timedelta(days=1 + j),
                                        done=done, done_at=timezone.now() - dt.timedelta(weeks=w_back) if done else None,
                                        created_by=u[k], created_at=timezone.now() - dt.timedelta(weeks=w_back + 1))

        # ---------------- L10 in progress ----------------
        meeting = Meeting.objects.create(team=lead, quarter=q, date=today, facilitator=u["noah"], current_section="rocks",
                                         segue_notes="Ava: daughter's first marathon. Mia: biggest week of quotes ever.")
        meeting.attendees.set(lead.members.all())
        for kind, text, k in [
            (Headline.CUSTOMER, "Hillcrest Dairy doubled their monthly order", "ruby"),
            (Headline.EMPLOYEE, "Ivy finished her ISO lead auditor course", "leo"),
            (Headline.CUSTOMER, "Two complaints about bag labels this week", "ivy"),
        ]:
            Headline.objects.create(team=lead, meeting=meeting, kind=kind, text=text, author=u[k])
        last_l10 = Meeting.objects.create(team=lead, quarter=q, date=today - dt.timedelta(days=7), facilitator=u["noah"],
                                          current_section="conclude", concluded_at=timezone.now() - dt.timedelta(days=7),
                                          cascading_messages="- Portal pilot starts next month (Mia tells sales)\n- New safety huddle format from Monday (Leo tells the plant)")
        last_l10.attendees.set(lead.members.all())
        for k, r in zip(("ava", "noah", "mia", "leo", "zoe"), (9, 8, 9, 8, 10)):
            MeetingRating.objects.create(meeting=last_l10, user=u[k], rating=r)

        # ---------------- Quarterly Conversations ----------------
        def convo(person, manager, colors, gwc, complete, highlight):
            c = OneOnOne.objects.create(person=person, manager=manager, kind=OneOnOne.QUARTERLY, quarter=q, date=today - dt.timedelta(days=3),
                                        highlight=highlight, gets_it=gwc[0], wants_it=gwc[1], capacity=gwc[2],
                                        completed_at=timezone.now() if complete else None, created_by=manager)
            subjects = [("value", v) for v in values] + [("statement", s) for s in person.success_statements.all()] + \
                       [("rock", r) for r in Rock.objects.filter(owner=person, quarter=q)]
            for (field, obj), color in zip(subjects, colors):
                ConversationScore.objects.create(conversation=c, color=color, **{field: obj})
            return c

        convo(u["eli"], u["leo"], ["green"] * 4 + ["green", "yellow", "green", "green", "green"] + ["green"], (True, True, True), True,
              "Strong quarter. Wants to own the second plant project.")
        convo(u["sam"], u["eli"], ["green", "green", "yellow", "green", "green", "red", "green", "yellow", "green", "green"], (True, True, False), False,
              "Changeovers are a capacity problem, not effort. Needs SMED training.")
        convo(u["ruby"], u["mia"], ["green", "green", "green", "green", "yellow", "green", "green", "green", "green", "yellow"], (True, True, True), True,
              "Northern territory is slow but the pipeline is real.")
        OneOnOne.objects.create(person=u["ivy"], manager=u["leo"], kind=OneOnOne.ONE_ON_ONE, date=today - dt.timedelta(days=10),
                                notes="Talked through the ISO timeline.", created_by=u["leo"])

        # ---------------- Planning sessions ----------------
        qs = Session.objects.create(kind=QUARTERLY, team=lead, quarter=q, next_quarter=next_q, date=today, facilitator=u["noah"], current_section="rocks",
                                    section_notes={"review": "Four of five company rocks will land; changeover is the miss."})
        qs.attendees.set(lead.members.all())
        for section, kind, text, k in [
            ("segue", "best_news", "Signed our 600th farm", "mia"), ("segue", "best_news", "Zero lost-time incidents all quarter", "leo"),
            ("segue", "working", "Weekly scorecard reviews", "noah"), ("segue", "working", "The portal pilot feedback loop", "mia"),
            ("segue", "not_working", "Changeovers still too long", "leo"), ("segue", "expectation", "Leave with 5 company rocks", "ava"),
            ("review", "lesson", "Hire before we need the seat, not after", "noah"),
            ("vto", "vto_check", "3-year revenue still right? Feels light.", "zoe"),
            ("ids", "priority", "Night shift coverage", "noah"), ("next_steps", "cascade", "Share the new rocks at Friday's all-hands", "noah"),
        ]:
            SessionItem.objects.create(session=qs, section=section, kind=kind, text=text, author=u[k])
        for i, (title, k) in enumerate([("Portal live for all farms", "mia"), ("Night shift fully staffed", "noah"), ("ISO 22000 certified", "ivy")]):
            Rock.objects.create(quarter=next_q, team=lead, is_company=True, title=title, owner=u[k], sort=i)
        an = Session.objects.create(kind=ANNUAL, team=lead, quarter=prev_q, next_quarter=q, date=prev_q.end_date - dt.timedelta(days=10),
                                    facilitator=u["ava"], current_section="conclude", concluded_at=timezone.now() - dt.timedelta(days=60))
        an.attendees.set(lead.members.all())
        for section, kind, text in [
            ("swot", "strength", "Formulation know-how"), ("swot", "weakness", "Single plant"), ("swot", "opportunity", "Northern territory"),
            ("swot", "threat", "Freight costs"), ("team_health", "does_well", "Calm under pressure"),
        ]:
            SessionItem.objects.create(session=an, section=section, kind=kind, text=text, author=u["ava"], about=u["leo"] if section == "team_health" else None)
        for k, r in zip(("ava", "noah", "mia", "leo", "zoe"), (9, 9, 8, 9, 8)):
            SessionRating.objects.create(session=an, user=u[k], rating=r)
