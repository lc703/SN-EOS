from django.db import migrations

from scorecard.units import CURRENCY, NUMBER, unit_for


def flag_dollars(apps, schema_editor):
    """Imported number metrics that are money by name or by a $ goal (e.g. a facility's revenue difference)
    were stored as plain numbers and showed -116000. Make them dollars."""
    Measurable = apps.get_model("scorecard", "Measurable")
    for m in Measurable.objects.filter(unit=NUMBER, legacy_id__isnull=False):
        legacy = m.legacy if isinstance(m.legacy, dict) else {}
        if unit_for(legacy.get("unit"), m.title, legacy.get("goal")) == CURRENCY:
            m.unit = CURRENCY
            m.save(update_fields=["unit"])


class Migration(migrations.Migration):
    dependencies = [("scorecard", "0005_assign_plants")]
    operations = [migrations.RunPython(flag_dollars, migrations.RunPython.noop)]
