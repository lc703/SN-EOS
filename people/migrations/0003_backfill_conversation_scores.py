from django.db import migrations


def forwards(apps, schema_editor):
    OneOnOne = apps.get_model("people", "OneOnOne")
    Score = apps.get_model("people", "ConversationScore")
    Statement = apps.get_model("people", "SuccessStatement")
    CoreValue = apps.get_model("vision", "CoreValue")
    statements = {s.legacy_id: s for s in Statement.objects.exclude(legacy_id=None)}
    values = {v.legacy_id: v for v in CoreValue.objects.exclude(legacy_id=None)}
    for one in OneOnOne.objects.exclude(legacy={}):
        legacy = one.legacy or {}
        if Score.objects.filter(conversation=one).exists():
            continue
        for key, score in (legacy.get("scores") or {}).items():
            pk = int(key[2:]) if key[2:].isdigit() else None
            target = {"ss": ("statement", statements), "cv": ("value", values)}.get(key[:2])
            if not target or pk not in target[1]:
                continue
            color = (score or {}).get("rag") or ""
            Score.objects.create(conversation=one, color=color if color in ("green", "yellow", "red") else "",
                                 note=(score or {}).get("note") or "", **{target[0]: target[1][pk]})
        if legacy.get("completed_at") and not one.completed_at:
            from django.utils.dateparse import parse_datetime

            one.completed_at = parse_datetime(legacy["completed_at"])
            one.save(update_fields=["completed_at"])


class Migration(migrations.Migration):
    dependencies = [("people", "0002_alter_oneonone_options_oneonone_capacity_and_more"), ("vision", "0002_seat_agency_seat_status_coreprocess")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
