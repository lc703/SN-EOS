from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Quarter, Team
from vision.models import VTO

DEFAULT_TEAMS = [
    ("Company", "CO", True),
    ("Kentucky", "KY", False),
    ("Le Roy", "LR", False),
    ("Mabel", "MB", False),
]


class Command(BaseCommand):
    help = "Create the default teams, the current quarter and the V/TO row if missing. Never overwrites."

    def handle(self, **opts):
        for sort, (name, code, lead) in enumerate(DEFAULT_TEAMS):
            _, created = Team.objects.get_or_create(
                name=name, defaults={"short_code": code, "is_leadership": lead, "sort": sort}
            )
            if created:
                self.stdout.write(f"Created team {name}")
        q = Quarter.for_calendar(timezone.localdate())
        self.stdout.write(f"Current quarter: {q}")
        VTO.load()
