import datetime as dt

from django.db import migrations


def forwards(apps, schema_editor):
    Rock = apps.get_model("rocks", "Rock")
    RockUpdate = apps.get_model("rocks", "RockUpdate")
    User = apps.get_model("core", "User")
    names = {u.name: u for u in User.objects.exclude(name="")}
    for rock in Rock.objects.exclude(legacy={}):
        for h in (rock.legacy or {}).get("status_history", []):
            if h.get("rag") not in ("green", "yellow", "red") or not h.get("week_start"):
                continue
            week = dt.date.fromisoformat(h["week_start"])
            week -= dt.timedelta(days=week.weekday())
            RockUpdate.objects.get_or_create(
                rock=rock, week_start=week,
                defaults={"color": h["rag"], "note": h.get("note") or "", "recovery_plan": h.get("recovery_plan") or "",
                          "author": names.get(h.get("author"))},
            )


class Migration(migrations.Migration):
    dependencies = [("rocks", "0002_rockupdate"), ("core", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
