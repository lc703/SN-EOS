# SN EOS

Internal EOS (Entrepreneurial Operating System) app for Steuart Nutrition. It replaces the SN Strategy Battle Planner with a tool that follows EOS closely: Scorecard, Rocks, Issues (IDS), To-Dos, the weekly Level 10 meeting, Quarterly and Annual planning sessions, the V/TO, the Accountability Chart and People (Quarterly Conversations and the People Analyzer). The Battle Planner's Strategy House lives on the V/TO.

There are deliberately no meeting timers and no forced step order: the facilitator can jump to any L10 or session step at any time.

Stack: Python 3.12, Django 5.2, Postgres (SQLite in dev), Django templates, HTMX, Alpine, Tailwind (compiled), django-allauth with Google sign-in. Deploys to Railway.

## What's in it

Everything is scoped by **team** (Company/Leadership, Kentucky, Le Roy, Mabel) and **quarter**, picked in the bar under the header. People can belong to several teams. Press `?` anywhere for keyboard shortcuts (`g` then a letter to jump between pages, `n` for new, `[` / `]` to move between L10 or session steps).

| Page | What it does |
| --- | --- |
| **My 90** (`/`) | What needs you now (rock updates due this week, numbers missing for last week, overdue to-dos), quarter progress, your rocks, measurables, to-dos and issues, and team visuals: rock status donut, Scorecard on-goal trend, L10 rating trend and to-do completion. |
| **Scorecard** | Weekly Measurables per team over the quarter's 13 weeks. Type in a cell (arrow keys / Enter move between cells); it autosaves and turns green or red against the goal (`≥`, `≤` or `=`). Trend sparklines, average/total columns, an on-goal footer, weekly summary charts, drag to reorder, and a side panel per measurable with a 26-week trend and autosaved settings. |
| **Rocks** | 90-day Rocks, company or departmental, with owner, due date, goal link and milestones. Owners post a weekly **green / yellow / red** update; red requires a recovery plan. Each rock shows a 13-week strip and the update timeline. |
| **Issues** | Short-term and long-term lists per team. Rank the top three, then **IDS**: record the decision, add to-dos, mark solved. |
| **To-Dos** | Team and private to-dos, 7 days by default. Weekly completion % per person and per team. |
| **L10** | The weekly Level 10: Segue, Scorecard, Rock Review, Customer/Employee Headlines, To-Do List, IDS, Conclude. A rail shows section badges (red numbers, off-track rocks, overdue to-dos, open issues) and progress. Conclude collects a 1-10 rating per attendee and **cascading messages**, which show up in other teams' next L10 headlines. Printable/emailable recap with rocks and cascades; meeting list with a rating trend. |
| **Quarterly & Annual** | Session runner with the EOS agendas. Quarterly: Segue, Review previous quarter, Review the V/TO, Establish Rocks, IDS, Next steps, Conclude. Annual adds Team health building, SWOT / Issues List and Establish 1-year goals. Boards for news, SWOT, lessons and rock ideas; one click turns an item into a Rock, an Issue or a 1-year goal. The review step scores the previous period (rocks done %, Scorecard on goal, to-do completion). |
| **V/TO** | Core values, core focus, 10-year target, marketing strategy, 3-year picture, 1-year plan with **goals** (strategy, tactics, owner, linked rock status), the Battle Planner Strategy House as a strategy card, this quarter's company rocks and the long-term issues list. Admins edit it. |
| **Chart** | Accountability Chart: seats colored by status (filled, open/hiring, future, agency) with counts, zoom/pan/fit, collapse, titles-only and print layouts, drag to re-parent, a side panel with the seat's five roles, and GWC / People Analyzer / Quarterly Conversation flags. |
| **People** | Directory with Quarterly Conversation status. **Quarterly Conversations** (5-5-5): a completion tracker built from the chart, and a G/Y/R grid per success statement and core value with notes and last quarter's score alongside. People Analyzer reviews (core values `+`, `+/-`, `-` and GWC). Conversations and reviews are visible only to the person, their manager (parent seat) and admins. |
| **API & AI** (`/settings/api/`) | Personal API tokens for the REST API and the MCP server (see below). |

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

Demo data: `python manage.py seed_demo` fills an empty database with Steuart-like teams, a chart, a Scorecard, Rocks with weekly updates, L10s (including one in progress today), Quarterly Conversations, the V/TO and planning sessions. It refuses to run if rocks already exist (`--force` overrides) and is for development only.

No export handy? `python manage.py ensure_defaults` creates the four teams, the current quarter and an empty V/TO; then create a superuser with `python manage.py createsuperuser`.

