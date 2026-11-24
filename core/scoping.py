"""The Company team is a roll-up, not a business unit.

Picking Company shows everything across Company, Kentucky, Le Roy and Mabel; picking a site shows that
site. Use `team_q` on anything with a team foreign key so every list agrees on this one rule.
Creating something from the Company view still files it under the Company team.
"""
from django.db.models import Q


def is_rollup(team):
    return bool(team is not None and team.is_leadership)


def team_q(team, field="team"):
    """A filter for items in `team`'s view: every item for Company, otherwise only that team's."""
    if team is None or is_rollup(team):
        return Q()
    return Q(**{field: team})


def for_team(qs, team, field="team", extra=None):
    """`qs` limited to `team`'s view. `extra` is another Q that also belongs to a site view (not to Company's)."""
    q = team_q(team, field)
    if extra is not None and q:
        q = q | extra
    return qs.filter(q)


def company_team():
    from core.models import Team

    return Team.objects.filter(is_leadership=True).order_by("sort", "pk").first()


def is_site(team):
    return team is not None and not team.is_leadership


def company_items(qs, team, field="team"):
    """Company's own items for a site view (a Company group shown below the site's own), nothing elsewhere.

    The items keep their Company team, so ranks, ownership and permissions stay Company's. Never includes
    another site's items. Company and roll-up views return nothing here: they already show everything.
    """
    company = company_team() if is_site(team) else None
    return qs.filter(**{field: company}) if company else qs.none()
