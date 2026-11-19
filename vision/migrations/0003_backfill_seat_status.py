from django.db import migrations

STATUS = {"green": "filled", "yellow": "future", "red": "open"}


def forwards(apps, schema_editor):
    Seat = apps.get_model("vision", "Seat")
    for seat in Seat.objects.exclude(legacy={}):
        legacy = seat.legacy or {}
        status = STATUS.get(legacy.get("status"))
        agency = bool(legacy.get("agency"))
        if status and (seat.status != status or seat.agency != agency):
            seat.status, seat.agency = status, agency
            seat.save(update_fields=["status", "agency"])


class Migration(migrations.Migration):
    dependencies = [("vision", "0002_seat_agency_seat_status_coreprocess")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
