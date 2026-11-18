# SN EOS

Internal EOS (Entrepreneurial Operating System) app for Steuart Nutrition. It replaces the SN Strategy Battle Planner with a simpler tool that follows EOS closely: Scorecard, Rocks, Issues (IDS), To-Dos, the weekly Level 10 meeting, the V/TO, the Accountability Chart and People (1:1s and a light People Analyzer).

It is modeled on the core of Ninety.io but deliberately less rigid: there are no meeting timers and no forced step order. The facilitator can jump to any L10 section at any time.

Stack: Python 3.12, Django 5.2, Postgres (SQLite in dev), Django templates, HTMX, Alpine, Tailwind, django-allauth with Google sign-in. Deploys to Railway the same way the Battle Planner did.

## What's in it

Everything is scoped by **team** (Company/Leadership, Kentucky, Le Roy, Mabel) and **quarter**, picked in the bar under the header. People can belong to several teams.

| Page | What it does |
| --- | --- |
| **My 90** (`/`) | Your open to-dos, rocks, measurables and issues, plus your to-do completion for the last 4 weeks. |
| **Scorecard** | Weekly measurables per team. Columns are the 13 weeks of the quarter. Type a value in any cell; it saves on change and turns green (on goal) or red (off goal). Goal can be `≥`, `≤` or `=`; units are number, %, currency or yes/no. Optional average or total column. |
| **Rocks** | Quarterly rocks with owner, due date, status (On Track / Off Track / Done), description and milestones. Company rocks (the leadership team's rocks) show on every team's Rocks page. |
| **Issues** | Short-term and long-term lists per team. Click 1, 2 or 3 to rank the top three. **IDS** opens the solve panel: record the decision, add to-dos (owner, due date), then mark solved. |
| **To-Dos** | Team and private to-dos. Due date defaults to 7 days out, past dates are allowed. Weekly completion % per person and per team (by due week). |
| **L10** | Start the week's meeting per team. Sections: Segue, Scorecard, Rock Review, Headlines, To-Do List, IDS, Conclude. Each shows live data you can edit in place. Red measurables, off-track rocks and headlines have a one-click **Drop to Issues** button. Conclude shows new to-dos and solved issues, collects a 1-10 rating per attendee (average shown) and links to a printable recap that can be emailed to attendees. Attendees on other devices see a banner when the facilitator moves to another section. |
| **V/TO** | Core values, core focus, 10-year target, marketing strategy, 3-year picture, 1-year plan, this quarter's company rocks and the long-term issues list. Admins edit it. |
| **Chart** | Accountability Chart: seats in a tree (title, person, roles, parent seat) plus an editable list. |
| **People** | Directory. Each person's page shows their seats, success statements, 1:1 notes and People Analyzer reviews (core values `+`, `+/-`, `-`, and Get it / Want it / Capacity). 1:1s and reviews are visible only to the person, their manager (the person in the parent seat on the chart) and admins. |

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

Rows with no EOS equivalent (offsites, reflections, lessons, SWOT, 4 Whats, offsite evaluations, round robin questions, evaluation criteria) are stored raw in the `LegacyRecord` table (visible in `/admin/`) and listed under "Not mapped" in the command output.

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
| `TAILWIND_CDN` | Prod only. `1` (default) uses the Tailwind CDN, `0` uses compiled `static/css/app.css` |
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

## Tailwind in prod

Prod uses the Tailwind CDN until a compiled file is committed (`TAILWIND_CDN=1`). To compile with the standalone CLI (no Node), download `tailwindcss` v3 into `bin/` and run:

```
bin/tailwindcss -c tailwind.config.js -i static/src/input.css -o static/css/app.css --minify
```

Commit `static/css/app.css` and set `TAILWIND_CDN=0`. Brand styles that don't depend on Tailwind (colors, cards, buttons, scorecard cells, chart tree) are in `static/css/sn.css`.

## Tests

```
pytest
```

Covers models, the importer (with a small synthetic fixture in `tests/fixtures/`), scorecard coloring and inline entry, the drop-to-issue → IDS → to-do flow, the L10 conclude/recap flow, and permissions. Run against Postgres with `TEST_DATABASE_URL=postgres://... pytest`.

## Code map

- `config/` settings (`base`, `dev`, `prod`, `test`) and URLs
- `core/` users, teams, quarters, permissions, login (allauth adapters, dev login), My 90, `/healthz`, `/export.json`, the importer (`core/importer.py`) and management commands
- `scorecard/`, `rocks/`, `issues/`, `todos/`, `meetings/` (L10), `vision/` (V/TO, core values, Accountability Chart), `people/` (1:1s, People Analyzer)
- `templates/` base layout, nav, login pages; each app has its own `templates/<app>/`
- `static/` logo, `sn.css`, vendored htmx and Alpine
- `scripts/screenshots.py` captures page screenshots from a running dev server (needs `pip install playwright && playwright install chromium`)
