"""Turn the per-statement and per-value G/Y/R scores kept in OneOnOne.legacy into OneOnOneScore rows."""

from django.db import migrations
from django.utils.dateparse import parse_datetime

from core.legacy_map import RAGS


def forwards(apps, schema_editor):
    OneOnOne = apps.get_model("people", "OneOnOne")
    Score = apps.get_model("people", "OneOnOneScore")
    Statement = apps.get_model("people", "SuccessStatement")
    CoreValue = apps.get_model("vision", "CoreValue")
    statements = {s.legacy_id: s for s in Statement.objects.exclude(legacy_id=None)}
    values = {v.legacy_id: v for v in CoreValue.objects.exclude(legacy_id=None)}

    for one in OneOnOne.objects.exclude(legacy={}):
        legacy = one.legacy or {}
        for key, score in (legacy.get("scores") or {}).items():
            if not isinstance(score, dict) or not key[2:].isdigit():
                continue
            rag = score.get("rag") if score.get("rag") in RAGS else ""
            target = {}
            if key.startswith("ss") and int(key[2:]) in statements:
                target = {"statement": statements[int(key[2:])]}
            elif key.startswith("cv") and int(key[2:]) in values:
                target = {"value": values[int(key[2:])]}
            if target and (rag or score.get("note")):
                Score.objects.update_or_create(one_on_one=one, **target, defaults={"rag": rag, "note": score.get("note") or ""})
        fields = []
        if legacy.get("completed_at") and not one.completed_at:
            one.completed_at = parse_datetime(legacy["completed_at"])
            fields.append("completed_at")
        first = (one.notes or "").split("\n", 1)[0]
        if first.startswith("Highlight: ") and not one.highlight:
            one.highlight = first[len("Highlight: "):]
            fields.append("highlight")
        if fields:
            one.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [("people", "0002_quarterly_conversation_scores"), ("vision", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
