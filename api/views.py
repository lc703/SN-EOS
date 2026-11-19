import datetime as dt
import json
import re

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import services
from .models import ApiToken, AuditLog

MCP_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "sn-eos", "title": "SN EOS", "version": "2.0"}


def client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None


def bearer_token(request):
    header = request.headers.get("Authorization", "")
    raw = header[7:].strip() if header.lower().startswith("bearer ") else request.headers.get("X-Api-Key", "").strip()
    return ApiToken.find(raw)


def unauthorized(message="Missing or invalid API token. Send `Authorization: Bearer sneos_…`."):
    resp = JsonResponse({"error": message}, status=401)
    resp["WWW-Authenticate"] = 'Bearer realm="sn-eos"'
    return resp


# ---------------------------------------------------------------- REST

# (method, path regex, tool, {path group: argument})
ROUTES = [
    ("GET", r"me", "whoami", {}),
    ("GET", r"teams", "list_teams", {}),
    ("GET", r"quarters", "list_quarters", {}),
    ("GET", r"scorecard", "get_scorecard", {}),
    ("POST", r"measurables/(?P<id>\d+)/values", "set_measurable_value", {"id": "measurable_id"}),
    ("GET", r"rocks", "list_rocks", {}),
    ("POST", r"rocks", "create_rock", {}),
    ("GET", r"rocks/(?P<id>\d+)", "get_rock", {"id": "rock_id"}),
    ("PATCH", r"rocks/(?P<id>\d+)", "update_rock", {"id": "rock_id"}),
    ("POST", r"rocks/(?P<id>\d+)/updates", "add_rock_update", {"id": "rock_id"}),
    ("GET", r"issues", "list_issues", {}),
    ("POST", r"issues", "create_issue", {}),
    ("PATCH", r"issues/(?P<id>\d+)", "update_issue", {"id": "issue_id"}),
    ("GET", r"todos", "list_todos", {}),
    ("POST", r"todos", "create_todo", {}),
    ("PATCH", r"todos/(?P<id>\d+)", "update_todo", {"id": "todo_id"}),
    ("GET", r"headlines", "list_headlines", {}),
    ("POST", r"headlines", "create_headline", {}),
    ("GET", r"meetings", "list_meetings", {}),
    ("GET", r"meetings/(?P<id>\d+)", "get_meeting", {"id": "meeting_id"}),
    ("POST", r"meetings/(?P<id>\d+)/rating", "rate_meeting", {"id": "meeting_id"}),
    ("POST", r"meetings/(?P<id>\d+)/notes", "add_meeting_notes", {"id": "meeting_id"}),
    ("POST", r"meetings/(?P<id>\d+)/cascades", "add_cascading_message", {"id": "meeting_id"}),
    ("GET", r"vto", "get_vto", {}),
    ("GET", r"chart", "get_accountability_chart", {}),
    ("GET", r"sessions", "list_sessions", {}),
    ("GET", r"sessions/(?P<id>\d+)", "get_session", {"id": "session_id"}),
    ("POST", r"sessions/(?P<id>\d+)/items", "add_session_item", {"id": "session_id"}),
]
COMPILED = [(m, re.compile(rf"^{p}/?$"), t, a) for m, p, t, a in ROUTES]


def rest_index():
    return {
        "name": "SN EOS API",
        "version": "v1",
        "auth": "Authorization: Bearer <token>",
        "endpoints": [f"{m} /api/v1/{p.replace('(?P<id>\\d+)', '{id}')}" for m, p, _, _ in ROUTES],
        "mcp": "/mcp",
    }


@csrf_exempt
def rest(request, path=""):
    token = bearer_token(request)
    if not token:
        return unauthorized()
    path = path.strip("/")
    if not path:
        return JsonResponse(rest_index())
    method = "PATCH" if request.method == "PUT" else request.method
    matched_path = False
    for m, rx, tool_name, mapping in COMPILED:
        match = rx.match(path)
        if not match:
            continue
        matched_path = True
        if m != method:
            continue
        args = {k: v for k, v in request.GET.items()}
        if method in ("POST", "PATCH"):
            try:
                body = json.loads(request.body or b"{}") if request.body else {}
            except json.JSONDecodeError:
                return JsonResponse({"error": "Body must be JSON."}, status=400)
            if not isinstance(body, dict):
                return JsonResponse({"error": "Body must be a JSON object."}, status=400)
            args.update(body)
        for group, arg in mapping.items():
            args[arg] = int(match.group(group))
        status, result = services.run(token, tool_name, args, AuditLog.REST, client_ip(request), f"{request.method} /api/v1/{path}")
        return JsonResponse(result, status=status)
    if matched_path:
        return JsonResponse({"error": f"{request.method} not allowed here."}, status=405)
    return JsonResponse({"error": "Not found. GET /api/v1/ lists the endpoints."}, status=404)


