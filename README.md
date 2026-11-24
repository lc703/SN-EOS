# SN EOS

Internal EOS (Entrepreneurial Operating System) app for Steuart Nutrition. It replaces the SN Strategy Battle Planner with a tool that follows EOS (Traction / EOS Worldwide) closely: Scorecard Measurables, Rocks, Issues (IDS), To-Dos, the weekly Level 10 Meeting, the V/TO (with Core Processes and the old Strategy House folded in), the Accountability Chart, People (1:1s, Quarterly Conversations, People Analyzer) and Quarterly / Annual Planning sessions. AI assistants and scripts can read and write it through a REST API and an MCP server.

It is deliberately less rigid than Ninety.io: there are no meeting timers and no forced step order. The facilitator can jump to any section at any time.

Stack: Python 3.12, Django 5.2, Postgres (SQLite in dev), Django templates, HTMX, Alpine, Tailwind, django-allauth with Google sign-in. Deploys to Railway the same way the Battle Planner did.

## What's in it

Everything is scoped by **team** (Company/Leadership, Kentucky, Le Roy, Mabel) and **quarter**, picked in the bar under the header. People can belong to several teams.

**Company is a roll-up, not a business unit.** Picking Company shows everything across Company, Kentucky, Le Roy and Mabel: rocks, to-dos, issues, headlines, L10s and their meeting runner, planning sessions, people, the Scorecard and the dashboard counts. Each item carries a small team chip (Kentucky, Le Roy, ...) so you can tell where it comes from, and rocks are grouped by team. Picking a site shows only that site (plus the Company measurables on its Scorecard). Something created from the Company view is still filed under the Company team. Private to-dos are never part of the roll-up: only their owner (and whoever created them) sees them, as before. The one rule lives in `core/scoping.py` (`for_team`).

