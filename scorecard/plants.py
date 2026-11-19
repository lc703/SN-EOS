"""Plants and the single Scorecard layout.

One Scorecard shows every active measurable. Company measurables (no plant) come first. Plant measurables
follow, grouped by measurable name with one sub-row per plant, the way the old Battle Planner laid them out.
"""

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
    """A plant L10 shows only that plant's rows. Any other team's L10 shows the whole Scorecard."""
    if team is None:
        return None
    return next((p for p in Plant.objects.all() if p.name.lower() == team.name.lower()), None)


def scorecard_for_team(team):
    """(active measurables, plant or None) for a team's L10 and pulse: a plant team sees its plant's rows, anyone
    else sees the whole Scorecard."""
    plant = plant_filter_for_team(team)
    qs = Measurable.objects.filter(active=True).select_related("owner", "team", "plant")
    return (qs.filter(plant=plant) if plant else qs), plant


def layout(measurables):
    """Order measurables for the single Scorecard.

    Returns (ordered, groups): Company first, then plant measurables grouped by name. `groups` maps a
    measurable pk to (group title, first-in-group) for the rows that sit under a group header."""
    measurables = list(measurables)
    company = sorted((m for m in measurables if m.plant_id is None), key=lambda m: (m.sort, m.pk))
    plant_ms = [m for m in measurables if m.plant_id is not None]
    order, first = {}, {}
    for m in plant_ms:
        key = " ".join(m.title.lower().split())
        order.setdefault(key, []).append(m)
        first.setdefault(key, min(first.get(key, (m.sort, m.pk)), (m.sort, m.pk)))
    keys = sorted(order, key=lambda k: first[k])
    ordered, groups = list(company), {}
    for key in keys:
        members = sorted(order[key], key=lambda m: (m.plant.sort, m.plant.name, m.pk))
        for i, m in enumerate(members):
            ordered.append(m)
            groups[m.pk] = (members[0].title, i == 0)
    return ordered, groups
