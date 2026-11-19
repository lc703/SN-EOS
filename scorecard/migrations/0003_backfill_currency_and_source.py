from django.db import migrations

from scorecard.units import CURRENCY, NUMBER, SOURCE_NOTES, unit_from_text


def backfill(apps, schema_editor):
    """Imported measurables keep the old unit text in `legacy`. Read it again so "USD" and "$M" become dollars,
    and give the rows the old app filled by itself a source note."""
    Measurable = apps.get_model("scorecard", "Measurable")
    for m in Measurable.objects.all():
        legacy = m.legacy if isinstance(m.legacy, dict) else {}
        changed = []
        if m.unit == NUMBER and unit_from_text(legacy.get("unit")) == CURRENCY:
            m.unit = CURRENCY
            changed.append("unit")
        note = SOURCE_NOTES.get(legacy.get("source") or "")
        if note and not m.source:
            m.source = note
            changed.append("source")
        if changed:
            m.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [("scorecard", "0002_measurable_source")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
