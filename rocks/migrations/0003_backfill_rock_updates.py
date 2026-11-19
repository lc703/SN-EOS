"""Turn the weekly G/Y/R history the V1 importer kept in Rock.legacy into RockUpdate rows."""

import datetime as dt

from django.db import migrations
from django.utils import timezone

from core.legacy_map import RAGS


def forwards(apps, schema_editor):
    Rock = apps.get_model("rocks", "Rock")
    RockUpdate = apps.get_model("rocks", "RockUpdate")
    User = apps.get_model("core", "User")
    by_name = {u.name.lower(): u for u in User.objects.exclude(name="")}

    for rock in Rock.objects.exclude(legacy={}):
        for h in (rock.legacy or {}).get("status_history") or []:
            if h.get("rag") not in RAGS or not h.get("week_start"):
                continue
            week = dt.date.fromisoformat(h["week_start"][:10])
            week -= dt.timedelta(days=week.weekday())
            RockUpdate.objects.update_or_create(
                rock=rock, week_start=week,
                defaults={
                    "rag": h["rag"], "note": h.get("note") or "", "recovery_plan": h.get("recovery_plan") or "",
                    "author": by_name.get((h.get("author") or "").lower()),
                    "created_at": timezone.make_aware(dt.datetime.combine(week, dt.time(9))),
                },
            )


class Migration(migrations.Migration):
    dependencies = [("rocks", "0002_rock_updates_goals"), ("core", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