| Page | What it does |
| --- | --- |
| **My 90** (`/`) | Your rocks (donut + 13-week strips), to-do completion bars for the last 6 weeks against the EOS 90% target, your measurables with trend sparklines, your issues, and a pulse for the team in scope (company scorecard on goal last week, rocks on track, team to-dos done, open issues). |
| **Scorecard** | One company Scorecard. The Company view shows all of it; a site's view (Kentucky, Le Roy, Mabel) opens with a labeled **Company** section (the Company measurables, read-only or editable by the usual owner/admin rules), then the site's own measurables below under the site's name. Every Measurable has a **plant**: Company (high-level numbers like sales or marketing, the default for new ones) or Kentucky, Le Roy or Mabel. Company rows come first, then plant rows grouped by measurable name with a sub-row per plant (OEE → Kentucky / Le Roy / Mabel), each with its own owner, goal, values and green/red, like Battle Planner. Change a plant from the side panel's Plant field. Columns are the 13 weeks of the quarter. Type a value in any cell (Enter / arrow keys move like a spreadsheet); it saves on change and turns green (on goal) or red. Goal has an operator (`≥`, `≤`, `=`); units are number, %, currency or yes/no. Each row shows owner, goal, a trend sparkline with "x/y on goal", and an average or total column (yes/no shows "5/7"). Click a title for the 13-week trend chart with the goal line. Drag the handle to reorder. |
| **Rocks** | Company and departmental rocks with owner, due date, milestones and a **weekly G/Y/R update** (On track / At risk / Off track, with a note). Red requires a **recovery plan**; choosing "Off Track" opens the update panel. Each rock shows a 13-week status strip. Drag to reorder. Company rocks show on every team's page. |
| **Issues** | Short-term and long-term lists per team. Click 1, 2 or 3 to rank the top three. **IDS** opens the solve panel: record the decision, add to-dos, then mark solved. |
| **To-Dos** | Team and private to-dos. Due date defaults to 7 days out. Weekly completion % per person and per team. |
| **L10** | Segue, Scorecard, Rock Review (with strips and the update panel), Headlines, To-Do List, IDS, Conclude. Red measurables, off-track rocks and headlines have **Drop to Issues**. Conclude autosaves **cascading messages** and notes, collects a 1-10 rating per attendee, and produces a printable recap that can be emailed (new to-dos, issues solved, headlines, cascading messages, ratings). Attendees on other devices see a banner when the facilitator moves on. No timer. |
| **Planning** | Quarterly and Annual Planning session runner with the EOS agendas. Quarterly: Segue, Review previous quarter (rocks done %, scorecard on goal %, issues solved), Review the V/TO, Establish next quarter's Rocks, Tackle key issues, Next steps (to-dos + cascading messages), Conclude (1-10). Annual adds Team health building (does well / should work on, per person), SWOT, V/TO through the 3-year picture and the 1-year plan (edits the V/TO live). Anything captured can go to the Issues List in one click. Concluding opens a printable recap. Battle Planner offsites are imported as Annual Planning sessions. |
| **V/TO** | Core values, core focus, 10-year target, marketing strategy, 3-year picture, 1-year plan, this quarter's company rocks, the long-term Issues List (Strategy House items are tagged) and **Core Processes** (steps, owner, documented, followed by all). Admins edit it. |
| **Chart** | Accountability Chart. Seats are colored by status (**filled**, **future**, **open / hiring**) with a legend and counts; agency seats are tagged. Zoom (buttons, `+`/`-`/`0`, Ctrl/⌘ + scroll), pan (drag the background), fit (`f`), collapse/expand branches, titles-only (`t`), and a print/PDF layout. Admins drag a seat onto another to re-parent it (cycles are refused) and edit any seat in the side panel, which autosaves. GWC, People Analyzer and "struggling" flags show on seats, only to admins, the person's manager and the person. "Whole company" (default for the leadership team) or a single team; also a filterable list view. |
| **People** | Directory. Each person's page shows seats, success statements, 1:1s and Quarterly Conversations with their G/Y/R counts, and People Analyzer reviews. Private to the person, their manager (parent seat on the chart) and admins. |
| **Quarterly Conversations** (`/conversations/`) | The EOS 5-5-5. A tracker per team (or everyone) with completion %, in progress, struggling, last 1:1. The editor is a G/Y/R grid for each core value, each success statement (the seat's roles) and each rock, with a note per row, GWC, highlight and notes, all autosaved, then **Mark complete**. Any red or a GWC "no" flags the seat on the chart. |
| **API & AI connections** (account menu) | Personal API tokens, MCP setup snippets, the tool list, and your recent API activity. Admins also get the **Audit log**. |

Cross-links: scorecard row / rock / headline → issue → to-dos. Issues and to-dos created in a meeting are tied to it for the recap.

### Roles

- **Admins** (role `admin`; imported for Ben Steuart, Rachel and Lucas Cole) can edit everything, including the V/TO and Accountability Chart, and can use `/admin/` and `/export.json`.
- **Members** edit what they own (rocks, measurables, milestones) and their teams' issues and to-dos. Items with no owner can be edited by the team.

Change someone's role in `/admin/` (Users → Role).

## Local setup

Needs Python 3.12. Postgres is optional in dev; with no `DATABASE_URL` it uses a local SQLite file.

```
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
python manage.py migrate
python manage.py import_battle_planner path/to/battle-planner-export.json
python manage.py runserver
```

Open http://localhost:8000. With `DEV_LOGIN=1` (the default in dev) the login page has a **Dev quick login** link where you pick a user, so you can demo without Google OAuth. It is always off in production settings.

No export handy? `python manage.py ensure_defaults` creates the four teams, the current quarter and an empty V/TO; then create a superuser with `python manage.py createsuperuser`.

Health check: http://localhost:8000/healthz

Postgres locally: `docker compose up -d db` and set `DATABASE_URL=postgres://sneos:sneos@localhost:5432/sneos`.

## Importing from the Battle Planner

```
python manage.py import_battle_planner battle-planner-export.json [--refresh]
```

The file is the Battle Planner's `/export.json` (a Django `dumpdata`). **It contains real 1:1 notes, so keep it out of git**; `.gitignore` already ignores `*export*.json` and `data/`.

The command is idempotent: every imported row stores its old id in `legacy_id`, so running it again creates nothing new. By default it leaves rows already in SN EOS alone, so edits made in the app survive a re-run. `--refresh` overwrites imported rows with the values from the file.

`--sync` implies `--refresh` and then deletes imported rows (ones with a `legacy_id`) that are no longer in the file, so a database can be made to mirror the export exactly. Rows created in SN EOS, which have no `legacy_id`, are kept, unless they hang off a parent the sync deleted. Users who are missing from the export are deactivated rather than deleted, and passwords and Google logins are never touched. The command prints what it removed.

Asana links come across too: a Battle Planner action item that was sent to Asana keeps its task link (and sent / completed times) on the matching to-do, and each person's `asana_email` is kept. A re-import only fills a missing link, it never overwrites or clears one that was made by sending the to-do from SN EOS.

### Weekly values the old app filled by itself

Battle Planner filled five Company rows without storing entries: Prelim quotes sent and R&D formulas sent (iQuote), and Prelim Proposal, R&D Stage and Final Proposal Deal Value (Attio deal totals by stage). SN EOS does not rebuild those connectors. An assistant with the iQuote and Attio MCP servers posts the numbers each week through `set_measurable_value`, and the import marks those rows with a quiet source note, "Filled weekly by assistant from Attio" (or iQuote). Anyone who can edit a measurable can change the note.

To load a backfill, give the importer a CSV with the columns `metric`, `facility`, `week_start`, `value` (`facility` is the plant: Kentucky, Le Roy or Mabel; blank or `Company` for Company rows):

```
python manage.py import_battle_planner --values-csv weekly-values.csv
python manage.py import_battle_planner battle-planner-export.json --values-csv weekly-values.csv
```

Each row is an upsert on (measurable, week): new weeks are created, a changed value replaces the old one, an identical one is left alone, so re-running is safe. A date in the middle of a week lands on that week's Monday, and a blank value never clears a week. Rows it can't match or read are skipped and listed.

### Plants

Plants (Kentucky, Le Roy, Mabel) are their own small list, separate from Teams, so rocks, to-dos, issues and L10s are untouched. A measurable with no plant is a Company measurable. The migration puts measurables that sit on the Kentucky, Le Roy or Mabel teams on the matching plant and everything else on Company, and numbers the sort order once. Moving a measurable to a plant also moves it to the team of the same name when there is one (so who can edit an unowned row, and where Drop to Issues sends it, stay sensible); moving it back to Company keeps its team unless that was a plant team. The L10 Scorecard segment matches the Scorecard page: Company L10 shows everything, and a plant team's L10 (a team named like a plant) shows the Company measurables then that plant's rows. Add more plants in the Django admin. Dragging reorders Company rows; plant groups sit in the order of their first row.

### Dollar measurables

A measurable with the Currency unit shows `$11,000,000` or `$48,213` everywhere: scorecard grid and cells, goals, the side panel, trend chart axis and tooltips, the dashboard, the L10 scorecard segment, and the API's `display` fields. Whole dollars, thousands separators, halves rounded up. Stored values and the API's raw `value` fields are never rounded. The importer reads `$`, `USD`, `$M`, `$k` and "dollars" as Currency.

| Battle Planner | SN EOS |
| --- | --- |
| facility (+ its team members) | Team (Company becomes the leadership team). Non-Company facilities are also the **plants** that scorecard metrics are assigned to. |
| user | User, matched by email; no passwords. Role `admin` stays admin. |
| quarter | Quarter |
| rock + milestone + rockstatus | Rock + milestones. Each weekly status becomes a **weekly rock update** (green / yellow / red with note and recovery plan, `complete` marks the rock Done). The rock's status follows the latest update. |
| issue | Issue. resolved = solved, open = short-term, parked = long-term. The first three `high_priority` open issues per team get ranks 1-3. |
| commitment | To-Do. hit = done, miss = not done with `Missed: <why not>` in the notes, open = open. Linked to its rock/issue. |
| scorecardmetric (+ weekly values) | Measurable with owner, goal, goal direction and weekly values (`%` = percent, `count` = number, `yes/no` = yes/no). The metric's facility becomes its **plant** (Company and no facility = Company). A plain number is flagged as dollars when the goal has a `$` or the name is about money ("revenue", "cost", "pipeline"; ratios, rates and counts are not). |
| value | Core value (the generic offsite evaluation statements are kept in `legacy`) |
| strategyhouse purpose/vision + visiondoc | V/TO. Purpose → purpose, vision → 10-year target (when visiondoc has none), visiondoc → marketing strategy, 3-year picture and 1-year plan. Targets are added to the 1-year measurables. The major business challenge, each strategy box (strategy, tactics, due date, DRI as owner) and each parked idea become **long-term issues** on the leadership team. Lessons and the rudder note show in a "Strategy House notes" panel. |
| seat | Accountability Chart seat (parents kept; people matched by user or by name). Status green → filled, yellow → future, red → open / hiring; agency flag kept. |
| successstatement | Success statements on the person's page |
| oneonone | 1:1 with its highlight, and its G/Y/R grid (each success statement and core value with note) as conversation scores. Its core value ratings also become a People Analyzer review (green `+`, yellow `+/-`, red `-`). Manager comes from the chart. |
| meeting + roundrobinanswer + meetingevaluation | Historical L10 meetings (concluded) with attendees, round robin answers in the segue notes, and a 1-10 rating per attendee: each criterion's color is scored green 10, yellow 7, red 4, then averaged. |

| offsite + reflections, lessons, SWOT, 4 Whats, value / mission / priority evaluations | Annual Planning session per offsite, with each item in the matching agenda section: 4 Whats and reflections in the segue, lessons in the review, SWOT, mission / vision / value checks in the V/TO review (with their color), priorities in key issues. Attendees come from the item authors. |

Round robin questions and L10 evaluation criteria have no EOS home; they stay raw in the `LegacyRecord` table (visible in `/admin/`) and are listed under "Not mapped". Cross-model rows (Strategy House → issues, offsite items) are matched on a stored source key, so re-runs stay idempotent.

## Google login

1. In Google Cloud Console create an OAuth client, type **Web application**.
2. Authorized redirect URIs: `http://localhost:8000/accounts/google/login/callback/` and `https://<your-domain>/accounts/google/login/callback/`.
3. Put the client id and secret in `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. No database setup is needed; the app reads them from settings.
4. Set the OAuth consent screen to **Internal** so only the Workspace can use it.

Only `ALLOWED_EMAIL_DOMAIN` emails get in (default `steuartnutrition.com`); anyone else sees a "this app is for the team" page. Imported users are linked to their Google account by email on first login. A new person on the domain gets a member account automatically; add them to teams in `/admin/`.

## Settings

- `config.settings.dev`: default for `manage.py`. DEBUG on, console email, dev quick login.
- `config.settings.prod`: default for `wsgi.py`. Set `DJANGO_SETTINGS_MODULE=config.settings.prod` on the server. Refuses to start without `SECRET_KEY`.
- `config.settings.test`: used by pytest.

| Var | Purpose |
| --- | --- |
| `SECRET_KEY` | Django secret (required in prod) |
| `DATABASE_URL` | Postgres URL. Empty = SQLite |
| `ALLOWED_HOSTS` | Comma-separated hostnames (prod) |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated `https://` origins (prod) |
| `APP_NAME` | Display name, default `SN EOS`. Rename the app here. |
| `SITE_URL` | Base URL used in recap emails |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth client |
| `ALLOWED_EMAIL_DOMAIN` | Only this domain can log in. Default `steuartnutrition.com` |
| `DEV_LOGIN` | Dev only. `1` (default) shows the pick-a-user login |
| `TAILWIND_CDN` | `0` (default everywhere) uses the compiled `static/css/app.css`. `1` loads the Tailwind CDN instead, handy while iterating on templates locally. |
| `STAGING_PASSWORD_LOGIN` | Staging only. `1` shows an email + password form on the login page for existing users. Never set it in production. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | SMTP for L10 recap emails. Without them dev prints emails to the console. |
| `ASANA_PAT` | Asana personal access token. Turns on "Send to Asana"; without it the Asana buttons are hidden. Same name as the Battle Planner. |
| `ASANA_WORKSPACE_GID` | Asana workspace. Defaults to Steuart's (`1201499979026080`), same as the Battle Planner. |
| `ASANA_TEAM_GID` | Team the Strategic Action project is created in if it has to be made. Defaults to Steuart's. |
| `ASANA_PROJECT_GID` | Optional. Pin the Asana project to use instead of finding or creating "Strategic Action". |
| `TIME_ZONE` | Default `America/New_York` |

## Send to Asana

Most of the team works in Asana, so every to-do has a **Send to Asana** button (and a "Send to Asana" tick on the add forms). It works the way the Battle Planner's does and reads the same variables, so one set of Railway values can serve both apps.

- **Auth:** one server-side personal access token (`ASANA_PAT`). No per-person OAuth. Without it, nothing Asana shows up.
- **Where tasks go:** a private project called **Strategic Action**, with a section per team (Company, Kentucky, Le Roy, Mabel; anything else lands in Company). If `ASANA_PROJECT_GID` is not set, the app looks for a project with that name in the workspace and reuses it (so it shares the Battle Planner's project), and only creates it when none exists. The ids it looks up are cached in the `AppSetting` table.
- **What is sent:** the title (prefixed with the rock or issue it belongs to), the notes plus a link back to the to-do, the due date, and the owner as assignee. The owner is matched to a workspace member by email (or by the optional **Asana email** on the person in `/admin/` when their Asana login differs). The assignee is added to the private project so the link opens. If the owner is not in Asana the task is created unassigned and gets assigned automatically once they show up.
- **No duplicates:** once sent, the button turns into an **In Asana** link; sending again does nothing, and the send is locked per row so two taps make one task.
- **Private to-dos are never sent** (the project is shared).
- **Coming back:** completing the task in Asana checks the to-do off here (**Done in Asana**). It syncs from the To-Dos page at most every 10 minutes, or run `python manage.py sync_asana` (for example as a Railway cron). Editing a to-do's notes also updates the Asana task. Checking a to-do off here does not touch Asana.
- **API and MCP:** `list_todos` / `GET /api/v1/todos` (and anything else that returns to-dos) include `in_asana`, `asana_url`, `asana_state` (`none`, `sent`, `done`) and `asana_unassigned`. Sending is done in the app.

Setup: create a token in Asana (Asana developer console → Personal access tokens) for a user who can create and share projects in the workspace, and add it as `ASANA_PAT` on the web service. The defaults for the workspace and team already match Steuart's.

## Deploy (Railway)

1. Create a Railway project with a **Postgres** service and a **web** service from this repo.
2. Web service variables: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `DJANGO_SETTINGS_MODULE=config.settings.prod`, `SECRET_KEY`, `ALLOWED_HOSTS=<your>.up.railway.app`, `CSRF_TRUSTED_ORIGINS=https://<your>.up.railway.app`, `ALLOWED_EMAIL_DOMAIN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SITE_URL`.
3. The start command is in `Procfile`: collectstatic, migrate, `ensure_defaults` (create-only), then gunicorn. `railway.json` points the health check at `/healthz`.
4. Deploy (`railway up --service web`, or connect the GitHub repo).
5. Import once from your machine against the Railway database: `DATABASE_URL=<Railway public Postgres URL> python manage.py import_battle_planner battle-planner-export.json`. You can also run it in the Railway shell after uploading the file there. Don't commit the file.
6. Add the Railway URL's `/accounts/google/login/callback/` to the Google OAuth client.

Data lives in the Railway Postgres volume; deploys only replace code. Admins can download a full JSON backup at `/export.json` (account menu → Download backup).

## Tailwind

The compiled stylesheet `static/css/app.css` is committed, so deploys need no Node and no CDN. After changing templates, or class names in Python (`*/views.py`, `core/forms.py`, `core/charts.py`, template tags) or `static/js/*.js`, rebuild and commit it:

```
scripts/build_css.sh
```

It downloads the standalone Tailwind v3 CLI into `bin/` (gitignored) on first run. Brand styles that don't depend on Tailwind (colors, cards, buttons, badges, side panel, modals, scorecard cells, the chart, G/Y/R strips) are in `static/css/sn.css`. Brand: black, lime `#D5FF03`, paper `#f6f6f4`, Montserrat headings, Inter body.

### UI conventions

- **Side panel**: any element with `data-panel="<url>"` loads that URL into the right-hand drawer. The server can close it or refresh the page part with `HX-Trigger: panel:close` / `chart:refresh` / `rock:changed`, or open it with `panel:open`.
- **Autosave**: forms post on input with a short delay; the indicator at the bottom right shows Saving… / Saved / Couldn't save.
- **Keyboard**: `?` shows all shortcuts. `g` then `h` `s` `r` `i` `t` `l` `q` `v` `c` `p` `o` jumps to My 90, Scorecard, Rocks, Issues, To-Dos, L10, Planning, V/TO, Chart, People, Conversations. Ctrl/⌘ K or `/` opens the command palette. `n` adds a new item on the current page. Esc closes panels.
- **Drag reorder**: lists with `data-sortable="<url>"` post the new order of their `[data-id]` children.
- **Charts** are server-side SVG (`core/charts.py`): sparklines, trend lines with goal, donut, bars and the 13-week rock strip. They print and need no JS.

## REST API and MCP (AI assistants)

Each person creates their own tokens under **account menu → API & AI connections** (`/settings/api/`). A token acts as that person with their permissions. Choose **Read & write** or **Read only**. The token is shown once; only a SHA-256 hash is stored. Revoke it on the same page. Every write through the API or MCP is recorded in the **audit log** (`/settings/audit/`; admins see everyone's, members their own) with who, which token, what and when.

1:1s, Quarterly Conversations and People Analyzer data are never exposed through the API.

### MCP server

Streamable HTTP at `https://<your-domain>/mcp` (stateless; JSON responses). Authenticate with `Authorization: Bearer <token>`.

```
# Claude Code
claude mcp add --transport http sn-eos https://<your-domain>/mcp --header "Authorization: Bearer sneos_..."
```

```json
// Cursor (.cursor/mcp.json) or other clients that take a URL + headers
{"mcpServers": {"sn-eos": {"url": "https://<your-domain>/mcp", "headers": {"Authorization": "Bearer sneos_..."}}}}
```

Tools (write tools are hidden from read-only tokens):

| Read | Write |
| --- | --- |
| `whoami`, `list_teams`, `my_90`, `get_scorecard`, `list_rocks`, `get_rock`, `list_issues`, `list_todos`, `list_headlines`, `get_l10` | `set_measurable_value`, `update_rock_status` (green/yellow/red; red needs `recovery_plan`), `set_rock_done`, `set_milestone`, `create_issue`, `update_issue`, `solve_issue` (with to-dos), `create_todo`, `update_todo`, `add_headline`, `rate_l10`, `add_cascading_message` |

Teams are referenced by slug (see `list_teams`).

**Company queries.** The list tools (`list_rocks`, `list_issues`, `list_todos`, `list_headlines`) keep their old behavior by default: `team=company` returns only the Company team's items, and `team` omitted keeps each tool's existing default. Pass `include_all=true` to get the Company roll-up: with `team` Company (or omitted) you get every team's items, each tagged with its `team` slug. `include_all` is ignored for a site team. On `get_scorecard`, `include_all=true` with a site `team` also returns the Company measurables, the way that site's Scorecard page shows them. Private to-dos stay private either way. Tool errors (not allowed, bad input) come back as `isError` results the assistant can read.

### REST

Same tools over JSON at `/api/v1/`, same bearer token. Responses are `{"data": ...}` or `{"error": "..."}` (401 bad token, 403 not allowed or read-only, 400 bad input).

| Method | Path | Tool |
| --- | --- | --- |
| GET | `/api/v1/me`, `/teams`, `/my90` | whoami, list_teams, my_90. `my90` takes an optional `?person=` (email, name, or id) for someone else's 90. Private to-dos stay with the people who can already see them. 1:1s, Quarterly Conversations and People Analyzer are never returned. |
| GET | `/api/v1/scorecard` (optional `?plant=company\|kentucky\|le-roy\|mabel`, `?team=kentucky&include_all=true` for the site's Company-then-own view) | get_scorecard: the whole company Scorecard, Company first, then plants grouped by name; each measurable has `plant` |
| POST | `/api/v1/measurables/<id>/values` `{"value": 12, "week": "2026-11-16"}` | set_measurable_value |
| POST | `/api/v1/measurables/values` `{"measurable": "Prelim Proposal Deal Value", "value": 1250000, "week": "2026-11-16"}` | set_measurable_value by name (add `"plant"` — `company`, `kentucky`, `le-roy` or `mabel` — if the name is on several plants, e.g. OEE). Posting the same week again replaces it. |
| GET | `/api/v1/rocks`, `/rocks/<id>` | list_rocks, get_rock |
| POST | `/api/v1/rocks/<id>/updates` `{"color": "red", "note": "...", "recovery_plan": "..."}` | update_rock_status |
| POST | `/api/v1/rocks/<id>/done`, `/rocks/<id>/milestones` | set_rock_done, set_milestone |
| GET, POST | `/api/v1/issues` (`?team=company&include_all=true` rolls up every team; same for `/rocks`, `/todos`, `/headlines`) | list_issues, create_issue |
| PATCH | `/api/v1/issues/<id>`; POST `/issues/<id>/solve` | update_issue, solve_issue |
| GET, POST | `/api/v1/todos`; PATCH `/todos/<id>` | list_todos, create_todo, update_todo |
| GET, POST | `/api/v1/headlines` | list_headlines, add_headline |
| GET | `/api/v1/l10?team=company`; POST `/l10/<id>/rating`, `/l10/<id>/cascading-messages` | get_l10, rate_l10, add_cascading_message |

```
curl -H "Authorization: Bearer sneos_..." https://<your-domain>/api/v1/my90
```

## Demo data

`seed_demo` fills an **empty** database with a fictional company (people, a full Accountability Chart with open and future seats, 13 weeks of scorecard values, weekly rock updates, an L10 in progress, Quarterly Conversations, planning sessions). It refuses to run if any users exist. Use a separate database:

```
DATABASE_URL=sqlite:////tmp/demo.sqlite3 python manage.py migrate
DATABASE_URL=sqlite:////tmp/demo.sqlite3 python manage.py seed_demo
DATABASE_URL=sqlite:////tmp/demo.sqlite3 python manage.py runserver
```

Then use the dev quick login as Ava Mercer or Noah Bennett. `scripts/screenshots.py` captures pages from it.

## Upgrading an existing database (Phase 1)

`migrate` adds the new tables and backfills what it can from data the importer had already stored in `legacy` fields:

- seat status (green/yellow/red) → filled / future / open;
- each rock's weekly status history → weekly rock updates;
- each 1:1's success-statement grid → conversation scores, and its completion date.

Then run the importer once with `--refresh` to bring in what the old import didn't keep (seat agency, core value grid cells, Strategy House issues, offsites as planning sessions) and to drop the generated grid text from old 1:1 notes:

```
python manage.py import_battle_planner battle-planner-export.json --refresh
```

`--refresh` overwrites imported rows with the export's values, so do it before people start editing those rows in SN EOS (or skip `--refresh`; new rows still get created).

## Tests

```
pytest
```

Covers the Company roll-up and shared Company measurables (`tests/test_rollup.py`), models, the importer (with a small synthetic fixture in `tests/fixtures/`), scorecard coloring, inline entry, trends and reorder, the drop-to-issue → IDS → to-do flow, the L10 conclude/recap flow with cascading messages, weekly rock updates (red needs a recovery plan), the Accountability Chart (status counts, drag re-parent and cycle checks, side-panel autosave, private people flags), Quarterly Conversations, the planning session runner, the REST API and MCP server (tokens, read-only, permissions, audit log), `seed_demo`, Send to Asana (against a fake Asana, including a phone-sized browser run), the compiled CSS, and permissions. Run against Postgres with `TEST_DATABASE_URL=postgres://... pytest`. `tests/test_mobile_overflow.py` opens every page at 375px in headless Chromium and fails if the page is wider than the phone; it skips when Playwright is not installed.

## Code map

- `config/` settings (`base`, `dev`, `prod`, `test`) and URLs
- `core/` users, teams, quarters, permissions, login (allauth adapters, dev login), My 90, `/healthz`, `/export.json`, the importer (`core/importer.py`), the Asana adapter (`core/asana_client.py`) and management commands (`sync_asana`)
- `scorecard/`, `rocks/` (+ `services.py` for weekly updates), `issues/`, `todos/`, `meetings/` (L10), `vision/` (V/TO, core values, core processes, Accountability Chart), `people/` (1:1s, Quarterly Conversations, People Analyzer, chart flags), `planning/` (Quarterly / Annual sessions)
- `api/` tokens, audit log, the tool registry shared by REST and MCP (`api/tools.py`) and the endpoints (`api/views.py`)
- `templates/` base layout, nav, login pages; each app has its own `templates/<app>/`
- `static/` logo, `sn.css`, compiled `app.css`, `js/app.js` (panel, palette, shortcuts, autosave indicator, drag reorder, scorecard keys), `js/chart.js` (Accountability Chart), vendored htmx and Alpine
- `scripts/screenshots.py` captures page screenshots from a running dev server (needs `pip install playwright && playwright install chromium`)
- `scripts/mobile_audit.py` screenshots every page at 375, 390 and 768px with touch emulation and reports page overflow and tap targets under 44px
