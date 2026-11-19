from django.contrib import admin
from django.urls import include, path, re_path

from api import views as api

from core import views as core
from issues import views as issues
from meetings import views as meetings
from planning import views as planning
from people import views as people
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
    # API + MCP (bearer tokens)
    re_path(r"^api/v1/(?P<path>.*)$", api.rest, name="api_rest"),
    path("mcp", api.mcp, name="mcp"),
    path("mcp/", api.mcp),
    path("settings/api/", api.tokens, name="api_tokens"),
    path("settings/api/<int:pk>/revoke/", api.token_revoke, name="api_token_revoke"),
    # Scorecard
    path("scorecard/", scorecard.scorecard, name="scorecard"),
    path("scorecard/new/", scorecard.measurable_new, name="measurable_new"),
    path("scorecard/<int:pk>/edit/", scorecard.measurable_edit, name="measurable_edit"),
    path("scorecard/<int:pk>/panel/", scorecard.measurable_panel, name="measurable_panel"),
    path("scorecard/reorder/", scorecard.measurable_reorder, name="measurable_reorder"),
    path("scorecard/<int:pk>/cell/<str:week>/", scorecard.cell, name="scorecard_cell"),
    # Rocks
    path("rocks/", rocks.rocks_list, name="rocks"),
    path("rocks/new/", rocks.rock_new, name="rock_new"),
    path("rocks/reorder/", rocks.rocks_reorder, name="rocks_reorder"),
    path("rocks/<int:pk>/", rocks.rock_detail, name="rock_detail"),
    path("rocks/<int:pk>/status/", rocks.rock_status, name="rock_status"),
    path("rocks/<int:pk>/update/", rocks.rock_update, name="rock_update"),
    path("rocks/<int:pk>/milestones/", rocks.milestone_add, name="milestone_add"),
    path("rocks/<int:pk>/milestones/reorder/", rocks.milestone_reorder, name="milestone_reorder"),
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
    path("meetings/<int:pk>/cascades/", meetings.cascade_add, name="cascade_add"),
    path("cascades/<int:pk>/delete/", meetings.cascade_delete, name="cascade_delete"),
    path("meetings/<int:pk>/recap/", meetings.recap, name="meeting_recap"),
    path("meetings/<int:pk>/recap/send/", meetings.send_recap, name="meeting_send_recap"),
    # Quarterly & annual sessions
    path("sessions/", planning.sessions_list, name="sessions"),
    # Vision
    path("vto/", vision.vto, name="vto"),
    path("vto/edit/", vision.vto_edit, name="vto_edit"),
    path("vto/goals/new/", vision.goal_edit, name="goal_new"),
    path("vto/goals/<int:pk>/", vision.goal_edit, name="goal_edit"),
    path("chart/", vision.chart, name="chart"),
    path("chart/seats/new/", vision.seat_edit, name="seat_new"),
    path("chart/seats/<int:pk>/", vision.seat_edit, name="seat_edit"),
    path("chart/seats/<int:pk>/panel/", vision.seat_panel, name="seat_panel"),
    path("chart/seats/<int:pk>/move/", vision.seat_move, name="seat_move"),
    # People
    path("people/", people.people_list, name="people"),
    path("people/conversations/", people.conversations, name="conversations"),
    path("people/<int:pk>/conversations/start/", people.qc_start, name="qc_start"),
    path("people/<int:pk>/statements/", people.statement_add, name="statement_add"),
    path("conversations/<int:pk>/", people.qc_detail, name="qc_detail"),
    path("conversations/<int:pk>/score/", people.qc_score, name="qc_score"),
    path("statements/<int:pk>/delete/", people.statement_delete, name="statement_delete"),
    path("people/<int:pk>/", people.person, name="person"),
    path("people/<int:pk>/one-on-ones/", people.one_on_one_add, name="one_on_one_add"),
    path("people/<int:pk>/reviews/", people.review_add, name="review_add"),
]
