import json
import re

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.permissions import is_admin

from . import tools
from .models import ApiToken, AuditLog

MCP_PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
MCP_INSTRUCTIONS = (
    "SN EOS is Steuart Nutrition's EOS (Entrepreneurial Operating System) app. Use these tools to read and update the "
    "signed-in person's own EOS data: weekly Scorecard numbers (Measurables), Rock check-ins (green/yellow/red, red needs a "
    "recovery plan), Issues (IDS), To-Dos, Headlines and the Level 10 Meeting. Start with `whoami` or `my_90`. Teams are "
    "referenced by slug. Every change is attributed to the token owner and logged."
)

REST_ROUTES = [
    ("GET", r"me", "whoami"),
    ("GET", r"teams", "list_teams"),
    ("GET", r"my90", "my_90"),
    ("GET", r"scorecard", "get_scorecard"),
    ("POST", r"measurables/(?P<measurable_id>\d+)/values", "set_measurable_value"),
    ("POST", r"measurables/values", "set_measurable_value"),
    ("GET", r"rocks", "list_rocks"),
    ("GET", r"rocks/(?P<rock_id>\d+)", "get_rock"),
    ("POST", r"rocks/(?P<rock_id>\d+)/updates", "update_rock_status"),
    ("POST", r"rocks/(?P<rock_id>\d+)/done", "set_rock_done"),
    ("POST", r"rocks/(?P<rock_id>\d+)/milestones", "set_milestone"),
    ("GET", r"issues", "list_issues"),
    ("POST", r"issues", "create_issue"),
    ("PATCH", r"issues/(?P<issue_id>\d+)", "update_issue"),
    ("POST", r"issues/(?P<issue_id>\d+)/solve", "solve_issue"),
    ("GET", r"todos", "list_todos"),
    ("POST", r"todos", "create_todo"),
    ("PATCH", r"todos/(?P<todo_id>\d+)", "update_todo"),
    ("GET", r"headlines", "list_headlines"),
    ("POST", r"headlines", "add_headline"),
    ("GET", r"l10", "get_l10"),
    ("POST", r"l10/(?P<meeting_id>\d+)/rating", "rate_l10"),
    ("POST", r"l10/(?P<meeting_id>\d+)/cascading-messages", "add_cascading_message"),
]


def _json(data, status=200, **kwargs):
    return JsonResponse(data, status=status, encoder=DjangoJSONEncoder, safe=False, **kwargs)


def _bearer(request):
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def _unauthorized(realm):
    resp = _json({"error": "Missing or invalid API token. Send 'Authorization: Bearer <token>'. Create one under API & AI connections."}, 401)
    resp["WWW-Authenticate"] = f'Bearer realm="{realm}"'
    return resp


def _coerce(spec, args):
    """Query-string values arrive as strings; coerce them to the schema's types."""
    props = spec["schema"]["properties"]
    out = {}
    for k, v in args.items():
        kind = props.get(k, {}).get("type")
        if kind == "integer" and isinstance(v, str) and re.fullmatch(r"-?\d+", v):
            v = int(v)
        elif kind == "boolean" and isinstance(v, str):
            v = v.lower() in {"1", "true", "yes", "on"}
        out[k] = v
    return out


@csrf_exempt
def rest(request, path):
    token = ApiToken.authenticate(_bearer(request))
    if token is None:
        return _unauthorized("SN EOS API")
    method = request.method.upper()
    allowed = []
    for verb, pattern, name in REST_ROUTES:
        match = re.fullmatch(pattern, path.strip("/"))
        if not match:
            continue
        allowed.append(verb)
        if verb != method:
            continue
        args = {k: v for k, v in request.GET.items()}
        if method != "GET" and request.body:
            try:
                body = json.loads(request.body)
            except ValueError:
                return _json({"error": "Body must be JSON."}, 400)
            if not isinstance(body, dict):
                return _json({"error": "Body must be a JSON object."}, 400)
            args.update(body)
        args.update({k: int(v) for k, v in match.groupdict().items()})
        spec = tools.TOOLS[name]
        actor = tools.Actor(user=token.user, token=token, source=AuditLog.API)
        try:
            data = tools.call(actor, name, _coerce(spec, args))
        except tools.ToolError as exc:
            return _json({"error": str(exc)}, 403 if isinstance(exc, tools.ToolForbidden) else 400)
        return _json({"data": data}, 201 if method == "POST" and name.startswith(("create", "add")) else 200)
    if allowed:
        resp = _json({"error": f"Method {method} not allowed here."}, 405)
        resp["Allow"] = ", ".join(sorted(set(allowed)))
        return resp
    return _json({"error": f"No endpoint /api/v1/{path}. See the README for the list."}, 404)