Health check: http://localhost:8000/healthz

Postgres locally: `docker compose up -d db` and set `DATABASE_URL=postgres://sneos:sneos@localhost:5432/sneos`.

## Importing from the Battle Planner

```
python manage.py import_battle_planner battle-planner-export.json [--refresh]
```

The file is the Battle Planner's `/export.json` (a Django `dumpdata`). **It contains real 1:1 notes, so keep it out of git**; `.gitignore` already ignores `*export*.json` and `data/`.

The command is idempotent: every imported row stores its old id in `legacy_id`, so running it again creates nothing new. By default it leaves rows already in SN EOS alone, so edits made in the app survive a re-run. `--refresh` overwrites imported rows with the values from the file.

| Battle Planner | SN EOS |
| --- | --- |
| facility (+ its team members) | Team (Company becomes the leadership team) |
| user | User, matched by email; no passwords. Role `admin` stays admin. |
| quarter | Quarter |
| rock + milestone + rockstatus | Rock + milestones. Status from the latest weekly status: green/yellow = On Track, red = Off Track, complete = Done. The weekly history is kept and shown on the rock page. |
| issue | Issue. resolved = solved, open = short-term, parked = long-term. The first three `high_priority` open issues per team get ranks 1-3. |
| commitment | To-Do. hit = done, miss = not done with `Missed: <why not>` in the notes, open = open. Linked to its rock/issue. |
| scorecardmetric | Measurable (`%` = percent, `count` = number, `yes/no` = yes/no). The old app had no goals, owners or weekly values, so set them on the Scorecard page. |
| value | Core value (the generic offsite evaluation statements are kept in `legacy`) |
| strategyhouse purpose/vision + visiondoc | V/TO. Purpose → purpose, vision → 10-year target (when visiondoc has none), visiondoc → marketing strategy, 3-year picture and 1-year plan. Major business challenge, targets, lessons and the strategy boxes are kept in `legacy` and shown in a "From the Battle Planner" panel on the V/TO. |
| seat | Accountability Chart seat (parents kept; people matched by user or by name) |
| successstatement | Success statements on the person's page |
| oneonone | 1:1 record: highlight plus each success statement's red/yellow/green and note. Its core value ratings also become a People Analyzer review (green `+`, yellow `+/-`, red `-`). Manager comes from the chart. |
| meeting + roundrobinanswer + meetingevaluation | Historical L10 meetings (concluded) with attendees, round robin answers in the segue notes, and a 1-10 rating per attendee: each criterion's color is scored green 10, yellow 7, red 4, then averaged. |

Offsites become Quarterly/Annual sessions (reflections, lessons, SWOT and 4 Whats as board items), the weekly rock statuses become weekly G/Y/R updates, 1:1 scores become the Quarterly Conversation grid, seat status comes from the old chart, and the Strategy House boxes become V/TO goals and the strategy card. Anything else with no EOS equivalent is stored raw in the `LegacyRecord` table (visible in `/admin/`) and listed under "Not mapped" in the command output.

### Migration notes (V1 → this version)

All new migrations are additive (new tables and nullable/defaulted columns), so `migrate` is safe on the V1 database:

- `vision 0002`, `rocks 0002`, `people 0002`, `meetings 0002`, `planning 0001`, `api 0001`: seat status, 1-year goals, weekly rock updates, Quarterly Conversation scores, cascading messages, sessions, API tokens and the audit log.
- `vision 0003`, `rocks 0003`, `people 0003`, `planning 0002`: data migrations that move what the V1 importer parked in `legacy` JSON and `LegacyRecord` rows into the new tables. They only create rows that don't exist yet, so they are safe to re-run via a fresh import, and they are no-ops on an empty database.

No re-import is needed after deploying. Running `import_battle_planner` again is still idempotent.

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
| `STAGING_PASSWORD_LOGIN` | `1` adds an email + password form to the login page (for staging; users need a password set in `/admin/`). Off by default; never set it in production |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | SMTP for L10 recap emails. Without them dev prints emails to the console. |
| `TIME_ZONE` | Default `America/New_York` |

## Deploy (Railway)

