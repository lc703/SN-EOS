import re

from django.db import migrations
from django.utils.text import slugify

PLANTS = ["Kentucky", "Le Roy", "Mabel"]


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def assign(apps, schema_editor):
    """The three plants exist from day one. Measurables on a team named for a plant move to that plant;
    everything else is a Company measurable (no plant). The teams themselves are left alone."""
    Plant = apps.get_model("scorecard", "Plant")
    Measurable = apps.get_model("scorecard", "Measurable")
    Team = apps.get_model("core", "Team")
    by_key = {}
    for i, name in enumerate(PLANTS, start=1):
        plant = Plant.objects.filter(slug=slugify(name)).first() or Plant.objects.filter(name__iexact=name).first()
        if plant is None:
            plant = Plant.objects.create(name=name, slug=slugify(name), sort=i)
        by_key[_norm(name)] = plant
    for team in Team.objects.filter(is_leadership=False):
        plant = by_key.get(_norm(team.name)) or by_key.get(_norm(team.short_code))
        if plant:
            Measurable.objects.filter(team=team).update(plant=plant)
    # Sort used to restart at zero on every team. Number everything once, in the order people saw it.
    for i, m in enumerate(Measurable.objects.order_by("team__sort", "sort", "id")):
        if m.sort != i:
            Measurable.objects.filter(pk=m.pk).update(sort=i)


class Migration(migrations.Migration):
    dependencies = [("scorecard", "0004_plants"), ("core", "0001_initial")]
    operations = [migrations.RunPython(assign, migrations.RunPython.noop)]
