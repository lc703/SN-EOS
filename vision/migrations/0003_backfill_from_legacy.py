"""Move Battle Planner data the V1 importer parked in `legacy` JSON into real fields and rows."""

from django.db import migrations

from core.legacy_map import box_goal, seat_status, targets_text


def forwards(apps, schema_editor):
    Seat = apps.get_model("vision", "Seat")
    VTO = apps.get_model("vision", "VTO")
    Goal = apps.get_model("vision", "Goal")
    User = apps.get_model("core", "User")

    for seat in Seat.objects.exclude(legacy={}):
        legacy = seat.legacy or {}
        changed = False
        if legacy.get("status") and seat.status == "filled":
            seat.status = seat_status(legacy["status"])
            changed = True
        if legacy.get("agency") and not seat.is_agency:
            seat.is_agency = True
            changed = True
        if changed:
            seat.save(update_fields=["status", "is_agency"])

    by_name = {u.name.lower(): u for u in User.objects.exclude(name="")}
    for vto in VTO.objects.all():
        legacy = vto.legacy or {}
        house = legacy.get("strategy_house") or {}
        fields = []
        if house.get("major_business_challenge") and not vto.niche:
            vto.niche = house["major_business_challenge"]
            fields.append("niche")
        if house.get("targets") and not vto.one_year_measurables:
            vto.one_year_measurables = targets_text(house["targets"])
            fields.append("one_year_measurables")
        if fields:
            vto.save(update_fields=fields)
        if Goal.objects.exists():
            continue
        for i, box in enumerate(legacy.get("boxes") or []):
            data = box_goal(box)
            data["sort"] = data["sort"] or i
            Goal.objects.create(owner=by_name.get((box.get("dri") or "").lower()), **data)


class Migration(migrations.Migration):
    dependencies = [("vision", "0002_seat_status_goals"), ("core", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