1. Create a Railway project with a **Postgres** service and a **web** service from this repo.
2. Web service variables: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `DJANGO_SETTINGS_MODULE=config.settings.prod`, `SECRET_KEY`, `ALLOWED_HOSTS=<your>.up.railway.app`, `CSRF_TRUSTED_ORIGINS=https://<your>.up.railway.app`, `ALLOWED_EMAIL_DOMAIN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SITE_URL`.
3. The start command is in `Procfile`: collectstatic, migrate, `ensure_defaults` (create-only), then gunicorn. `railway.json` points the health check at `/healthz`.
4. Deploy (`railway up --service web`, or connect the GitHub repo).
5. Import once from your machine against the Railway database: `DATABASE_URL=<Railway public Postgres URL> python manage.py import_battle_planner battle-planner-export.json`. You can also run it in the Railway shell after uploading the file there. Don't commit the file.
6. Add the Railway URL's `/accounts/google/login/callback/` to the Google OAuth client.

Data lives in the Railway Postgres volume; deploys only replace code. Admins can download a full JSON backup at `/export.json` (account menu → Download backup).

## REST API and MCP server

Every feature is available to scripts and AI assistants through the same set of tools, with the same permissions as the person who owns the token.

1. Go to **API & AI** in the sidebar (`/settings/api/`), create a token (read-only or read & write, optional expiry). It is shown once and stored hashed.
2. Every call is recorded in the audit log with the user, tool, object, payload and result. You see your own recent calls under **Activity** on the same page; admins see all of them in `/admin/` → Audit logs.

**REST** at `/api/v1/` with `Authorization: Bearer <token>`. `GET /api/v1/` lists the endpoints:

| Method | Path | Tool |
| --- | --- | --- |
| GET | `me`, `teams`, `quarters` | whoami, list_teams, list_quarters |
| GET | `scorecard?team=&quarter=` | get_scorecard |
| POST | `measurables/<id>/values` | set_measurable_value |
| GET/POST | `rocks`, `rocks/<id>` (PATCH to update) | list_rocks, create_rock, get_rock, update_rock |
| POST | `rocks/<id>/updates` | add_rock_update (weekly G/Y/R; red needs `recovery_plan`) |
| GET/POST/PATCH | `issues`, `todos`, `headlines` | list/create/update |
| GET | `meetings`, `meetings/<id>` | list_meetings, get_meeting |
| POST | `meetings/<id>/rating`, `/notes`, `/cascades` | rate_meeting, add_meeting_notes, add_cascading_message |
| GET | `vto`, `chart` | get_vto, get_accountability_chart |
| GET/POST | `sessions`, `sessions/<id>`, `sessions/<id>/items` | list_sessions, get_session, add_session_item |

```
curl -H "Authorization: Bearer $SN_EOS_TOKEN" "https://<host>/api/v1/rocks?team=kentucky&mine=true"
```

**MCP** (Streamable HTTP, JSON-RPC over `POST /mcp`) exposes the same tools to Claude, Cursor and other MCP clients. Example client config:

```json
{
  "mcpServers": {
    "sn-eos": {
      "url": "https://<host>/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

Tools live in `api/services.py` (`@tool(...)`); REST routes map to them in `api/views.py`.

## CSS (Tailwind)

The compiled stylesheet `static/css/app.css` is committed, so deploys need no Node. After changing templates or `static/src/input.css`, rebuild and commit it:

```
npm install
npm run build:css      # or npm run watch:css while developing
```

Status classes built at runtime (`rag-*`, `dot-*`, `st-*`) are safelisted in `tailwind.config.js`.

## Tests

```
pytest
```

Covers models, the importer and backfills (with small synthetic fixtures in `tests/fixtures/`), the chart, scorecard, rocks and weekly updates, the issue → IDS → to-do flow, L10 sections, cascades and recap, the dashboard, Quarterly Conversations, the V/TO, the session runner, the REST API, MCP server, tokens and audit log, permissions and the staging password login. Run against Postgres with `TEST_DATABASE_URL=postgres://... pytest`.

## Code map

- `config/` settings (`base`, `dev`, `prod`, `test`) and URLs
- `core/` users, teams, quarters, permissions, login (allauth adapters, dev login), My 90, `/healthz`, `/export.json`, the importer (`core/importer.py`) and management commands
- `scorecard/`, `rocks/`, `issues/`, `todos/`, `meetings/` (L10), `planning/` (Quarterly/Annual sessions), `vision/` (V/TO, goals, Accountability Chart), `people/` (Quarterly Conversations, People Analyzer), `api/` (tokens, audit log, REST, MCP)
- `templates/` base layout, nav, login pages; each app has its own `templates/<app>/`
- `static/` logo, `src/input.css` (Tailwind source and design system components), compiled `css/app.css`, `js/app.js` (panels, toasts, autosave, shortcuts), vendored htmx, Alpine and Sortable
- `scripts/screenshots.py` captures page screenshots from a running dev server (needs `pip install playwright && playwright install chromium`)
