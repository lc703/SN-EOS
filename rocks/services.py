from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import monday_of

from .models import Rock, RockUpdate


def record_update(rock, user, color, note="", recovery_plan="", week=None):
    """Create or replace this week's G/Y/R check-in. Red requires a recovery plan."""
    if color not in dict(RockUpdate.COLOR_CHOICES):
        raise ValidationError("Status must be green, yellow or red.")
    note, recovery_plan = (note or "").strip(), (recovery_plan or "").strip()
    if color == RockUpdate.RED and not recovery_plan:
        raise ValidationError("An off-track (red) rock needs a recovery plan: what will get it back on track, and by when?")
    week = monday_of(week or timezone.localdate())
    update, _ = RockUpdate.objects.update_or_create(
        rock=rock, week_start=week,
        defaults={"color": color, "note": note, "recovery_plan": recovery_plan, "author": user},
    )
    rock.apply_update(update)
    return update


def set_done(rock, done=True):
    rock.status = Rock.DONE if done else Rock.ON_TRACK
    rock.save(update_fields=["status", "updated_at"])
    if not done:
        latest = rock.updates.order_by("-week_start").first()
        if latest:
            rock.apply_update(latest)
    return rock
