"""Plants and the single Scorecard layout.

One Scorecard holds every active measurable. Company measurables (no plant) come first. Plant measurables
follow, grouped by measurable name with one sub-row per plant, the way the old Battle Planner laid them out.
The Company view shows all of it; a plant's view shows the Company measurables on top, then its own plant.
"""

from django.db.models import Q

from core.models import Team

from .models import Measurable, Plant


def team_for_plant(plant, current=None):
    """The team a measurable belongs to for permissions and issues.

    A plant measurable belongs to the team named for its plant when there is one. A Company measurable keeps its
    team, unless that is a plant team, in which case it falls back to the leadership team."""
    teams = list(Team.objects.all())
    plant_names = {p.name.lower() for p in Plant.objects.all()}
    if plant is not None:
        for t in teams:
            if t.name.lower() == plant.name.lower():
                return t
        return current or _leadership(teams)
    if current is not None and current.name.lower() not in plant_names:
        return current
    return _leadership(teams)


def _leadership(teams):
    return next((t for t in teams if t.is_leadership), teams[0] if teams else None)


def assign_plant(m, plant):
    """Move a measurable to a plant (None = Company). Returns True when something changed."""
    team = team_for_plant(plant, m.team if m.team_id else None)
    if m.plant_id == (plant.pk if plant else None) and m.team_id == (team.pk if team else None):
        return False
    m.plant = plant
    if team is not None:
        m.team = team
    m.save(update_fields=["plant", "team"])
    return True


def plant_filter_for_team(team):
    """A plant team's Scorecard and L10 show Company rows plus that plant. Any other team shows everything."""
    if team is None:
        return None
    return next((p for p in Plant.objects.all() if p.name.lower() == team.name.lower()), None)


def scorecard_for_team(team):
    """(active measurables, plant or None) for a team's Scorecard, L10 and pulse.

    Company (and any team that is not a plant) sees the whole Scorecard: Company measurables first, then every
    plant. A plant team sees the Company measurables on top, then its own plant's measurables."""
    plant = plant_filter_for_team(team)
    qs = Measurable.objects.filter(active=True).select_related("owner", "team", "plant")
    if plant is None or (team is not None and team.is_leadership):
        return qs, None
    return qs.filter(Q(plant__isnull=True) | Q(plant=plant)), plant


COMPANY_GROUP = "Company"


def layout(measurables, plant=None):
    """Order measurables for the Scorecard.

    Returns (ordered, groups): Company first, then plant measurables. `groups` maps a measurable pk to
    (group title, first-in-group, sub-row) for rows that sit under a group header.

    Without `plant` (the Company roll-up) plant measurables are grouped by name with one sub-row per plant, the
    way the old Battle Planner laid them out. With `plant` (a site's own view) its measurables follow the Company
    section under the site's name, each with its full title."""
    measurables = list(measurables)
    company = sorted((m for m in measurables if m.plant_id is None), key=lambda m: (m.sort, m.pk))
    plant_ms = [m for m in measurables if m.plant_id is not None]
    ordered, groups = list(company), {}
    for i, m in enumerate(company):
        groups[m.pk] = (COMPANY_GROUP, i == 0, False)
    if plant is not None:
        own = sorted(plant_ms, key=lambda m: (m.sort, m.pk))
        for i, m in enumerate(own):
            ordered.append(m)
            groups[m.pk] = (plant.name, i == 0, False)
        return ordered, groups
    order, first = {}, {}
    for m in plant_ms:
        key = " ".join(m.title.lower().split())
        order.setdefault(key, []).append(m)
        first.setdefault(key, min(first.get(key, (m.sort, m.pk)), (m.sort, m.pk)))
    keys = sorted(order, key=lambda k: first[k])
    for key in keys:
        members = sorted(order[key], key=lambda m: (m.plant.sort, m.plant.name, m.pk))
        for i, m in enumerate(members):
            ordered.append(m)
            groups[m.pk] = (members[0].title, i == 0, True)
    return ordered, groups
