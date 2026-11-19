"""Turn Battle Planner offsites the V1 importer archived as LegacyRecord rows into sessions."""

import datetime as dt

from django.db import migrations

from core.legacy_map import OFFSITE_ITEM_MODELS, OFFSITE_STEP, offsite_item


def forwards(apps, schema_editor):
    LegacyRecord = apps.get_model("core", "LegacyRecord")
    Session = apps.get_model("planning", "Session")
    Item = apps.get_model("planning", "SessionItem")
    Team = apps.get_model("core", "Team")
    Quarter = apps.get_model("core", "Quarter")
    User = apps.get_model("core", "User")

    teams = {t.legacy_id: t for t in Team.objects.exclude(legacy_id=None)}
    quarters = {q.legacy_id: q for q in Quarter.objects.exclude(legacy_id=None)}
    users = {u.legacy_id: u for u in User.objects.exclude(legacy_id=None)}
    lead = Team.objects.filter(is_leadership=True).first()
    sessions = {}
    for rec in LegacyRecord.objects.filter(model="core.offsite"):
        f = rec.data
        team = teams.get(f.get("facility")) or lead
        if team is None or Session.objects.filter(legacy_id=rec.legacy_id).exists():
            continue
        date = dt.date.fromisoformat(f["date"][:10]) if f.get("date") else dt.date.today()
        sessions[rec.legacy_id] = Session.objects.create(
            legacy_id=rec.legacy_id, team=team, quarter=quarters.get(f.get("quarter")), kind="quarterly", date=date,
            current_step=OFFSITE_STEP.get(f.get("current_step"), "segue"), notes=f.get("agenda_notes") or "",
            legacy={"status": f.get("status")},
        )
    for rec in LegacyRecord.objects.filter(model__in=OFFSITE_ITEM_MODELS).order_by("model", "legacy_id"):
        session = sessions.get(rec.data.get("offsite"))
        item = offsite_item(rec.model, rec.data)
        if session is None or not item:
            continue
        Item.objects.create(
            session=session, step=item["step"], kind=item["kind"], text=item["text"], rag=item.get("rag") or "",
            author=users.get(item.get("author")), about=users.get(item.get("about")), sort=item.get("sort") or 0,
            legacy={"model": rec.model, "pk": rec.legacy_id},
        )


class Migration(migrations.Migration):
    dependencies = [("planning", "0001_initial"), ("core", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