# ---------------------------------------------------------------- MCP (streamable HTTP, stateless JSON responses)

def rpc_result(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def rpc_error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


INSTRUCTIONS = (
    "SN EOS runs Steuart Nutrition on EOS. Use list_teams to find team slugs. Rocks are 90-day priorities with a "
    "weekly green/yellow/red update (red needs a recovery plan). Measurables are weekly Scorecard numbers. "
    "Issues are solved with IDS in the L10. To-Dos are 7-day commitments. Every write is recorded under your name."
)


def handle_rpc(msg, token, ip):
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return rpc_error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid request")
    rid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if rid is None:  # notification
        return None
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in MCP_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSIONS[0]
        return rpc_result(rid, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return rpc_result(rid, {})
    if method == "tools/list":
        tools = [t.definition() for t in services.TOOLS.values() if token.can_write or not t.write]
        return rpc_result(rid, {"tools": tools})
    if method == "tools/call":
        name = params.get("name")
        if name not in services.TOOLS:
            return rpc_error(rid, -32602, f"Unknown tool: {name}")
        status, result = services.run(token, name, params.get("arguments") or {}, AuditLog.MCP, ip)
        ok = status < 400
        text = json.dumps(result, indent=1, default=str) if ok else result.get("error", "Error")
        payload = {"content": [{"type": "text", "text": text}], "isError": not ok}
        if ok:
            payload["structuredContent"] = result
        return rpc_result(rid, payload)
    if method in ("resources/list", "prompts/list"):
        return rpc_result(rid, {method.split("/")[0]: []})
    return rpc_error(rid, -32601, f"Method not found: {method}")


@csrf_exempt
def mcp(request):
    if request.method == "GET":
        resp = HttpResponse(status=405)
        resp["Allow"] = "POST"
        return resp
    if request.method == "DELETE":
        return HttpResponse(status=405)
    if request.method != "POST":
        return HttpResponse(status=405)
    token = bearer_token(request)
    if not token:
        return unauthorized()
    try:
        body = json.loads(request.body or b"null")
    except json.JSONDecodeError:
        return JsonResponse(rpc_error(None, -32700, "Parse error"), status=400)
    ip = client_ip(request)
    if isinstance(body, list):
        replies = [r for r in (handle_rpc(m, token, ip) for m in body) if r is not None]
        return JsonResponse(replies, safe=False) if replies else HttpResponse(status=202)
    reply = handle_rpc(body, token, ip)
    if reply is None:
        return HttpResponse(status=202)
    return JsonResponse(reply)


# ---------------------------------------------------------------- token management (signed-in users)

def tokens(request):
    if request.method == "POST":
        label = request.POST.get("label", "").strip() or "API token"
        days = request.POST.get("expires", "")
        expires = timezone.now() + dt.timedelta(days=int(days)) if days.isdigit() and int(days) > 0 else None
        token, raw = ApiToken.issue(request.user, label, can_write=request.POST.get("scope") != "read", expires_at=expires)
        request.session["new_api_token"] = {"id": token.pk, "raw": raw}
        return redirect("api_tokens")
    new = request.session.pop("new_api_token", None)
    mine = ApiToken.objects.filter(user=request.user)
    logs = AuditLog.objects.filter(user=request.user).select_related("token")[:40]
    base = request.build_absolute_uri("/").rstrip("/")
    return render(request, "api/tokens.html", {
        "tokens": mine, "logs": logs, "new": new, "hide_scope": True, "base_url": base,
        "tools": list(services.TOOLS.values()), "routes": ROUTES,
    })


@require_POST
def token_revoke(request, pk):
    token = get_object_or_404(ApiToken, pk=pk, user=request.user)
    if not token.revoked_at:
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])
        messages.success(request, f"Revoked “{token.label}”.")
    return redirect("api_tokens")
