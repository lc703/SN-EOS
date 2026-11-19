from django.contrib import admin
from django.urls import include, path

from api import views as api
from core import views as core
from issues import views as issues
from meetings import views as meetings
from people import views as people
from planning import views as planning
from rocks import views as rocks
from scorecard import views as scorecard
from todos import views as todos
from vision import views as vision

urlpatterns = [
    path("", core.home, name="home"),
    path("healthz", core.healthz, name="healthz"),
    path("export.json", core.export_json, name="export_json"),
    path("dev-login/", core.dev_login, name="dev_login"),
    path("admin/", admin.site.urls),
    path("accounts/password-login/", core.password_login, name="password_login"),
    path("accounts/", include("allauth.urls")),
    # Scorecard
    path("scorecard/", scorecard.scorecard, name="scorecard"),
    path("scorecard/new/", scorecard.measurable_new, name="measurable_new"),
    path("scorecard/<int:pk>/edit/", scorecard.measurable_edit, name="measurable_edit"),
    path("scorecard/<int:pk>/cell/<str:week>/", scorecard.cell, name="scorecard_cell"),
    path("scorecard/<int:pk>/panel/", scorecard.measurable_panel, name="measurable_panel"),
    path("scorecard/sort/", scorecard.measurables_sort, name="measurables_sort"),
    # Rocks
    path("rocks/", rocks.rocks_list, name="rocks"),
    path("rocks/new/", rocks.rock_new, name="rock_new"),
    path("rocks/<int:pk>/", rocks.rock_detail, name="rock_detail"),
    path("rocks/<int:pk>/status/", rocks.rock_status, name="rock_status"),
    path("rocks/<int:pk>/update/", rocks.rock_update, name="rock_update"),
    path("rocks/<int:pk>/row/", rocks.rock_row, name="rock_row"),
    path("rocks/sort/", rocks.rocks_sort, name="rocks_sort"),
    path("rocks/<int:pk>/milestones/", rocks.milestone_add, name="milestone_add"),
    path("rocks/<int:pk>/todos/", rocks.rock_todo, name="rock_todo"),
    path("milestones/<int:pk>/", rocks.milestone_toggle, name="milestone_toggle"),
    # Issues
    path("issues/", issues.issues_list, name="issues"),
    path("issues/new/", issues.issue_new, name="issue_new"),
    path("issues/drop/", issues.drop_to_issues, name="drop_to_issues"),
    path("issues/<int:pk>/", issues.issue_detail, name="issue_detail"),
    path("issues/<int:pk>/solve/", issues.issue_solve, name="issue_solve"),
    path("issues/<int:pk>/reopen/", issues.issue_reopen, name="issue_reopen"),
    path("issues/<int:pk>/priority/", issues.issue_priority, name="issue_priority"),
    path("issues/<int:pk>/move/", issues.issue_move, name="issue_move"),
    # To-dos
    path("todos/", todos.todos_list, name="todos"),
    path("todos/new/", todos.todo_new, name="todo_new"),
    path("todos/<int:pk>/", todos.todo_edit, name="todo_edit"),
    path("todos/<int:pk>/toggle/", todos.todo_toggle, name="todo_toggle"),
    # L10
    path("meetings/", meetings.meetings_list, name="meetings"),
    path("meetings/start/", meetings.meeting_start, name="meeting_start"),
    path("meetings/<int:pk>/", meetings.meeting, name="meeting"),
    path("meetings/<int:pk>/where/", meetings.meeting_where, name="meeting_where"),
    path("meetings/<int:pk>/update/", meetings.meeting_update, name="meeting_update"),
    path("meetings/<int:pk>/headlines/", meetings.headline_add, name="headline_add"),
    path("meetings/<int:pk>/rate/", meetings.rate, name="meeting_rate"),
    path("meetings/<int:pk>/conclude/", meetings.conclude, name="meeting_conclude"),
    path("meetings/<int:pk>/recap/", meetings.recap, name="meeting_recap"),
    path("meetings/<int:pk>/recap/send/", meetings.send_recap, name="meeting_send_recap"),
    # Vision
    path("vto/", vision.vto, name="vto"),
    path("vto/processes/", vision.core_process, name="core_process_new"),
    path("vto/processes/<int:pk>/", vision.core_process, name="core_process"),
    path("vto/edit/", vision.vto_edit, name="vto_edit"),
    path("chart/", vision.chart, name="chart"),
    path("chart/seats/new/", vision.seat_edit, name="seat_new"),
    path("chart/seats/<int:pk>/", vision.seat_edit, name="seat_edit"),
    path("chart/seats/panel/", vision.seat_panel, name="seat_panel_new"),
    path("chart/seats/<int:pk>/panel/", vision.seat_panel, name="seat_panel"),
    path("chart/seats/<int:pk>/move/", vision.seat_move, name="seat_move"),
    # People
    path("people/", people.people_list, name="people"),
    path("people/<int:pk>/", people.person, name="person"),
    path("people/<int:pk>/one-on-ones/", people.one_on_one_add, name="one_on_one_add"),
    path("people/<int:pk>/reviews/", people.review_add, name="review_add"),
    path("people/<int:pk>/conversations/new/", people.conversation_new, name="conversation_new"),
    path("people/<int:pk>/statements/", people.statement_add, name="statement_add"),
    path("conversations/", people.conversations, name="conversations"),
    path("conversations/<int:pk>/", people.conversation, name="conversation"),
    path("conversations/<int:pk>/score/", people.conversation_score, name="conversation_score"),
    # Quarterly & annual planning
    path("planning/", planning.sessions_list, name="planning"),
    path("planning/start/", planning.session_start, name="session_start"),
    path("planning/<int:pk>/", planning.session_view, name="session"),
    path("planning/<int:pk>/items/", planning.item_add, name="session_item_add"),
    path("planning/<int:pk>/update/", planning.session_update, name="session_update"),
    path("planning/<int:pk>/rocks/", planning.session_rock, name="session_rock"),
    path("planning/<int:pk>/todos/", planning.session_todo, name="session_todo"),
    path("planning/<int:pk>/rate/", planning.session_rate, name="session_rate"),
    path("planning/<int:pk>/conclude/", planning.session_conclude, name="session_conclude"),
    path("planning/<int:pk>/recap/", planning.session_recap, name="session_recap"),
    path("planning/items/<int:pk>/", planning.item_update, name="session_item"),
    # Integrations
    path("settings/api/", api.tokens, name="api_tokens"),
    path("settings/api/<int:pk>/revoke/", api.token_revoke, name="api_token_revoke"),
    path("settings/audit/", api.audit_log, name="audit_log"),
    path("api/v1/<path:path>", api.rest, name="api_rest"),
    path("mcp", api.mcp, name="mcp"),
    path("mcp/", api.mcp),
]
