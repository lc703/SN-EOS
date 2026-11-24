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
