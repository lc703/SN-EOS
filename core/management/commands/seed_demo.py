"""Fill an empty database with fictional demo data for local development and screenshots.

    python manage.py seed_demo            # refuses if rocks already exist
    python manage.py seed_demo --force    # add demo data anyway

Everything here is made up. Never point this at production.
"""

import datetime as dt
import random
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from api.models import ApiToken
from api.services import run as run_tool
from core.models import Quarter, Team, User, monday_of
from issues.models import Issue
from meetings.models import CascadingMessage, Headline, Meeting, MeetingRating
from people.models import OneOnOne, OneOnOneScore, PeopleReview, SuccessStatement, ValueRating
from planning.models import Session, SessionItem, SessionRating
from rocks.models import Milestone, Rock, RockUpdate
from scorecard.models import Measurable, ScoreEntry
from todos.models import Todo
from vision.models import VTO, CoreValue, Goal, Seat

DOMAIN = "steuartnutrition.com"

PEOPLE = [
    # key, name, title, admin, teams
    ("ben", "Ben Steuart", "CEO", True, ["Company"]),
    ("rachel", "Rachel Moore", "President / Integrator", True, ["Company"]),
    ("dan", "Dan Kessler", "VP Operations", False, ["Company", "Kentucky", "Le Roy", "Mabel"]),
    ("maria", "Maria Lopez", "VP Sales & Marketing", False, ["Company"]),
    ("tom", "Tom Hughes", "Controller", False, ["Company"]),
    ("jenna", "Jenna Price", "People Director", False, ["Company"]),
    ("luke", "Luke Barrett", "Plant Manager, Kentucky", False, ["Kentucky"]),
    ("sam", "Sam Ortiz", "Production Lead", False, ["Kentucky"]),
    ("amy", "Amy Chen", "Quality Manager", False, ["Kentucky"]),
    ("greg", "Greg Walsh", "Plant Manager, Le Roy", False, ["Le Roy"]),
    ("nate", "Nate Fisher", "Maintenance Lead", False, ["Le Roy"]),
    ("olivia", "Olivia Grant", "Logistics Manager", False, ["Le Roy"]),
    ("chris", "Chris Dahl", "Plant Manager, Mabel", False, ["Mabel"]),
    ("hannah", "Hannah Berg", "Office Manager", False, ["Mabel"]),
    ("kyle", "Kyle Turner", "Territory Sales, East", False, ["Company"]),
]

VALUES = [
    ("Do the right thing", "Honest with farmers, each other and the numbers."),
    ("Serve the farmer", "Their herd's health is our business."),
    ("Own it", "Say what you'll do, do what you say."),
    ("Better every day", "Small improvements, every week."),
]