def _rpc_error(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _rpc_result(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _tool_list(token):
    out = []
    for name, spec in tools.TOOLS.items():
        if spec["write"] and not token.can_write:
            continue
        out.append({
            "name": name, "description": spec["description"], "inputSchema": spec["schema"],
            "annotations": {"readOnlyHint": not spec["write"], "destructiveHint": False, "openWorldHint": False},
        })
    return out


def _handle_rpc(msg, token):
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _rpc_error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid JSON-RPC request.")
    mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if "id" not in msg:
        return None  # notification (e.g. notifications/initialized)
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _rpc_result(mid, {
            "protocolVersion": asked if asked in MCP_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "sn-eos", "title": settings.APP_NAME, "version": "1.0"},
            "instructions": MCP_INSTRUCTIONS,
        })
    if method == "ping":
        return _rpc_result(mid, {})
    if method == "tools/list":
        return _rpc_result(mid, {"tools": _tool_list(token)})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        actor = tools.Actor(user=token.user, token=token, source=AuditLog.MCP)
        try:
            data = tools.call(actor, name, args)
        except tools.ToolError as exc:
            return _rpc_result(mid, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        text = json.dumps(data, cls=DjangoJSONEncoder, indent=1)
        structured = json.loads(text)
        return _rpc_result(mid, {
            "content": [{"type": "text", "text": text}],
            "structuredContent": structured if isinstance(structured, dict) else {"result": structured},
            "isError": False,
        })
    if method in {"resources/list", "prompts/list"}:
        return _rpc_result(mid, {method.split("/")[0]: []})
    return _rpc_error(mid, -32601, f"Method not found: {method}")


@csrf_exempt
def mcp(request):
    """MCP over Streamable HTTP. Stateless: every POST carries a bearer token; responses are plain JSON (no SSE)."""
    if request.method != "POST":
        resp = HttpResponse(status=405)
        resp["Allow"] = "POST"
        return resp
    token = ApiToken.authenticate(_bearer(request))
    if token is None:
        return _unauthorized("SN EOS MCP")
    try:
        payload = json.loads(request.body or b"null")
    except ValueError:
        return _json(_rpc_error(None, -32700, "Parse error."), 400)
    batch = isinstance(payload, list)
    replies = [r for r in (_handle_rpc(m, token) for m in (payload if batch else [payload])) if r is not None]
    if not replies:
        return HttpResponse(status=202)
    return _json(replies if batch else replies[0])


# ---- pages ---------------------------------------------------------------------------------

def tokens(request):
    new_token = None
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()[:80] or "API token"
        token, new_token = ApiToken.issue(request.user, name, can_write=request.POST.get("access") != "read")
        AuditLog.objects.create(user=request.user, token=token, source=AuditLog.WEB, action="token.create", object_type="apitoken",
                                object_id=str(token.pk), summary=f"Created token '{token.name}'{' (read-only)' if not token.can_write else ''}")
    mine = ApiToken.objects.filter(user=request.user)
    others = ApiToken.objects.filter(revoked_at__isnull=True).exclude(user=request.user).select_related("user") if is_admin(request.user) else []
    base = request.build_absolute_uri("/").rstrip("/")
    return render(request, "api/tokens.html", {
        "tokens": mine, "others": others, "new_token": new_token, "base_url": base,
        "tool_list": [(n, s["description"], s["write"]) for n, s in tools.TOOLS.items()],
        "recent": AuditLog.objects.filter(user=request.user).exclude(source=AuditLog.WEB).select_related("token")[:8],
    })


@require_POST
def token_revoke(request, pk):
    token = get_object_or_404(ApiToken, pk=pk)
    if token.user_id != request.user.pk and not is_admin(request.user):
        return HttpResponse(status=403)
    if token.revoked_at is None:
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])
        AuditLog.objects.create(user=request.user, token=token, source=AuditLog.WEB, action="token.revoke", object_type="apitoken",
                                object_id=str(token.pk), summary=f"Revoked token '{token.name}' ({token.user.display_name})")
        messages.success(request, f"Token “{token.name}” revoked. It stops working immediately.")
    return redirect("api_tokens")


def audit_log(request):
    qs = AuditLog.objects.select_related("user", "token")
    show_all = is_admin(request.user) and request.GET.get("mine") != "1"
    if not show_all:
        qs = qs.filter(user=request.user)
    source = request.GET.get("source")
    if source in dict(AuditLog.SOURCE_CHOICES):
        qs = qs.filter(source=source)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "api/audit.html", {"page": page, "show_all": show_all, "source": source, "sources": AuditLog.SOURCE_CHOICES})
