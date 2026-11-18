"""The selected team and quarter live in the session; `?team=<slug>` / `?quarter=<id>` switch them."""

from .models import Quarter, Team


def current_team(request):
    teams = list(Team.objects.all())
    if not teams:
        return None
    slug = request.GET.get("team")
    if slug:
        for t in teams:
            if t.slug == slug:
                request.session["team_id"] = t.pk
                return t
    team_id = request.session.get("team_id")
    for t in teams:
        if t.pk == team_id:
            return t
    if request.user.is_authenticated:
        mine = [t for t in teams if t.members.filter(pk=request.user.pk).exists()]
        if mine:
            return mine[0]
    return teams[0]


def current_quarter(request):
    qid = request.GET.get("quarter")
    if qid and qid.isdigit():
        q = Quarter.objects.filter(pk=int(qid)).first()
        if q:
            request.session["quarter_id"] = q.pk
            return q
    qid = request.session.get("quarter_id")
    if qid:
        q = Quarter.objects.filter(pk=qid).first()
        if q:
            return q
    return Quarter.objects.current()