SEATS = [
    # key, title, holder key / name, parent key, status, agency, roles
    ("vis", "Visionary", "ben", None, "filled", False, "Big relationships: key dealers and suppliers\nCulture and core values\nNew products and R&D direction\nSolve the big problems\nCreativity and the 10-year target"),
    ("int", "Integrator", "rachel", "vis", "filled", False, "Lead, manage and hold the leadership team accountable\nRun the business plan and P&L\nBreak ties across functions\nExecute the V/TO\nRun the weekly L10"),
    ("ops", "Operations", "dan", "int", "filled", False, "Plant safety and production\nQuality and feed safety\nPurchasing and inventory\nLogistics and delivery\nCapital projects"),
    ("sales", "Sales & Marketing", "maria", "int", "filled", False, "Revenue and margin targets\nDealer network growth\nMarketing and brand\nCustomer service\nPricing"),
    ("fin", "Finance", "tom", "int", "filled", False, "Accounting and AR/AP\nBudget and forecasting\nIT and systems\nRisk and insurance\nBanking"),
    ("hr", "People", "jenna", "int", "filled", False, "Hiring and onboarding\nQuarterly Conversations\nBenefits and payroll\nTraining\nCulture programs"),
    ("ky", "Plant Manager, Kentucky", "luke", "ops", "filled", False, "Daily production plan\nSafety walk and audits\nStaffing and shift schedule\nMill uptime\nCost per ton"),
    ("lr", "Plant Manager, Le Roy", "greg", "ops", "filled", False, "Daily production plan\nSafety walk and audits\nStaffing and shift schedule\nMill uptime\nCost per ton"),
    ("mb", "Plant Manager, Mabel", "chris", "ops", "filled", False, "Daily production plan\nSafety and audits\nStaffing\nUptime\nCost per ton"),
    ("log", "Logistics", "olivia", "ops", "filled", False, "Fleet and drivers\nRoute planning\nOn-time delivery\nCarrier contracts\nDOT compliance"),
    ("qa", "Quality Assurance", "amy", "ops", "filled", False, "SQF program\nLab testing\nSupplier approval\nComplaints and recalls\nLabel review"),
    ("east", "Territory Sales, East", "kyle", "sales", "filled", False, "Dealer visits\nNew accounts\nOrder forecasting\nTrade shows\nCRM hygiene"),
    ("west", "Territory Sales, West", None, "sales", "open", False, "Dealer visits\nNew accounts\nOrder forecasting\nTrade shows\nCRM hygiene"),
    ("mkt", "Marketing Manager", None, "sales", "future", False, "Brand and website\nDealer co-op programs\nLead generation\nTrade show calendar"),
    ("acct", "Staff Accountant", "Priya Nair", "fin", "filled", True, "AP and AR\nMonth-end close\nBank reconciliations\nExpense reports"),
    ("rec", "Recruiter", None, "hr", "future", False, "Sourcing\nInterview scheduling\nOffer letters\nCareer fairs"),
    ("kyprod", "Production Lead, Kentucky", "sam", "ky", "filled", False, "Shift start-up\nBatching accuracy\nOperator training\nHousekeeping"),
    ("kymaint", "Maintenance Lead, Kentucky", None, "ky", "open", False, "Preventive maintenance\nParts inventory\nBreakdown response\nContractors"),
    ("lrmaint", "Maintenance Lead, Le Roy", "nate", "lr", "filled", False, "Preventive maintenance\nParts inventory\nBreakdown response\nContractors"),
    ("lrnight", "Night Shift Lead, Le Roy", "Marcus Webb", "lr", "filled", True, "Night production\nShift handoff\nSafety"),
    ("mboffice", "Office Manager, Mabel", "hannah", "mb", "filled", False, "Order entry\nScale tickets\nPayroll inputs\nFront desk"),
]

COMPANY_MEASURABLES = [
    # title, owner, unit, compare, goal, trailing, base, spread
    ("Revenue", "maria", "currency", "gte", 480000, "total", 495000, 60000),
    ("Tons shipped", "dan", "number", "gte", 1850, "total", 1880, 160),
    ("Gross margin", "tom", "percent", "gte", 22, "avg", 22.4, 1.6),
    ("New dealer accounts", "maria", "number", "gte", 2, "total", 2.2, 1.6),
    ("On-time delivery", "olivia", "percent", "gte", 97, "avg", 96.8, 2.2),
    ("Recordable safety incidents", "dan", "number", "lte", 0, "total", 0.2, 0.6),
    ("AR over 60 days", "tom", "currency", "lte", 40000, "avg", 38000, 9000),
    ("Open positions", "jenna", "number", "lte", 2, "avg", 2.4, 1.2),
]

KY_MEASURABLES = [
    ("Tons produced", "luke", "number", "gte", 720, "total", 735, 60),
    ("Unplanned downtime (hrs)", "sam", "number", "lte", 4, "total", 4.2, 2.4),
    ("Batch accuracy", "amy", "percent", "gte", 99.5, "avg", 99.5, 0.4),
    ("Cost per ton", "luke", "currency", "lte", 31, "avg", 30.6, 1.8),
]

GOALS = [
    ("Grow revenue to $26M at 22% gross margin", "maria", "Win Ohio and Indiana dealers; protect margin with smarter pricing.", "Add 12 dealers\nQuarterly price reviews\nLaunch premium mineral line"),
    ("World-class plant reliability", "dan", "Preventive maintenance at every mill; measure downtime weekly.", "PM software at all mills\nCross-train operators\nCritical spares on hand"),
    ("One system for orders, inventory and accounting", "tom", "Replace spreadsheets with the ERP inventory module.", "Inventory module live at all mills\nDealer portal pilot"),
    ("Build the leadership bench", "jenna", "Every seat has a clear owner, five roles and a Quarterly Conversation.", "QCs every quarter\nHire West sales rep\nPromote two leads"),
]


def d(s):
    return dt.date.fromisoformat(s)


class Command(BaseCommand):
    help = "Create fictional demo data (people, chart, scorecard, rocks, L10s, sessions) for development and screenshots."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even if rocks already exist.")

    def handle(self, force=False, **opts):
        if not settings.DEBUG and not force:
            raise CommandError("seed_demo is for development. Pass --force if you really mean it.")
        if Rock.objects.exists() and not force:
            raise CommandError("This database already has rocks. Pass --force to add demo data anyway.")
        random.seed(42)
        with transaction.atomic():
            self.seed()
        self.stdout.write(self.style.SUCCESS("Demo data ready. Sign in as Ben Steuart (admin) or Luke Barrett (member) with dev login."))

    # ------------------------------------------------------------------ helpers
    def seed(self):
        self.today = timezone.localdate()
        self.monday = monday_of(self.today)
        self.q = Quarter.for_calendar(self.today)
        self.q.is_current = True
        self.q.save()
        self.prev_q = Quarter.for_calendar(self.q.start_date - dt.timedelta(days=1))
        self.teams = {}
        for sort, (name, code, lead) in enumerate([("Company", "CO", True), ("Kentucky", "KY", False), ("Le Roy", "LR", False), ("Mabel", "MB", False)]):
            self.teams[name], _ = Team.objects.get_or_create(name=name, defaults={"short_code": code, "is_leadership": lead, "sort": sort})
        self.u = {}
        for key, name, title, admin, teams in PEOPLE:
            first, last = name.lower().split(" ", 1)
            user, _ = User.objects.get_or_create(
                email=f"{first}.{last.replace(' ', '')}@{DOMAIN}",
                defaults={"username": f"{first}.{last}@{DOMAIN}", "name": name, "title": title, "role": User.ROLE_ADMIN if admin else User.ROLE_MEMBER},
            )
            for t in teams:
                self.teams[t].members.add(user)
            self.u[key] = user
        self.values = [CoreValue.objects.get_or_create(name=n, defaults={"description": desc, "sort": i})[0] for i, (n, desc) in enumerate(VALUES)]
        self.vto()
        self.seats()
        self.scorecard()
        self.rocks()
        self.issues_todos()
        self.meetings()
        self.people()
        self.sessions()
        self.api()

    def vto(self):
        v = VTO.load()
        v.purpose = "Helping farm families raise healthy, profitable animals."
        v.niche = "Custom mineral and feed programs, delivered on time, backed by people who know livestock."
        v.ten_year_target = "$60M revenue, the most trusted feed partner in the Midwest"
        v.target_market = "Beef and dairy producers with 100+ head within 250 miles of our mills, reached through independent dealers."
        v.uniques = "Nutritionist on every account\nOwn fleet, on-time delivery\nFamily-owned since 1921"
        v.proven_process = "Visit → Ration plan → Deliver → Follow up"
        v.guarantee = "On time or the freight is free."
        v.three_year_date = "Dec 31, 2029"
        v.three_year_revenue = "$34M"
        v.three_year_profit = "9% net"
        v.three_year_measurables = "40,000 tons/yr\n90 active dealers\n98% on-time"
        v.three_year_picture = "Four mills on one system\nDealer portal live\nEvery seat filled with an A player"
        v.one_year_date = "Dec 31, 2026"
        v.one_year_revenue = "$26M"
        v.one_year_profit = "7% net"
        v.one_year_measurables = "24,000 tons\n70 active dealers\n97% on-time delivery"
        v.legacy = {"strategy_house": {
            "major_business_challenge": "Grow volume without adding a fourth mill before 2028.",
            "targets": [{"value": "$26M", "label": "Revenue"}, {"value": "22%", "label": "Gross margin"},
                        {"value": "95%", "label": "Mill uptime", "sub": "all three mills"}, {"value": "70", "label": "Active dealers"}],
        }}
        v.save()
        for i, (title, owner, strategy, tactics) in enumerate(GOALS):
            Goal.objects.get_or_create(title=title, defaults={"owner": self.u[owner], "strategy": strategy, "tactics": tactics, "sort": i, "due_date": d(f"{self.today.year}-12-31")})
        self.goals = list(Goal.objects.all())

    def seats(self):
        team = self.teams["Company"]
        made = {}
        for i, (key, title, holder, parent, status, agency, roles) in enumerate(SEATS):
            person = self.u.get(holder) if holder in self.u else None
            made[key] = Seat.objects.create(
                team=team, title=title, person=person, person_name="" if person else (holder or ""),
                parent=made.get(parent), status=status, is_agency=agency, roles=roles, sort=i,
            )
        ky = self.teams["Kentucky"]
        top = Seat.objects.create(team=ky, title="Plant Manager", person=self.u["luke"], roles=SEATS[6][6])
        Seat.objects.create(team=ky, title="Production Lead", person=self.u["sam"], parent=top, roles=SEATS[16][6])
        Seat.objects.create(team=ky, title="Quality Manager", person=self.u["amy"], parent=top, roles=SEATS[10][6])
        Seat.objects.create(team=ky, title="Maintenance Lead", parent=top, status="open", roles=SEATS[17][6])

    def _values(self, m, base, spread, weeks, compare):
        out = []
        for i, w in enumerate(weeks):
            if w >= self.monday:
                break
            drift = (i - len(weeks) / 2) * spread * 0.03
            v = base + drift + random.uniform(-spread, spread) / 2
            if m.unit == "number" and spread >= 1:
                v = max(0, round(v))
            elif m.unit == "number":
                v = 1 if random.random() < 0.12 else 0
            v = Decimal(str(round(v, 1 if m.unit == "percent" else 0 if m.unit == "currency" else 1)))
            out.append((w, v))
        return out

    def scorecard(self):
        for team_name, rows in (("Company", COMPANY_MEASURABLES), ("Kentucky", KY_MEASURABLES)):
            for i, (title, owner, unit, compare, goal, trailing, base, spread) in enumerate(rows):
                m = Measurable.objects.create(team=self.teams[team_name], title=title, owner=self.u[owner], unit=unit, goal_compare=compare, goal=goal, trailing=trailing, sort=i)
                for w, v in self._values(m, base, spread, self.prev_q.weeks() + self.q.weeks(), compare):
                    if title == "Gross margin" and w == self.monday - dt.timedelta(weeks=1):
                        continue  # one late number so My 90 has something to nag about
                    ScoreEntry.objects.create(measurable=m, week_start=w, value=v, updated_by=m.owner)

    def _updates(self, rock, pattern, notes):
        weeks = [w for w in self.q.weeks() if w <= self.monday]
        for i, w in enumerate(weeks):
            if i >= len(pattern):
                break
            if pattern[i] == "-":
                continue
            rag = {"g": "green", "y": "yellow", "r": "red"}[pattern[i]]
            RockUpdate.objects.create(
                rock=rock, week_start=w, rag=rag, note=notes[i % len(notes)], author=rock.owner,
                recovery_plan="Daily stand-up with vendor; escalate to Rachel Friday if no ship date." if rag == "red" else "",
            )

    def rocks(self):
        co, ky = self.teams["Company"], self.teams["Kentucky"]
        g = self.goals
        specs = [
            (co, True, "Launch ERP inventory module at all three mills", "tom", g[2], "ggyyygy", ["Kentucky live; Le Roy data load underway", "Vendor training booked", "Le Roy counts don't reconcile yet", "Mabel scheduled for Dec 1"], ["Kentucky go-live", "Le Roy go-live", "Mabel go-live", "Retire inventory spreadsheet"], 2),
            (co, True, "Hire Territory Sales Rep — West", "maria", g[3], "ggyyrrry", ["Job posted", "12 applicants, 2 strong", "Top candidate declined", "Recruiter engaged; 3 new candidates"], ["Post job", "First interviews", "Ride-alongs", "Offer accepted"], 2),
            (co, True, "Close 3 new dealer accounts in Ohio", "maria", g[0], "gggggggg", ["Two dealers signed", "Third dealer reviewing terms", "On track"], ["Dealer #1", "Dealer #2", "Dealer #3"], 2),
            (co, True, "Cut Le Roy unplanned downtime 25%", "dan", g[1], "yyygggyg", ["PM schedule loaded", "Hammer mill rebuild done", "Down 18% so far"], ["PM schedule in software", "Hammer mill rebuild", "Critical spares list", "4 weeks under target"], 2),
            (co, True, "Roll out Quarterly Conversations to every manager", "jenna", g[3], "gggggggg", ["Training done", "11 of 14 managers complete"], ["Train managers", "Schedule all QCs", "100% complete"], 2),
            (co, True, "Finalize 2027 budget", "tom", None, "gggggg", ["Department drafts in", "Board review Nov 12"], ["Department drafts", "Leadership review", "Board approval"], 3),
            (ky, False, "Install new pellet mill die and retrain operators", "luke", g[1], "ggggyyg", ["Die arrived", "Install weekend booked", "Throughput +6%"], ["Order die", "Install", "Train 3 shifts"], 2),
            (ky, False, "Cross-train 4 operators on batching", "sam", g[3], "gggyygg", ["2 trained", "3 trained"], ["Operator 1", "Operator 2", "Operator 3", "Operator 4"], 3),
            (ky, False, "Pass SQF surveillance audit with zero majors", "amy", None, "gggggggg", ["Mock audit clean", "Docs ready"], ["Mock audit", "Close findings", "Audit day"], 1),
        ]
        self.rocks_made = []
        for i, (team, company, title, owner, goal, pattern, notes, milestones, done_n) in enumerate(specs):
            rock = Rock.objects.create(team=team, quarter=self.q, is_company=company, title=title, owner=self.u[owner], goal=goal, sort=i,
                                       description="Why it matters: keeps us on pace for the 1-year plan.")
            for j, mt in enumerate(milestones):
                due = self.q.start_date + dt.timedelta(days=20 * (j + 1))
                ms = Milestone.objects.create(rock=rock, title=mt, owner=rock.owner, due_date=min(due, self.q.end_date), sort=j)
                if j < done_n:
                    ms.set_done(True)
            self._updates(rock, pattern, notes)
            self.rocks_made.append(rock)
        budget = self.rocks_made[5]
        budget.status = Rock.DONE
        budget.save()
        for title, owner in [("Open Ohio warehouse lease", "dan"), ("Launch dealer price list v2", "maria"), ("SQF certification renewal", "dan")]:
            Rock.objects.create(team=co, quarter=self.prev_q, is_company=True, title=title, owner=self.u[owner], status=Rock.DONE)

    def issues_todos(self):
        co, ky = self.teams["Company"], self.teams["Kentucky"]
        open_issues = [
            ("Le Roy inventory counts don't match the ERP", "tom", 1),
            ("West territory dealers going unvisited", "maria", 2),
            ("Truck #14 keeps failing DOT inspection", "olivia", 3),
            ("Corn price spike — do we adjust December pricing?", "maria", None),
            ("Night shift turnover at Le Roy", "greg", None),
            ("Customer complaints about bag labels smudging", "dan", None),
        ]
        for title, owner, prio in open_issues:
            i = Issue.objects.create(team=co, title=title, owner=self.u[owner], created_by=self.u["rachel"], description="Raised in the L10.")
            if prio:
                i.set_priority(prio)
        for title in ["Fourth mill: build or buy?", "Dealer portal vendor selection", "Succession plan for plant managers"]:
            Issue.objects.create(team=co, title=title, owner=self.u["ben"], horizon=Issue.LONG)
        for title, res in [("Fuel surcharge not on invoices", "Added to invoice template; Tom to verify Friday."), ("Overtime at Kentucky", "Added a Saturday half-shift through December.")]:
            i = Issue.objects.create(team=co, title=title, owner=self.u["tom"])
            i.solve(resolution=res)
        Issue.objects.create(team=ky, title="Pellet durability below spec on line 2", owner=self.u["amy"])
        Issue.objects.create(team=ky, title="Need second forklift for receiving", owner=self.u["sam"])

        todos = [
            ("Send Le Roy count variance report", "tom", -2, False),
            ("Call recruiter about West candidates", "maria", 1, False),
            ("Book DOT re-inspection for truck #14", "olivia", 3, False),
            ("Draft December price letter", "maria", 4, False),
            ("Confirm hammer mill parts order", "dan", -1, True),
            ("Share QC completion list with managers", "jenna", 2, True),
            ("Update 2027 budget deck for board", "tom", -5, True),
            ("Visit Hillcrest Farms with Kyle", "maria", 6, False),
            ("Review night shift exit interviews", "jenna", 5, False),
            ("Approve Kentucky Saturday shift", "dan", -3, True),
        ]
        for title, owner, days, done in todos:
            t = Todo.objects.create(team=co, title=title, owner=self.u[owner], due_date=self.today + dt.timedelta(days=days), created_by=self.u["rachel"])
            if done:
                t.set_done(True)
        Todo.objects.create(team=None, is_private=True, title="Prep notes for Greg's Quarterly Conversation", owner=self.u["dan"], due_date=self.today + dt.timedelta(days=2), created_by=self.u["dan"])
        for title, owner, days in [("Order replacement die bolts", "sam", 2), ("Post maintenance lead job", "luke", 1), ("Calibrate lab moisture meter", "amy", -1)]:
            Todo.objects.create(team=ky, title=title, owner=self.u[owner], due_date=self.today + dt.timedelta(days=days), created_by=self.u["luke"])

    def meetings(self):
        co = self.teams["Company"]
        leaders = [self.u[k] for k in ("ben", "rachel", "dan", "maria", "tom", "jenna")]
        ratings = [8, 9, 8, 9, 9, 8, 9, 10]
        for n in range(7, 0, -1):
            day = self.monday - dt.timedelta(weeks=n - 1)
            if day > self.today:
                continue
            m = Meeting.objects.create(team=co, quarter=Quarter.for_calendar(day), date=day, facilitator=self.u["rachel"],
                                       started_at=timezone.make_aware(dt.datetime.combine(day, dt.time(9))),
                                       concluded_at=timezone.make_aware(dt.datetime.combine(day, dt.time(10, 30))), current_section="conclude",
                                       segue_notes="Ben: great harvest weekend\nMaria: Ohio dealer signed")
            m.attendees.set(leaders)
            for j, u in enumerate(leaders):
                MeetingRating.objects.create(meeting=m, user=u, rating=max(6, min(10, ratings[(j + n) % len(ratings)] - (1 if n == 4 and j < 3 else 0))))
            if n == 1:
                CascadingMessage.objects.create(meeting=m, text="2027 budget approved by the board. Department budgets go out Friday.", to_everyone=True, author=self.u["rachel"], created_at=m.concluded_at)
                c = CascadingMessage.objects.create(meeting=m, text="Le Roy downtime is down 18% this quarter. Thank the maintenance crew!", author=self.u["dan"], created_at=m.concluded_at)
                c.to_teams.add(self.teams["Le Roy"])
                c = CascadingMessage.objects.create(meeting=m, text="New SQF audit date is Dec 9. Kentucky leads the mock audit for all three mills.", author=self.u["dan"], created_at=m.concluded_at)
                c.to_teams.add(self.teams["Kentucky"])
        ky = self.teams["Kentucky"]
        live = Meeting.objects.create(team=ky, quarter=self.q, date=self.today, facilitator=self.u["luke"], current_section="rocks",
                                      segue_notes="Luke: daughter's first deer season\nSam: passed the feed safety exam\nAmy: lab audit prep is done")
        live.attendees.set(ky.members.filter(is_active=True))
        Headline.objects.create(team=ky, meeting=live, kind="customer", text="Miller Dairy asked for a second weekly delivery", author=self.u["sam"])
        Headline.objects.create(team=ky, meeting=live, kind="employee", text="Night shift has been fully staffed for 3 weeks", author=self.u["luke"])
        Headline.objects.create(team=co, kind="customer", text="Hillcrest Farms doubled their mineral order after the ration review", author=self.u["kyle"])
        Headline.objects.create(team=co, kind="employee", text="Sam Ortiz earned his feed safety certification", author=self.u["luke"])
        Headline.objects.create(team=co, kind="customer", text="Two late deliveries in Mabel route last week — fixed", author=self.u["olivia"])

    def people(self):
        plan = [
            ("luke", "dan", ["Mill runs at 95% uptime", "Cost per ton under $31", "Zero recordable injuries"], ["green", "green", "yellow"], ["green"] * 4, (True, True, True), ["+", "+", "+", "+"]),
            ("greg", "dan", ["Mill runs at 95% uptime", "Night shift fully staffed", "Weekly safety walk done"], ["red", "red", "green"], ["green", "yellow", "green", "green"], (True, True, False), ["+", "+", "+/-", "+"]),
            ("chris", "dan", ["Mill runs at 95% uptime", "Orders shipped same day"], ["green", "green"], ["green"] * 4, (True, True, True), ["+", "+", "+", "+"]),
            ("olivia", "dan", ["97% on-time delivery", "Fleet passes DOT"], ["yellow", "red"], ["green", "green", "yellow", "green"], (True, True, None), ["+", "+/-", "+", "+"]),
            ("kyle", "maria", ["2 new dealers per month", "Visit every A dealer monthly"], ["green", "yellow"], ["green"] * 4, (True, True, True), ["+", "+", "+", "+"]),
            ("maria", "rachel", ["Revenue plan hit", "West rep hired"], ["green", "red"], ["green"] * 4, (True, True, True), ["+", "+", "+", "+"]),
            ("dan", "rachel", ["Plants hit uptime", "No recordables"], ["green", "green"], ["green"] * 4, (True, True, True), ["+", "+", "+", "+"]),
            ("tom", "rachel", ["Close books by day 5", "ERP live at all mills"], ["green", "yellow"], ["green"] * 4, (True, True, True), ["+", "+", "+", "+/-"]),
            ("jenna", "rachel", ["Every manager runs QCs", "Open seats under 2"], ["green", "yellow"], ["green"] * 4, (True, True, True), ["+", "+", "+", "+"]),
        ]
        qc_day = self.q.start_date + dt.timedelta(days=24)
        for key, mgr, statements, ss_rags, cv_rags, gwc, pa in plan:
            person, manager = self.u[key], self.u[mgr]
            ss = [SuccessStatement.objects.create(person=person, text=t, sort=i) for i, t in enumerate(statements)]
            done = key not in ("chris", "jenna")
            o = OneOnOne.objects.create(person=person, manager=manager, kind=OneOnOne.QUARTERLY, date=qc_day, created_by=manager,
                                        highlight="Strong quarter; keep building the team." if "red" not in ss_rags else "Needs a plan for the red items before next quarter.",
                                        notes="5-5-5 discussed: core values, roles, rocks.", completed_at=timezone.now() if done else None)
            if done:
                for s, rag in zip(ss, ss_rags):
                    OneOnOneScore.objects.create(one_on_one=o, statement=s, rag=rag, note="Behind plan; see rock." if rag == "red" else "")
                for v, rag in zip(self.values, cv_rags):
                    OneOnOneScore.objects.create(one_on_one=o, value=v, rag=rag)
            if key in ("greg", "luke", "olivia"):
                last = OneOnOne.objects.create(person=person, manager=manager, kind=OneOnOne.QUARTERLY, date=self.prev_q.start_date + dt.timedelta(days=30),
                                               created_by=manager, completed_at=timezone.now(), highlight="Good quarter overall.")
                for s in ss:
                    OneOnOneScore.objects.create(one_on_one=last, statement=s, rag="yellow" if key == "greg" else "green")
                for v in self.values:
                    OneOnOneScore.objects.create(one_on_one=last, value=v, rag="green")
            r = PeopleReview.objects.create(person=person, reviewer=manager, date=qc_day, gets_it=gwc[0], wants_it=gwc[1], capacity=gwc[2])
            for v, rating in zip(self.values, pa):
                ValueRating.objects.create(review=r, value=v, rating=rating)

    def sessions(self):
        co = self.teams["Company"]
        leaders = [self.u[k] for k in ("ben", "rachel", "dan", "maria", "tom", "jenna")]
        qs = Session.objects.create(team=co, quarter=self.q, kind=Session.QUARTERLY, date=self.q.start_date + dt.timedelta(days=1),
                                    facilitator=self.u["rachel"], current_step="conclude",
                                    concluded_at=timezone.make_aware(dt.datetime.combine(self.q.start_date + dt.timedelta(days=1), dt.time(16))))
        qs.attendees.set(leaders)
        items = [
            ("segue", "news", "ben", "Best harvest season in five years for our dairy customers"),
            ("segue", "working", "rachel", "Weekly L10s start and end on time"),
            ("segue", "not_working", "dan", "Le Roy downtime still too high"),
            ("segue", "expectation", "maria", "Leave with a clear plan for the West territory"),
            ("review", "lesson", "tom", "We under-resourced the ERP rollout; add a project lead"),
            ("review", "lesson", "jenna", "QCs work when managers schedule them in week 1"),
            ("rocks", "rock_idea", "maria", "Hire West sales rep"),
            ("rocks", "rock_idea", "dan", "Cut Le Roy downtime 25%"),
            ("next", "next_step", "rachel", "Owners load milestones by Friday"),
            ("conclude", "feedback", "ben", "Best quarterly yet. Crisp IDS."),
        ]
        for i, (step, kind, who, text) in enumerate(items):
            SessionItem.objects.create(session=qs, step=step, kind=kind, text=text, author=self.u[who], sort=i)
        for u, r in zip(leaders, [9, 9, 8, 9, 8, 10]):
            SessionRating.objects.create(session=qs, user=u, rating=r)

        annual = Session.objects.create(team=co, quarter=self.q, kind=Session.ANNUAL, date=self.today + dt.timedelta(days=21), facilitator=self.u["rachel"], current_step="swot")
        annual.attendees.set(leaders)
        for i, (kind, who, text) in enumerate([
            ("swot_strength", "ben", "Loyal dealer network"), ("swot_strength", "dan", "Own trucking fleet"),
            ("swot_weakness", "tom", "Systems still on spreadsheets"), ("swot_weakness", "jenna", "Thin bench behind plant managers"),
            ("swot_opportunity", "maria", "Ohio and Indiana dealers want a second supplier"), ("swot_threat", "tom", "Commodity price swings"),
        ]):
            SessionItem.objects.create(session=annual, step="swot", kind=kind, text=text, author=self.u[who], sort=i)

    def api(self):
        token, _ = ApiToken.issue(self.u["ben"], "Claude desktop")
        ApiToken.issue(self.u["ben"], "Weekly numbers script", can_write=True)
        rev = Measurable.objects.get(title="Revenue")
        run_tool(token, "get_scorecard", {"team": "company"}, "mcp")
        run_tool(token, "list_rocks", {"mine": True}, "mcp")
        run_tool(token, "create_headline", {"team": "company", "text": "Board approved the 2027 budget", "kind": "employee"}, "mcp")
        run_tool(token, "set_measurable_value", {"measurable_id": rev.pk, "week": (self.monday - dt.timedelta(weeks=1)).isoformat(), "value": 512000}, "rest")
